"""Platform-wide Command Center aggregation — GET /v1/admin/overview.

Every "today"/"month-to-date" figure is narrowed **in the database** with
a `gte` on its own timestamp, then summed in Python.

It used to select the whole table and filter afterwards, on the grounds
that the fake test client supported only eq/is_/in_. That stopped being
true - the fake has gte/lte/order/limit now - and the approach broke in
production the moment a table outgrew PostgREST's default 1000-row page:
the select returned the *oldest* 1000 rows, none of which were today, so
Collections Today read TZS 0.00 on a morning that had taken 41 payments.
Withdrawals Today kept working only because there were 34 payouts in
total.

So a counter must never depend on a row being inside the first page.
Anything scoped to a day or a month is filtered server-side; the two that
are not - active payment links and outstanding invoice value - are
unbounded by nature and will need paging or an aggregate before they
reach 1000 rows.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from supabase import Client

from app.core.time import (
    dar_es_salaam_day_start_utc,
    dar_es_salaam_month_start_utc,
    is_dar_es_salaam_today,
)
from app.schemas.enums import AccountStatus
from app.services.crud import execute_maybe_single, fetch_all

logger = logging.getLogger("infinity.admin.overview")


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_today(value: str, today: datetime) -> bool:
    """The merchant's day, not UTC's. See app/core/time.py — Tanzania is
    UTC+3, so comparing UTC dates rolled the business day over at 03:00
    local and reset these counters mid-trading."""
    return is_dar_es_salaam_today(value, today)


def _platform_revenue_account_id(client: Client) -> str | None:
    account = execute_maybe_single(
        client.table("ledger_accounts")
        .select("id")
        .eq("purpose", "platform_revenue")
        .is_("merchant_id", "null")
        .maybe_single()
    )
    return account["id"] if account else None


def _platform_revenue_since(client: Client, *, account_id: str | None, since: str) -> Decimal:
    """What the platform has earned since `since`, a UTC ISO instant.

    Paged, not a single select. One month already runs to 1,083 credit
    entries, so the first page stopped short of the newest ones and
    month-to-date read TZS 27,592.58 against a true 29,430.08 — revenue
    under-reported by 1,837.50 and widening with every collection.
    """
    if not account_id:
        return Decimal(0)

    entries = fetch_all(
        lambda: client.table("ledger_entries")
        .select("amount, created_at")
        .eq("ledger_account_id", account_id)
        .eq("direction", "credit")
        .gte("created_at", since)
    )
    return sum((Decimal(str(e["amount"])) for e in entries), Decimal(0))


def _money_totals(client: Client, *, day_start: str, month_start: str) -> dict | None:
    """All six money figures in one database call, or None.

    public.admin_overview_money (migration 20261031030000) sums them in
    Postgres. The alternative is what this module did before: read every
    matching row a thousand at a time and add them up here, which at
    28,695 collection transactions and 28,710 revenue entries would be
    roughly sixty sequential requests for one dashboard, growing with
    every payment the platform takes.

    Returns None if the function is not there - the migration ships
    separately and may not have been applied yet. The caller then falls
    back to the old per-row summing for today and this month, and reports
    the lifetime figures as unavailable rather than guessing at them.
    """
    try:
        result = client.rpc(
            "admin_overview_money",
            {"p_day_start": day_start, "p_month_start": month_start},
        ).execute()
    except Exception:  # noqa: BLE001 - the dashboard must render regardless
        logger.warning("admin_overview_money_unavailable - apply migration 20261031030000")
        return None

    data = result.data
    if not isinstance(data, dict):
        logger.warning("admin_overview_money_unexpected_shape")
        return None

    try:
        # Text in, Decimal here. The function returns these as strings on
        # purpose: a numeric(14,2) read back through a JSON number arrives
        # as a float, and these are money.
        return {key: Decimal(str(data[key])) for key in _MONEY_KEYS}
    except (KeyError, InvalidOperation, TypeError):
        logger.warning("admin_overview_money_unparsable")
        return None


_MONEY_KEYS = (
    "collections_today",
    "collections_this_month",
    "collections_total",
    "revenue_today",
    "revenue_this_month",
    "revenue_total",
)


def get_admin_overview(client: Client) -> dict:
    now = datetime.now(timezone.utc)

    # Businesses, not rows. A closed account is a business that has left,
    # and counting it made the headline figure drift further from reality
    # with every account that was ever wound up — including the duplicate
    # signups a typo creates (see app/services/duplicate_signup.py).
    #
    # `suspended` still counts: those are customers, temporarily blocked,
    # not gone. Only `closed` is terminal.
    #
    # This cannot catch a duplicate that is still `active` — nothing can,
    # automatically. Those come off the count when someone closes them.
    total_merchants = (
        client.table("merchants").select("id", count="exact").neq("status", "closed").execute()
    ).count or 0

    day_start = dar_es_salaam_day_start_utc(now)
    month_start = dar_es_salaam_month_start_utc(now)
    revenue_account_id = _platform_revenue_account_id(client)

    def _successful_collections_since(since: str) -> list[dict]:
        """Paged, not a single select.

        A month of successful collections already runs past a thousand
        rows on this platform, and a single request answers with one page
        and says nothing about the rest - which is how Collections Today
        once read TZS 0.00. Today's own count is a few hundred and
        climbing, so it gets the same treatment rather than waiting to
        cross the same line.
        """
        return fetch_all(
            lambda: client.table("transactions")
            .select("gross_amount, created_at")
            .eq("type", "collection")
            .eq("status", "successful")
            .gte("created_at", since)
        )

    # One database call for all six money figures. Falls back to the
    # per-row summing below if the function has not been applied yet.
    money = _money_totals(client, day_start=day_start, month_start=month_start)

    if money is None:
        successful_collections = _successful_collections_since(day_start)
        collections_today = sum(
            (
                Decimal(str(t["gross_amount"]))
                for t in successful_collections
                if _is_today(t["created_at"], now)
            ),
            Decimal(0),
        )

        # Month to date, on the merchant's calendar - the same month
        # boundary platform revenue uses, so the two cards describe the
        # same period.
        collections_this_month = sum(
            (Decimal(str(t["gross_amount"])) for t in _successful_collections_since(month_start)),
            Decimal(0),
        )
        platform_revenue_today = _platform_revenue_since(
            client, account_id=revenue_account_id, since=day_start
        )
        platform_revenue_month = _platform_revenue_since(
            client, account_id=revenue_account_id, since=month_start
        )
        # Not computable this way: a lifetime figure read a thousand rows
        # at a time is exactly what the function exists to avoid, and a
        # number that silently stops at the first page is worse than no
        # number. The card says so rather than showing a wrong total or a
        # misleading zero.
        collections_total: Decimal | None = None
        revenue_total: Decimal | None = None
    else:
        collections_today = money["collections_today"]
        collections_this_month = money["collections_this_month"]
        collections_total = money["collections_total"]
        platform_revenue_today = money["revenue_today"]
        platform_revenue_month = money["revenue_this_month"]
        revenue_total = money["revenue_total"]

    # Counted by the database, not by how many rows came back. This used
    # to sum a plain select, and PostgREST caps a response at 1000 rows —
    # so the card read exactly "1,000" on 2026-10-24 when the true figure
    # was 1,049, and would have stayed pinned at 1,000 however far it
    # actually rose. It became wrong precisely because the platform grew
    # enough to cross that line in a single day.
    #
    # day_start is already midnight on the merchant's calendar (see
    # app/core/time.py), so the filter alone defines "today" and the
    # per-row _is_today check it used to need is redundant.
    failed_transactions = (
        client.table("transactions")
        .select("id", count="exact")
        .eq("status", "failed")
        .gte("created_at", day_start)
        .execute()
    ).count or 0

    successful_withdrawals = (
        client.table("disbursements")
        .select("amount, completed_at")
        .eq("status", "SUCCESS")
        .gte("completed_at", day_start)
        .execute()
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
        client.table("invoices")
        .select("updated_at")
        .eq("status", "PAID")
        .gte("updated_at", day_start)
        .execute()
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
        "collections_this_month": collections_this_month,
        "withdrawals_today": withdrawals_today,
        "active_payment_links": active_payment_links,
        "paid_invoices_today": paid_invoices_today,
        "outstanding_invoice_value": outstanding_invoice_value,
        "failed_transactions": failed_transactions,
        # Three windows, one account. "Today" is what the platform has
        # earned since midnight in Dar es Salaam; "this month" since the
        # 1st, same clock; the total since the platform began.
        #
        # The lifetime pair carries no period at all, so nothing about it
        # changes at a month or year boundary - 1 November moves the two
        # monthly cards to November and leaves these untouched, because a
        # period is only ever derived from the timestamps in the query.
        # Nothing resets them and nothing needs to.
        "platform_revenue_today": platform_revenue_today,
        "platform_revenue": platform_revenue_month,
        "collections_total": collections_total,
        "revenue_total": revenue_total,
        "pending_onboarding_requests": pending_onboarding_requests,
        "pending_withdrawals": pending_withdrawals,
    }
