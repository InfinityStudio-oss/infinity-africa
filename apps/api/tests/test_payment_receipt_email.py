"""Payment receipt email — app/services/collections.py::_apply_collection_success
sends one via app/services/email.py::send_payment_receipt_email once a
collection is genuinely settled. Never sent for a collection that's still
pending/failed/reversed, and a send failure must never fail the payment
itself.
"""

import uuid

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.selcom.client import get_selcom_client
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "0")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    get_settings.cache_clear()
    get_selcom_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_selcom_client.cache_clear()


class _FakeResend:
    def __init__(self):
        self.calls: list[dict] = []
        self.should_fail = False

    def send(self, params: dict) -> dict:
        self.calls.append(params)
        if self.should_fail:
            raise Exception("Resend rejected the request")  # noqa: TRY002
        return {"id": "resend-test-message-id"}


@pytest.fixture(autouse=True)
def fake_resend(monkeypatch):
    fake = _FakeResend()
    monkeypatch.setattr(resend.Emails, "send", fake.send)
    return fake


def _create_link(merchant_id: uuid.UUID, user_id: uuid.UUID, **overrides) -> dict:
    body = {"merchant_id": str(merchant_id), "amount": "1000.00", "currency": "TZS", **overrides}
    response = client.post(
        "/v1/payment-links",
        headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _collect(slug: str, **body) -> dict:
    response = client.post(
        f"/public/payment-links/{slug}/collect",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"method": "STK_PUSH", "customer_phone": "+255700000000", **body},
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]


def test_receipt_email_sent_after_a_successful_payment(fake_client, fake_resend):
    merchant = create_merchant(fake_client, business_name="Masanja Traders", merchant_code="27048391")
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    link = _create_link(merchant_id, admin_id, customer_email="jane@example.com")

    _collect(link["public_slug"])

    assert len(fake_resend.calls) == 1
    assert fake_resend.calls[0]["to"] == ["jane@example.com"]
    assert fake_resend.calls[0]["subject"] == "Your payment receipt from InfinityPay"
    html = fake_resend.calls[0]["html"]
    assert "Masanja Traders" in html
    assert "27048391" in html
    assert "Successful" in html


def test_receipt_email_includes_a_working_receipt_link(fake_client, fake_resend):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    link = _create_link(merchant_id, admin_id, customer_email="jane@example.com")

    _collect(link["public_slug"])

    html = fake_resend.calls[0]["html"]
    assert f"/pay/{link['public_slug']}/receipt/" in html


def test_no_receipt_email_when_customer_email_is_missing(fake_client, fake_resend):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    link = _create_link(merchant_id, admin_id)  # no customer_email

    _collect(link["public_slug"])

    assert len(fake_resend.calls) == 0


def test_no_receipt_email_for_a_failed_collection(fake_client, fake_resend, monkeypatch):
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "1")
    get_settings.cache_clear()
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    link = _create_link(merchant_id, admin_id, customer_email="jane@example.com")

    response = client.post(
        f"/public/payment-links/{link['public_slug']}/collect",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"method": "STK_PUSH", "customer_phone": "+255700000000"},
    )
    assert response.json()["data"]["status"] == "failed"

    assert len(fake_resend.calls) == 0


def test_payment_completes_even_when_receipt_email_delivery_fails(fake_client, fake_resend):
    """The core business requirement: a broken email provider must never
    take down the actual payment flow."""
    fake_resend.should_fail = True
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    link = _create_link(merchant_id, admin_id, customer_email="jane@example.com")

    result = _collect(link["public_slug"])

    assert result["status"] == "successful"
    deliveries = fake_client.table("email_deliveries")._table.rows
    assert any(d["email_type"] == "payment_receipt" and d["status"] == "failed" for d in deliveries)


def test_receipt_email_delivery_is_logged(fake_client, fake_resend):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    link = _create_link(merchant_id, admin_id, customer_email="jane@example.com")

    _collect(link["public_slug"])

    deliveries = fake_client.table("email_deliveries")._table.rows
    receipt_deliveries = [d for d in deliveries if d["email_type"] == "payment_receipt"]
    assert len(receipt_deliveries) == 1
    assert receipt_deliveries[0]["status"] == "sent"
    assert receipt_deliveries[0]["recipient_email"] == "jane@example.com"


def test_receipt_email_sent_for_a_request_collection_with_email_in_metadata(fake_client, fake_resend):
    """A "Request Collection" push (or a direct API collection) has no
    payment_links/invoices row to read customer_email from — the caller
    supplies it straight on the push request instead, and
    create_processing_collection stores it in collection.metadata since
    collections has no dedicated column for it. _apply_collection_success
    must still find it there and send the receipt."""
    from app.services.collections import _apply_collection_success

    merchant = create_merchant(fake_client, business_name="Masanja Traders", merchant_code="27048391")
    merchant_id = uuid.UUID(merchant["id"])
    collection = {
        "id": str(uuid.uuid4()),
        "merchant_id": str(merchant_id),
        "amount": "1000.00",
        "currency": "TZS",
        "method": "STK_PUSH",
        "payment_link_id": None,
        "invoice_id": None,
        "metadata": {"customer_email": "jane@example.com"},
    }

    _apply_collection_success(fake_client, collection, {"id": "txn-1", "gross_amount": "1000.00"})

    assert len(fake_resend.calls) == 1
    assert fake_resend.calls[0]["to"] == ["jane@example.com"]


def test_receipt_email_uses_info_as_the_help_contact(fake_client, fake_resend):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    link = _create_link(merchant_id, admin_id, customer_email="jane@example.com")

    _collect(link["public_slug"])

    html = fake_resend.calls[0]["html"]
    assert "info@infinityafrica.net" in html
    assert "support@infinityafrica.net" not in html
