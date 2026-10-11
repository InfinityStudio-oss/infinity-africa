"""Merchant referrals: issuing codes, capturing who used one, and opening
the earning window when the referred business is approved.

The money is calculated elsewhere (app/services/referral_commissions.py).
Nothing in this module pays anything or touches a wallet.

Two rules run through all of it:

**A referral is an attribution, not an entitlement.** Using a code creates
a row that is worth nothing. It becomes worth something only if a Super
Admin approves the referred business, that business then trades past a
volume floor inside its first 30 days, and a Super Admin approves the
resulting commission. Signing people up earns nobody anything, which is
the whole point of the design.

**Capture must never break a signup.** A referral is a marketing feature
sitting on the path of someone creating a real business account. A bad,
disabled, self-referring or unknown code is recorded and ignored; it never
turns into a failed signup. The only thing that can stop a signup is the
signup's own validation.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from supabase import Client

from app.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationAPIError
from app.core.time import utc_now_iso
from app.services.audit import write_audit_log, write_audit_log_best_effort
from app.services.crud import execute_maybe_single, get_by_id, insert_row, update_row
from app.services.referral_code import generate_referral_code, normalise_referral_code

logger = logging.getLogger("infinity.referrals")

# A merchant must be trading in good standing to invite anyone or to be
# earned from. Mirrors merchants.status in
# supabase/migrations/..._merchants.sql — 'pending', 'suspended' and
# 'closed' all mean "not now".
_ACTIVE = "active"

# Statuses in merchant_referrals that no longer accrue. Kept here rather
# than scattered so the daily job and the admin views agree on what
# "finished" means.
TERMINAL_STATUSES = frozenset(
    {
        "ineligible",
        "expired",
        "commission_approved",
        "commission_paid",
        "commission_rejected",
    }
)


def _merchant(client: Client, merchant_id: uuid.UUID) -> dict:
    merchant = get_by_id(client, "merchants", merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")
    return merchant


# --- Codes -----------------------------------------------------------------


def issue_referral_code(client: Client, *, merchant_id: uuid.UUID, actor_id: uuid.UUID | None) -> dict:
    """Gives a merchant their code, or returns the one they already have.

    Idempotent: asking twice does not rotate the code, because a rotated
    code would silently orphan every poster and WhatsApp message already
    carrying the old one.

    Only an active merchant gets one. A pending business handing out
    invite links before anyone has checked who they are is exactly the
    shape of a referral farm.
    """
    merchant = _merchant(client, merchant_id)

    if merchant.get("referral_code"):
        return merchant

    if merchant.get("status") != _ACTIVE:
        raise ValidationAPIError(
            "Your account needs to be approved before you can invite other businesses."
        )

    updated = update_row(
        client,
        "merchants",
        merchant_id,
        {
            "referral_code": generate_referral_code(client),
            "referral_code_created_at": utc_now_iso(),
            "referral_code_status": "active",
        },
    )

    write_audit_log(
        client,
        actor_id=actor_id,
        actor_type="user" if actor_id else "system",
        merchant_id=merchant_id,
        action="referral.code_created",
        resource_type="merchant",
        resource_id=merchant_id,
        # The code is an identifier, not a secret, and an audit of "a code
        # was created" that does not say which one is not an audit.
        metadata={"referral_code": updated["referral_code"]},
    )
    return updated


def set_referral_code_status(
    client: Client, *, merchant_id: uuid.UUID, status: str, actor_id: uuid.UUID, reason: str | None = None
) -> dict:
    """Super Admin's kill switch for one merchant's code.

    Disabling stops the code working at signup. It deliberately does not
    touch referrals already captured under it: whether those still pay is
    a separate decision, made per commission, with its own audit trail.
    """
    if status not in ("active", "disabled"):
        raise ValidationAPIError("Referral code status must be 'active' or 'disabled'")

    merchant = _merchant(client, merchant_id)
    if not merchant.get("referral_code"):
        raise ValidationAPIError("This merchant has no referral code")

    updated = update_row(client, "merchants", merchant_id, {"referral_code_status": status})
    write_audit_log(
        client,
        actor_id=actor_id,
        merchant_id=merchant_id,
        action=f"referral.code_{status}",
        resource_type="merchant",
        resource_id=merchant_id,
        metadata={"referral_code": merchant["referral_code"], "reason": reason},
    )
    return updated


def find_merchant_by_referral_code(client: Client, code: str) -> dict | None:
    """The merchant a code belongs to, if it is usable.

    Returns None for an unknown code, a disabled one, or one belonging to
    a merchant who is no longer active — the caller treats all three the
    same way, because telling them apart would let a stranger probe which
    codes exist.
    """
    normalised = normalise_referral_code(code)
    if not normalised:
        return None

    merchant = execute_maybe_single(
        client.table("merchants")
        .select("*")
        .eq("referral_code", normalised)
        .eq("referral_code_status", "active")
        .maybe_single()
    )
    if not merchant or merchant.get("status") != _ACTIVE:
        return None
    return merchant


# --- Capture at signup -----------------------------------------------------


def capture_referral(
    client: Client, *, code: str | None, referred_merchant_id: uuid.UUID
) -> dict | None:
    """Records that a new merchant arrived through someone's code.

    Never raises. Every rejection path returns None and leaves a log line,
    because this sits inside merchant signup and a marketing feature must
    not be able to stop a business being created.

    Returns the referral row when one was created, else None.
    """
    settings = get_settings()
    if not settings.referral_program_enabled:
        return None
    if not code:
        return None

    def _reject(reason: str, **extra: Any) -> None:
        # Best-effort: on a signup path, an audit insert that fails must
        # not turn a successful signup into a 500.
        write_audit_log_best_effort(
            client,
            actor_type="system",
            merchant_id=referred_merchant_id,
            action="referral.signup_rejected",
            resource_type="merchant",
            resource_id=referred_merchant_id,
            # The attempted code is kept so a merchant complaining their
            # friend's code "did not work" can be answered. It is not a
            # secret and identifies no person.
            metadata={"attempted_code": normalise_referral_code(code) or "invalid", "reason": reason, **extra},
        )
        logger.info("referral_signup_rejected reason=%s merchant_id=%s", reason, referred_merchant_id)

    try:
        referrer = find_merchant_by_referral_code(client, code)
        if not referrer:
            _reject("unknown_or_inactive_code")
            return None

        referrer_id = uuid.UUID(referrer["id"])
        if referrer_id == referred_merchant_id:
            _reject("self_referral")
            return None

        existing = execute_maybe_single(
            client.table("merchant_referrals")
            .select("id")
            .eq("referred_merchant_id", str(referred_merchant_id))
            .maybe_single()
        )
        if existing:
            # A business belongs to whoever invited it first. The unique
            # index would refuse this anyway; checking first keeps it out
            # of the logs as an error.
            _reject("already_referred")
            return None

        defaults = settings.referral_defaults
        referral = insert_row(
            client,
            "merchant_referrals",
            {
                "referrer_merchant_id": str(referrer_id),
                "referred_merchant_id": str(referred_merchant_id),
                "referral_code_used": referrer["referral_code"],
                "signup_at": utc_now_iso(),
                # Not earning yet. The window opens at approval.
                "status": "pending_approval",
                "currency": referrer.get("currency", "TZS"),
                **defaults,
            },
        )

        write_audit_log_best_effort(
            client,
            actor_type="system",
            merchant_id=referred_merchant_id,
            action="referral.signup_captured",
            resource_type="merchant_referral",
            resource_id=uuid.UUID(referral["id"]),
            metadata={
                "referrer_merchant_id": str(referrer_id),
                "referral_code_used": referrer["referral_code"],
            },
        )
        return referral
    # Broad on purpose: see the module docstring. A marketing feature
    # must not be able to fail a business signup.
    except Exception:
        # Anything unexpected: the signup continues without an
        # attribution. Logged with a stack trace so it is still visible.
        logger.exception("referral_capture_failed merchant_id=%s", referred_merchant_id)
        return None


def start_referral_period(client: Client, *, referred_merchant_id: uuid.UUID) -> dict | None:
    """Opens the 30-day earning window, called when a merchant is approved.

    Measured from approval rather than signup so a business that waits two
    weeks for review does not spend its referrer's window sitting in a
    queue.

    Idempotent and best-effort: re-approving does not restart the window,
    and a failure here must not stop an approval, which is a far more
    important operation than a referral.
    """
    settings = get_settings()
    if not settings.referral_program_enabled:
        return None

    try:
        referral = execute_maybe_single(
            client.table("merchant_referrals")
            .select("*")
            .eq("referred_merchant_id", str(referred_merchant_id))
            .maybe_single()
        )
        if not referral:
            return None
        if referral.get("referral_period_start_at"):
            # Already running. A second approval must not hand the
            # referrer a fresh 30 days.
            return referral

        start = datetime.now(timezone.utc)
        now = start.isoformat()
        end = start + timedelta(days=settings.referral_period_days)

        updated = update_row(
            client,
            "merchant_referrals",
            uuid.UUID(referral["id"]),
            {
                "referred_approved_at": now,
                "referral_period_start_at": now,
                "referral_period_end_at": end.isoformat(),
                "status": "active",
                "updated_at": now,
            },
        )
        write_audit_log_best_effort(
            client,
            actor_type="system",
            merchant_id=referred_merchant_id,
            action="referral.period_started",
            resource_type="merchant_referral",
            resource_id=uuid.UUID(referral["id"]),
            metadata={
                "referrer_merchant_id": referral["referrer_merchant_id"],
                "period_start_at": now,
                "period_end_at": end.isoformat(),
            },
        )
        return updated
    # Broad on purpose: an approval must not fail because a referral
    # bookkeeping write did.
    except Exception:
        logger.exception("referral_period_start_failed merchant_id=%s", referred_merchant_id)
        return None


# --- Admin controls --------------------------------------------------------


def set_fraud_hold(
    client: Client, *, referral_id: uuid.UUID, on: bool, reason: str | None, actor_id: uuid.UUID
) -> dict:
    """Freezes or releases a referral the platform is suspicious of.

    A held referral stops accruing and cannot be approved for payout. It
    is reversible on purpose: a hold is a question, not a verdict, and
    releasing one has to be as auditable as placing it.
    """
    referral = get_by_id(client, "merchant_referrals", referral_id)
    if not referral:
        raise NotFoundError("Referral not found")

    if on and not reason:
        raise ValidationAPIError("A fraud hold needs a reason")

    if on:
        changes = {"status": "fraud_hold", "fraud_flag_reason": reason}
    else:
        if referral["status"] != "fraud_hold":
            raise ConflictError("This referral is not on hold")
        # Back to whichever state its window puts it in; the daily
        # recalculation settles the detail.
        changes = {
            "status": "active" if referral.get("referral_period_start_at") else "pending_approval",
            "fraud_flag_reason": None,
        }

    updated = update_row(client, "merchant_referrals", referral_id, {**changes, "updated_at": utc_now_iso()})
    write_audit_log(
        client,
        actor_id=actor_id,
        merchant_id=uuid.UUID(referral["referrer_merchant_id"]),
        action="referral.fraud_hold_set" if on else "referral.fraud_hold_cleared",
        resource_type="merchant_referral",
        resource_id=referral_id,
        metadata={"reason": reason, "referred_merchant_id": referral["referred_merchant_id"]},
    )
    return updated


# --- Read models -----------------------------------------------------------


def merchant_referral_summary(client: Client, *, merchant_id: uuid.UUID) -> dict:
    """What a merchant sees about their own invitations.

    Deliberately counts and money only. The referred businesses' contact
    details, owners, fraud flags and individual revenue are not a
    referrer's to see — they are another business's private trading
    information, and the referrer's interest in it ends at "did it
    qualify".
    """
    merchant = _merchant(client, merchant_id)
    referrals = (
        client.table("merchant_referrals")
        .select("id,status,referred_merchant_id,signup_at,referred_approved_at,referral_period_end_at")
        .eq("referrer_merchant_id", str(merchant_id))
        .order("signup_at", desc=True)
        .execute()
    ).data or []

    commissions = (
        client.table("referral_commissions")
        .select("status,commission_amount,currency")
        .eq("referrer_merchant_id", str(merchant_id))
        .execute()
    ).data or []

    def _sum(statuses: set[str]) -> Decimal:
        return sum(
            (Decimal(str(c["commission_amount"])) for c in commissions if c["status"] in statuses),
            Decimal(0),
        )

    approved_statuses = {"active", "qualified", "commission_pending", "commission_approved", "commission_paid"}
    return {
        "referral_code": merchant.get("referral_code"),
        "referral_code_status": merchant.get("referral_code_status", "active"),
        "referral_link": referral_link(merchant.get("referral_code")),
        "total_invited": len(referrals),
        "approved_referrals": sum(1 for r in referrals if r["status"] in approved_statuses),
        "qualified_referrals": sum(
            1
            for r in referrals
            if r["status"] in {"qualified", "commission_pending", "commission_approved", "commission_paid"}
        ),
        # "Pending" is everything still being worked out or waiting on a
        # review - what the merchant might yet be paid.
        "pending_commission": _sum({"accruing", "below_threshold", "pending_review"}),
        "approved_commission": _sum({"approved"}),
        "paid_commission": _sum({"paid"}),
        "currency": merchant.get("currency", "TZS"),
    }


def referral_link(code: str | None) -> str | None:
    """The link a merchant shares. Points at the public signup page with
    the code as ?ref=, which is what the create-account form reads."""
    if not code:
        return None
    base = get_settings().app_url.rstrip("/")
    return f"{base}/create-account?ref={code}"
