"""Selcom's own identifiers live under unique indexes of ours.

`collections.provider_reference` and `checkout_orders.provider_reference`
both hold a value Selcom chose, under a UNIQUE index this app added. That
is the right constraint — two rows claiming the same provider reference
would make a callback ambiguous — but it puts a value we do not control
on the critical path of a live payment. When Selcom repeats a reference,
the insert raises

    duplicate key value violates unique constraint
    "collections_provider_reference_key"

and a push that has *already been sent to the customer* fails with a 500
before its row exists. The customer gets the payment prompt; we have no
record of it.

So a repeat must not be fatal. It is answered by falling back to an
identifier of our own — the `transid` this app generated for the same
push, which is already what the linked transactions row uses when Selcom
returns no reference at all (`result.reference or transid`). The row then
exists, stays findable, and keeps Selcom's reply whole in `raw_response`.

The check is deliberately narrow on both the SQLSTATE and the index name:
any other unique violation is a real bug and must keep raising rather
than be quietly retried into a second row.
"""

import logging

from supabase import Client

from app.services.crud import insert_row, update_row

logger = logging.getLogger("infinity.provider_references")

UNIQUE_VIOLATION = "23505"
COLLECTIONS_PROVIDER_REFERENCE_INDEX = "collections_provider_reference_key"
CHECKOUT_ORDERS_PROVIDER_REFERENCE_INDEX = "checkout_orders_provider_reference_key"
TRANSACTIONS_PROVIDER_REFERENCE_INDEX = "transactions_provider_reference_key"


def is_duplicate_provider_reference(exc: Exception, index_name: str) -> bool:
    """True only for "the provider gave us a reference we already hold"."""
    code = getattr(exc, "code", None)
    message = str(getattr(exc, "message", "") or exc)
    return code == UNIQUE_VIOLATION and index_name in message


def insert_collection_tolerating_repeated_reference(
    client: Client,
    row: dict,
    *,
    fallback_reference: str,
    context: str,
) -> dict:
    """Inserts a collection, surviving a provider reference Selcom reused.

    `fallback_reference` must be an identifier this app generated for the
    same push — the `transid`, in every current caller — so the row stays
    unique and findable. Passing the provider's value again, or None,
    would defeat the point: None leaves the row unmatchable by
    `resolve_collection_from_callback`, which looks collections up by
    exactly this column.

    Logged at warning, never captured: a provider repeating its own
    identifier is not a fault of ours to fix, but a run of them says
    something is wrong upstream and should be visible.
    """
    try:
        return insert_row(client, "collections", row)
    except Exception as exc:
        if not is_duplicate_provider_reference(exc, COLLECTIONS_PROVIDER_REFERENCE_INDEX):
            raise
        logger.warning(
            "collection_duplicate_provider_reference context=%s provider_reference=%s "
            "falling_back_to=%s",
            context,
            row.get("provider_reference"),
            fallback_reference,
        )
        return insert_row(client, "collections", {**row, "provider_reference": fallback_reference})


def insert_transaction_tolerating_repeated_reference(
    client: Client,
    row: dict,
    *,
    fallback_reference: str,
    context: str,
) -> dict:
    """Inserts a transaction, surviving a provider reference already held.

    `transactions.provider_reference` carries its own UNIQUE index, and the
    value put in it is Selcom's — copied from the collection at push time.
    Nothing ever syncs it afterwards, while
    update_collection_tolerating_repeated_reference *does* refresh the
    collection's copy from Selcom's later replies. Measured on 2026-10-25:
    all 10,447 transactions of the preceding five days held a reference
    their collection no longer had.

    So every superseded value stays locked in `transactions` while being
    free in `collections`. When Selcom then reuses one - which they
    demonstrably do - the new collection takes it legally and this insert
    is the thing that breaks:

        duplicate key value violates unique constraint
        "transactions_provider_reference_key"

    That raised out of POST /v1/collections/wallet-push as a 500, *after*
    the customer had already been charged, leaving a collection that later
    resolved to `successful` with no transaction behind it - so no ledger
    posting, and the merchant never credited. Four real payments reached
    that state (TZS 2,500, all BennyWiFi) before this guard existed.

    The fallback is the transaction's own generated reference, which is
    unique by construction and is an identifier this app owns - the same
    reasoning as the collection fallback. Losing Selcom's value here costs
    nothing that matters: the collection still holds the authoritative
    reference, and this column was already unreliable for lookups because
    of the drift above. A row that exists and is slightly less searchable
    beats a 500 on a payment the customer has already made.

    Narrow on both SQLSTATE and index name, so any other unique violation
    - a repeated `reference`, say - still raises as the real bug it is.
    """
    try:
        return insert_row(client, "transactions", row)
    except Exception as exc:
        if not is_duplicate_provider_reference(exc, TRANSACTIONS_PROVIDER_REFERENCE_INDEX):
            raise
        logger.warning(
            "transaction_duplicate_provider_reference context=%s provider_reference=%s "
            "falling_back_to=%s",
            context,
            row.get("provider_reference"),
            fallback_reference,
        )
        return insert_row(client, "transactions", {**row, "provider_reference": fallback_reference})


def update_collection_tolerating_repeated_reference(
    client: Client,
    collection_id,
    changes: dict,
    *,
    context: str,
) -> dict:
    """Applies an update, surviving a provider reference Selcom reused.

    The reconciliation path refreshes `provider_reference` from whatever
    Selcom's latest callback or status query returned. When that value
    already belongs to a *different* collection, the update raises 23505
    and the whole resolution fails — on the webhook path, meaning a paid
    collection never gets credited.

    The recovery is to keep the reference the row already has. We cannot
    adopt a value that identifies another collection, and the row's own
    reference is what every callback and status lookup has been using, so
    leaving it alone is both correct and the least surprising. Every other
    field in the update still applies, including raw_response, so Selcom's
    reply is recorded in full and the colliding value is never lost.
    """
    try:
        return update_row(client, "collections", collection_id, changes)
    except Exception as exc:
        if not is_duplicate_provider_reference(exc, COLLECTIONS_PROVIDER_REFERENCE_INDEX):
            raise
        logger.warning(
            "collection_duplicate_provider_reference_on_update context=%s collection_id=%s "
            "rejected_reference=%s keeping_existing",
            context,
            collection_id,
            changes.get("provider_reference"),
        )
        kept = {k: v for k, v in changes.items() if k != "provider_reference"}
        return update_row(client, "collections", collection_id, kept)
