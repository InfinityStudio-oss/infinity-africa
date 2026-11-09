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

The link to the payment lives inside the delivered payload. PostgREST can
filter on that JSON directly, and this originally did - but no index can
serve `payload->>'collection_id'`, so every lookup scanned the whole of
webhook_events. At ~69,000 rows growing by ~4,700 a day, a cold run took
over five seconds and the statement timeout began cancelling it, which
the Super Admin Collections page rendered as "no collections recorded".

So collection_id is now a stored generated column over that same JSON,
with its own index. Same one batched query for a whole page rather than a
lookup per row, but an index lookup instead of a scan - and the payload
blob no longer has to come back over the wire at all.
"""

from __future__ import annotations

import logging
import uuid

from supabase import Client

from app.services.crud import fetch_in_chunks

logger = logging.getLogger(__name__)

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
        .select("collection_id, event_name, status, response_status_code, attempts, created_at")
        .eq("merchant_id", str(merchant_id))
        .in_("collection_id", batch)
        .in_("event_name", list(COLLECTION_EVENTS)),
        ids,
    )

    # A collection can in principle produce more than one event; the most
    # recent one is the current truth about its delivery.
    return _latest_by_collection(rows)


def admin_batch_collection_webhook_status(
    client: Client, collection_ids: list[str] | set[str]
) -> dict[str, dict]:
    """The same lookup across every merchant, for Super Admin.

    Separate function rather than an optional merchant_id, deliberately.
    This one cannot be scoped, so a merchant-facing caller must not be
    able to reach it by leaving an argument out - the name says who it is
    for and the merchant-scoped version stays the default.

    Super Admin fields the "my customer paid and was never connected"
    complaint, and until now that was the one screen where the answer was
    invisible: the merchant could see the delivery failure on their own
    page, the person being asked about it could not.
    """
    ids = [str(collection_id) for collection_id in collection_ids if collection_id]
    if not ids:
        return {}

    # Supplementary, and treated as such. This answers "did the
    # merchant's endpoint hear about it" alongside a list of payments;
    # the payments are the page. A collection with no row here already
    # renders as "nothing to say" (see the docstring above), so a lookup
    # that fails can return the same thing instead of taking the whole
    # Collections page down with it.
    #
    # That is not theoretical. This lookup timed out in production and
    # the page showed "No collections have been recorded yet" over
    # 85,000 real ones, because a 500 here is a 500 for everything.
    # Losing one display column is the right failure; losing the page is
    # not.
    return _latest_by_collection(_rows_in_batches(client, ids))


# Small enough that one statement stays short, and that losing a batch
# loses a slice of a page rather than the page. The URL limit allows far
# more (see crud._IN_CHUNK), but length was never what hurt here: this
# table is rewritten on every delivery attempt, so it carries a lot of
# dead rows and occasionally stalls for seconds. A 100-id statement that
# normally runs in 50ms has room to be ten times slower and still finish
# inside the 8s the database allows it.
_BATCH = 100


def _rows_in_batches(client: Client, ids: list[str]) -> list[dict]:
    """Every delivery row for these collections, batch by batch, where a
    failed batch costs only itself.

    `fetch_in_chunks` is all-or-nothing: one statement timing out loses
    every row, so the Super Admin Collections page showed an empty
    "Merchant notified" column for all hundred rows because of a stall
    affecting some of them. Partial truth is worth more than none here -
    this answers a display column, and a collection with no row already
    renders as nothing-to-say.
    """
    rows: list[dict] = []
    for index in range(0, len(ids), _BATCH):
        batch = ids[index : index + _BATCH]
        try:
            rows.extend(
                (
                    client.table("webhook_events")
                    .select(
                        "collection_id, event_name, status, "
                        "response_status_code, attempts, created_at"
                    )
                    .in_("collection_id", batch)
                    # Filtered here rather than in _latest_by_collection:
                    # the rows that are not about a payment outcome are
                    # discarded anyway, and discarding them in Postgres
                    # keeps them off the wire.
                    .in_("event_name", list(COLLECTION_EVENTS))
                    .execute()
                ).data
                or []
            )
        except Exception:
            logger.warning(
                "webhook_status_batch_unavailable collections=%s offset=%s - "
                "delivery status omitted for these, the rest still shown",
                len(batch),
                index,
                exc_info=True,
            )
    return rows


def _latest_by_collection(rows: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for row in rows:
        # collection_id is a stored generated column off payload->>'collection_id';
        # reading it directly keeps the whole payload blob off the wire.
        collection_id = str(row.get("collection_id") or "")
        if not collection_id or row.get("event_name") not in COLLECTION_EVENTS:
            continue
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
