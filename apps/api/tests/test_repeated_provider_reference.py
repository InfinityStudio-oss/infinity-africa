"""When Selcom repeats a reference, both rows must agree on what to store.

Reported from production as INFINITYPAY-API-15's neighbour,
INFINITYPAY-API-14, on /v1/collections/wallet-push:

    APIError: duplicate key value violates unique constraint
    "transactions_provider_reference_key"

Selcom sometimes returns a reference we have already seen. Both
`collections.provider_reference` and `transactions.provider_reference`
carry a partial unique index, so both inserts have to cope with that.

Only one of them did. The collection went through
`insert_collection_tolerating_repeated_reference`, which falls back to our
own transid when Selcom repeats a value. The transactions insert directly
below it recomputed `result.reference or transid` from scratch, kept the
repeated value, and violated its own unique index - despite a comment
claiming it matched "what the linked transactions row does below".

Two consequences, and the second is the one that matters:

1. The partner gets a 500 on a push that had already been accepted.
2. The collection row survives - nothing rolls it back - so a `processing`
   collection is left with **no linked transaction**. That transaction is
   the row `resolve_collection()` needs to post ledger entries against, so
   a payment that later succeeds has nothing to settle into.

The fix is to stop computing the value twice: the transactions row now
reuses whatever the collection insert actually stored, so the two cannot
disagree by construction.
"""

import asyncio
import uuid

import pytest

from app.config import get_settings
from app.services.wallet_push import execute_wallet_push_for_payment_link
from tests.factories import create_merchant

REPEATED = "S20776126233"

CREATE_ORDER_OK = {
    "reference": "S20690427372",
    "resultcode": "000",
    "result": "SUCCESS",
    "message": "Payment notification logged",
    "data": [],
}
PUSH_PENDING_REPEATED = {
    "reference": REPEATED,
    "resultcode": "111",
    "result": "PENDING",
    "message": "Request in progress.",
    "data": [],
}


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret-do-not-use")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _Client:
    """A Selcom that hands back the same reference every time."""

    async def create_order_minimal(self, **kwargs):
        from app.services.selcom_checkout.parsing import parse_create_order_minimal_response

        return parse_create_order_minimal_response(CREATE_ORDER_OK)

    async def process_wallet_payment(self, **kwargs):
        from app.services.selcom_checkout.parsing import parse_wallet_payment_response

        return parse_wallet_payment_response(PUSH_PENDING_REPEATED)


@pytest.fixture
def _patched(monkeypatch):
    import app.services.checkout_orders as orders_module
    import app.services.wallet_push as push_module

    client = _Client()
    monkeypatch.setattr(orders_module, "SelcomCheckoutHTTPClient", lambda **kw: client)
    monkeypatch.setattr(push_module, "SelcomCheckoutHTTPClient", lambda **kw: client)


def _link(fake_client, merchant):
    return fake_client.seed(
        "payment_links",
        {
            "merchant_id": merchant["id"],
            "amount": "1000.00",
            "currency": "TZS",
            "status": "ACTIVE",
            "allowed_payment_methods": ["STK_PUSH"],
            "public_slug": "repeat-" + uuid.uuid4().hex[:8],
        },
    )


def _push(fake_client, link):
    return asyncio.run(
        execute_wallet_push_for_payment_link(
            fake_client, payment_link=link, buyer_phone="255747730270"
        )
    )


def _transactions(fake_client):
    return fake_client.table("transactions")._table.rows


def test_two_pushes_with_a_repeated_reference_both_succeed(fake_client, _patched):
    """The production failure: the second push raised on the transactions
    unique index after its collection had already been written."""
    merchant = create_merchant(fake_client)

    first = _push(fake_client, _link(fake_client, merchant))
    second = _push(fake_client, _link(fake_client, merchant))

    assert first["id"] != second["id"]


def test_every_processing_collection_has_its_transaction(fake_client, _patched):
    """The consequence that outlives the 500. resolve_collection() needs
    exactly one linked transaction to post ledger entries against, so a
    collection without one cannot settle when the payment succeeds."""
    merchant = create_merchant(fake_client)

    first = _push(fake_client, _link(fake_client, merchant))
    second = _push(fake_client, _link(fake_client, merchant))

    linked = {str(t.get("collection_id")) for t in _transactions(fake_client)}
    for collection in (first, second):
        assert collection["status"] == "processing"
        assert str(collection["id"]) in linked, "a processing collection has no transaction"


def test_the_two_rows_never_disagree_on_the_reference(fake_client, _patched):
    """The invariant the fix establishes: the transaction stores exactly
    what its collection stored, whatever the de-duplication decided."""
    merchant = create_merchant(fake_client)

    first = _push(fake_client, _link(fake_client, merchant))
    second = _push(fake_client, _link(fake_client, merchant))

    by_collection = {
        str(t["collection_id"]): t["provider_reference"] for t in _transactions(fake_client)
    }
    for collection in (first, second):
        assert by_collection[str(collection["id"])] == collection["provider_reference"]


def test_the_repeat_falls_back_rather_than_reusing_selcoms_value(fake_client, _patched):
    """The first push keeps Selcom's reference; the second cannot, so it
    falls back to our own transid. Both remain unique."""
    merchant = create_merchant(fake_client)

    first = _push(fake_client, _link(fake_client, merchant))
    second = _push(fake_client, _link(fake_client, merchant))

    assert first["provider_reference"] == REPEATED
    assert second["provider_reference"] != REPEATED
    assert second["provider_reference"], "a blank reference would be worse than a repeated one"


def test_transaction_references_stay_unique(fake_client, _patched):
    """What the database index enforces, asserted here so the fake's lack
    of one cannot hide a regression."""
    merchant = create_merchant(fake_client)

    for _ in range(3):
        _push(fake_client, _link(fake_client, merchant))

    refs = [t["provider_reference"] for t in _transactions(fake_client)]
    assert len(refs) == len(set(refs)), f"duplicate provider_reference in transactions: {refs}"
