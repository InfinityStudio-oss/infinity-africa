"""Generic supabase-py query helpers shared by every resource service.

There's no ORM/typed query layer yet (see app/database/session.py) — these
wrap the repeated "list/get/insert/update, scoped to a merchant" pattern
that's otherwise identical across merchants/api_keys/payment_links/etc.

Known limitation: PostgREST returns `numeric` columns as JSON numbers, so
money amounts round-trip through Python `float` here before Pydantic
coerces them back to `Decimal` in the response schema — floating-point
artifacts are possible. Acceptable for now; revisit if/when a typed query
layer (e.g. SQLAlchemy Core against DATABASE_URL) replaces this.
"""

import uuid
from typing import Any

from supabase import Client

from app.core.pagination import PaginationParams


def list_for_merchant(
    client: Client,
    table: str,
    *,
    merchant_id: uuid.UUID,
    pagination: PaginationParams,
    order_by: str = "created_at",
    ascending: bool = False,
    filters: dict[str, Any] | None = None,
    search: tuple[str, str] | None = None,
) -> tuple[list[dict], int]:
    """`search` is an optional (column, term) pair matched case-insensitively
    as a substring. Deliberately one column rather than an OR across
    several: PostgREST's or_() has syntax the in-memory test client does
    not model, and a search that passes its tests while behaving
    differently against the real database is worse than a narrower one
    that does not.

    Applied before the range, so paging reflects the filtered total rather
    than the filtered slice of one page."""
    query = client.table(table).select("*", count="exact").eq("merchant_id", str(merchant_id))
    for column, value in (filters or {}).items():
        query = query.eq(column, value)
    if search:
        column, term = search
        query = query.ilike(column, f"%{term}%")
    query = query.order(order_by, desc=not ascending).range(pagination.start, pagination.end)

    result = query.execute()
    return result.data or [], result.count or 0


def execute_maybe_single(query) -> dict | None:
    """`.maybe_single().execute()` returns `None` outright — not a Result
    object — when zero rows match (postgrest-py 2.x's documented contract:
    `execute(self) -> Optional[SingleAPIResponse]`). Every `.maybe_single()`
    call site in this codebase must route through this rather than reading
    `.execute().data` directly, which raises AttributeError against the
    real client on the zero-row case (the in-memory fake test client
    doesn't replicate this quirk — it always returns a wrapper object).
    """
    result = query.execute()
    return result.data if result is not None else None


def get_for_merchant(
    client: Client, table: str, *, merchant_id: uuid.UUID, row_id: uuid.UUID
) -> dict | None:
    query = (
        client.table(table)
        .select("*")
        .eq("merchant_id", str(merchant_id))
        .eq("id", str(row_id))
        .maybe_single()
    )
    return execute_maybe_single(query)


def get_by_id(client: Client, table: str, row_id: uuid.UUID) -> dict | None:
    query = client.table(table).select("*").eq("id", str(row_id)).maybe_single()
    return execute_maybe_single(query)


def insert_row(client: Client, table: str, data: dict) -> dict:
    result = client.table(table).insert(data).execute()
    return result.data[0]


def update_row(
    client: Client,
    table: str,
    row_id: uuid.UUID,
    data: dict,
    *,
    merchant_id: uuid.UUID | None = None,
) -> dict | None:
    query = client.table(table).update(data).eq("id", str(row_id))
    if merchant_id is not None:
        query = query.eq("merchant_id", str(merchant_id))

    result = query.execute()
    return result.data[0] if result.data else None
