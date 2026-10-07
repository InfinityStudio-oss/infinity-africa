"""Per-network minimum amounts, and the promise that a payment which
cannot succeed never reaches Selcom.

Mixx by Yas (Tigo) refuses a push below TZS 1,000. Sending one anyway
costs a provider attempt, shows the merchant a failed payment and leaves
the customer with a prompt that dies — for a request that was never going
to work. The point of these tests is not only that the amount is
rejected, but that it is rejected *early*: no collection row, no
transaction, no checkout order, no Selcom call.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.payment_minimums import (
    AmountBelowOperatorMinimumError,
    assert_amount_allowed,
    detect_network,
    minimum_for,
    normalize_network,
)
from app.main import app
from app.schemas.enums import DestinationCode
from tests.factories import (
    TEST_JWT_SECRET,
    create_merchant,
    make_api_key,
)

client = TestClient(app)

TIGO_PHONE = "0713000000"
VODACOM_PHONE = "0754000000"


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "0")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- which network a number belongs to --------------------------------------


@pytest.mark.parametrize(
    ("phone", "expected"),
    [
        ("0651111111", DestinationCode.MIXXBYYAS),
        ("0671111111", DestinationCode.MIXXBYYAS),
        ("0711111111", DestinationCode.MIXXBYYAS),
        # 077 was Zantel, merged into Tigo and now sold as Mixx by Yas.
        ("0771111111", DestinationCode.MIXXBYYAS),
        ("0741111111", DestinationCode.MPESA),
        ("0751111111", DestinationCode.MPESA),
        ("0761111111", DestinationCode.MPESA),
        ("0681111111", DestinationCode.AIRTELMONEY),
        ("0691111111", DestinationCode.AIRTELMONEY),
        ("0781111111", DestinationCode.AIRTELMONEY),
        ("0611111111", DestinationCode.HALOPESA),
        ("0621111111", DestinationCode.HALOPESA),
        ("0731111111", DestinationCode.TTCLPESA),
    ],
)
def test_the_network_is_read_from_the_prefix(phone, expected):
    assert detect_network(phone) == expected


@pytest.mark.parametrize("shape", ["0713000000", "255713000000", "+255713000000", "713000000"])
def test_the_network_is_found_whatever_shape_the_number_arrives_in(shape):
    """A customer types their number however they like; the rule cannot
    depend on which."""
    assert detect_network(shape) == DestinationCode.MIXXBYYAS


@pytest.mark.parametrize("bad", [None, "", "not-a-phone", "12345", "255999999999"])
def test_an_unusable_number_falls_back_rather_than_blocking(bad):
    """An unknown prefix must not invent a 1,000 floor. Phone validity is
    the phone validator's job; this one defaults to the baseline."""
    assert detect_network(bad) is None
    assert minimum_for(detect_network(bad)) == Decimal(100)


@pytest.mark.parametrize(
    "alias", ["TIGO", "Tigo Pesa", "TIGO_PESA", "MIX", "MIXX", "YAS", "Mixx by Yas", "MIX_BY_YAS", "MIXXBYYAS"]
)
def test_every_spelling_of_tigo_resolves_to_one_network(alias):
    """A partner's billing system will send whichever name it has. All of
    them must mean the same floor."""
    assert normalize_network(alias) == DestinationCode.MIXXBYYAS


# --- the rule itself --------------------------------------------------------


def test_tigo_below_one_thousand_is_rejected():
    with pytest.raises(AmountBelowOperatorMinimumError) as exc:
        assert_amount_allowed(Decimal(500), customer_phone=TIGO_PHONE)
    assert exc.value.code == "AMOUNT_BELOW_OPERATOR_MINIMUM"
    assert "Tigo / Mixx by Yas is TZS 1,000" in exc.value.message


def test_tigo_at_exactly_one_thousand_is_allowed():
    """The boundary, explicitly: 1,000 is the minimum, not the threshold
    you must exceed."""
    assert_amount_allowed(Decimal(1000), customer_phone=TIGO_PHONE)


def test_another_network_at_one_hundred_is_allowed():
    assert_amount_allowed(Decimal(100), customer_phone=VODACOM_PHONE)


def test_another_network_below_one_hundred_is_rejected():
    with pytest.raises(AmountBelowOperatorMinimumError) as exc:
        assert_amount_allowed(Decimal(99), customer_phone=VODACOM_PHONE)
    assert exc.value.message == "Minimum payment amount is TZS 100."


def test_five_hundred_is_fine_on_a_network_that_accepts_it():
    """The rule is per-network, not a blanket raise. An amount refused on
    Tigo must still work on Vodacom."""
    assert_amount_allowed(Decimal(500), customer_phone=VODACOM_PHONE)


def test_an_explicit_network_beats_the_prefix():
    """A stated network is a stronger signal than a lookup — e.g. a
    partner that knows its subscriber is on Tigo."""
    with pytest.raises(AmountBelowOperatorMinimumError):
        assert_amount_allowed(Decimal(500), customer_phone=VODACOM_PHONE, network="TIGO")


def test_with_no_phone_and_no_network_only_the_baseline_applies():
    """A QR scan or hosted checkout page: the customer picks their network
    at the moment of paying, so a Tigo floor must not be imposed on a
    payment that may well be made by M-Pesa."""
    assert_amount_allowed(Decimal(500))
    with pytest.raises(AmountBelowOperatorMinimumError):
        assert_amount_allowed(Decimal(99))


# --- nothing is started for an amount that cannot succeed -------------------


class _FakeSelcomCheckoutClient:
    """Stands in for the real Selcom Checkout client. Every method raises:
    these tests are about requests that must never reach it, and the two
    that legitimately do are asserted on the collection row instead."""

    def __init__(self, *, credentials=None):
        pass

    async def create_order_minimal(self, **kwargs):
        from app.services.selcom_checkout.parsing import (
            parse_create_order_minimal_response,
        )

        return parse_create_order_minimal_response(
            {
                "resultcode": "000",
                "result": "SUCCESS",
                "message": "Order created",
                "data": [{"order_id": "ORD-TEST-1", "payment_token": "tok", "payment_gateway_url": "https://x"}],
            }
        )

    async def process_wallet_payment(self, **kwargs):
        from app.services.selcom_checkout.parsing import parse_wallet_payment_response

        return parse_wallet_payment_response(
            {"resultcode": "111", "result": "PENDING", "message": "Request accepted", "reference": "REF-1"}
        )


def _patch_checkout_client(monkeypatch):
    import app.services.checkout_orders as checkout_orders_module
    import app.services.wallet_push as wallet_push_module

    fake = _FakeSelcomCheckoutClient()
    monkeypatch.setattr(checkout_orders_module, "SelcomCheckoutHTTPClient", lambda **kw: fake)
    monkeypatch.setattr(wallet_push_module, "SelcomCheckoutHTTPClient", lambda **kw: fake)


def _merchant_with_key(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    raw_key, _ = make_api_key(fake_client, merchant_id)
    return merchant_id, raw_key


def _wallet_push(raw_key: str, merchant_id: uuid.UUID, amount: str, phone: str):
    return client.post(
        "/v1/collections/wallet-push",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": amount,
            "phone": phone,
            "currency": "TZS",
        },
    )


def test_the_api_returns_a_clean_400_with_the_structured_code(fake_client):
    merchant_id, raw_key = _merchant_with_key(fake_client)

    response = _wallet_push(raw_key, merchant_id, "500.00", TIGO_PHONE)

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "AMOUNT_BELOW_OPERATOR_MINIMUM"
    assert body["error"]["message"] == (
        "Minimum amount for Tigo / Mixx by Yas is TZS 1,000. "
        "Please enter TZS 1,000 or more, or use another mobile money network."
    )


def test_the_api_error_leaks_nothing_about_the_provider(fake_client):
    """The merchant's own customer may see this text. It must name no
    provider, no internal path, and no stack."""
    merchant_id, raw_key = _merchant_with_key(fake_client)
    body = _wallet_push(raw_key, merchant_id, "500.00", TIGO_PHONE).text.lower()

    for leak in ("selcom", "traceback", "app/services", "app.services", "exception", "order_id"):
        assert leak not in body, f"{leak!r} leaked to the caller"


def test_selcom_is_never_called_for_an_amount_below_the_minimum(fake_client, monkeypatch):
    """The reason this check lives where it does. If it ran any later, a
    doomed request would still cost a real provider attempt."""
    from app.services import checkout_orders

    async def _explode(*_args, **_kwargs):
        raise AssertionError("Selcom must not be reached for a below-minimum amount")

    monkeypatch.setattr(checkout_orders, "create_checkout_order_minimal", _explode)

    merchant_id, raw_key = _merchant_with_key(fake_client)
    assert _wallet_push(raw_key, merchant_id, "500.00", TIGO_PHONE).status_code == 400


def test_nothing_at_all_is_created_for_a_rejected_amount(fake_client):
    """No collection, no transaction, no checkout order — so there is
    nothing to mark failed afterwards and nothing for a merchant to see
    in their ledger."""
    merchant_id, raw_key = _merchant_with_key(fake_client)

    assert _wallet_push(raw_key, merchant_id, "500.00", TIGO_PHONE).status_code == 400

    for table in ("collections", "transactions", "checkout_orders"):
        rows = [
            r
            for r in fake_client.table(table)._table.rows
            if r.get("merchant_id") == str(merchant_id)
        ]
        assert rows == [], f"{table} should be untouched, found {len(rows)}"


def test_a_tigo_payment_of_exactly_one_thousand_goes_through(fake_client, monkeypatch):
    _patch_checkout_client(monkeypatch)
    merchant_id, raw_key = _merchant_with_key(fake_client)

    response = _wallet_push(raw_key, merchant_id, "1000.00", TIGO_PHONE)

    assert response.status_code == 202, response.text
    collections = fake_client.table("collections")._table.rows
    assert len(collections) == 1
    assert collections[0]["status"] in ("processing", "failed")


def test_another_network_at_one_hundred_goes_through(fake_client, monkeypatch):
    _patch_checkout_client(monkeypatch)
    merchant_id, raw_key = _merchant_with_key(fake_client)

    response = _wallet_push(raw_key, merchant_id, "100.00", VODACOM_PHONE)

    assert response.status_code == 202, response.text
    assert len(fake_client.table("collections")._table.rows) == 1


def test_another_network_below_one_hundred_is_refused_by_the_api(fake_client):
    merchant_id, raw_key = _merchant_with_key(fake_client)

    response = _wallet_push(raw_key, merchant_id, "99.00", VODACOM_PHONE)

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "AMOUNT_BELOW_OPERATOR_MINIMUM"
    assert response.json()["error"]["message"] == "Minimum payment amount is TZS 100."


# --- every failed collection must say why, in a code a partner can read ---


def test_a_failed_push_records_a_machine_readable_reason(fake_client, monkeypatch):
    """A third of real production failures arrived with
    failure_reason_code null — the one field the public API tells a
    partner to switch on — because the Selcom Checkout push paths wrote
    only free text. Some wrote the provider's own message, which is
    exactly what app/services/failure_reasons.py exists to keep out of
    merchant-facing columns.
    """
    import app.services.wallet_push as wallet_push
    from app.services.failure_reasons import all_reason_codes

    class _RejectingClient:
        def __init__(self, **_kwargs):
            pass

        async def create_order_minimal(self, **kwargs):
            from app.services.selcom_checkout.parsing import parse_create_order_minimal_response

            return parse_create_order_minimal_response(
                {"resultcode": "038", "result": "FAIL", "message": "SELCOM SAYS: vendor not permitted", "data": []}
            )

    monkeypatch.setattr(wallet_push, "SelcomCheckoutHTTPClient", _RejectingClient)
    import app.services.checkout_orders as checkout_orders

    monkeypatch.setattr(checkout_orders, "SelcomCheckoutHTTPClient", _RejectingClient)

    merchant_id, raw_key = _merchant_with_key(fake_client)
    response = _wallet_push(raw_key, merchant_id, "5000.00", VODACOM_PHONE)
    assert response.status_code == 202, response.text

    collection = fake_client.table("collections")._table.rows[0]
    assert collection["status"] == "failed"

    code = collection.get("failure_reason_code")
    assert code is not None, "a failed collection with no reason code is what this fixes"
    assert code in all_reason_codes(), f"{code!r} is outside the published vocabulary"

    # And the merchant-facing text is ours, not Selcom's.
    for field in ("failure_reason", "failure_reason_message"):
        assert "SELCOM SAYS" not in (collection.get(field) or ""), f"provider text leaked via {field}"
