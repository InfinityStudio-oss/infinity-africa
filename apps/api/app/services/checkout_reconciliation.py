"""Shared completion logic for Selcom Checkout wallet-push collections —
the one place both the inbound webhook handler
(app/routers/webhooks.py::selcom_checkout_webhook) and the manual
order-status refresh endpoints
(POST /v1/merchant/collections/{id}/refresh-status,
POST /v1/admin/collections/{id}/refresh-status) apply a Selcom result to
a collection.

**Reuses app/services/collections.py::resolve_collection() rather than
reimplementing crediting** — that function already does everything the
credit rule needs: idempotent (a no-op if the collection isn't still
"processing"), posts ledger entries exactly once, marks a linked
payment_link PAID and a linked invoice PAID/PARTIALLY_PAID, and enqueues
the outbound developer webhook event. This module's own job is just:
map Selcom Checkout's fields onto the CollectionResult shape
resolve_collection() already understands, and additionally keep
checkout_orders (a concept resolve_collection() has no reason to know
about) and the merchant notification in sync.

Credit rule (never decided anywhere else): a collection is only ever
resolved "successful" — and therefore only ever credited — when all
three of result == "SUCCESS", resultcode == "000", and
payment_status == "COMPLETED" agree. A payment_status of "COMPLETED"
without the other two agreeing is treated as still-unresolved
("processing"), not silently accepted and not silently marked
failed — that combination is corrupted/suspicious input, not a normal
outcome, and the safe response to "the signal doesn't add up" is to
leave money movement pending, never to guess.
"""

import logging
import uuid
from decimal import Decimal, InvalidOperation

from supabase import Client

from app.core.errors import ConflictError, NotFoundError
from app.schemas.enums import NotificationType
from app.services.audit import write_audit_log
from app.services.collections import resolve_collection, reverse_successful_collection
from app.services.crud import execute_maybe_single, get_by_id, update_row
from app.services.notifications_service import notify_merchant
from app.services.provider_references import (
    update_collection_tolerating_repeated_reference,
)
from app.services.selcom.schemas import CollectionResult, ProviderStatus
from app.services.selcom_checkout.client import (
    SelcomCheckoutHTTPClient,
    get_selcom_checkout_credentials,
)

logger = logging.getLogger("infinity.checkout_reconciliation")

_COMPLETED_PAYMENT_STATUSES = {"COMPLETED"}
# REVERSED is Selcom reporting that a payment it earlier called COMPLETED
# has since bounced (e.g. the live incident this module was hardened for:
# an M-Pesa "own till" payment that Selcom accepted then reversed) — a
# terminal failure/reversal outcome either way, never silently treated as
# still-pending.
_TERMINAL_FAILED_PAYMENT_STATUSES = {"CANCELLED", "USERCANCELLED", "REJECTED", "REVERSED"}
_STILL_PENDING_PAYMENT_STATUSES = {"PENDING", "INPROGRESS"}

# Selcom's free-text message/result fields have carried this wording on
# real deliveries (see the live incident's own M-Pesa message: "Payment
# unsuccessful. You are trying to pay into your own till") — checked as a
# belt-and-suspenders signal alongside payment_status, since a free-text
# field is far less reliable than a coded status but still worth catching
# when it's the only place the true outcome shows up.
_REVERSAL_MESSAGE_MARKERS = ("own till", "unsuccessful", "reversed", "reversal")


def _looks_like_reversal_message(raw_response: dict) -> str | None:
    message = str(raw_response.get("message") or "").strip()
    if not message:
        return None
    lowered = message.lower()
    if any(marker in lowered for marker in _REVERSAL_MESSAGE_MARKERS):
        return message
    return None


def map_checkout_status_to_provider_status(
    *, payment_status: str | None, result: str | None, resultcode: str | None
) -> ProviderStatus:
    """The credit rule, as a pure function so it's independently
    testable: result/resultcode/payment_status together decide
    "successful" / "processing" / "failed" — the same three-value
    vocabulary app/services/selcom/schemas.py::CollectionResult already
    uses, so the result plugs straight into resolve_collection()."""
    payment_status = (payment_status or "").upper()
    result = (result or "").upper()

    if payment_status in _COMPLETED_PAYMENT_STATUSES:
        if result == "SUCCESS" and resultcode == "000":
            return "successful"
        # COMPLETED without result/resultcode agreeing is inconsistent —
        # never credit on this alone, and don't mark it failed either
        # (that could hide a real success behind a mismatched field).
        # Stays "processing" — unresolved, safe, and still refreshable.
        return "processing"

    if payment_status in _TERMINAL_FAILED_PAYMENT_STATUSES:
        return "failed"

    if payment_status in _STILL_PENDING_PAYMENT_STATUSES:
        return "processing"

    # Unrecognized payment_status (or none at all — e.g. a bare
    # wallet-payment PENDING/111 result before any payment_status field
    # exists yet) — fall back to resultcode alone, same convention as
    # wallet-payment's own parsing.
    if resultcode == "000" and result == "SUCCESS":
        return "successful"
    if resultcode in ("111", "927"):
        return "processing"
    if resultcode == "999":
        return "processing"  # ambiguous — see module docstring, never a silent failure
    return "failed"


def find_collection_by_transid(client: Client, *, transid: str) -> dict | None:
    """The precise match for "which payment attempt is this delivery
    about" — transid is generated fresh per wallet-payment call
    (app/services/wallet_push.py), so unlike order_id (which can be
    reused across a retried order-creation-but-not-yet-pushed attempt)
    it identifies exactly one collection."""
    return execute_maybe_single(
        client.table("collections").select("*").eq("provider_transid", transid).maybe_single()
    )


def find_collection_by_order_id(client: Client, *, order_id: str) -> dict | None:
    """Fallback lookup when a delivery doesn't carry (or predates) a
    transid — resolves via the checkout_orders row's own order_id, then
    the collection linked to it."""
    order = execute_maybe_single(
        client.table("checkout_orders").select("id").eq("order_id", order_id).maybe_single()
    )
    if not order:
        return None
    return execute_maybe_single(
        client.table("collections")
        .select("*")
        .eq("checkout_order_id", order["id"])
        .order("created_at", desc=True)
        .range(0, 0)
        .maybe_single()
    )


async def complete_checkout_collection_once(
    client: Client,
    *,
    collection_id: uuid.UUID,
    payment_status: str | None,
    result: str | None,
    resultcode: str | None,
    reference: str | None,
    transid: str | None,
    channel: str | None,
    raw_response: dict,
) -> dict | None:
    """Applies one Selcom Checkout result to a collection, exactly once
    per resolution — safe to call repeatedly (a webhook retry, or a
    status refresh after the webhook already resolved it) without
    double-crediting, since resolve_collection() itself no-ops once the
    collection is no longer "processing". Audit fields (provider_*,
    channel, raw_response) are refreshed on every call regardless, so a
    later delivery's data is never lost even when it can't change the
    outcome anymore.

    A collection that's already "successful" and receives a *new* signal
    indicating the payment actually failed/reversed (payment_status ==
    REVERSED, or a terminal-failure payment_status, or Selcom's message
    text itself reads as a reversal — see module docstring/live incident)
    routes to reverse_successful_collection() instead of
    resolve_collection(), since resolve_collection()'s own idempotency
    guard would otherwise silently no-op on an already-resolved
    collection and the reversal would never be applied.

    Returns None if collection_id doesn't exist at all (caller decides
    whether that's a 404 or something to log and ACK anyway)."""
    collection = get_by_id(client, "collections", collection_id)
    if not collection:
        return None
    # Captured before resolve_collection() runs — its own idempotency
    # check is keyed on this same field, and this call needs to know
    # whether *this* call is the one doing the resolving, or a repeat
    # arriving after an earlier call already did. Skipping this check
    # would re-notify/re-mark the linked order "completed" on every
    # duplicate webhook delivery, even though the ledger itself stays
    # correctly protected by resolve_collection()'s own guard.
    was_still_processing = collection["status"] == "processing"
    was_already_successful = collection["status"] == "successful"

    # provider_reference is Selcom's value under our unique index. If the
    # reference they send now already belongs to another collection, the
    # update raises 23505 and this whole resolution fails — on the webhook
    # path, that means a paid collection never gets credited. The helper
    # keeps the reference this row already has and applies the rest.
    update_collection_tolerating_repeated_reference(
        client,
        collection_id,
        {
            "provider_reference": reference or collection.get("provider_reference"),
            "provider_transid": transid or collection.get("provider_transid"),
            "provider_result": result,
            "provider_resultcode": resultcode,
            "provider_payment_status": payment_status,
            "channel": channel or collection.get("channel"),
            "raw_response": raw_response,
        },
        context="checkout_reconciliation",
    )

    status = map_checkout_status_to_provider_status(
        payment_status=payment_status, result=result, resultcode=resultcode
    )
    reversal_message = _looks_like_reversal_message(raw_response)

    if was_already_successful and (status == "failed" or reversal_message):
        reason = (
            reversal_message
            or f"Selcom payment_status={payment_status or 'unknown'} after this collection had already settled"
        )
        return reverse_successful_collection(client, collection_id=collection_id, reason=reason)

    failure_reason = None
    if status == "failed":
        failure_reason = f"Selcom payment_status={payment_status or 'unknown'}"
    elif reversal_message:
        # payment_status/result/resultcode all looked fine, but the
        # free-text message itself reads as a reversal/failure — never
        # silently credited on a mixed signal like this (same "don't
        # guess" principle as the COMPLETED-without-agreement case
        # above), and also never left "processing" — it's treated as a
        # clear failure rather than an ambiguous one, since this text has
        # only ever meant "the money didn't actually move" so far.
        status = "failed"
        failure_reason = reversal_message

    collection_result = CollectionResult(
        provider="selcom_checkout",
        provider_reference=reference or collection.get("provider_reference") or "",
        status=status,
        failure_reason=failure_reason,
        # Passed through so the failure can be normalized into a stable
        # code rather than stored as the provider's own text.
        provider_payment_status=payment_status,
        provider_resultcode=resultcode,
    )
    resolved = resolve_collection(client, collection_id=collection_id, result=collection_result)

    if was_still_processing and status == "successful" and resolved.get("status") == "successful":
        if collection.get("checkout_order_id"):
            update_row(client, "checkout_orders", uuid.UUID(collection["checkout_order_id"]), {"status": "completed"})
        notify_merchant(
            client,
            merchant_id=uuid.UUID(resolved["merchant_id"]),
            notification_type=NotificationType.PAYMENT_RECEIVED,
            title="Payment received",
            body=f"You received a payment of {resolved['amount']} {resolved['currency']}.",
            related_resource_type="collection",
            related_resource_id=collection_id,
        )

    return resolved


def _amount_and_currency_agree(
    *,
    expected_amount: Decimal,
    expected_currency: str,
    reported_amount: str | None,
    reported_currency: str | None,
) -> bool:
    """Defense-in-depth cross-check applied before crediting, against
    Selcom's own authenticated order-status answer (never against an
    inbound webhook's unauthenticated claim — see
    resolve_checkout_collection_from_webhook_hint). Agrees (True) when a
    field isn't reported at all — Selcom's Checkout order-status response
    currently never includes a currency, only amount — since there's
    nothing to contradict; rejects (False) only on an actual, confirmed
    mismatch. Never guesses in the credit's favor on a real mismatch."""
    if reported_amount is not None:
        try:
            if Decimal(reported_amount) != expected_amount:
                return False
        except (InvalidOperation, ValueError):
            return False
    return reported_currency is None or reported_currency.strip().upper() == expected_currency.strip().upper()


async def _query_and_complete_checkout_collection(client: Client, *, collection: dict, order_id: str) -> dict | None:
    """Shared core: queries Selcom's own order-status API with our own
    outbound-authenticated credentials, cross-checks the amount it
    reports against what this collection actually expects, then applies
    the result via complete_checkout_collection_once() — only ever this
    live, authenticated answer, never an inbound webhook's own claimed
    fields (see resolve_checkout_collection_from_webhook_hint's
    docstring). Used by the manual Refresh Status endpoints, the
    webhook's post-signature-verification lookup, and the scheduled
    reconciliation sweep alike, so the amount check protects all three
    uniformly. Returns None (never credits, collection stays whatever it
    already was) on a mismatch — logged and audited, not silently
    ignored."""
    checkout_client = SelcomCheckoutHTTPClient(credentials=get_selcom_checkout_credentials())
    status_result = await checkout_client.get_order_status(order_id=order_id)

    expected_amount = Decimal(str(collection["amount"]))
    expected_currency = collection.get("currency") or "TZS"
    if not _amount_and_currency_agree(
        expected_amount=expected_amount,
        expected_currency=expected_currency,
        reported_amount=status_result.amount,
        reported_currency=None,  # Selcom's order-status response never reports one today
    ):
        logger.warning(
            "selcom_checkout_amount_mismatch collection_id=%s expected=%s %s reported_amount=%s",
            collection["id"],
            expected_amount,
            expected_currency,
            status_result.amount,
        )
        write_audit_log(
            client,
            action="collection.checkout_amount_mismatch",
            resource_type="collection",
            resource_id=uuid.UUID(collection["id"]),
            actor_type="system",
            merchant_id=uuid.UUID(collection["merchant_id"]),
            metadata={"expected_amount": str(expected_amount), "reported_amount": status_result.amount},
        )
        return None

    return await complete_checkout_collection_once(
        client,
        collection_id=uuid.UUID(collection["id"]),
        payment_status=status_result.payment_status,
        result=status_result.result,
        resultcode=status_result.resultcode,
        reference=status_result.reference,
        transid=status_result.transid or collection.get("provider_transid"),
        channel=status_result.channel,
        raw_response=status_result.raw_response,
    )


async def refresh_checkout_collection_status(client: Client, *, collection_id: uuid.UUID) -> dict:
    """The manual reconciliation path — queries Selcom directly
    (get_order_status()) rather than waiting for a webhook, and applies
    the same completion logic via complete_checkout_collection_once().
    This is a fully independent path from the webhook: it only ever
    calls Selcom, never receives from it."""
    collection = get_by_id(client, "collections", collection_id)
    if not collection:
        raise NotFoundError("Collection not found")
    if not collection.get("checkout_order_id"):
        raise ConflictError("This collection has no linked Selcom Checkout order to refresh")

    order = get_by_id(client, "checkout_orders", uuid.UUID(collection["checkout_order_id"]))
    if not order:
        raise ConflictError("The linked Selcom Checkout order no longer exists")

    resolved = await _query_and_complete_checkout_collection(client, collection=collection, order_id=order["order_id"])
    return resolved if resolved is not None else collection


async def resolve_checkout_collection_from_webhook_hint(
    client: Client, *, collection: dict, order_id: str
) -> dict | None:
    """Called by the webhook handler — but ONLY after signature
    verification has already accepted the delivery (or, in local
    development only, the internal test-secret bypass). A delivery that
    fails verification never reaches this function at all: it's rejected
    with 401 before any collection is even looked up (see
    app/routers/webhooks.py::selcom_checkout_webhook and
    docs/selcom-checkout-collections.md's "Signature verification"
    section for why, as of 2026-08-27, Selcom's real Checkout webhook
    never carries a signature and therefore never reaches here in
    production — app/services/checkout_reconciliation.py::
    reconcile_pending_checkout_collections is what actually keeps wallets
    credited from real traffic today).

    Even once past signature verification, this still never trusts the
    delivery's own claimed payment_status/result/resultcode/amount
    directly — the whole point of a signature is proving *who* sent a
    message, not that its claims are independently correct, and this
    account's provider has already shown its callback data can't be
    assumed reliable (see this module's docstring on the COMPLETED/
    reversal handling). Same as refresh_checkout_collection_status and
    the scheduled sweep: it re-queries Selcom's order-status API with our
    own authenticated outbound credentials and applies only that
    (amount-cross-checked) answer."""
    return await _query_and_complete_checkout_collection(client, collection=collection, order_id=order_id)


async def reconcile_pending_checkout_collections(client: Client) -> dict:
    """Backend-initiated, webhook-independent reconciliation sweep —
    called on a timer from app/main.py's lifespan startup task (see
    Settings.selcom_checkout_reconcile_interval_seconds), not from any
    inbound signal. This is what actually keeps merchant wallets credited
    for Selcom Checkout collections now that the inbound webhook fails
    closed on every real delivery (Selcom sends no signature — see
    docs/selcom-checkout-collections.md): every collection still
    "processing" with a linked Selcom Checkout order gets the exact same
    authenticated order-status lookup + amount cross-check +
    completion logic refresh_checkout_collection_status uses for a single
    collection, just swept across all of them. Mirrors
    app/services/disbursements.py::reconcile_pending_disbursements's
    identical shape for withdrawals.

    Safe to run concurrently with itself (e.g. more than one API replica
    each running this loop) or with a manual refresh/webhook-triggered
    call for the same collection — resolve_collection()'s own idempotency
    guard means only the first call to actually observe "successful" ever
    credits anything; every other concurrent/later call for the same
    collection just re-confirms the same already-settled outcome."""
    rows = (client.table("collections").select("id, checkout_order_id, status").eq("status", "processing").execute()).data or []
    pending_with_order = [row for row in rows if row.get("checkout_order_id")]
    # Logged every sweep, even 0/0 — the point is being able to tell from
    # Railway logs alone whether the sweep ran and what it found, without
    # waiting for a real pending collection to exist. If processing_no_order
    # is ever nonzero, that's worth investigating on its own: a
    # "processing" collection with no checkout_order_id link can never be
    # picked up by this sweep (or by manual Refresh Status) at all.
    logger.info(
        "checkout_reconciliation_sweep_starting processing_total=%s eligible_with_checkout_order=%s processing_no_order=%s",
        len(rows),
        len(pending_with_order),
        len(rows) - len(pending_with_order),
    )

    resolved = 0
    still_pending = 0
    for row in pending_with_order:
        collection_id = uuid.UUID(row["id"])
        try:
            outcome = await refresh_checkout_collection_status(client, collection_id=collection_id)
        except (NotFoundError, ConflictError) as exc:
            # Collection or its linked order vanished between the list
            # query and this call, or lost its order link somehow — skip
            # rather than let one bad row abort the whole sweep.
            logger.warning("checkout_reconciliation_skipped collection_id=%s reason=%s", collection_id, exc)
            continue
        except Exception:
            # Anything else (e.g. a DB constraint violation on one
            # malformed/duplicate row) must never take down every other
            # collection's chance to be checked this sweep — confirmed
            # live on 2026-08-28: a single collection whose Selcom-reported
            # provider_reference collided with another row's (a data
            # problem, not a logic bug) was silently aborting the entire
            # sweep, every tick, blocking unrelated collections from ever
            # being reconciled. Logged with the traceback so the
            # underlying data issue is still visible and fixable.
            logger.exception("checkout_reconciliation_row_failed collection_id=%s", collection_id)
            continue
        outcome_status = outcome.get("status")
        logger.info("checkout_reconciliation_checked collection_id=%s result=%s", collection_id, outcome_status)
        if outcome_status == "processing":
            still_pending += 1
        else:
            resolved += 1

    return {"checked": len(pending_with_order), "resolved": resolved, "still_pending": still_pending}
