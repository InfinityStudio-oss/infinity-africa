"""Deciding that a merchant should get an SMS, and freezing what it says.

This module runs on the payment path, so its first duty is to never be the
reason a payment fails. Every public function here swallows its own
errors: a collection that is credited, webhooked and audited correctly but
produces no SMS row is a missing text message, while an exception escaping
into resolve_collection() would be a payment that appears to fail after
the money has already moved.

**Who receives.** The merchant, and only the merchant. The number comes
from merchant_notification_settings.sms_notification_phone, falling back
to merchants.contact_phone. collections.customer_phone is never read in
this file, and sms_messages has no column that could store it.

**What it says.** The amounts are copied from the committed transaction
and the closing balance from that posting's own immutable
ledger_entries.balance_after. They are frozen into the row before the
first send attempt and never recomputed, so a withdrawal five minutes
later cannot change the number in a message already queued.
"""

import logging
import uuid
from decimal import Decimal

from supabase import Client

from app.config import get_settings
from app.core.phone import normalize_tz_phone
from app.core.time import utc_now_iso
from app.services.sms_text import message_cost, render_collection_alert

logger = logging.getLogger("infinity.sms")

# Why a merchant got no alert, in words an operator can act on. These
# surface in the Super Admin SMS screen; they are not error strings.
SKIP_NO_NUMBER = "No notification number on file for this merchant"
SKIP_INVALID_NUMBER = "The notification number on file is not a valid Tanzanian number"
SKIP_MERCHANT_DISABLED = "This merchant has collection SMS switched off"
SKIP_NO_BALANCE_SNAPSHOT = (
    "No closing-balance snapshot exists for this posting, so the balance "
    "line could not be stated accurately"
)
SKIP_NO_SENDER = "No approved sender ID is configured"


def _settings_row(client: Client, merchant_id: uuid.UUID) -> dict:
    rows = (
        client.table("merchant_notification_settings")
        .select("collection_sms_enabled,announcement_sms_enabled,sms_notification_phone")
        .eq("merchant_id", str(merchant_id))
        .execute()
        .data
        or []
    )
    return rows[0] if rows else {}


def resolve_recipient(client: Client, merchant_id: uuid.UUID) -> tuple[str | None, str | None]:
    """The merchant's own notification number, or why there isn't one.

    Returns ``(phone, skip_reason)`` with exactly one of the two set.
    Falls back to merchants.contact_phone because every merchant already
    has one and it is the number support already calls - requiring a
    separate opt-in number before anybody can receive anything would make
    the feature arrive switched off for all 60.
    """
    row = _settings_row(client, merchant_id)
    raw = (row.get("sms_notification_phone") or "").strip()

    if not raw:
        merchant = (
            client.table("merchants")
            .select("contact_phone")
            .eq("id", str(merchant_id))
            .execute()
            .data
            or []
        )
        raw = ((merchant[0] if merchant else {}).get("contact_phone") or "").strip()

    if not raw:
        return None, SKIP_NO_NUMBER

    try:
        return normalize_tz_phone(raw), None
    except Exception:  # noqa: BLE001 — an unusable number is a skip, not a crash
        return None, SKIP_INVALID_NUMBER


def collection_sms_enabled_for(client: Client, merchant_id: uuid.UUID) -> bool:
    row = _settings_row(client, merchant_id)
    # Absent row means the merchant has never opened notification
    # settings. The column defaults to false, and so does this.
    return bool(row.get("collection_sms_enabled"))


def _idempotency_key(purpose: str, anchor: uuid.UUID) -> str:
    """Stable, derived, and inside the provider's documented format
    (1-64 visible ASCII, no spaces).

    Derived from the collection rather than random, so the key for a given
    collection is the same key no matter which code path composed it. That
    is what makes a retry a retry: the provider recognises it, replays the
    original response and charges nothing, instead of sending a second
    message to a merchant who already has one.
    """
    return f"ipay-{purpose}-{anchor.hex}"


def _insert(client: Client, row: dict) -> dict | None:
    try:
        result = client.table("sms_messages").insert(row).execute()
        return (result.data or [None])[0]
    except Exception as exc:  # noqa: BLE001
        # The overwhelmingly likely cause is the partial unique index on
        # (collection_id, merchant_id, purpose) doing its job: the Selcom
        # callback and the reconciliation sweep resolved the same
        # collection at the same moment and both got here. One alert is
        # the correct outcome, so losing this race is success.
        logger.info("sms_enqueue_skipped reason=duplicate_or_rejected error=%s", type(exc).__name__)
        return None


def enqueue_collection_alert(
    client: Client,
    *,
    collection: dict,
    transaction: dict,
    closing_balance: Decimal | None,
) -> dict | None:
    """Queue one merchant alert for a collection that has been credited.

    Called only after post_collection_entries has committed, so by the
    time this runs the money has moved and the balance snapshot exists.
    `closing_balance` is that posting's own ledger_entries.balance_after,
    handed down rather than looked up - re-reading the wallet here would
    return whatever the balance happens to be now, which is the one thing
    the brief forbids.

    Returns the queued row, a skipped row, or None (already queued, or
    nothing to do). Never raises.
    """
    try:
        settings = get_settings()
        merchant_id = uuid.UUID(collection["merchant_id"])
        collection_id = uuid.UUID(collection["id"])

        # Globally off: no row at all, deliberately. Writing a skipped row
        # per collection while the feature is dark would add thousands of
        # rows that say nothing (GodyNet alone has over 2000 collections),
        # and leaving them queued would mean switching SMS on later blasts
        # a backlog of historical payments - the backfill the brief rules
        # out. Nothing enqueued while off means nothing to send when on.
        if not settings.oasis_sms_enabled:
            return None

        # Past this point a row is always written, including for skips:
        # once the feature is live, "this merchant is getting no alerts
        # and here is why" is exactly what an operator needs to see.
        if not collection_sms_enabled_for(client, merchant_id):
            return _skip(client, merchant_id, collection_id, transaction, SKIP_MERCHANT_DISABLED)

        if not settings.oasis_sms_sender_id:
            return _skip(client, merchant_id, collection_id, transaction, SKIP_NO_SENDER)

        phone, skip_reason = resolve_recipient(client, merchant_id)
        if skip_reason:
            return _skip(client, merchant_id, collection_id, transaction, skip_reason)

        if closing_balance is None:
            # Pre-2026-08-28 postings have no snapshot, and the migration
            # that added the column is explicit that there is no sound way
            # to reconstruct one. Stating a balance we inferred would be
            # worse than stating none, so the merchant gets no SMS and the
            # operator gets a reason.
            return _skip(client, merchant_id, collection_id, transaction, SKIP_NO_BALANCE_SNAPSHOT)

        gross = Decimal(str(transaction["gross_amount"]))
        fee = Decimal(str(transaction["fee_amount"]))
        net = Decimal(str(transaction["net_amount"]))
        reference = transaction["reference"]

        body = render_collection_alert(
            gross_amount=gross,
            fee_amount=fee,
            net_amount=net,
            closing_balance=closing_balance,
            reference=reference,
        )
        cost = message_cost(body)

        return _insert(
            client,
            {
                "merchant_id": str(merchant_id),
                "purpose": "collection_alert",
                "collection_id": str(collection_id),
                "transaction_id": transaction["id"],
                "recipient_phone": phone,
                "sender_id": settings.oasis_sms_sender_id,
                "body": body,
                "currency": transaction.get("currency") or "TZS",
                "gross_amount": str(gross),
                "fee_amount": str(fee),
                "net_amount": str(net),
                "closing_balance": str(closing_balance),
                "reference": reference,
                "status": "queued",
                "next_attempt_at": utc_now_iso(),
                "idempotency_key": _idempotency_key("c", collection_id),
                "segments": cost["segments"],
                "encoding": cost["encoding"],
            },
        )
    except Exception:  # noqa: BLE001 — never break the payment path
        logger.warning("sms_enqueue_failed collection_id=%s", collection.get("id"))
        return None


def _skip(
    client: Client,
    merchant_id: uuid.UUID,
    collection_id: uuid.UUID,
    transaction: dict,
    reason: str,
) -> dict | None:
    """A row recording that nothing was sent, and why.

    Carries no body and no recipient - there was no message and, in the
    no-number case, nobody to send it to. It still takes an idempotency
    key because the unique index covers every row, and a stable key here
    means the same skip is recorded once rather than on every retry of the
    same collection.
    """
    return _insert(
        client,
        {
            "merchant_id": str(merchant_id),
            "purpose": "collection_alert",
            "collection_id": str(collection_id),
            "transaction_id": transaction.get("id"),
            "recipient_phone": "",
            "sender_id": get_settings().oasis_sms_sender_id or "-",
            "body": "",
            "status": "skipped",
            "skipped_reason": reason,
            "reference": transaction.get("reference"),
            "idempotency_key": _idempotency_key("c", collection_id),
        },
    )
