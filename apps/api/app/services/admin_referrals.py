"""Super Admin's view of the referral programme.

Joins each referral to its merchants and its current commission, so a
reviewer can see what a payout was earned from without opening three
tables. Reads only — every state change lives in app/services/referrals.py
or app/services/referral_commissions.py, where it is audit logged.
"""

import uuid
from decimal import Decimal

from supabase import Client

from app.core.pagination import PaginationParams
from app.services.admin_directory import batch_merchant_codes, batch_merchant_names
from app.services.crud import fetch_all


def list_admin_referrals(
    client: Client,
    *,
    status: str | None = None,
    referrer_merchant_id: uuid.UUID | None = None,
    referral_id: uuid.UUID | None = None,
    pagination: PaginationParams | None = None,
) -> tuple[list[dict], int]:
    """Referrals with their merchants and current commission attached.

    Paged through rather than selected in one go: a referral programme is
    exactly the kind of table that quietly passes a thousand rows and
    starts reporting a page as if it were the whole set.
    """

    def query():
        q = client.table("merchant_referrals").select("*").order("signup_at", desc=True)
        if status:
            q = q.eq("status", status)
        if referrer_merchant_id:
            q = q.eq("referrer_merchant_id", str(referrer_merchant_id))
        if referral_id:
            q = q.eq("id", str(referral_id))
        return q

    referrals = fetch_all(query)
    total = len(referrals)
    page = referrals
    if pagination is not None:
        page = referrals[pagination.start : pagination.end + 1]

    if not page:
        return [], total

    merchant_ids = {r["referrer_merchant_id"] for r in page} | {r["referred_merchant_id"] for r in page}
    names = batch_merchant_names(client, merchant_ids)
    codes = batch_merchant_codes(client, merchant_ids)

    commissions = fetch_all(
        lambda: client.table("referral_commissions")
        .select("*")
        .in_("referral_id", [r["id"] for r in page])
    )
    by_referral = {c["referral_id"]: c for c in commissions}

    rows = []
    for referral in page:
        commission = by_referral.get(referral["id"])
        amount = Decimal(str(commission["commission_amount"])) if commission else None
        minimum = Decimal(str(referral["minimum_payout_amount"]))
        rows.append(
            {
                **referral,
                "referrer_name": names.get(referral["referrer_merchant_id"]),
                "referrer_code": codes.get(referral["referrer_merchant_id"]),
                "referred_name": names.get(referral["referred_merchant_id"]),
                "referred_code": codes.get(referral["referred_merchant_id"]),
                "commission_id": commission["id"] if commission else None,
                "commission_status": commission["status"] if commission else None,
                "successful_volume": commission["successful_volume"] if commission else None,
                "infinitypay_net_revenue": (
                    commission["infinitypay_net_revenue"] if commission else None
                ),
                "commission_amount": commission["commission_amount"] if commission else None,
                # What a reviewer actually wants to know at a glance:
                # could this be approved right now?
                "payout_eligible": bool(
                    commission
                    and commission["status"] == "pending_review"
                    and amount is not None
                    and amount >= minimum
                ),
            }
        )
    return rows, total


def referral_programme_summary(client: Client) -> dict:
    """Counts across every referral, for the Super Admin KPI cards.

    Counted here rather than in the browser, so the cards cannot end up
    reporting a page size as a total.
    """
    referrals = fetch_all(lambda: client.table("merchant_referrals").select("status"))
    commissions = fetch_all(
        lambda: client.table("referral_commissions").select("status, commission_amount")
    )

    def _sum(statuses: set[str]) -> Decimal:
        return sum(
            (Decimal(str(c["commission_amount"])) for c in commissions if c["status"] in statuses),
            Decimal(0),
        )

    return {
        "total_referrals": len(referrals),
        "active_referrals": sum(1 for r in referrals if r["status"] in {"active", "qualified"}),
        "fraud_holds": sum(1 for r in referrals if r["status"] == "fraud_hold"),
        "awaiting_review": sum(1 for c in commissions if c["status"] == "pending_review"),
        "pending_review_amount": _sum({"pending_review"}),
        "approved_unpaid_amount": _sum({"approved"}),
        "paid_amount": _sum({"paid"}),
    }
