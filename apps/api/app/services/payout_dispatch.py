"""Sending an authorised payout to the provider, and deciding what its
answer means for the money.

By the time a payout reaches this module its funds are already reserved -
`authorize_payout` did that, and the payout is `processing`. So every
branch here is about one question: **may the reserve be let go?**

    provider says                 reserve
    -------------                 -------
    successful                    becomes a real outflow (settled)
    definitively failed           returns to the wallet (released)
    still working / unclear       STAYS HELD (needs_reconciliation)

The third row is the one that matters, and it is why there is no timeout
branch that releases anything. A payout whose outcome is unknown may have
been paid. Releasing its reserve would let the merchant spend money that
has already left, and the platform would be short - so an unknown outcome
parks the payout for reconciliation with the funds still committed, and a
person or a later provider query resolves it. Nothing in this module
releases funds on a timeout.

Each money movement is also guarded so a replay cannot repeat it: the
status transition is conditional on the status the caller believed it was
acting on, so a duplicate callback, a double worker tick and a retried
reconciliation all find the row already moved on and do nothing. The
ledger is the second line - payout_reserved may not go negative, so a
settle or release that slipped through the first guard still fails rather
than inventing money.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from supabase import Client

from app.core.errors import ConflictError, NotFoundError
from app.services.audit import write_audit_log
from app.services.crud import get_by_id
from app.services.ledger import post_payout_release, post_payout_settlement
from app.services.selcom_business.client import (
    SelcomBusinessMisconfiguredError,
    get_selcom_business_client,
)
from app.services.selcom_business.schemas import SelcomBusinessResult
from app.services.webhooks import enqueue_webhook_event

logger = logging.getLogger("infinity.payouts")

# How long to wait before asking the provider again about a payout whose
# outcome we do not know. Deliberately not aggressive: the funds are
# already held, so nothing is at risk from waiting, and hammering a
# provider about an ambiguous transaction is how you turn one unclear
# payout into several.
_RECONCILE_BACKOFF_SECONDS = (60, 300, 900, 3600)

# Terminal: nothing further to do, and the reserve has been accounted for.
TERMINAL_STATUSES = ("successful", "failed", "cancelled", "reversed")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _backoff_for(attempts: int) -> datetime:
    index = min(max(attempts - 1, 0), len(_RECONCILE_BACKOFF_SECONDS) - 1)
    return _now() + timedelta(seconds=_RECONCILE_BACKOFF_SECONDS[index])


def _transition(
    client: Client, *, payout_id: uuid.UUID, expected_status: str, changes: dict
) -> dict | None:
    """Apply `changes` only if the payout is still `expected_status`.

    The compare-and-set that makes every branch below replay-safe. A
    duplicate callback arriving after the first one has settled the
    payout matches nothing and changes nothing, so the caller knows not
    to post a second set of ledger entries.
    """
    result = (
        client.table("payouts")
        .update({**changes, "updated_at": _now().isoformat()})
        .eq("id", str(payout_id))
        .eq("status", expected_status)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def _claim_for_dispatch(client: Client, payout: dict) -> dict | None:
    """Take this payout, or discover someone else already has.

    Conditional on the attempt count the caller read, so two workers
    picking up the same row cannot both dispatch it. Without this a
    second tick would send the payout to the provider twice, and the
    provider would be the only thing standing between that and paying
    twice - which is exactly what the idempotency key on
    provider_reference is for, but a guard here is cheaper than relying
    on theirs.
    """
    attempts = int(payout.get("dispatch_attempts") or 0)
    result = (
        client.table("payouts")
        .update(
            {
                "dispatch_attempts": attempts + 1,
                "last_dispatched_at": _now().isoformat(),
                "updated_at": _now().isoformat(),
            }
        )
        .eq("id", payout["id"])
        .eq("status", "processing")
        .eq("dispatch_attempts", attempts)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def _parent_transaction_id(client: Client, payout_id: uuid.UUID) -> uuid.UUID | None:
    """The transactions row authorize_payout created for this payout.

    The ledger entries must hang off the same parent the reservation
    used, or the settle and the reserve would belong to different
    transactions and neither would balance.
    """
    result = (
        client.table("transactions")
        .select("id")
        .eq("payout_id", str(payout_id))
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return uuid.UUID(rows[0]["id"]) if rows else None


async def dispatch_payout(client: Client, payout: dict) -> str:
    """Send one authorised payout and record what came back.

    Returns the status the payout ended in. Safe to call twice: the
    second call will not claim the row.
    """
    payout_id = uuid.UUID(payout["id"])

    # Resolve the provider BEFORE claiming the row.
    #
    # This is what decides which Selcom the money goes to, and it is the
    # payout's own environment that decides it - not SELCOM_BUSINESS_MODE,
    # which in any deployment that pays real withdrawals is `live`.
    # Resolving first means a misconfiguration leaves the payout exactly
    # as it was, ready for a later attempt, instead of claiming it and
    # then having to guess whether anything was sent.
    try:
        provider = get_selcom_business_client(payout.get("environment"))
    except SelcomBusinessMisconfiguredError as exc:
        logger.error(
            "payout_dispatch_misconfigured id=%s environment=%s error=%s",
            payout_id,
            payout.get("environment"),
            exc,
        )
        return payout.get("status", "unknown")

    claimed = _claim_for_dispatch(client, payout)
    if claimed is None:
        logger.info("payout_dispatch_skipped id=%s reason=already_claimed", payout_id)
        return payout.get("status", "unknown")

    beneficiary = get_by_id(client, "payout_beneficiaries", uuid.UUID(claimed["beneficiary_id"]))
    if not beneficiary:
        # Cannot happen through the API - create_payout resolves the
        # beneficiary first - so this is a deleted row or a bad backfill.
        # The reserve stays held: we do not know whether a previous
        # attempt reached the provider.
        return _park_for_reconciliation(
            client,
            payout=claimed,
            failure_code="beneficiary_missing",
            failure_reason="The beneficiary record could not be read.",
        )

    try:
        result: SelcomBusinessResult = await provider.process_transaction(
            trans_id=claimed["provider_reference"],
            recipient_fi_code=beneficiary["destination_code"],
            recipient_account=beneficiary["destination_identifier"],
            recipient_name=beneficiary["name"],
            amount=str(claimed["amount"]),
            # "FT" (Funds transfer), NOT "payout".
            #
            # Selcom's live API validates purpose against a fixed
            # enumerated list and answers error_code 651, "The selected
            # purpose is invalid", for anything else. Their sandbox
            # accepts arbitrary free text, so nothing catches this until
            # a real call.
            #
            # This exact mistake has now been made twice. Withdrawals
            # shipped with purpose="withdrawal" and failed on their first
            # production call; the comment recording that sits in
            # disbursements.py, and this module was written with
            # purpose="payout" anyway. The first live payout - TZS 1,000
            # of real money - failed on it, and so did every sandbox
            # attempt before it, which is why the sandbox endpoint looked
            # like the culprit.
            purpose="FT",
            remarks=f"InfinityPay payout {claimed['provider_reference']}",
        )
    except Exception as exc:  # noqa: BLE001 - any provider error is "unknown", never "failed"
        # The critical distinction in this module. An exception means the
        # request may have been received and acted on; it is NOT evidence
        # the payout did not happen, so the reserve must not be released.
        logger.warning(
            "payout_dispatch_error id=%s error=%s", payout_id, type(exc).__name__
        )
        return _park_for_reconciliation(
            client,
            payout=claimed,
            failure_code="provider_unreachable",
            failure_reason=f"The provider request did not complete ({type(exc).__name__}).",
        )

    return apply_provider_result(client, payout=claimed, result=result)


def apply_provider_result(
    client: Client, *, payout: dict, result: SelcomBusinessResult
) -> str:
    """Turn one provider answer into one money decision.

    Shared by dispatch, reconciliation and the inbound callback, so all
    three agree about what a given status means - and all three are
    replay-safe, because each branch transitions conditionally from
    `processing` or `needs_reconciliation` and posts entries only if that
    transition was the one that won.
    """
    payout_id = uuid.UUID(payout["id"])
    from_status = payout["status"]

    if from_status in TERMINAL_STATUSES:
        logger.info(
            "payout_result_ignored id=%s status=%s reason=already_terminal", payout_id, from_status
        )
        return from_status

    if result.status == "successful":
        return _settle(client, payout=payout, result=result)
    if result.status == "failed":
        return _release(client, payout=payout, result=result)

    # "processing" and "ambiguous" are both unknown outcomes.
    return _park_for_reconciliation(
        client,
        payout=payout,
        failure_code="awaiting_provider",
        failure_reason=result.failure_reason or "The provider has not confirmed this payout yet.",
        raw_response=result.raw_response,
    )


def _emit_payout_event(client: Client, *, payout: dict, event_name: str) -> None:
    """Tell the merchant what happened to one payout.

    Only terminal outcomes. A payout in flight has nothing to report,
    and needs_reconciliation in particular means "we do not know yet" -
    telling a partner about that invites exactly the retry that pays
    twice.

    The `environment` field is in the payload and it matters: there is
    one webhook URL per merchant, with no sandbox/live separation, so a sandbox
    payout notifies the same endpoint a live one does. A receiver that
    ignores this field will credit a customer for money that never
    moved. The docs say so in as many words.

    Best-effort by design, like every other emit in this codebase: a
    webhook that cannot be queued must never unwind a money decision
    that has already been posted to the ledger.
    """
    try:
        enqueue_webhook_event(
            client,
            merchant_id=uuid.UUID(payout["merchant_id"]),
            event_name=event_name,
            payload={
                "payout_id": payout["id"],
                "reference": payout.get("provider_reference"),
                "status": payout.get("status"),
                "environment": payout.get("environment"),
                "amount": str(payout.get("amount")),
                "fee_amount": str(payout.get("fee_amount")),
                "total_debit": str(payout.get("total_debit")),
                "currency": payout.get("currency"),
                "beneficiary_id": payout.get("beneficiary_id"),
                "failure_code": payout.get("failure_code"),
                "failure_reason": payout.get("failure_reason"),
            },
        )
    except Exception:
        logger.exception("payout_webhook_enqueue_failed id=%s event=%s", payout.get("id"), event_name)


def _settle(client: Client, *, payout: dict, result: SelcomBusinessResult) -> str:
    payout_id = uuid.UUID(payout["id"])
    transaction_id = _parent_transaction_id(client, payout_id)
    if transaction_id is None:
        logger.error("payout_settle_no_transaction id=%s", payout_id)
        return payout["status"]

    moved = _transition(
        client,
        payout_id=payout_id,
        expected_status=payout["status"],
        changes={
            "status": "successful",
            "provider_transid": result.receipt or result.transaction_id,
            "provider_raw_response": result.raw_response or None,
            "failure_code": None,
            "failure_reason": None,
            "completed_at": _now().isoformat(),
            "next_check_at": None,
        },
    )
    if moved is None:
        # Someone else resolved it between our read and our write. Posting
        # the settlement anyway would double-debit the reserve.
        logger.info("payout_settle_skipped id=%s reason=lost_the_transition", payout_id)
        return payout["status"]

    post_payout_settlement(
        client,
        transaction_id=transaction_id,
        merchant_id=uuid.UUID(payout["merchant_id"]),
        amount=Decimal(str(payout["amount"])),
        currency=payout["currency"],
        environment=payout["environment"],
        fee_amount=Decimal(str(payout["fee_amount"])),
    )
    client.table("transactions").update({"status": "successful"}).eq(
        "id", str(transaction_id)
    ).execute()
    logger.info("payout_settled id=%s amount=%s", payout_id, payout["amount"])
    _emit_payout_event(client, payout={**payout, **(moved or {})}, event_name="payout.success")
    return "successful"


def _release(client: Client, *, payout: dict, result: SelcomBusinessResult) -> str:
    """A payout the provider says it did NOT pay.

    Only reached for an explicit `failed`. Everything uncertain goes to
    reconciliation with the funds still held, because releasing a reserve
    for a payout that actually went out is how the platform ends up
    covering the difference.
    """
    payout_id = uuid.UUID(payout["id"])
    transaction_id = _parent_transaction_id(client, payout_id)
    if transaction_id is None:
        logger.error("payout_release_no_transaction id=%s", payout_id)
        return payout["status"]

    moved = _transition(
        client,
        payout_id=payout_id,
        expected_status=payout["status"],
        changes={
            "status": "failed",
            "failure_code": "provider_declined",
            "failure_reason": result.failure_reason or "The provider declined this payout.",
            "provider_raw_response": result.raw_response or None,
            "completed_at": _now().isoformat(),
            "next_check_at": None,
        },
    )
    if moved is None:
        logger.info("payout_release_skipped id=%s reason=lost_the_transition", payout_id)
        return payout["status"]

    post_payout_release(
        client,
        transaction_id=transaction_id,
        merchant_id=uuid.UUID(payout["merchant_id"]),
        total_debit=Decimal(str(payout["total_debit"])),
        currency=payout["currency"],
        environment=payout["environment"],
    )
    client.table("transactions").update({"status": "failed"}).eq(
        "id", str(transaction_id)
    ).execute()
    logger.info("payout_released id=%s total_debit=%s", payout_id, payout["total_debit"])
    _emit_payout_event(client, payout={**payout, **(moved or {})}, event_name="payout.failed")
    return "failed"


def _park_for_reconciliation(
    client: Client,
    *,
    payout: dict,
    failure_code: str,
    failure_reason: str,
    raw_response: dict | None = None,
) -> str:
    """Unknown outcome. The reserve stays held; nothing is posted.

    `needs_reconciliation` is not a failure state and must never be read
    as one. The money is still committed, which is the only safe reading
    of "we do not know".
    """
    payout_id = uuid.UUID(payout["id"])
    attempts = int(payout.get("dispatch_attempts") or 0)

    moved = _transition(
        client,
        payout_id=payout_id,
        expected_status=payout["status"],
        changes={
            "status": "needs_reconciliation",
            "failure_code": failure_code,
            "failure_reason": failure_reason,
            "provider_raw_response": raw_response or None,
            "next_check_at": _backoff_for(attempts).isoformat(),
        },
    )
    if moved is None:
        return payout["status"]

    logger.warning(
        "payout_needs_reconciliation id=%s code=%s attempts=%s", payout_id, failure_code, attempts
    )
    return "needs_reconciliation"


async def reconcile_payout(client: Client, payout: dict) -> str:
    """Ask the provider again about a payout we could not resolve.

    Reads rather than sends: `query_transaction`, never
    `process_transaction`. Re-sending a payout whose outcome is unknown
    is the one action that can actually pay twice.
    """
    payout_id = uuid.UUID(payout["id"])
    # Same environment rule as dispatch. Asking the wrong Selcom about a
    # reference it has never seen returns "not found", which this would
    # read as a real answer about a payout that is in fact outstanding.
    try:
        provider = get_selcom_business_client(payout.get("environment"))
    except SelcomBusinessMisconfiguredError as exc:
        logger.error(
            "payout_reconcile_misconfigured id=%s environment=%s error=%s",
            payout_id,
            payout.get("environment"),
            exc,
        )
        return payout.get("status", "needs_reconciliation")
    try:
        result = await provider.query_transaction(trans_id=payout["provider_reference"])
    except Exception as exc:  # noqa: BLE001 - still unknown, so still held
        logger.warning("payout_reconcile_error id=%s error=%s", payout_id, type(exc).__name__)
        attempts = int(payout.get("dispatch_attempts") or 0) + 1
        client.table("payouts").update(
            {"dispatch_attempts": attempts, "next_check_at": _backoff_for(attempts).isoformat()}
        ).eq("id", str(payout_id)).eq("status", "needs_reconciliation").execute()
        return "needs_reconciliation"

    return apply_provider_result(client, payout=payout, result=result)


async def sweep_payouts(client: Client, *, limit: int = 50) -> dict[str, int]:
    """One pass: dispatch what is authorised, chase what is unresolved.

    Returns a count per outcome. Ordered oldest-first so a backlog drains
    in the order partners created it rather than newest-first, which would
    starve the oldest payout indefinitely.
    """
    counts: dict[str, int] = {}

    to_dispatch = (
        client.table("payouts")
        .select("*")
        .eq("status", "processing")
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    ).data or []

    for payout in to_dispatch:
        outcome = await dispatch_payout(client, payout)
        counts[outcome] = counts.get(outcome, 0) + 1

    due = (
        client.table("payouts")
        .select("*")
        .eq("status", "needs_reconciliation")
        .lte("next_check_at", _now().isoformat())
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    ).data or []

    for payout in due:
        outcome = await reconcile_payout(client, payout)
        key = f"reconciled_{outcome}"
        counts[key] = counts.get(key, 0) + 1

    return counts


def release_parked_payout(
    client: Client, *, payout_id: uuid.UUID, reason: str, actor_id: uuid.UUID | None
) -> dict:
    """Give back the reserve on a payout parked in reconciliation.

    THE MOST DANGEROUS OPERATION IN THIS MODULE. Everything else that
    releases funds does so because the provider said, in so many words,
    that it did not pay. This releases on a human's judgement instead,
    and if that judgement is wrong the money went out AND went back to
    the merchant, and the platform covers the difference.

    It exists because the alternative is worse. A payout can park
    forever - ours did, against a sandbox endpoint that 404s - and until
    now the only way to free the funds was to edit the database by hand:
    no validation, no audit entry, no record of who decided. The same
    argument as granting live access. A deliberate route that leaves a
    trail beats a forbidden one people work around.

    Two guards, and they are the whole safety of it:

    * Only from `needs_reconciliation`. A `processing` payout may be
      mid-flight at the provider this second.
    * Only when the payout carries NO provider_transid and NO
      provider_raw_response. Either one means the provider acknowledged
      it, and an acknowledged payout must be resolved by asking them -
      never by assuming.

    The caller is responsible for having checked with the provider. The
    reason is stored and audited because that check is the only thing
    standing behind this.
    """
    payout = get_by_id(client, "payouts", payout_id)
    if not payout:
        raise NotFoundError("Payout not found")

    if payout["status"] != "needs_reconciliation":
        raise ConflictError(
            f"This payout is {payout['status']}, not needs_reconciliation. Only a parked "
            "payout can be released."
        )
    if payout.get("provider_transid") or payout.get("provider_raw_response"):
        raise ConflictError(
            "The provider has acknowledged this payout, so it may have been paid. Resolve it "
            "with the provider rather than releasing the funds here."
        )

    transaction_id = _parent_transaction_id(client, payout_id)
    if transaction_id is None:
        raise ConflictError("This payout has no transaction behind it; its funds cannot be traced.")

    moved = _transition(
        client,
        payout_id=payout_id,
        expected_status="needs_reconciliation",
        changes={
            "status": "failed",
            "failure_code": "released_by_admin",
            "failure_reason": reason,
            "completed_at": _now().isoformat(),
            "next_check_at": None,
        },
    )
    if moved is None:
        raise ConflictError("This payout changed while you were looking at it. Reload and check again.")

    post_payout_release(
        client,
        transaction_id=transaction_id,
        merchant_id=uuid.UUID(payout["merchant_id"]),
        total_debit=Decimal(str(payout["total_debit"])),
        currency=payout["currency"],
        environment=payout["environment"],
    )
    client.table("transactions").update({"status": "failed"}).eq("id", str(transaction_id)).execute()

    write_audit_log(
        client,
        actor_id=actor_id,
        actor_type="user" if actor_id else "system",
        merchant_id=uuid.UUID(payout["merchant_id"]),
        action="payout.reserve_released",
        resource_type="payouts",
        resource_id=payout_id,
        metadata={
            "total_debit": str(payout["total_debit"]),
            "currency": payout["currency"],
            "environment": payout["environment"],
            "previous_failure_code": payout.get("failure_code"),
            "reason": reason,
        },
    )
    logger.warning(
        "payout_reserve_released_by_admin id=%s total_debit=%s actor=%s",
        payout_id,
        payout["total_debit"],
        actor_id,
    )
    # The merchant is told, same as any other confirmed failure. They
    # have money back and a payout that will never complete; finding
    # that out by polling days later is not good enough.
    _emit_payout_event(client, payout={**payout, **moved}, event_name="payout.failed")
    return moved
