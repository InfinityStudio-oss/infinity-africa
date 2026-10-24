"""Did the merchant's own system actually hear about this payment?

A collection can be entirely successful on our side - customer charged,
wallet credited, nothing wrong anywhere in the ledger - while the
merchant's endpoint never received the notification. Their screen then
shows a payment they cannot act on, and from the customer's side the
service simply never activates.

That gap was invisible to the merchant. The Collections page showed
"Success", because the payment *was* a success; the delivery failure
lived only in webhook_events, which merchants cannot see. On 2026-10-23
that cost one partner nine customers in a day, every one of which had to
be activated by hand after they complained.

So the delivery outcome is read back alongside the payment, and the
merchant is told plainly: succeeded, but your endpoint returned 500.

webhook_events has no collection_id column - the link lives inside the
delivered payload, which carries `collection_id`. PostgREST can filter on
it directly (`payload->>collection_id`), so this stays one batched query
for a whole page rather than a lookup per row.
"""

from __future__ import annotations

import uuid

from supabase import Client

from app.services.crud import fetch_in_chunks

# Only the events that describe a payment's outcome. A merchant does not
# need to be told their endpoint missed an event that was never about
# money reaching them.
COLLECTION_EVENTS = ("collection.success", "collection.failed")

# The statuses worth surfacing. `delivered` is reported too, so a caller
# can distinguish "delivered fine" from "no webhook configured at all" -
# the UI only draws attention to the failures.
_SORT_KEY = "created_at"


def batch_collection_webhook_status(
    client: Client,
    *,
    merchant_id: uuid.UUID | str,
    collection_ids: list[str] | set[str],
) -> dict[str, dict]:
    """collection_id -> how its notification delivery went.

    Merchant-scoped on purpose: the filter is on merchant_id as well as
    the collection ids, so this can never read another merchant's delivery
    history even if a caller passes an id they do not own.

    A collection with no row here simply does not appear - which covers
    both "this merchant has no webhook configured" and "the event has not
    been created yet". Callers treat a missing key as "nothing to say".
    """
    ids = [str(collection_id) for collection_id in collection_ids if collection_id]
    if not ids:
        return {}

    rows = fetch_in_chunks(
        lambda batch: client.table("webhook_events")
        .select("payload, event_name, status, response_status_code, attempts, created_at")
        .eq("merchant_id", str(merchant_id))
        .in_("payload->>collection_id", batch),
        ids,
    )

    latest: dict[str, dict] = {}
    for row in rows:
        payload = row.get("payload") or {}
        collection_id = str(payload.get("collection_id") or "")
        if not collection_id or row.get("event_name") not in COLLECTION_EVENTS:
            continue
        # A collection can in principle produce more than one event; the
        # most recent one is the current truth about its delivery.
        seen = latest.get(collection_id)
        if seen is None or str(row.get(_SORT_KEY) or "") >= str(seen.get(_SORT_KEY) or ""):
            latest[collection_id] = row

    return {
        collection_id: {
            "status": row.get("status"),
            "response_code": row.get("response_status_code"),
            "attempts": row.get("attempts"),
            "event_name": row.get("event_name"),
            _SORT_KEY: row.get(_SORT_KEY),
        }
        for collection_id, row in latest.items()
    }


def apply_webhook_status(rows: list[dict], statuses: dict[str, dict]) -> list[dict]:
    """Thread the delivery outcome onto collection rows for the response.

    Returns new dicts rather than mutating the rows, so nothing that reads
    a collection for a financial purpose can be affected by a display
    field being attached to it.
    """
    out = []
    for row in rows:
        found = statuses.get(str(row.get("id")))
        out.append(
            {
                **row,
                "webhook_delivery_status": found.get("status") if found else None,
                "webhook_response_code": found.get("response_code") if found else None,
                "webhook_attempts": found.get("attempts") if found else None,
            }
        )
    return out
