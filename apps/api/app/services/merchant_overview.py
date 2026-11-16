"""Merchant Overview aggregation — GET /v1/merchant/overview.

The only genuinely new business logic behind the /v1/merchant/* API
surface; every other endpoint in app/routers/merchant_portal.py delegates
to an existing service. No aggregate SQL/RPC exists for any of this —
acceptable at merchant-portal scale (fetching and summing in Python);
revisit with a real aggregate query or materialized view if this ever
needs to scale past that.

total_fees_charged sums transactions.fee_amount for this merchant's
successful collections — NOT the ledger's platform_revenue account
balance, which is platform-wide (merchant_id=None, see
app/services/ledger.py's post_collection_entries), not per-merchant.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from supabase import Client

from app.core.cache import cache_get, cache_set, merchant_key
from app.core.errors import NotFoundError
from app.core.time import (
    dar_es_salaam_date,
    dar_es_salaam_day_bounds_utc,
    dar_es_salaam_day_start_utc,
    is_dar_es_salaam_today,
)
from app.services.crud import fetch_all, get_by_id
from app.services.ledger import get_wallet_balance

# A trend, not a figure anyone pays against, so a minute of staleness is
# free. Deliberately longer than the overview's own TTL.
_SERIES_TTL_SECONDS = 120


def _is_today(value: str | None, now: datetime) -> bool:
    """Calendar-day comparison in Africa/Dar_es_Salaam, matching
    admin_overview's and the reports/export endpoints, which already use
    the merchant's own midnight. A null timestamp (a withdrawal with no
    completed_at) is never "today"."""
    return is_dar_es_salaam_today(value, now)

_PENDING_TRANSACTION_STATUSES = ("pending", "processing")
_UNPAID_INVOICE_STATUSES = ("SENT", "PARTIALLY_PAID", "OVERDUE")


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# The expensive part of the overview, cached. Nine Supabase queries at
# ~57ms each, for figures that describe a merchant's own history.
_OVERVIEW_TTL_SECONDS = 20


def get_merchant_overview(client: Client, *, merchant_id: uuid.UUID) -> dict:
    """The dashboard figures, with the aggregates cached and the balance
    never cached.

    **available_balance is deliberately left out of the cache and read
    fresh on every call.** It is one query of the nine, so caching it
    would buy about a ninth of the saving, and it is the single number a
    merchant trusts most: the one they look at to decide whether to
    withdraw. A stale total-collections figure is a cosmetic lag; a stale
    balance is a merchant being told they have money they have already
    moved, which is a support call and a dent in trust.

    This does not make the balance here authoritative - the withdrawal
    path reads it again for itself in app/services/disbursements.py,
    which is what actually protects the money. It means the displayed
    number matches the database at the moment it was displayed.
    """
    cache_key = merchant_key(merchant_id, "overview")
    cached = cache_get(cache_key)
    if cached is not None:
        merchant = get_by_id(client, "merchants", merchant_id)
        if merchant:
            currency = merchant["currency"]
            return {
                **cached,
                "merchant": merchant,
                "available_balance": get_wallet_balance(
                    client, merchant_id=merchant_id, currency=currency
                ),
            }

    merchant = get_by_id(client, "merchants", merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")

    currency = merchant["currency"]

    # Lifetime totals, so every page is needed: an unbounded select stops
    # at 1000 rows and would quietly under-report a busy merchant's
    # takings and fees.
    successful_collections = fetch_all(
        lambda: client.table("transactions")
        .select("gross_amount, fee_amount, created_at")
        .eq("merchant_id", str(merchant_id))
        .eq("type", "collection")
        .eq("status", "successful")
    )
    total_collections = sum(
        (Decimal(str(row["gross_amount"])) for row in successful_collections), Decimal(0)
    )
    # Same definition the Super Admin dashboard uses (app/services/
    # admin_overview.py), scoped to this merchant: gross amount of
    # successful collections created today, and amount of withdrawals
    # that COMPLETED today. A withdrawal requested yesterday and paid
    # this morning counts today, because the money moved today — which is
    # the question "withdrawals today" is asking.
    now = datetime.now(timezone.utc)
    day_start = dar_es_salaam_day_start_utc(now)

    # Asked for separately rather than filtered out of the lifetime list:
    # today's rows must not depend on how many lifetime rows there are.
    collections_today = sum(
        (
            Decimal(str(row["gross_amount"]))
            for row in (
                client.table("transactions")
                .select("gross_amount, created_at")
                .eq("merchant_id", str(merchant_id))
                .eq("type", "collection")
                .eq("status", "successful")
                .gte("created_at", day_start)
                .execute()
            ).data
            or []
            if _is_today(row.get("created_at"), now)
        ),
        Decimal(0),
    )

    completed_withdrawals = (
        client.table("disbursements")
        .select("amount, completed_at")
        .eq("merchant_id", str(merchant_id))
        .eq("status", "SUCCESS")
        .gte("completed_at", day_start)
        .execute()
    ).data or []
    withdrawals_today = sum(
        (
            Decimal(str(row["amount"]))
            for row in completed_withdrawals
            if _is_today(row.get("completed_at"), now)
        ),
        Decimal(0),
    )
    total_fees_charged = sum(
        (Decimal(str(row["fee_amount"])) for row in successful_collections), Decimal(0)
    )

    pending_transactions = (
        client.table("transactions")
        .select("id", count="exact")
        .eq("merchant_id", str(merchant_id))
        .in_("status", list(_PENDING_TRANSACTION_STATUSES))
        .execute()
    ).count or 0

    successful_withdrawals = (
        client.table("transactions")
        .select("id", count="exact")
        .eq("merchant_id", str(merchant_id))
        .eq("type", "disbursement")
        .eq("status", "successful")
        .execute()
    ).count or 0

    active_links = (
        client.table("payment_links")
        .select("id, expires_at")
        .eq("merchant_id", str(merchant_id))
        .eq("status", "ACTIVE")
        .execute()
    ).data or []
    now = datetime.now(timezone.utc)
    active_payment_links = sum(
        1 for link in active_links if not link.get("expires_at") or _parse_dt(link["expires_at"]) > now
    )

    unpaid_invoices = (
        client.table("invoices")
        .select("id", count="exact")
        .eq("merchant_id", str(merchant_id))
        .in_("status", list(_UNPAID_INVOICE_STATUSES))
        .execute()
    ).count or 0

    # Cached without the two live parts: the merchant row (so a settings
    # change shows immediately) and the balance (see the docstring).
    cache_set(
        cache_key,
        {
            "total_collections": total_collections,
            "collections_today": collections_today,
            "withdrawals_today": withdrawals_today,
            "pending_transactions": pending_transactions,
            "successful_withdrawals": successful_withdrawals,
            "active_payment_links": active_payment_links,
            "unpaid_invoices": unpaid_invoices,
            "total_fees_charged": total_fees_charged,
        },
        _OVERVIEW_TTL_SECONDS,
    )

    return {
        "merchant": merchant,
        "total_collections": total_collections,
        "collections_today": collections_today,
        "withdrawals_today": withdrawals_today,
        "available_balance": get_wallet_balance(client, merchant_id=merchant_id, currency=currency),
        "pending_transactions": pending_transactions,
        "successful_withdrawals": successful_withdrawals,
        "active_payment_links": active_payment_links,
        "unpaid_invoices": unpaid_invoices,
        "total_fees_charged": total_fees_charged,
    }



def get_merchant_overview_report(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> dict:
    """Everything the Overview charts and cards need, from one pass.

    The daily series and the by-method breakdown are built from the SAME
    fetched rows rather than two queries with two filters. That is not an
    optimisation - it is what makes the bar chart's total and the donut's
    centre agree by construction. Two queries drift the moment one of
    them grows a condition the other does not, and a merchant comparing
    the two numbers has no way to tell which is wrong.

    **Source is `transactions`, not `collections`.** Two reasons:

    1. Fees are posted there (`fee_amount`), so "Fees Paid" is what was
       actually charged rather than what a pricing rule would charge now.
    2. Sandbox collections never get a transactions row, so this is
       live-only by construction. There is no environment column to
       filter on and none is needed - adding one would be a filter that
       does nothing, which reads as a guarantee it is not making.

    Reversals follow the same rule the rest of merchant reporting uses:
    only `status = 'successful'` counts. A reversed transaction leaves
    `successful` and stops counting, in the period it was reversed, which
    is how the wallet balance behaves too.

    Dates are Africa/Dar_es_Salaam calendar days, inclusive at both ends,
    matching every other merchant-facing date filter.
    """
    start_utc, end_utc = dar_es_salaam_day_bounds_utc(start_date, end_date)

    rows = fetch_all(
        lambda: client.table("transactions")
        .select("gross_amount, fee_amount, method, created_at")
        .eq("merchant_id", str(merchant_id))
        .eq("type", "collection")
        .eq("status", "successful")
        .gte("created_at", start_utc.isoformat())
        .lt("created_at", end_utc.isoformat())
    )

    # A dense day-by-day series: every calendar day in the window, zeros
    # included. A sparse one lets the chart close its own gaps, which
    # hides the quiet days - usually the ones worth seeing.
    buckets: dict[str, dict] = {}
    cursor = start_date
    while cursor <= end_date:
        buckets[cursor.isoformat()] = {
            "date": cursor.isoformat(),
            "amount": Decimal(0),
            "count": 0,
        }
        cursor += timedelta(days=1)

    by_method: dict[str, dict] = {}
    total_amount = Decimal(0)
    total_fees = Decimal(0)

    for row in rows:
        amount = Decimal(str(row.get("gross_amount") or 0))
        total_amount += amount
        total_fees += Decimal(str(row.get("fee_amount") or 0))

        day = dar_es_salaam_date(row["created_at"]).isoformat()
        bucket = buckets.get(day)
        if bucket is not None:
            bucket["amount"] += amount
            bucket["count"] += 1

        method = row.get("method") or "UNKNOWN"
        entry = by_method.setdefault(method, {"method": method, "amount": Decimal(0), "count": 0})
        entry["amount"] += amount
        entry["count"] += 1

    pending = (
        client.table("transactions")
        .select("gross_amount", count="exact")
        .eq("merchant_id", str(merchant_id))
        .eq("type", "collection")
        .in_("status", list(_PENDING_TRANSACTION_STATUSES))
        .execute()
    )
    pending_rows = pending.data or []
    pending_amount = sum(
        (Decimal(str(row.get("gross_amount") or 0)) for row in pending_rows), Decimal(0)
    )

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "series": [
            {"date": b["date"], "amount": str(b["amount"]), "count": b["count"]}
            for b in buckets.values()
        ],
        # Biggest first: a donut legend ordered by size is read top-down
        # as a ranking, which is the question being asked of it.
        "by_method": [
            {"method": e["method"], "amount": str(e["amount"]), "count": e["count"]}
            for e in sorted(by_method.values(), key=lambda e: e["amount"], reverse=True)
        ],
        "successful_collections": str(total_amount),
        "successful_count": sum(b["count"] for b in buckets.values()),
        "fees_paid": str(total_fees),
        # Pending is deliberately NOT date-filtered. "What is still in
        # flight" is a question about now, not about the reporting window
        # - a merchant narrowing to last week does not stop caring about
        # a payment that is pending today.
        "pending_collections": str(pending_amount),
        "pending_count": pending.count or len(pending_rows),
    }
