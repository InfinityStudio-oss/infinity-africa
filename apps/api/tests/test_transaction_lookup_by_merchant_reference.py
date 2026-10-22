"""A partner should be able to look up a payment by the reference they sent.

Both references are shaped `TXN-...`: the one we generate for the
transactions row, and the one a partner sends as their own order id. The
create response then hands theirs back in a field named `reference`, so
polling `/v1/transactions/{reference}` with it is the obvious thing to
do - and it returned 404 every time.

Measured in production on 2026-10-22: **3,793 of those lookups, 18.9% of
all API traffic**, with single references retried 50-90 times. One
partner was spending 48.9% of their calls on it. They had not complained;
they had simply never had payment status work, on their first day doing
TZS 414,800 of volume.

The fallback resolves their reference through the collection, so the
answer is the same row every other status endpoint returns - and it needs
no change on the partner's side.

The scoping matters as much as the feature. `merchant_reference` is
unique **per merchant**, not globally: two merchants can both call an
order "ORDER-1". So the lookup is merchant-scoped, and never uses
`.maybe_single()`, which raises outright on more than one row rather than
returning anything useful.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    create_merchant,
    create_transaction,
    make_api_key,
)

client = TestClient(app)
URL = "/v1/transactions/{}"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _merchant_with_key(fake_client):
    merchant = create_merchant(fake_client)
    raw_key, _row = make_api_key(
        fake_client, uuid.UUID(merchant["id"]), scopes=["transactions:read"]
    )
    return merchant, {"X-API-Key": raw_key}


def _payment(fake_client, merchant, *, their_ref, our_ref=None, amount="500.00"):
    collection = fake_client.seed(
        "collections",
        {
            "merchant_id": merchant["id"],
            "merchant_reference": their_ref,
            "status": "successful",
            "amount": amount,
            "currency": "TZS",
            "environment": "live",
        },
    )
    tx = create_transaction(
        fake_client,
        uuid.UUID(merchant["id"]),
        collection_id=collection["id"],
        reference=our_ref or f"TXN-{uuid.uuid4().hex[:8].upper()}",
        gross_amount=amount,
        fee_amount="11.50",
        net_amount="488.50",
    )
    return collection, tx


# --- the fix -----------------------------------------------------------


def test_a_partner_can_look_up_by_their_own_reference(fake_client):
    """The exact call that was 404ing 3,793 times."""
    merchant, headers = _merchant_with_key(fake_client)
    _collection, tx = _payment(fake_client, merchant, their_ref="TXN-1792656322-5117")

    response = client.get(URL.format("TXN-1792656322-5117"), headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["reference"] == tx["reference"]


def test_our_own_reference_still_works(fake_client):
    """The original behaviour, unchanged - this is a fallback, not a
    replacement."""
    merchant, headers = _merchant_with_key(fake_client)
    _collection, tx = _payment(
        fake_client, merchant, their_ref="ORDER-9", our_ref="TXN-20261022-ABCD1234"
    )

    response = client.get(URL.format("TXN-20261022-ABCD1234"), headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["reference"] == "TXN-20261022-ABCD1234"


def test_the_answer_describes_the_payment(fake_client):
    merchant, headers = _merchant_with_key(fake_client)
    _payment(fake_client, merchant, their_ref="TXN-ME-1", amount="500.00")

    data = client.get(URL.format("TXN-ME-1"), headers=headers).json()["data"]

    assert data["status"] == "successful"
    assert str(data["gross_amount"]) in ("500.00", "500.0")


def test_an_unknown_reference_is_still_a_404(fake_client):
    _merchant, headers = _merchant_with_key(fake_client)

    assert client.get(URL.format("TXN-DOES-NOT-EXIST"), headers=headers).status_code == 404


# --- scoping: the part that must not leak ------------------------------


def test_one_merchants_reference_does_not_resolve_for_another(fake_client):
    """merchant_reference is unique per merchant, so the same string can
    exist twice. Without scoping this would be a cross-merchant read."""
    owner, _owner_headers = _merchant_with_key(fake_client)
    _payment(fake_client, owner, their_ref="ORDER-1")
    _outsider, outsider_headers = _merchant_with_key(fake_client)

    response = client.get(URL.format("ORDER-1"), headers=outsider_headers)

    assert response.status_code in (403, 404)


def test_two_merchants_using_the_same_reference_both_get_their_own(fake_client):
    """The collision case, end to end - each caller must see their own
    payment and nobody else's."""
    a, a_headers = _merchant_with_key(fake_client)
    b, b_headers = _merchant_with_key(fake_client)
    _ca, tx_a = _payment(fake_client, a, their_ref="ORDER-1", amount="100.00")
    _cb, tx_b = _payment(fake_client, b, their_ref="ORDER-1", amount="900.00")

    got_a = client.get(URL.format("ORDER-1"), headers=a_headers).json()["data"]
    got_b = client.get(URL.format("ORDER-1"), headers=b_headers).json()["data"]

    assert got_a["reference"] == tx_a["reference"]
    assert got_b["reference"] == tx_b["reference"]
    assert got_a["reference"] != got_b["reference"]


def test_a_duplicated_reference_within_one_merchant_does_not_raise(fake_client):
    """A merchant reusing their own reference twice must produce a clean
    404, not a 500. `.maybe_single()` raises on multiple rows - the
    failure mode that broke the wallet ledger for the largest merchants
    once already."""
    merchant, headers = _merchant_with_key(fake_client)
    _payment(fake_client, merchant, their_ref="DUP-1", amount="100.00")
    _payment(fake_client, merchant, their_ref="DUP-1", amount="200.00")

    response = client.get(URL.format("DUP-1"), headers=headers)

    assert response.status_code != 500, response.text
    assert response.status_code == 404


def test_an_unauthenticated_caller_gets_nothing(fake_client):
    merchant = create_merchant(fake_client)
    _payment(fake_client, merchant, their_ref="TXN-OPEN-1")

    assert client.get(URL.format("TXN-OPEN-1")).status_code in (401, 403)


def test_a_collection_with_no_transaction_is_a_404_not_a_crash(fake_client):
    """A payment that never reached a transaction - the shape left behind
    by the duplicate-reference bug - must answer cleanly."""
    merchant, headers = _merchant_with_key(fake_client)
    fake_client.seed(
        "collections",
        {
            "merchant_id": merchant["id"],
            "merchant_reference": "TXN-ORPHAN-1",
            "status": "processing",
            "amount": "500.00",
            "currency": "TZS",
        },
    )

    assert client.get(URL.format("TXN-ORPHAN-1"), headers=headers).status_code == 404
