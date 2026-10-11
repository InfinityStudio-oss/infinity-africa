"""Super Admin "Customers" — GET /v1/admin/customers.

There is no populated customers table to read from: public.customers
exists in the schema but is never written to by any real code path (a
collection's customer_id is only ever set if a caller explicitly passes
one, which none of the real collection-creation flows do) — it would
show zero rows if queried directly. What genuinely exists, for every
real payment, is `collections.customer_phone` (always present) and,
where the collection is payment-link-bound, `payment_links.customer_name`
(often present). "Customers" here is derived by grouping real collections
by (merchant_id, customer_phone) — matching the page's own description,
"everyone who has actually paid a merchant" — rather than reading an
empty table.

Aggregation happens in Python, not SQL, since supabase-py's query
builder has no GROUP BY. _MAX_COLLECTIONS_SCANNED is the honest boundary
of that approach — a real materialized view/RPC would be needed if
collection volume grows far beyond it, not attempted here.

That cap is now applied while paging, which is the only place it can be
applied truthfully: PostgREST answers a single request with at most 1000
rows no matter what `.limit()` asks for, so `.limit(5000)` returned a
thousand and said nothing about the rest.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from supabase import Client

from app.core.pagination import PaginationParams
from app.core.time import dar_es_salaam_date
from app.services.admin_directory import batch_merchant_codes, batch_merchant_names
from app.services.crud import fetch_all

_MAX_COLLECTIONS_SCANNED = 5000


@dataclass
class _CustomerAgg:
    merchant_id: str
    phone: str
    full_name: str | None = None
    currency: str = "TZS"
    total_spent: Decimal = field(default_factory=lambda: Decimal(0))
    transaction_count: int = 0
    first_seen_at: str | None = None
    last_transaction_at: str | None = None


def _earliest(a: str | None, b: str) -> str:
    return b if a is None or b < a else a


def _latest(a: str | None, b: str) -> str:
    return b if a is None or b > a else a


def _grouped_customers(client: Client, *, merchant_id: uuid.UUID | None) -> list[_CustomerAgg]:
    """Every customer, newest activity first. The one definition of "a
    customer" that both the list and its summary read, so a KPI card can
    never disagree with the table beneath it."""
    def query():
        q = (
            client.table("collections")
            .select(
                "merchant_id,customer_phone,payment_link_id,amount,currency,status,completed_at,created_at"
            )
            .order("created_at", desc=True)
        )
        return q.eq("merchant_id", str(merchant_id)) if merchant_id is not None else q

    # Paged, because the server answers any single request with at most
    # 1000 rows however large a .limit() asks for. The old
    # .limit(_MAX_COLLECTIONS_SCANNED) therefore scanned 1000 collections,
    # not 5000, and the page silently described only the most recent
    # thousand payments - 547 customers where there were 940.
    collections = fetch_all(query, max_rows=_MAX_COLLECTIONS_SCANNED)
    collections = [c for c in collections if c.get("customer_phone")]

    payment_link_ids = {c["payment_link_id"] for c in collections if c.get("payment_link_id")}
    names_by_payment_link_id: dict[str, str] = {}
    if payment_link_ids:
        links = (
            client.table("payment_links")
            .select("id,customer_name")
            .in_("id", list(payment_link_ids))
            .execute()
        ).data or []
        names_by_payment_link_id = {link["id"]: link["customer_name"] for link in links if link.get("customer_name")}

    groups: dict[tuple[str, str], _CustomerAgg] = {}
    for row in collections:
        key = (row["merchant_id"], row["customer_phone"])
        agg = groups.setdefault(key, _CustomerAgg(merchant_id=row["merchant_id"], phone=row["customer_phone"]))

        name = names_by_payment_link_id.get(row.get("payment_link_id"))
        if name and not agg.full_name:
            agg.full_name = name

        agg.currency = row.get("currency") or agg.currency
        agg.transaction_count += 1
        if row["status"] == "successful":
            agg.total_spent += Decimal(str(row["amount"]))

        activity_at = row.get("completed_at") or row["created_at"]
        agg.first_seen_at = _earliest(agg.first_seen_at, row["created_at"])
        agg.last_transaction_at = _latest(agg.last_transaction_at, activity_at)

    return sorted(groups.values(), key=lambda a: a.last_transaction_at or "", reverse=True)


def summarise_admin_customers(client: Client, *, merchant_id: uuid.UUID | None) -> dict:
    """The three figures above the table, counted across **every**
    customer rather than the page the browser happened to receive.

    The page asks for page_size=100, which the API caps at 100, and the
    cards used to count the rows that came back - so they read "Total
    Customers 100 / Repeat 53" when the real figures were 940 and 461,
    with 840 customers invisible. A total that is exactly the page size
    is not a total.
    """
    customers = _grouped_customers(client, merchant_id=merchant_id)
    month_prefix = dar_es_salaam_date(datetime.now(timezone.utc)).strftime("%Y-%m")
    return {
        "total_customers": len(customers),
        # First seen inside the current Tanzanian month, matching every
        # other "this month" figure on the platform.
        "new_this_month": sum(
            1
            for c in customers
            if c.first_seen_at and dar_es_salaam_date(c.first_seen_at).strftime("%Y-%m") == month_prefix
        ),
        "repeat_customers": sum(1 for c in customers if c.transaction_count > 1),
    }


def list_admin_customers(
    client: Client, *, merchant_id: uuid.UUID | None, pagination: PaginationParams
) -> tuple[list[dict], int]:
    ordered = _grouped_customers(client, merchant_id=merchant_id)
    total = len(ordered)
    page = ordered[pagination.start : pagination.end + 1]

    merchant_ids = {a.merchant_id for a in page}
    merchant_names = batch_merchant_names(client, merchant_ids)
    merchant_codes = batch_merchant_codes(client, merchant_ids)

    data = [
        {
            "id": f"{a.merchant_id}:{a.phone}",
            "merchant_id": a.merchant_id,
            "merchant_name": merchant_names.get(a.merchant_id, ""),
            "merchant_code": merchant_codes.get(a.merchant_id),
            "full_name": a.full_name,
            "phone": a.phone,
            "currency": a.currency,
            "total_spent": a.total_spent,
            "transaction_count": a.transaction_count,
            "first_seen_at": a.first_seen_at,
            "last_transaction_at": a.last_transaction_at,
        }
        for a in page
    ]
    return data, total
