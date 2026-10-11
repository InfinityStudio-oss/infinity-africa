"""What a referral is worth, and whether it is payable yet.

The commission base is **InfinityPay's net revenue**, not the amount the
referred merchant collected. Those differ by roughly two orders of
magnitude — a TZS 500 collection earns the platform TZS 12.50 — so paying
15% of the wrong one would be a catastrophic overpayment rather than a
rounding error.

That revenue is not re-derived from pricing rules here. It is read from
the double-entry ledger, which already records it: every collection fee is
posted as a credit to the single platform_revenue account
(app/services/ledger.py::post_collection_entries), and a reversal posts
the matching debit (::reverse_collection_entries). So:

    net revenue = sum(credits) - sum(debits)

for the referred merchant's collection transactions inside the window.
A reversed collection cancels its own fee with no special case, and the
figure agrees by construction with what the platform reports as its own
revenue. Duplicating the fee calculation would have given a second,
competing answer.

Refunds are a deliberate exception: post_refund_entry moves the wallet and
settlement legs but leaves the fee, so InfinityPay keeps its revenue on a
refunded collection and the commission follows it. That is the existing
product decision, not one taken here.

Recalculation is idempotent. There is one commission row per referral,
updated in place while it is still open and frozen the moment a human has
ruled on it. A recalculation can never produce a second payable record.
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any

from supabase import Client

from app.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationAPIError
from app.core.time import utc_now_iso
from app.services.audit import write_audit_log
from app.services.crud import (
    execute_maybe_single,
    fetch_all,
    get_by_id,
    insert_row,
    update_row,
)

logger = logging.getLogger("infinity.referral_commissions")

_BPS_DIVISOR = Decimal(10000)

# Statuses a recalculation may still overwrite. Once a Super Admin has
# approved, rejected or paid, the figure is history and the job leaves it
# alone — a commission that moved after someone signed it off would make
# every approval meaningless.
MUTABLE_STATUSES = frozenset({"accruing", "below_threshold", "pending_review"})

# A merchant has to be trading in good standing at both ends. Suspended,
# closed or still-pending accounts earn and generate nothing.
_ACTIVE = "active"


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _platform_revenue_account_id(client: Client) -> str | None:
    account = execute_maybe_single(
        client.table("ledger_accounts")
        .select("id")
        .eq("purpose", "platform_revenue")
        .is_("merchant_id", "null")
        .maybe_single()
    )
    return account["id"] if account else None


def _collection_transactions(
    client: Client, *, merchant_id: str, start: str, end: str
) -> list[dict]:
    """The referred merchant's successful collections inside the window.

    Paged: a busy merchant can put more than one page of transactions
    through in 30 days, and a single select would silently stop at a
    thousand and under-pay the referrer.
    """
    return fetch_all(
        lambda: client.table("transactions")
        .select("id, gross_amount, status, created_at")
        .eq("merchant_id", merchant_id)
        .eq("type", "collection")
        .eq("status", "successful")
        .gte("created_at", start)
        .lt("created_at", end)
    )


def _net_revenue_for(client: Client, *, transaction_ids: list[str], account_id: str) -> Decimal:
    """Credits minus debits on the platform revenue account for these
    transactions.

    Queried in chunks because `in_` builds a URL, and a few thousand ids
    in one request is a request that gets rejected for its length rather
    than answered.
    """
    if not transaction_ids or not account_id:
        return Decimal(0)

    total = Decimal(0)
    chunk = 200
    for index in range(0, len(transaction_ids), chunk):
        batch = transaction_ids[index : index + chunk]
        entries = fetch_all(
            lambda batch=batch: client.table("ledger_entries")
            .select("amount, direction")
            .eq("ledger_account_id", account_id)
            .in_("transaction_id", batch)
        )
        for entry in entries:
            amount = Decimal(str(entry["amount"]))
            total += amount if entry["direction"] == "credit" else -amount
    # A reversal can in principle take a window negative; the platform
    # never owes a referrer money, so the floor is zero.
    return total if total > 0 else Decimal(0)


def _money(value: Decimal) -> Decimal:
    """Two decimal places, always rounded down. The platform never pays a
    cent more than it earned on the referral."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def calculate_referral_commission(client: Client, *, referral: dict) -> dict | None:
    """Works out what one referral is worth and records it.

    Returns the commission row, or None when there is nothing to record
    yet (the window has not opened, or the programme is off).

    Safe to run repeatedly: it writes one row per referral and updates it
    in place while it is still open.
    """
    settings = get_settings()
    if not settings.referral_program_enabled:
        return None

    start = referral.get("referral_period_start_at")
    end = referral.get("referral_period_end_at")
    if not start or not end:
        # Referred merchant is not approved yet. Nothing accrues.
        return None

    referral_id = uuid.UUID(referral["id"])
    existing = execute_maybe_single(
        client.table("referral_commissions")
        .select("*")
        .eq("referral_id", str(referral_id))
        .maybe_single()
    )
    if existing and existing["status"] not in MUTABLE_STATUSES:
        # A human has ruled on this. Leave it exactly as they left it.
        return existing

    referrer = get_by_id(client, "merchants", uuid.UUID(referral["referrer_merchant_id"])) or {}
    referred = get_by_id(client, "merchants", uuid.UUID(referral["referred_merchant_id"])) or {}

    # Clamp the window to now: a referral three days into its month must
    # be valued on three days, not thirty.
    now = datetime.now(timezone.utc)
    window_end = min(_parse(end), now)
    transactions: list[dict] = []
    if window_end > _parse(start):
        transactions = _collection_transactions(
            client,
            merchant_id=referral["referred_merchant_id"],
            start=start,
            end=window_end.isoformat(),
        )

    successful_volume = sum((Decimal(str(t["gross_amount"])) for t in transactions), Decimal(0))
    account_id = _platform_revenue_account_id(client)
    net_revenue = _net_revenue_for(
        client, transaction_ids=[t["id"] for t in transactions], account_id=account_id or ""
    )

    rate_bps = int(referral["commission_rate_bps"])
    threshold = Decimal(str(referral["qualification_volume_threshold"]))
    minimum_payout = Decimal(str(referral["minimum_payout_amount"]))

    qualified = successful_volume >= threshold
    commission_amount = _money(net_revenue * Decimal(rate_bps) / _BPS_DIVISOR) if qualified else Decimal(0)

    # Every reason a commission might not be payable, evaluated in the
    # order a person would explain it.
    blockers: list[str] = []
    if referral["status"] == "fraud_hold":
        blockers.append("fraud_hold")
    if referral["status"] == "ineligible":
        blockers.append("marked_ineligible")
    if referrer.get("status") != _ACTIVE:
        blockers.append(f"referrer_{referrer.get('status', 'unknown')}")
    if referred.get("status") != _ACTIVE:
        blockers.append(f"referred_{referred.get('status', 'unknown')}")

    if blockers:
        status = "cancelled"
    elif not qualified:
        status = "accruing" if now < _parse(end) else "below_threshold"
    elif commission_amount < minimum_payout:
        status = "below_threshold"
    elif now < _parse(end):
        # Qualified and over the floor, but the month is still running, so
        # the figure can still grow. Reviewing it now would mean reviewing
        # it again tomorrow.
        status = "accruing"
    else:
        status = "pending_review"

    snapshot: dict[str, Any] = {
        "calculated_at": utc_now_iso(),
        "window": {"start": start, "end": end, "valued_to": window_end.isoformat()},
        "transaction_count": len(transactions),
        "successful_volume": str(successful_volume),
        "infinitypay_net_revenue": str(net_revenue),
        "commission_rate_bps": rate_bps,
        "qualification_volume_threshold": str(threshold),
        "minimum_payout_amount": str(minimum_payout),
        "qualified": qualified,
        "blockers": blockers,
        # Where the revenue figure came from, so the number can be
        # re-derived from the ledger by hand if it is ever disputed.
        "revenue_source": "ledger_entries.platform_revenue credits minus debits",
        "platform_revenue_account_id": account_id,
    }

    row = {
        "referral_id": str(referral_id),
        "referrer_merchant_id": referral["referrer_merchant_id"],
        "referred_merchant_id": referral["referred_merchant_id"],
        "period_start_at": start,
        "period_end_at": end,
        "successful_volume": str(successful_volume),
        "infinitypay_net_revenue": str(net_revenue),
        "commission_rate_bps": rate_bps,
        "commission_amount": str(commission_amount),
        "minimum_payout_amount": str(minimum_payout),
        "currency": referral.get("currency", "TZS"),
        "status": status,
        "calculation_snapshot": snapshot,
        "updated_at": utc_now_iso(),
    }

    if existing:
        commission = update_row(client, "referral_commissions", uuid.UUID(existing["id"]), row)
    else:
        commission = insert_row(client, "referral_commissions", row)

    _sync_referral_status(client, referral=referral, commission_status=status, qualified=qualified, now=now, end=end)

    write_audit_log(
        client,
        actor_type="system",
        merchant_id=uuid.UUID(referral["referrer_merchant_id"]),
        action="referral.commission_calculated",
        resource_type="referral_commission",
        resource_id=uuid.UUID(commission["id"]),
        metadata={
            "status": status,
            "successful_volume": str(successful_volume),
            "infinitypay_net_revenue": str(net_revenue),
            "commission_amount": str(commission_amount),
            "blockers": blockers,
        },
    )
    return commission


def _sync_referral_status(
    client: Client, *, referral: dict, commission_status: str, qualified: bool, now: datetime, end: str
) -> None:
    """Keeps merchant_referrals.status readable beside the commission.

    A fraud hold is never overwritten here — only an admin clears that.
    """
    if referral["status"] in {"fraud_hold", "ineligible"}:
        return

    if commission_status == "pending_review":
        new_status = "commission_pending"
    elif qualified:
        new_status = "qualified"
    elif now >= _parse(end):
        new_status = "expired"
    else:
        new_status = "active"

    if new_status != referral["status"]:
        update_row(
            client,
            "merchant_referrals",
            uuid.UUID(referral["id"]),
            {"status": new_status, "updated_at": utc_now_iso()},
        )


def recalculate_open_referrals(client: Client) -> dict:
    """The daily sweep. Revalues every referral that is still open.

    Deliberately skips anything terminal, so the amount of work does not
    grow with the number of referrals the platform has ever had.
    """
    settings = get_settings()
    if not settings.referral_program_enabled:
        return {"processed": 0, "skipped": "programme_disabled"}

    referrals = fetch_all(
        lambda: client.table("merchant_referrals")
        .select("*")
        .in_("status", ["active", "qualified", "commission_pending", "pending_approval"])
    )

    processed = 0
    failures = 0
    for referral in referrals:
        try:
            if calculate_referral_commission(client, referral=referral) is not None:
                processed += 1
        # One bad referral must not stop the rest of the sweep.
        except Exception:
            failures += 1
            logger.exception("referral_commission_calculation_failed referral_id=%s", referral.get("id"))

    return {"processed": processed, "failures": failures, "considered": len(referrals)}


# --- Super Admin decisions -------------------------------------------------


def _commission(client: Client, commission_id: uuid.UUID) -> dict:
    commission = get_by_id(client, "referral_commissions", commission_id)
    if not commission:
        raise NotFoundError("Referral commission not found")
    return commission


def approve_commission(client: Client, *, commission_id: uuid.UUID, admin_id: uuid.UUID) -> dict:
    """Marks a commission payable. Does not pay it.

    The platform has no automated referral payout, by choice: this is the
    one place a human confirms that a referral was genuine before money
    leaves. Paying it is a separate, recorded act.
    """
    commission = _commission(client, commission_id)
    if commission["status"] != "pending_review":
        raise ConflictError(f"Only a commission pending review can be approved (this one is {commission['status']})")
    if Decimal(str(commission["commission_amount"])) < Decimal(str(commission["minimum_payout_amount"])):
        raise ValidationAPIError("This commission is below the minimum payout amount")

    updated = update_row(
        client,
        "referral_commissions",
        commission_id,
        {
            "status": "approved",
            "reviewed_by_admin_id": str(admin_id),
            "reviewed_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        },
    )
    update_row(
        client,
        "merchant_referrals",
        uuid.UUID(commission["referral_id"]),
        {"status": "commission_approved", "updated_at": utc_now_iso()},
    )
    write_audit_log(
        client,
        actor_id=admin_id,
        merchant_id=uuid.UUID(commission["referrer_merchant_id"]),
        action="referral.commission_approved",
        resource_type="referral_commission",
        resource_id=commission_id,
        metadata={"commission_amount": str(commission["commission_amount"])},
    )
    return updated


def reject_commission(
    client: Client, *, commission_id: uuid.UUID, admin_id: uuid.UUID, reason: str
) -> dict:
    """Refuses a commission, with a reason that is kept."""
    if not reason or not reason.strip():
        raise ValidationAPIError("A rejection needs a reason")

    commission = _commission(client, commission_id)
    if commission["status"] in {"paid", "rejected"}:
        raise ConflictError(f"This commission is already {commission['status']}")

    updated = update_row(
        client,
        "referral_commissions",
        commission_id,
        {
            "status": "rejected",
            "rejection_reason": reason.strip(),
            "reviewed_by_admin_id": str(admin_id),
            "reviewed_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        },
    )
    update_row(
        client,
        "merchant_referrals",
        uuid.UUID(commission["referral_id"]),
        {"status": "commission_rejected", "updated_at": utc_now_iso()},
    )
    write_audit_log(
        client,
        actor_id=admin_id,
        merchant_id=uuid.UUID(commission["referrer_merchant_id"]),
        action="referral.commission_rejected",
        resource_type="referral_commission",
        resource_id=commission_id,
        metadata={"reason": reason.strip()},
    )
    return updated


def mark_commission_paid(
    client: Client, *, commission_id: uuid.UUID, admin_id: uuid.UUID, note: str | None = None
) -> dict:
    """Records that an approved commission was paid out elsewhere.

    This moves no money. There is no automated referral payout path, and
    this endpoint deliberately is not one: it is bookkeeping for a payment
    made through the normal disbursement process, so that the referral
    record matches reality.
    """
    commission = _commission(client, commission_id)
    if commission["status"] != "approved":
        raise ConflictError("Only an approved commission can be marked paid")

    updated = update_row(
        client,
        "referral_commissions",
        commission_id,
        {"status": "paid", "paid_at": utc_now_iso(), "updated_at": utc_now_iso()},
    )
    update_row(
        client,
        "merchant_referrals",
        uuid.UUID(commission["referral_id"]),
        {"status": "commission_paid", "updated_at": utc_now_iso()},
    )
    write_audit_log(
        client,
        actor_id=admin_id,
        merchant_id=uuid.UUID(commission["referrer_merchant_id"]),
        action="referral.commission_paid",
        resource_type="referral_commission",
        resource_id=commission_id,
        metadata={"commission_amount": str(commission["commission_amount"]), "note": note},
    )
    return updated
