"""Selcom repeating a reference must not fail a live payment.

checkout_orders.provider_reference holds Selcom's own identifier under a
unique index of ours. In production Selcom handed back a reference we
already held, the insert hit
`duplicate key value violates unique constraint
"checkout_orders_provider_reference_key"`, and a merchant's
/v1/collections/wallet-push call returned 500 — on the Direct Wallet
Push path, which is the one every partner integrates against.

Their value, our constraint, our outage. The order is now recorded
without the duplicated column: our own order_id identifies it
everywhere that matters, and Selcom's reply is kept whole in
raw_response.
"""

import uuid
from decimal import Decimal

import pytest
from postgrest.exceptions import APIError

import app.services.checkout_orders as checkout_orders
from app.services.checkout_orders import _is_duplicate_provider_reference


def _api_error(message: str, code: str) -> APIError:
    return APIError({"message": message, "code": code, "details": None, "hint": None})


_DUPLICATE = _api_error(
    'duplicate key value violates unique constraint "checkout_orders_provider_reference_key"', "23505"
)


# --- the detection is deliberately narrow ----------------------------------


def test_selcoms_duplicate_reference_is_recognised():
    assert _is_duplicate_provider_reference(_DUPLICATE) is True


def test_our_own_duplicate_order_id_is_not_swallowed():
    """A repeated order_id is ours to generate, so a collision there is a
    real bug. It must keep raising rather than quietly writing a second
    row."""
    exc = _api_error('duplicate key value violates unique constraint "checkout_orders_order_id_key"', "23505")
    assert _is_duplicate_provider_reference(exc) is False


@pytest.mark.parametrize(
    "exc",
    [
        _api_error("null value in column violates not-null constraint", "23502"),
        _api_error("permission denied", "42501"),
        RuntimeError("connection reset"),
    ],
    ids=["not-null", "permission", "plain-exception"],
)
def test_other_failures_still_raise(exc):
    assert _is_duplicate_provider_reference(exc) is False


# --- and the order still gets written --------------------------------------


class _Result:
    is_success = True
    reference = "0289999288"  # the value Selcom repeated
    gateway_buyer_uuid = "g-1"
    payment_token = "tok"
    qr = None
    payment_gateway_url = "https://pay.example"
    resultcode = "000"
    result = "SUCCESS"
    message = "Payment notification logged"
    raw_response = {"reference": "0289999288", "resultcode": "000"}


@pytest.fixture
def selcom_returns_a_duplicate(monkeypatch):
    class _Client:
        def __init__(self, **_kwargs):
            pass

        async def create_order_minimal(self, **_kwargs):
            return _Result()

    monkeypatch.setattr(checkout_orders, "SelcomCheckoutHTTPClient", _Client)
    monkeypatch.setattr(checkout_orders, "get_selcom_checkout_credentials", lambda: None)


async def _create(client):
    return await checkout_orders.create_checkout_order_minimal(
        client,
        merchant_id=uuid.uuid4(),
        buyer_email="buyer@example.tz",
        buyer_name="Buyer",
        buyer_phone="255700000000",
        amount=Decimal(5000),
        currency="TZS",
        no_of_items=1,
    )


@pytest.mark.asyncio
async def test_the_payment_survives_a_repeated_reference(selcom_returns_a_duplicate, monkeypatch):
    """The regression. Before this, the second order 500d the merchant."""
    attempts = []

    def fake_insert(_client, _table, data):
        attempts.append(data)
        if len(attempts) == 1:
            raise _DUPLICATE
        return {"id": str(uuid.uuid4()), **data}

    monkeypatch.setattr(checkout_orders, "insert_row", fake_insert)

    order = await _create(object())

    assert len(attempts) == 2, "the insert was not retried without the duplicated column"
    assert attempts[0]["provider_reference"] == "0289999288"
    assert attempts[1]["provider_reference"] is None
    # Nothing else about the order changed, and Selcom's reply is intact.
    assert order["order_id"] == attempts[0]["order_id"]
    assert order["status"] == "created"
    assert order["raw_response"]["reference"] == "0289999288"


@pytest.mark.asyncio
async def test_a_healthy_order_is_inserted_once(selcom_returns_a_duplicate, monkeypatch):
    """No second write when the first one worked."""
    attempts = []

    def fake_insert(_client, _table, data):
        attempts.append(data)
        return {"id": str(uuid.uuid4()), **data}

    monkeypatch.setattr(checkout_orders, "insert_row", fake_insert)

    order = await _create(object())

    assert len(attempts) == 1
    assert order["provider_reference"] == "0289999288"


@pytest.mark.asyncio
async def test_an_unrelated_insert_failure_still_surfaces(selcom_returns_a_duplicate, monkeypatch):
    """Only the one known provider quirk is recovered from. Everything
    else is a real error and must reach the caller."""

    def fake_insert(_client, _table, _data):
        raise _api_error("null value in column violates not-null constraint", "23502")

    monkeypatch.setattr(checkout_orders, "insert_row", fake_insert)

    with pytest.raises(APIError):
        await _create(object())
