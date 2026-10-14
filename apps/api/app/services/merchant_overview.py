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
from datetime import datetime, timezone
from decimal import Decimal

from supabase import Client

from app.core.cache import cache_get, cache_set, merchant_key
from app.core.errors import NotFoundError
from app.core.time import dar_es_salaam_day_start_utc, is_dar_es_salaam_today
from app.services.crud import fetch_all, get_by_id
from app.services.ledger import get_wallet_balance


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
