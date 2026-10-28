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

import hashlib
import logging
import uuid
from decimal import Decimal

from supabase import Client

from app.config import get_settings
from app.core.phone import normalize_tz_phone
from app.core.time import utc_now_iso
from app.services.sms_text import (
    message_cost,
    render_new_merchant_admin,
    render_welcome,
    render_withdrawal_complete,
    render_withdrawal_request_admin,
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


LIMIT = 64

# Short codes for the purposes whose own name is too long to spell out
# inside the limit. 'admin_withdrawal_request' alone is 24 characters,
# and with the prefix, a 32-character anchor and a recipient's digits it
# produced a 75-character key - which the provider rejected, correctly
# and every time. Five identical retries later the first live operator
# alert was marked failed, with the row still looking perfectly healthy
# in the database. The docstring below had claimed the key stayed inside
# the format since the day it was written; nothing measured it.
_SHORT = {
    "admin_new_merchant": "anm",
    "admin_withdrawal_request": "awr",
}


def _bounded(candidate: str) -> str:
    """The provider's documented format, enforced here rather than
    discovered there.

    A key over the limit is a message that cannot be sent no matter how
    often it is retried, so the length is not a provider problem to find
    out about - it is ours to not produce. Over the limit the readable
    form is replaced by a digest of itself, which is still derived purely
    from the same inputs and so is still the same key every time the same
    message is composed.
    """
    if len(candidate) <= LIMIT:
        return candidate
    return "ipay-" + hashlib.sha256(candidate.encode("ascii", "ignore")).hexdigest()[:48]


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
    return _bounded(f"ipay-{_SHORT.get(purpose, purpose)}-{anchor.hex}")


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


# --- Super Admin alerts ------------------------------------------------
#
# Addressed to an operator, not to a merchant. merchant_id keeps its
# meaning but as the SUBJECT of the alert, and recipient_role says who it
# is actually for - see the 20261028090000 migration for why the
# administrator is not pretended into the merchant model.
#
# Both follow the same contract as every other enqueue here: never raise.
# A registration and a withdrawal are already committed by the time these
# run, and a message about them must not be able to undo either.

SKIP_NO_ADMIN_RECIPIENT = "no Super Admin SMS recipient configured"


def _admin_idempotency_key(purpose: str, anchor: uuid.UUID, phone: str) -> str:
    """Stable per purpose, per subject, AND per recipient.

    The recipient is in the key because configuring a second operator
    number must deliver a second message, not be swallowed as a duplicate
    of the first. Digits only, so no separator a number was configured
    with can put a space into the key, and _bounded keeps the whole thing
    inside the provider's documented 1-64 visible-ASCII format.
    """
    digits = "".join(ch for ch in phone if ch.isdigit())
    return _bounded(f"ipay-{_SHORT.get(purpose, purpose)}-{anchor.hex}-{digits}")


def _admin_rows(
    client: Client,
    *,
    purpose: str,
    merchant_id: uuid.UUID,
    anchor: uuid.UUID,
    body: str,
    **extra,
) -> list[dict]:
    """One row per configured operator number.

    Returns the rows actually written. An unusable number is recorded as a
    skip with a reason rather than silently dropped: a missing or
    malformed operator number must be visible to whoever reads the Super
    Admin SMS screen, without that visibility costing a registration or a
    withdrawal.
    """
    settings = get_settings()
    sender = settings.oasis_sms_sender_id or "-"
    numbers = settings.super_admin_sms_numbers
    if not numbers:
        key = _admin_idempotency_key(purpose, anchor, "")
        row = _skip(client, merchant_id, purpose, key, SKIP_NO_ADMIN_RECIPIENT, **extra)
        return [row] if row else []

    written: list[dict] = []
    for raw in numbers:
        key = _admin_idempotency_key(purpose, anchor, raw)
        try:
            phone = normalize_tz_phone(raw)
        except Exception:  # noqa: BLE001 - an unusable number is a skip, not a crash
            phone = None
        if not phone:
            row = _skip(client, merchant_id, purpose, key, SKIP_INVALID_NUMBER, **extra)
        else:
            row = _insert(
                client,
                {
                    **_base_row(merchant_id, purpose, phone, sender, body),
                    "idempotency_key": key,
                    "recipient_role": "super_admin",
                    **extra,
                },
            )
        if row:
            written.append(row)
    return written


def enqueue_admin_new_merchant_sms(
    client: Client, *, merchant_id: uuid.UUID, business_name: str
) -> list[dict]:
    """Tell an operator a business has registered.

    Called once, from the branch of create_merchant_onboarding that
    actually inserts a merchants row - so a resubmission, which updates an
    existing merchant and returns before that insert, produces nothing.

    Registered is not approved: the row is written `status='pending'`,
    `kyc_status='unverified'`, and the message says so. This never changes
    either.
    """
    settings = get_settings()
    if not (settings.super_admin_sms_enabled and settings.super_admin_sms_new_merchant_enabled):
        return []
    try:
        return _admin_rows(
            client,
            purpose="admin_new_merchant",
            merchant_id=merchant_id,
            anchor=merchant_id,
            body=render_new_merchant_admin(business_name=business_name),
        )
    except Exception:
        logger.exception("admin_new_merchant_sms_enqueue_failed merchant_id=%s", merchant_id)
        return []


def enqueue_admin_withdrawal_request_sms(
    client: Client, *, disbursement: dict, business_name: str, available_balance: Decimal
) -> list[dict]:
    """Tell an operator a withdrawal is waiting for them.

    The caller is responsible for only calling this once the withdrawal
    has come to rest at PENDING_ADMIN_APPROVAL - a rejected or
    auto-processed payout never reaches that state, so it never produces
    one of these. This function re-checks the status anyway, because a
    message that says "awaiting your approval" about something already
    paid is worse than no message.

    Amount is the Decimal from the committed row; nothing is recomputed
    here and nothing passes through a float.
    """
    settings = get_settings()
    if not (settings.super_admin_sms_enabled and settings.super_admin_sms_withdrawal_request_enabled):
        return []
    try:
        if str(disbursement.get("status")) != "PENDING_ADMIN_APPROVAL":
            return []
        disbursement_id = uuid.UUID(str(disbursement["id"]))
        merchant_id = uuid.UUID(str(disbursement["merchant_id"]))
        return _admin_rows(
            client,
            purpose="admin_withdrawal_request",
            merchant_id=merchant_id,
            anchor=disbursement_id,
            body=render_withdrawal_request_admin(
                business_name=business_name,
                amount=Decimal(str(disbursement.get("amount") or 0)),
                # provider_reference is assigned when the payout runs, so
                # at PENDING_ADMIN_APPROVAL it is null. The first eight
                # characters of the id are what the Super Admin withdrawals
                # queue shows and are enough to find the row; the full UUID
                # would cost a third segment and is unreadable on a handset.
                reference=str(
                    disbursement.get("provider_reference") or str(disbursement["id"])[:8]
                ),
                # The same figure the approval email already quotes, taken
                # from the same read, so the two can never disagree about
                # what an operator was told. Display-only: nothing reads
                # it back to authorize a payout.
                available_balance=available_balance,
            ),
            disbursement_id=str(disbursement_id),
        )
    except Exception:
        logger.exception(
            "admin_withdrawal_sms_enqueue_failed disbursement_id=%s", disbursement.get("id")
        )
        return []
