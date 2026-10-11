"""Platform-wide Command Center aggregation — GET /v1/admin/overview.

Same "acceptable for now, fetch and sum in Python" approach as
app/routers/merchant_portal.py's get_merchant_overview (no platform-wide
SQL/RPC aggregate exists yet); the fake test client's query builder only
supports eq/is_/in_ (no gte/lte), so every "today"/"month-to-date" cutoff is
applied in Python after a coarser eq/in_ filter, matching how
get_merchant_overview already filters active_payment_links in Python.
"""

from datetime import datetime, timezone
from decimal import Decimal

from supabase import Client

from app.core.time import is_dar_es_salaam_today
from app.schemas.enums import AccountStatus
from app.services.crud import execute_maybe_single


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_today(value: str, today: datetime) -> bool:
    """The merchant's day, not UTC's. See app/core/time.py — Tanzania is
    UTC+3, so comparing UTC dates rolled the business day over at 03:00
    local and reset these counters mid-trading."""
    return is_dar_es_salaam_today(value, today)


def _platform_revenue_mtd(client: Client, *, start_of_month: datetime) -> Decimal:
    account = execute_maybe_single(
        client.table("ledger_accounts")
        .select("id")
        .eq("purpose", "platform_revenue")
        .is_("merchant_id", "null")
        .maybe_single()
    )
    if not account:
        return Decimal(0)

    entries = (
        client.table("ledger_entries")
        .select("amount, created_at")
        .eq("ledger_account_id", account["id"])
        .eq("direction", "credit")
        .execute()
    ).data or []
    return sum(
        (Decimal(str(e["amount"])) for e in entries if _parse_dt(e["created_at"]) >= start_of_month),
        Decimal(0),
    )


def get_admin_overview(client: Client) -> dict:
    now = datetime.now(timezone.utc)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_merchants = (client.table("merchants").select("id", count="exact").execute()).count or 0

    successful_collections = (
        client.table("transactions")
        .select("gross_amount, created_at")
        .eq("type", "collection")
        .eq("status", "successful")
        .execute()
    ).data or []
    collections_today = sum(
        (Decimal(str(t["gross_amount"])) for t in successful_collections if _is_today(t["created_at"], now)),
        Decimal(0),
    )

    failed_transactions = sum(
        1
        for t in (client.table("transactions").select("created_at").eq("status", "failed").execute()).data or []
        if _is_today(t["created_at"], now)
    )

    successful_withdrawals = (
        client.table("disbursements").select("amount, completed_at").eq("status", "SUCCESS").execute()
    ).data or []
    withdrawals_today = sum(
        (Decimal(str(d["amount"])) for d in successful_withdrawals if d["completed_at"] and _is_today(d["completed_at"], now)),
        Decimal(0),
    )

    active_links = (
        client.table("payment_links").select("expires_at").eq("status", "ACTIVE").execute()
    ).data or []
    active_payment_links = sum(
        1 for link in active_links if not link.get("expires_at") or _parse_dt(link["expires_at"]) > now
    )

    paid_invoices = (
        client.table("invoices").select("updated_at").eq("status", "PAID").execute()
    ).data or []
    paid_invoices_today = sum(1 for inv in paid_invoices if _is_today(inv["updated_at"], now))

    outstanding_invoices = (
        client.table("invoices")
        .select("total_amount, amount_paid")
        .in_("status", ["SENT", "PARTIALLY_PAID", "OVERDUE"])
        .execute()
    ).data or []
    outstanding_invoice_value = sum(
        (Decimal(str(inv["total_amount"])) - Decimal(str(inv["amount_paid"])) for inv in outstanding_invoices),
        Decimal(0),
    )

    pending_onboarding_requests = (
        client.table("onboarding_submissions")
        .select("id", count="exact")
        .eq("review_status", AccountStatus.PENDING_VERIFICATION.value)
        .execute()
    ).count or 0

    pending_withdrawals = (
        client.table("disbursements")
        .select("id", count="exact")
        .eq("status", "PENDING_ADMIN_APPROVAL")
        .execute()
    ).count or 0

    return {
        "total_merchants": total_merchants,
        "collections_today": collections_today,
        "withdrawals_today": withdrawals_today,
        "active_payment_links": active_payment_links,
        "paid_invoices_today": paid_invoices_today,
        "outstanding_invoice_value": outstanding_invoice_value,
        "failed_transactions": failed_transactions,
        "platform_revenue": _platform_revenue_mtd(client, start_of_month=start_of_month),
        "pending_onboarding_requests": pending_onboarding_requests,
        "pending_withdrawals": pending_withdrawals,
    }
