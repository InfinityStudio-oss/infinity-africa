"""Who paid, for rows that reference a collection.

A ledger entry and a transaction both point at a collection, and the
collection is what records the customer's phone number
(`collections.customer_phone`). Resolving it here, on read, keeps the
number in exactly one place: nothing is copied onto `ledger_entries` or
`transactions` at write time, so no copy can drift from the collection it
came from, and every historic row shows a phone with no backfill.

Deliberately its own module rather than part of
`app/services/collections.py`: that module imports `app/services/ledger.py`,
which is one of this helper's callers, so putting it there would create an
import cycle.
"""

import uuid

from supabase import Client


def payer_phones_for_collections(
    client: Client, collection_ids: set[str] | set[uuid.UUID]
) -> dict[str, str | None]:
    """Maps collection id -> customer phone, in one batched query.

    Callers pass every collection id on the page at once rather than
    looking each up in a loop. An id with no row, or a row with no phone
    recorded, is simply absent from the result — callers `.get()` it and
    render "not available" rather than guessing a number.
    """
    ids = [str(cid) for cid in collection_ids if cid]
    if not ids:
        return {}

    rows = (
        client.table("collections").select("id,customer_phone").in_("id", ids).execute().data or []
    )
    return {row["id"]: row.get("customer_phone") for row in rows}
