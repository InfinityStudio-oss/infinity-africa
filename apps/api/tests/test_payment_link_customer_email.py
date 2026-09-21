"""Payment link customer email — POST /v1/merchant/payment-links sends the
link automatically via app/services/email.py::send_payment_link_customer_email
when customer_email is provided. Never blocks link creation itself; the
response's customer_email_sent field is what the frontend reads to show
the right "created" message.
"""

import uuid

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
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
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://infinitypay.me")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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


def _merchant_and_admin(fake_client, **merchant_overrides):
    merchant = create_merchant(fake_client, **merchant_overrides)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    return merchant_id, admin_id


def _create_link(admin_id: uuid.UUID, **overrides) -> dict:
    body = {"amount": "25000.00", "currency": "TZS", **overrides}
    response = client.post(
        "/v1/merchant/payment-links",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_email_sent_when_customer_email_provided(fake_client, fake_resend):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Masanja Traders")

    link = _create_link(admin_id, customer_email="jane@example.com")

    assert link["customer_email_sent"] is True
    assert len(fake_resend.calls) == 1
    assert fake_resend.calls[0]["to"] == ["jane@example.com"]
    assert fake_resend.calls[0]["subject"] == "Payment request from Masanja Traders via InfinityPay"


def test_email_contains_the_real_pay_now_url(fake_client, fake_resend):
    _merchant_id, admin_id = _merchant_and_admin(fake_client)

    link = _create_link(admin_id, customer_email="jane@example.com")

    html = fake_resend.calls[0]["html"]
    assert link["public_url"] in html
    assert link["public_url"] == f"https://infinitypay.me/pay/{link['public_slug']}"
    assert "pay.infinitypay.me" not in html


def test_no_email_when_customer_email_is_missing(fake_client, fake_resend):
    _merchant_id, admin_id = _merchant_and_admin(fake_client)

    link = _create_link(admin_id)

    assert link["customer_email_sent"] is None
    assert len(fake_resend.calls) == 0


def test_link_creation_succeeds_even_without_customer_email(fake_client, fake_resend):
    _merchant_id, admin_id = _merchant_and_admin(fake_client)

    link = _create_link(admin_id)

    assert link["status"] == "ACTIVE"
    assert link["public_url"]


def test_link_creation_succeeds_even_when_email_delivery_fails(fake_client, fake_resend):
    fake_resend.should_fail = True
    _merchant_id, admin_id = _merchant_and_admin(fake_client)

    link = _create_link(admin_id, customer_email="jane@example.com")

    assert link["status"] == "ACTIVE"
    assert link["public_url"]
    assert link["customer_email_sent"] is False


def test_email_delivery_is_logged(fake_client, fake_resend):
    _merchant_id, admin_id = _merchant_and_admin(fake_client)

    link = _create_link(admin_id, customer_email="jane@example.com")

    deliveries = fake_client.table("email_deliveries")._table.rows
    link_deliveries = [d for d in deliveries if d["email_type"] == "payment_link_customer"]
    assert len(link_deliveries) == 1
    assert link_deliveries[0]["status"] == "sent"
    assert link_deliveries[0]["recipient_email"] == "jane@example.com"
    assert link_deliveries[0]["related_resource_id"] == link["id"]


def test_failed_delivery_is_logged_too(fake_client, fake_resend):
    fake_resend.should_fail = True
    _merchant_id, admin_id = _merchant_and_admin(fake_client)

    _create_link(admin_id, customer_email="jane@example.com")

    deliveries = fake_client.table("email_deliveries")._table.rows
    link_deliveries = [d for d in deliveries if d["email_type"] == "payment_link_customer"]
    assert len(link_deliveries) == 1
    assert link_deliveries[0]["status"] == "failed"


def test_no_delivery_log_when_no_customer_email(fake_client, fake_resend):
    _merchant_id, admin_id = _merchant_and_admin(fake_client)

    _create_link(admin_id)

    deliveries = fake_client.table("email_deliveries")._table.rows
    assert not [d for d in deliveries if d["email_type"] == "payment_link_customer"]
