"""Deciding that a merchant should get an SMS, and freezing what it says.

Two automatic messages, each once in a merchant's life with us:

  * **welcome** - after their first approval. Not on signup; an account
    that exists is not an account that can trade.
  * **withdrawal_complete** - after a payout the provider has actually
    confirmed. Not on request, reservation, OTP, approval or acceptance.

A third kind, **announcement**, is composed by a Super Admin by hand and
lives in sms_campaigns.

**Collection alerts were retired on 2026-10-17.** They worked - proven
end to end the evening before - and were withdrawn for cost: 3,748
payments in the first sixteen days of October is roughly 230 messages a
day, growing with volume, for information the merchant already receives
by email. The collection *emails* are untouched.

Everything here runs on a path where money has already moved, so every
public function swallows its own errors. A missing text message is a
missing text message; an exception escaping into a payout completion
would be a confirmed payout that looks like it failed.

**Who receives.** The merchant, and only the merchant. The number comes
from merchant_notification_settings.sms_notification_phone - which only a
Super Admin can set - falling back to merchants.contact_phone. No
customer number is read in this file, and sms_messages has no column that
could hold one.
"""

import logging
import uuid
from decimal import Decimal

from supabase import Client

from app.config import get_settings
from app.core.phone import normalize_tz_phone
from app.core.time import utc_now_iso
from app.services.sms_text import (
    message_cost,
    render_welcome,
    render_withdrawal_complete,
)

logger = logging.getLogger("infinity.sms")

# Why a merchant got no message, in words an operator can act on. These
# surface in the Super Admin SMS screen; they are not error strings.
SKIP_NO_NUMBER = "No notification number on file for this merchant"
SKIP_INVALID_NUMBER = "The notification number on file is not a valid Tanzanian number"
SKIP_NO_BALANCE_SNAPSHOT = (
    "No closing-balance snapshot exists for this withdrawal, so the balance "
    "line could not be stated accurately"
)
SKIP_NO_SENDER = "No approved sender ID is configured"


def _settings_row(client: Client, merchant_id: uuid.UUID) -> dict:
    rows = (
        client.table("merchant_notification_settings")
        .select("sms_notification_phone")
        .eq("merchant_id", str(merchant_id))
        .execute()
        .data
        or []
    )
    return rows[0] if rows else {}


def resolve_recipient(client: Client, merchant_id: uuid.UUID) -> tuple[str | None, str | None]:
    """The merchant's own notification number, or why there isn't one.

    Returns ``(phone, skip_reason)`` with exactly one of the two set.
    Falls back to merchants.contact_phone, which every merchant has and
    which is the number support already calls.

    Never reads a customer's number. The only two columns consulted are
    the Super-Admin-managed notification number and the merchant's own
    business contact number.
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


def _idempotency_key(purpose: str, anchor: uuid.UUID) -> str:
    """Stable, derived, and inside the provider's documented format
    (1-64 visible ASCII, no spaces).

    Derived from the merchant (welcome) or the payout
    (withdrawal_complete) rather than random, so the key for a given
    message is the same no matter which code path composed it. That is
    what makes a retry a retry: the provider recognises it, replays the
    original response and charges nothing, instead of sending a second
    message to a merchant who already has one.
    """
    return f"ipay-{purpose}-{anchor.hex}"


def _insert(client: Client, row: dict) -> dict | None:
    try:
        result = client.table("sms_messages").insert(row).execute()
        return (result.data or [None])[0]
    except Exception as exc:  # noqa: BLE001
        # Overwhelmingly likely to be one of the partial unique indexes
        # doing its job - a retried approval, or a payout confirmed by
        # both a callback and the reconciliation sweep at once. One
        # message is the correct outcome, so losing this race is success.
        logger.info("sms_enqueue_skipped reason=duplicate_or_rejected error=%s", type(exc).__name__)
        return None


def _base_row(merchant_id: uuid.UUID, purpose: str, phone: str, sender: str, body: str) -> dict:
    cost = message_cost(body)
    return {
        "merchant_id": str(merchant_id),
        "purpose": purpose,
        "recipient_phone": phone,
        "sender_id": sender,
        "body": body,
        "status": "queued",
        "next_attempt_at": utc_now_iso(),
        "segments": cost["segments"],
        "encoding": cost["encoding"],
    }


def _skip(
    client: Client, merchant_id: uuid.UUID, purpose: str, key: str, reason: str, **extra
) -> dict | None:
    """A row recording that nothing was sent, and why.

    Only written once the relevant automation is switched on and the
    merchant was genuinely due a message - so a skip always means
    "somebody should have been told something and was not", never "this
    feature is off".
    """
    return _insert(
        client,
        {
            "merchant_id": str(merchant_id),
            "purpose": purpose,
            "recipient_phone": "",
            "sender_id": get_settings().oasis_sms_sender_id or "-",
            "body": "",
            "status": "skipped",
            "skipped_reason": reason,
            "idempotency_key": key,
            **extra,
        },
    )


# --- welcome -----------------------------------------------------------



def enqueue_welcome_sms(client: Client, *, merchant_id: uuid.UUID) -> dict | None:
    """Queue the one welcome message, after a merchant's first approval.

    Called from the approval path only, so an account merely existing
    never triggers it. The unique index on (merchant_id) where
    purpose = 'welcome' is what makes a retried approval - or a later
    suspension and reactivation - a no-op rather than a second message.

    Returns the queued row, a skipped row, or None. Never raises.
    """
    try:
        settings = get_settings()
        if not settings.oasis_sms_enabled or not settings.oasis_sms_welcome_enabled:
            return None

        key = _idempotency_key("w", merchant_id)
        if not settings.oasis_sms_sender_id:
            return _skip(client, merchant_id, "welcome", key, SKIP_NO_SENDER)

        phone, skip_reason = resolve_recipient(client, merchant_id)
        if skip_reason or not phone:
            return _skip(client, merchant_id, "welcome", key, skip_reason or SKIP_NO_NUMBER)

        body = render_welcome()
        return _insert(
            client,
            {
                **_base_row(merchant_id, "welcome", phone, settings.oasis_sms_sender_id, body),
                "idempotency_key": key,
            },
        )
    except Exception:  # noqa: BLE001 — never break an approval
        logger.warning("sms_welcome_enqueue_failed merchant_id=%s", merchant_id)
        return None


# --- completed withdrawal ----------------------------------------------


def enqueue_withdrawal_complete_sms(
    client: Client, *, disbursement: dict, transaction: dict | None
) -> dict | None:
    """Queue the one confirmation for a payout the provider has confirmed.

    Called only from the branches where a disbursement actually reaches
    SUCCESS - never on creation, reservation, OTP, Super Admin approval,
    provider acceptance, pending processing or failure.

    **The closing balance comes from the reservation, not from now.** The
    wallet is debited when the withdrawal is approved
    (_reserve_and_run_disbursement_provider), which can be minutes or
    hours before the provider confirms. The balance that debit produced
    lives on its immutable ledger entry; reading the wallet at this
    moment would report whatever is there after any collections that
    landed in between. Nothing here posts a second debit.

    Returns the queued row, a skipped row, or None. Never raises.
    """
    try:
        settings = get_settings()
        if not settings.oasis_sms_enabled or not settings.oasis_sms_withdrawal_enabled:
            return None

        merchant_id = uuid.UUID(disbursement["merchant_id"])
        disbursement_id = uuid.UUID(disbursement["id"])
        key = _idempotency_key("d", disbursement_id)
        extra = {"disbursement_id": str(disbursement_id)}

        if not settings.oasis_sms_sender_id:
            return _skip(client, merchant_id, "withdrawal_complete", key, SKIP_NO_SENDER, **extra)

        phone, skip_reason = resolve_recipient(client, merchant_id)
        if skip_reason or not phone:
            return _skip(
                client,
                merchant_id,
                "withdrawal_complete",
                key,
                skip_reason or SKIP_NO_NUMBER,
                **extra,
            )

        if not transaction:
            return _skip(
                client, merchant_id, "withdrawal_complete", key, SKIP_NO_BALANCE_SNAPSHOT, **extra
            )

        currency = disbursement.get("currency") or "TZS"
        from app.services.ledger import committed_wallet_balance_after

        closing_balance = committed_wallet_balance_after(
            client,
            transaction_id=uuid.UUID(transaction["id"]),
            merchant_id=merchant_id,
            currency=currency,
        )
        if closing_balance is None:
            # Payouts predating the snapshot columns have none, and the
            # migration that added them is explicit that there is no
            # sound way to reconstruct one. Stating a balance we inferred
            # would be worse than stating none.
            return _skip(
                client, merchant_id, "withdrawal_complete", key, SKIP_NO_BALANCE_SNAPSHOT, **extra
            )

        # What the merchant asked to withdraw, and what they were
        # actually charged for it - both read, neither derived. The fee
        # is rendered as it stands, so "Ada: TZS 0" appears only when it
        # really was nothing.
        amount = Decimal(str(disbursement["amount"]))
        fee_amount = Decimal(str(disbursement.get("total_charges") or "0"))
        reference = transaction.get("reference") or ""

        body = render_withdrawal_complete(
            amount=amount,
            fee_amount=fee_amount,
            closing_balance=closing_balance,
            reference=reference,
        )
        return _insert(
            client,
            {
                **_base_row(
                    merchant_id, "withdrawal_complete", phone, settings.oasis_sms_sender_id, body
                ),
                "idempotency_key": key,
                "disbursement_id": str(disbursement_id),
                "transaction_id": transaction["id"],
                "currency": currency,
                "gross_amount": str(amount),
                "fee_amount": str(fee_amount),
                "net_amount": str(amount),
                "closing_balance": str(closing_balance),
                "reference": reference,
            },
        )
    except Exception:  # noqa: BLE001 — never break a completed payout
        logger.warning("sms_withdrawal_enqueue_failed disbursement_id=%s", disbursement.get("id"))
        return None
