"""A reference Selcom reused must not cost a merchant their money.

`transactions.provider_reference` carries its own UNIQUE index and is
copied from the collection at push time. Nothing syncs it afterwards,
while the collection's own copy *is* refreshed from Selcom's later
replies - so the two drift apart permanently. Measured against production
on 2026-10-25: all 10,447 transactions of the preceding five days held a
reference their collection no longer had.

Every superseded value therefore stays locked in `transactions` while
being free in `collections`. When Selcom reuses one, the new collection
takes it legally and the transaction insert is what breaks:

    duplicate key value violates unique constraint
    "transactions_provider_reference_key"

That raised out of POST /v1/collections/wallet-push as a 500 *after* the
customer had been charged (INFINITYPAY-API-14). The collection survived,
later resolved to `successful`, and had no transaction behind it - so no
ledger posting, and the merchant was never credited. Four real payments
reached that state, TZS 2,500, all for one merchant.

What must hold now: the row exists, the amounts are untouched, and only
the least important column gives way.
"""

import uuid
from decimal import Decimal

import pytest

from app.services.collections import create_processing_transaction
from app.services.provider_references import (
    TRANSACTIONS_PROVIDER_REFERENCE_INDEX,
    insert_transaction_tolerating_repeated_reference,
    is_duplicate_provider_reference,
)
from tests.factories import create_merchant

REPEATED = "S20781338316"


def _seed_transaction_holding(fake_client, merchant_id, reference):
    """A transaction already holding the reference Selcom is about to reuse."""
    return fake_client.seed(
        "transactions",
        {
            "merchant_id": str(merchant_id),
            "reference": "TXN-20261024-OLDONE",
            "provider_reference": reference,
            "type": "collection",
            "method": "WALLET_PUSH",
            "collection_id": str(uuid.uuid4()),
            "gross_amount": "1000",
            "fee_amount": "23",
            "net_amount": "977",
            "currency": "TZS",
            "status": "successful",
        },
    )


def _create(fake_client, merchant_id, *, provider_reference=REPEATED, amount="1000"):
    return create_processing_transaction(
        fake_client,
        merchant_id=merchant_id,
        method="WALLET_PUSH",
        collection_id=str(uuid.uuid4()),
        provider_reference=provider_reference,
        amount=Decimal(amount),
        currency="TZS",
    )


# --- the row must exist ------------------------------------------------


def test_a_repeated_reference_no_longer_loses_the_transaction(fake_client):
    """The whole point. Before this, the insert raised and the merchant
    was never credited for a payment the customer had already made."""
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    _seed_transaction_holding(fake_client, merchant_id, REPEATED)

    row = _create(fake_client, merchant_id)

    assert row is not None
    assert row["collection_id"]


def test_the_fallback_is_the_transactions_own_reference(fake_client):
    """An identifier this app owns and knows to be unique, same reasoning
    as the collection fallback."""
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    _seed_transaction_holding(fake_client, merchant_id, REPEATED)

    row = _create(fake_client, merchant_id)

    assert row["provider_reference"] == row["reference"]
    assert row["provider_reference"] != REPEATED


def test_the_original_holder_is_untouched(fake_client):
    """Falling back must never mean taking the value off the row that
    legitimately has it."""
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    original = _seed_transaction_holding(fake_client, merchant_id, REPEATED)

    _create(fake_client, merchant_id)

    still = next(
        r for r in fake_client.table("transactions")._table.rows
        if r["id"] == original["id"]
    )
    assert still["provider_reference"] == REPEATED


def test_the_money_is_unchanged_by_the_fallback(fake_client):
    """Only the least important column gives way. If the amounts moved,
    this would be a worse bug than the one it fixes."""
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    _seed_transaction_holding(fake_client, merchant_id, REPEATED)

    clashed = _create(fake_client, merchant_id, amount="1000")
    clean = _create(fake_client, merchant_id, provider_reference="S-UNIQUE-1", amount="1000")

    assert clashed["gross_amount"] == clean["gross_amount"]
    assert clashed["fee_amount"] == clean["fee_amount"]
    assert clashed["net_amount"] == clean["net_amount"]


def test_two_collections_can_both_survive_the_same_repeat(fake_client):
    """Selcom repeating one reference across several pushes must not make
    the second and third fail where the first succeeded."""
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    _seed_transaction_holding(fake_client, merchant_id, REPEATED)

    rows = [_create(fake_client, merchant_id) for _ in range(3)]

    assert len({r["provider_reference"] for r in rows}) == 3


# --- the normal path is not disturbed ----------------------------------


def test_an_unused_reference_is_kept_exactly(fake_client):
    """Selcom's value is still what we store when it is free — the
    fallback must not fire on the ordinary path."""
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])

    row = _create(fake_client, merchant_id, provider_reference="S-FRESH-42")

    assert row["provider_reference"] == "S-FRESH-42"


def test_a_reference_free_in_transactions_is_taken_even_if_a_collection_holds_it(fake_client):
    """The indexes are separate. A collection holding the value is not a
    reason for the transaction to give it up."""
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    fake_client.seed("collections", {
        "merchant_id": str(merchant_id), "method": "PUSH", "amount": "1000",
        "currency": "TZS", "status": "processing", "provider_reference": "S-SHARED",
    })

    row = _create(fake_client, merchant_id, provider_reference="S-SHARED")

    assert row["provider_reference"] == "S-SHARED"


# --- the guard stays narrow -------------------------------------------


def test_any_other_unique_violation_still_raises(fake_client):
    """Narrow on the index name on purpose: a repeated `reference` is a
    real bug and must not be quietly retried into a second row."""
    merchant = create_merchant(fake_client)

    def _explode(*_a, **_k):
        err = Exception('duplicate key value violates unique constraint "transactions_reference_key"')
        err.code = "23505"
        err.message = str(err)
        raise err

    import app.services.provider_references as module
    original = module.insert_row
    module.insert_row = _explode
    try:
        with pytest.raises(Exception, match="transactions_reference_key"):
            insert_transaction_tolerating_repeated_reference(
                fake_client, {"merchant_id": merchant["id"]},
                fallback_reference="TXN-FALLBACK", context="test",
            )
    finally:
        module.insert_row = original


def test_a_non_duplicate_error_is_not_swallowed(fake_client):
    import app.services.provider_references as module

    def _explode(*_a, **_k):
        raise RuntimeError("database unreachable")

    original = module.insert_row
    module.insert_row = _explode
    try:
        with pytest.raises(RuntimeError, match="database unreachable"):
            insert_transaction_tolerating_repeated_reference(
                fake_client, {}, fallback_reference="TXN-FALLBACK", context="test",
            )
    finally:
        module.insert_row = original


def test_the_matcher_recognises_the_transactions_index():
    err = Exception(
        'duplicate key value violates unique constraint "transactions_provider_reference_key"'
    )
    err.code = "23505"

    assert is_duplicate_provider_reference(err, TRANSACTIONS_PROVIDER_REFERENCE_INDEX) is True
    assert is_duplicate_provider_reference(err, "collections_provider_reference_key") is False
