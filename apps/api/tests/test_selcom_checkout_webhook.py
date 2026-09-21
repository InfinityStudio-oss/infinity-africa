"""POST /v1/webhooks/selcom/checkout — Selcom Checkout's inbound webhook.

Fails closed, always: an unsigned/invalid/expired delivery is rejected
(401) before touching anything — no collection status change, no wallet
credit, no exception for "we're not sure the scheme is right." Confirmed
against 5 independent real deliveries on 2026-08-27 that Selcom's real
traffic carries no signature at all, which means every real production
delivery is (and is meant to be) rejected — see
docs/selcom-checkout-collections.md. Real crediting instead comes from
app/services/checkout_reconciliation.py::reconcile_pending_checkout_collections
(a scheduled, webhook-independent sweep — see tests/test_checkout_reconciliation.py)
and the manual Refresh Status endpoints.

Even a delivery that DOES pass signature verification (these tests build
real, correctly-signed ones with the exact signer.py functions, to prove
the sign/verify round-trip works) still never credits from its own
claimed fields directly — it only ever credits from a live, authenticated
Selcom order-status lookup this endpoint triggers, cross-checked against
the collection's own expected amount.
"""

import asyncio
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.selcom_checkout.signer import build_timestamp, sign_request
from app.services.wallet_push import execute_wallet_push_for_payment_link
from tests.factories import TEST_JWT_SECRET, create_merchant, make_merchant_member

client = TestClient(app)

_API_SECRET = "test-webhook-secret"
_TEST_BYPASS_SECRET = "local-dev-only-bypass-secret"

CREATE_ORDER_SUCCESS_RESPONSE = {
    "reference": "S20690427372",
    "resultcode": "000",
    "result": "SUCCESS",
    "message": "Payment notification logged",
    "data": [{"payment_token": "TOKEN", "payment_gateway_url": "aHR0cHM6Ly9leGFtcGxlLmNvbS9wYXk=", "qr": "QR"}],
}

WALLET_PAYMENT_PENDING_RESPONSE = {
    "reference": "0289999288",
    "resultcode": "111",
    "result": "PENDING",
    "message": "Request in progress.",
    "data": [],
}


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("SELCOM_CHECKOUT_BASE_URL", "https://checkout.example.selcommobile.com")
    monkeypatch.setenv("SELCOM_CHECKOUT_API_KEY", "test-key")
    monkeypatch.setenv("SELCOM_CHECKOUT_API_SECRET", _API_SECRET)
    monkeypatch.setenv("SELCOM_CHECKOUT_VENDOR", "VENDORTEST")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakeSelcomCheckoutClient:
    async def create_order_minimal(self, **kwargs):
        from app.services.selcom_checkout.parsing import (
            parse_create_order_minimal_response,
        )

        return parse_create_order_minimal_response(CREATE_ORDER_SUCCESS_RESPONSE)

    async def process_wallet_payment(self, **kwargs):
        from app.services.selcom_checkout.parsing import parse_wallet_payment_response

        return parse_wallet_payment_response(WALLET_PAYMENT_PENDING_RESPONSE)


def _seed_pending_collection(fake_client, monkeypatch) -> dict:
    import app.services.checkout_orders as checkout_orders_module
    import app.services.wallet_push as wallet_push_module

    fake = _FakeSelcomCheckoutClient()
    monkeypatch.setattr(checkout_orders_module, "SelcomCheckoutHTTPClient", lambda **kwargs: fake)
    monkeypatch.setattr(wallet_push_module, "SelcomCheckoutHTTPClient", lambda **kwargs: fake)

    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Merchant Wallet (test)",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": "TZS",
            "balance": "0",
        },
    )
    payment_link = fake_client.seed(
        "payment_links",
        {
            "merchant_id": str(merchant_id),
            "amount": "1000.00",
            "currency": "TZS",
            "status": "ACTIVE",
            "allowed_payment_methods": ["STK_PUSH"],
            "public_slug": "test-slug-" + uuid.uuid4().hex[:8],
        },
    )
    collection = asyncio.run(
        execute_wallet_push_for_payment_link(fake_client, payment_link=payment_link, buyer_phone="255747730270")
    )
    assert collection["status"] == "processing"
    return collection


def _webhook_body(collection: dict, *, payment_status: str, result: str = "SUCCESS", resultcode: str = "000") -> dict:
    return {
        "transid": collection["provider_transid"],
        "order_id": "irrelevant-not-matched-by-order-id-in-these-tests",
        "reference": "S20690471578",
        "result": result,
        "resultcode": resultcode,
        "payment_status": payment_status,
        "channel": "TIGOPESA",
        "amount": "1000.00",
        "phone": "255747730270",
    }


def _signed_headers(body: dict, *, api_secret: str = _API_SECRET) -> dict:
    signed_field_names = ["transid", "order_id", "reference", "result", "resultcode", "payment_status"]
    fields = {name: str(body[name]) for name in signed_field_names}
    timestamp = build_timestamp()
    ts, digest, signed_fields = sign_request(fields, digest_method="HS256", api_secret=api_secret, timestamp=timestamp)
    return {
        "Timestamp": ts,
        "Digest": digest,
        "Digest-Method": "HS256",
        "Signed-Fields": signed_fields,
    }


def _stub_order_status(monkeypatch, *, payment_status: str, result: str = "SUCCESS", resultcode: str = "000", amount: str | None = "1000.00"):
    """Patches the authenticated outbound lookup — this, and never the
    webhook payload, is what actually decides whether anything credits."""
    import app.services.checkout_reconciliation as reconciliation_module

    class _FakeStatusClient:
        def __init__(self, *, credentials=None):
            pass

        async def get_order_status(self, *, order_id):
            from app.services.selcom_checkout.parsing import parse_order_status_response

            data = {"order_id": order_id, "payment_status": payment_status}
            if amount is not None:
                data["amount"] = amount
            return parse_order_status_response(
                {"reference": "S20690471578", "resultcode": resultcode, "result": result, "message": "OK", "data": [data]}
            )

    monkeypatch.setattr(reconciliation_module, "SelcomCheckoutHTTPClient", lambda **kwargs: _FakeStatusClient())


def _post_webhook(body: dict, headers: dict | None = None):
    return client.post("/v1/webhooks/selcom/checkout", json=body, headers=headers or {})


# --- fails closed, always --------------------------------------------------------------


def test_unsigned_webhook_is_rejected(fake_client, monkeypatch):
    collection = _seed_pending_collection(fake_client, monkeypatch)
    body = _webhook_body(collection, payment_status="COMPLETED")

    response = _post_webhook(body)  # no signature headers at all

    assert response.status_code == 401
    balance = fake_client.table("ledger_accounts")._table.rows[0]["balance"]
    assert Decimal(str(balance)) == Decimal(0)
    assert fake_client.table("collections")._table.rows[0]["status"] == "processing"


def test_invalid_signature_is_rejected(fake_client, monkeypatch):
    collection = _seed_pending_collection(fake_client, monkeypatch)
    body = _webhook_body(collection, payment_status="COMPLETED")
    headers = _signed_headers(body, api_secret="wrong-secret")

    response = _post_webhook(body, headers)

    assert response.status_code == 401
    balance = fake_client.table("ledger_accounts")._table.rows[0]["balance"]
    assert Decimal(str(balance)) == Decimal(0)


def test_tampered_body_after_signing_is_rejected(fake_client, monkeypatch):
    collection = _seed_pending_collection(fake_client, monkeypatch)
    body = _webhook_body(collection, payment_status="COMPLETED")
    headers = _signed_headers(body)
    body["resultcode"] = "651"  # tampered after signing — digest no longer matches

    response = _post_webhook(body, headers)

    assert response.status_code == 401


def test_rejected_delivery_is_audited_without_secrets(fake_client, monkeypatch):
    collection = _seed_pending_collection(fake_client, monkeypatch)
    body = _webhook_body(collection, payment_status="COMPLETED")

    _post_webhook(body)

    logs = fake_client.table("audit_logs")._table.rows
    rejected = [log for log in logs if log["action"] == "webhook.selcom_checkout_rejected"]
    assert len(rejected) == 1
    assert "wrong-secret" not in str(rejected[0])
    assert _API_SECRET not in str(rejected[0])


# --- valid signature is accepted, but still only credits from a live lookup ------------


def test_valid_signature_credits_when_the_live_lookup_agrees(fake_client, monkeypatch):
    collection = _seed_pending_collection(fake_client, monkeypatch)
    _stub_order_status(monkeypatch, payment_status="COMPLETED")
    body = _webhook_body(collection, payment_status="COMPLETED")
    headers = _signed_headers(body)

    response = _post_webhook(body, headers)

    assert response.status_code == 200, response.text
    balance = fake_client.table("ledger_accounts")._table.rows[0]["balance"]
    assert Decimal(str(balance)) == Decimal("985.00")
    assert fake_client.table("payment_links")._table.rows[0]["status"] == "PAID"


def test_signed_delivery_claiming_success_is_ignored_if_the_live_lookup_disagrees(fake_client, monkeypatch):
    """Even a validly-signed delivery's own claimed result/resultcode/
    payment_status never directly credits anything — only the live,
    authenticated lookup's answer does."""
    collection = _seed_pending_collection(fake_client, monkeypatch)
    _stub_order_status(monkeypatch, payment_status="PENDING", result="PENDING", resultcode="111")
    body = _webhook_body(collection, payment_status="COMPLETED", result="SUCCESS", resultcode="000")
    headers = _signed_headers(body)

    response = _post_webhook(body, headers)

    assert response.status_code == 200, response.text
    balance = fake_client.table("ledger_accounts")._table.rows[0]["balance"]
    assert Decimal(str(balance)) == Decimal(0)
    assert fake_client.table("collections")._table.rows[0]["status"] == "processing"


def test_duplicate_webhook_does_not_double_credit(fake_client, monkeypatch):
    collection = _seed_pending_collection(fake_client, monkeypatch)
    _stub_order_status(monkeypatch, payment_status="COMPLETED")
    body = _webhook_body(collection, payment_status="COMPLETED")
    headers = _signed_headers(body)

    first = _post_webhook(body, headers)
    second = _post_webhook(body, headers)  # identical delivery, e.g. Selcom's own retry

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["status"] == "duplicate"
    balance = fake_client.table("ledger_accounts")._table.rows[0]["balance"]
    assert Decimal(str(balance)) == Decimal("985.00")


def test_accepted_delivery_is_audited(fake_client, monkeypatch):
    collection = _seed_pending_collection(fake_client, monkeypatch)
    _stub_order_status(monkeypatch, payment_status="COMPLETED")
    body = _webhook_body(collection, payment_status="COMPLETED")
    headers = _signed_headers(body)

    _post_webhook(body, headers)

    logs = fake_client.table("audit_logs")._table.rows
    accepted = [log for log in logs if log["action"] == "webhook.selcom_checkout_accepted"]
    assert len(accepted) == 1


# --- amount cross-check -----------------------------------------------------------------


def test_wrong_amount_from_the_live_lookup_is_rejected(fake_client, monkeypatch):
    collection = _seed_pending_collection(fake_client, monkeypatch)
    _stub_order_status(monkeypatch, payment_status="COMPLETED", amount="1.00")  # collection expects 1000.00
    body = _webhook_body(collection, payment_status="COMPLETED")
    headers = _signed_headers(body)

    response = _post_webhook(body, headers)

    assert response.status_code == 200, response.text
    balance = fake_client.table("ledger_accounts")._table.rows[0]["balance"]
    assert Decimal(str(balance)) == Decimal(0)
    assert fake_client.table("collections")._table.rows[0]["status"] == "processing"


# --- live lookup result decides everything, once past signature ------------------------


@pytest.mark.parametrize("payment_status", ["PENDING", "INPROGRESS"])
def test_still_pending_lookup_result_does_not_credit(fake_client, monkeypatch, payment_status):
    collection = _seed_pending_collection(fake_client, monkeypatch)
    _stub_order_status(monkeypatch, payment_status=payment_status, result="PENDING", resultcode="111")
    body = _webhook_body(collection, payment_status=payment_status, result="PENDING", resultcode="111")
    headers = _signed_headers(body)

    response = _post_webhook(body, headers)

    assert response.status_code == 200, response.text
    balance = fake_client.table("ledger_accounts")._table.rows[0]["balance"]
    assert Decimal(str(balance)) == Decimal(0)
    assert fake_client.table("collections")._table.rows[0]["status"] == "processing"


@pytest.mark.parametrize("payment_status", ["CANCELLED", "USERCANCELLED", "REJECTED"])
def test_terminal_failed_lookup_result_does_not_credit(fake_client, monkeypatch, payment_status):
    collection = _seed_pending_collection(fake_client, monkeypatch)
    _stub_order_status(monkeypatch, payment_status=payment_status, result="FAIL", resultcode="651")
    body = _webhook_body(collection, payment_status=payment_status, result="FAIL", resultcode="651")
    headers = _signed_headers(body)

    response = _post_webhook(body, headers)

    assert response.status_code == 200, response.text
    balance = fake_client.table("ledger_accounts")._table.rows[0]["balance"]
    assert Decimal(str(balance)) == Decimal(0)
    assert fake_client.table("collections")._table.rows[0]["status"] == "failed"


# --- unmatched delivery ----------------------------------------------------------------


def test_unmatched_transid_returns_404(fake_client, monkeypatch):
    _seed_pending_collection(fake_client, monkeypatch)  # exists, but body below references a different transid
    body = {
        "transid": "TXN-DOES-NOT-EXIST",
        "order_id": "ORD-DOES-NOT-EXIST",
        "reference": "REF-1",
        "result": "SUCCESS",
        "resultcode": "000",
        "payment_status": "COMPLETED",
    }
    headers = _signed_headers(body)

    response = _post_webhook(body, headers)

    assert response.status_code == 404


# --- dev/test-only unsigned bypass -------------------------------------------------------


def test_mock_unsigned_webhook_works_in_development_with_test_secret(fake_client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SELCOM_CHECKOUT_WEBHOOK_TEST_SECRET", _TEST_BYPASS_SECRET)
    get_settings.cache_clear()
    collection = _seed_pending_collection(fake_client, monkeypatch)
    _stub_order_status(monkeypatch, payment_status="COMPLETED")
    body = _webhook_body(collection, payment_status="COMPLETED")

    response = _post_webhook(body, headers={"X-Internal-Test-Secret": _TEST_BYPASS_SECRET})

    assert response.status_code == 200, response.text
    balance = fake_client.table("ledger_accounts")._table.rows[0]["balance"]
    assert Decimal(str(balance)) == Decimal("985.00")


def test_mock_unsigned_webhook_rejected_with_wrong_test_secret(fake_client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SELCOM_CHECKOUT_WEBHOOK_TEST_SECRET", _TEST_BYPASS_SECRET)
    get_settings.cache_clear()
    collection = _seed_pending_collection(fake_client, monkeypatch)
    body = _webhook_body(collection, payment_status="COMPLETED")

    response = _post_webhook(body, headers={"X-Internal-Test-Secret": "not-the-right-secret"})

    assert response.status_code == 401


def test_production_cannot_enable_unsigned_webhook_even_with_the_test_secret_set(fake_client, monkeypatch):
    """The core safety property: setting SELCOM_CHECKOUT_WEBHOOK_TEST_SECRET
    alone is never enough — environment must also be exactly
    "development", which a real deployed environment never is."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SELCOM_CHECKOUT_WEBHOOK_TEST_SECRET", _TEST_BYPASS_SECRET)
    monkeypatch.setenv("CORS_ORIGINS", '["https://infinitypay.me"]')
    get_settings.cache_clear()
    collection = _seed_pending_collection(fake_client, monkeypatch)
    body = _webhook_body(collection, payment_status="COMPLETED")

    response = _post_webhook(body, headers={"X-Internal-Test-Secret": _TEST_BYPASS_SECRET})

    assert response.status_code == 401
    balance = fake_client.table("ledger_accounts")._table.rows[0]["balance"]
    assert Decimal(str(balance)) == Decimal(0)


def test_no_bypass_at_all_when_test_secret_is_blank_even_in_development(fake_client, monkeypatch):
    """The default — SELCOM_CHECKOUT_WEBHOOK_TEST_SECRET unset — must
    never silently accept anything, even in development."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("SELCOM_CHECKOUT_WEBHOOK_TEST_SECRET", raising=False)
    get_settings.cache_clear()
    collection = _seed_pending_collection(fake_client, monkeypatch)
    body = _webhook_body(collection, payment_status="COMPLETED")

    response = _post_webhook(body, headers={"X-Internal-Test-Secret": ""})

    assert response.status_code == 401
