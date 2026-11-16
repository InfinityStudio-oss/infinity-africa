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
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from supabase import Client

from app.core.cache import cache_get, cache_set, merchant_key
from app.core.errors import NotFoundError
from app.core.time import dar_es_salaam_day_start_utc, is_dar_es_salaam_today
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


def get_merchant_activity_series(
    client: Client, *, merchant_id: uuid.UUID, days: int = 14
) -> list[dict]:
    """Daily money in and money out, for the Overview charts.

    Returned as a dense series: every day in the window gets a row, zeros
    included. A sparse series makes a chart lie - the gaps close up and a
    quiet Sunday renders as if it never happened, which flattens exactly
    the dips an operator is looking for. This product has already had one
    false alarm from a window that clipped a day.

    Days are Africa/Dar_es_Salaam calendar days, matching the "today"
    figures beside the chart. Using UTC here would put the chart and the
    KPI cards a few hours out of step with each other, which reads as one
    of them being broken.

    Cached with the other aggregates, never with a balance: these are
    historical totals, so a minute of staleness costs nothing. The chart
    is a trend, not a number anyone pays against.
    """
    cache_key = merchant_key(merchant_id, "activity-series", str(days))
    cached = cache_get(cache_key)
    if cached is not None:
        return cached["series"]

    now = datetime.now(timezone.utc)
    window_start = dar_es_salaam_day_start_utc(now) - timedelta(days=days - 1)

    buckets: dict[str, dict] = {}
    for offset in range(days):
        day = (window_start + timedelta(days=offset)).date().isoformat()
        buckets[day] = {"date": day, "collected": Decimal(0), "paid_out": Decimal(0), "count": 0}

    def _bucket_for(value: str | None) -> dict | None:
        if not value:
            return None
        try:
            when = _parse_dt(value)
        except ValueError:
            return None
        # Shift into Dar es Salaam before taking the calendar date, so a
        # 01:00 local payment lands on the right day rather than the
        # previous one.
        key = (when + timedelta(hours=3)).date().isoformat()
        return buckets.get(key)

    collections = fetch_all(
        client,
        "collections",
        select="amount, status, created_at",
        filters={"merchant_id": str(merchant_id)},
    )
    for row in collections:
        if row.get("status") != "successful":
            continue
        bucket = _bucket_for(row.get("created_at"))
        if bucket is None:
            continue
        bucket["collected"] += Decimal(str(row.get("amount") or 0))
        bucket["count"] += 1

    # Money out is both products: a withdrawal a person approved, and a
    # payout an API key sent. Charting only one would show a merchant
    # half of what left their account.
    for table, amount_field, settled in (
        ("disbursements", "amount", ("COMPLETED", "PROCESSED", "SUCCESSFUL")),
        ("payouts", "total_debit", ("successful",)),
    ):
        rows = fetch_all(
            client,
            table,
            select=f"{amount_field}, status, created_at",
            filters={"merchant_id": str(merchant_id)},
        )
        for row in rows:
            if str(row.get("status") or "").upper() not in {s.upper() for s in settled}:
                continue
            bucket = _bucket_for(row.get("created_at"))
            if bucket is None:
                continue
            bucket["paid_out"] += Decimal(str(row.get(amount_field) or 0))

    series = [
        {
            "date": bucket["date"],
            "collected": str(bucket["collected"]),
            "paid_out": str(bucket["paid_out"]),
            "count": bucket["count"],
        }
        for bucket in buckets.values()
    ]
    cache_set(cache_key, {"series": series}, _SERIES_TTL_SECONDS)
    return series
