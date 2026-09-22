"""Merchant collection notification email —
app/services/collections.py::_apply_collection_success calls
app/services/email.py::send_merchant_collection_notification_email right
after the customer's own receipt email, once a collection is genuinely
credited. Distinct from that receipt: this goes to the MERCHANT's own
configured notification email(s) (up to 2), only while
collection_notifications_enabled is true, and never for anything short of
a real "successful" collection.

_apply_collection_success is the one chokepoint every collection source in
the feature brief (Request Collection, Payment Link, Pay by Link, Invoice,
API Collection, Wallet Push, Push to Selcom Pesa, TanQR) funnels through —
see app/services/collections.py's own module docstring. Two sources get a
full HTTP-level test end to end (Request Collection via /v1/collections/
stk-push, Payment Link via the public collect endpoint); the rest are
proven directly at that shared chokepoint (same style as
test_payment_receipt_email.py's own
test_receipt_email_sent_for_a_request_collection_with_email_in_metadata),
since re-deriving each product surface's own full checkout flow here would
only re-test wiring already covered elsewhere (test_collections.py,
test_payment_links.py, test_invoices.py, test_pay_by_link.py) — see
test_pay_by_link.py's module docstring for the same reasoning applied to
Pay by Link's own test suite.
"""

import json
import uuid

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.selcom.client import get_selcom_client
from app.services.selcom.webhooks import compute_selcom_signature
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_api_key,
    make_merchant_member,
)

client = TestClient(app)

_SELCOM_WEBHOOK_SECRET = "test-selcom-webhook-secret"


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "0")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    monkeypatch.setenv("SELCOM_WEBHOOK_SECRET", _SELCOM_WEBHOOK_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    # This file's own tests rely on the customer receipt email still firing
    # right before the merchant notification (see module docstring) — the
    # 2026-09 email-volume reduction defaults SEND_CUSTOMER_RECEIPT_EMAILS
    # to false, which would otherwise silently drop that first call and
    # shift every fake_resend.calls[n] index this file asserts on.
    monkeypatch.setenv("SEND_CUSTOMER_RECEIPT_EMAILS", "true")
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


def _merchant_and_admin(fake_client, **overrides) -> tuple[uuid.UUID, uuid.UUID]:
    merchant = create_merchant(fake_client, **overrides)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    return merchant_id, admin_id


def _configure_notifications(
    admin_id: uuid.UUID, *, primary: str | None, secondary: str | None = None, enabled: bool = True
) -> None:
    response = client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(admin_id),
        json={
            "primary_notification_email": primary,
            "secondary_notification_email": secondary,
            "collection_notifications_enabled": enabled,
        },
    )
    assert response.status_code == 200, response.text


def _post_selcom_webhook(*, event_type: str, provider_reference: str, failure_reason: str | None = None):
    body = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "provider_reference": provider_reference,
        "failure_reason": failure_reason,
    }
    raw_body = json.dumps(body).encode("utf-8")
    signature = compute_selcom_signature(raw_body=raw_body, secret=_SELCOM_WEBHOOK_SECRET)
    return client.post(
        "/v1/webhooks/selcom",
        content=raw_body,
        headers={"Content-Type": "application/json", "X-Selcom-Signature": signature},
    )


def _stk_push_and_resolve(admin_id: uuid.UUID, merchant_id: uuid.UUID, *, headers: dict | None = None) -> dict:
    """Request Collection: initiate an STK push (JWT, merchant admin —
    exactly the Merchant Portal's "Request Collection" flow), then resolve
    it successful via the same provider callback path a real Selcom
    delivery uses. Returns the initiated collection body."""
    initiate = client.post(
        "/v1/collections/stk-push",
        headers={**(headers or auth_headers(admin_id)), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"},
    ).json()["data"]
    callback = _post_selcom_webhook(event_type="collection.success", provider_reference=initiate["provider_reference"])
    assert callback.status_code == 200, callback.text
    return initiate


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


# --- Request Collection (full HTTP flow) --------------------------------------


def test_notification_sent_to_primary_configured_email_for_request_collection(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Masanja Traders")
    _configure_notifications(admin_id, primary="owner@example.com")

    _stk_push_and_resolve(admin_id, merchant_id)

    notification_calls = [c for c in fake_resend.calls if c["to"] == ["owner@example.com"]]
    assert len(notification_calls) == 1
    assert notification_calls[0]["subject"].startswith("Collection payment received - ")


def test_notification_sent_to_both_primary_and_secondary(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _configure_notifications(admin_id, primary="owner@example.com", secondary="finance@example.com")

    _stk_push_and_resolve(admin_id, merchant_id)

    recipients = {c["to"][0] for c in fake_resend.calls}
    assert recipients == {"owner@example.com", "finance@example.com"}


def test_no_more_than_two_notification_emails_are_sent(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _configure_notifications(admin_id, primary="owner@example.com", secondary="finance@example.com")

    _stk_push_and_resolve(admin_id, merchant_id)

    assert len(fake_resend.calls) == 2


def test_no_notification_email_sent_when_none_configured(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    # Notification settings never touched at all — no row exists yet.

    _stk_push_and_resolve(admin_id, merchant_id)

    assert fake_resend.calls == []


def test_no_notification_email_sent_when_notifications_disabled(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _configure_notifications(admin_id, primary="owner@example.com", enabled=False)

    _stk_push_and_resolve(admin_id, merchant_id)

    assert fake_resend.calls == []


def test_no_notification_email_for_a_failed_collection(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _configure_notifications(admin_id, primary="owner@example.com")

    initiate = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"},
    ).json()["data"]
    callback = _post_selcom_webhook(
        event_type="collection.failed",
        provider_reference=initiate["provider_reference"],
        failure_reason="Customer cancelled the push",
    )
    assert callback.status_code == 200, callback.text

    assert fake_resend.calls == []


def test_delivery_log_created_per_recipient(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _configure_notifications(admin_id, primary="owner@example.com", secondary="finance@example.com")

    _stk_push_and_resolve(admin_id, merchant_id)

    deliveries = [
        d
        for d in fake_client.table("email_deliveries")._table.rows
        if d["email_type"] == "merchant_collection_notification"
    ]
    assert len(deliveries) == 2
    assert {d["recipient_email"] for d in deliveries} == {"owner@example.com", "finance@example.com"}
    assert all(d["status"] == "sent" and d["merchant_id"] == str(merchant_id) for d in deliveries)


def test_notification_email_failure_does_not_block_wallet_credit(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _configure_notifications(admin_id, primary="owner@example.com")
    fake_resend.should_fail = True

    _stk_push_and_resolve(admin_id, merchant_id)

    ledger_entries = fake_client.table("ledger_entries")._table.rows
    assert len(ledger_entries) > 0

    deliveries = [
        d
        for d in fake_client.table("email_deliveries")._table.rows
        if d["email_type"] == "merchant_collection_notification"
    ]
    assert any(d["status"] == "failed" for d in deliveries)


def test_duplicate_reconciliation_does_not_send_duplicate_notification(fake_client, fake_resend):
    """Belt-and-suspenders idempotency (feature brief Part 5): even though
    resolve_collection() itself already refuses to re-process a collection
    once its status has left 'processing' (see test_collections.py's own
    idempotent-initiate coverage), _apply_collection_success's notification
    call is independently guarded per (collection, recipient) too — see
    send_merchant_collection_notification_email's _notification_already_sent
    check. Exercised directly at that function, the same way
    test_payment_receipt_email.py drives _apply_collection_success
    directly for its own metadata-sourced-email case."""
    from app.services.collections import _apply_collection_success
    from app.services.merchant_notifications import upsert_notification_settings

    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    upsert_notification_settings(
        fake_client,
        merchant_id,
        primary_notification_email="owner@example.com",
        secondary_notification_email=None,
        collection_notifications_enabled=True,
        updated_by=None,
    )
    collection = {
        "id": str(uuid.uuid4()),
        "merchant_id": str(merchant_id),
        "amount": "1000.00",
        "currency": "TZS",
        "method": "STK_PUSH",
        "payment_link_id": None,
        "invoice_id": None,
        "metadata": {},
    }
    transaction = {"id": "txn-1", "gross_amount": "1000.00", "fee_amount": "20.00", "net_amount": "980.00"}

    _apply_collection_success(fake_client, collection, transaction)
    _apply_collection_success(fake_client, collection, transaction)  # simulated retry

    assert len(fake_resend.calls) == 1
    deliveries = [
        d
        for d in fake_client.table("email_deliveries")._table.rows
        if d["email_type"] == "merchant_collection_notification"
    ]
    assert len(deliveries) == 2
    assert sorted(d["status"] for d in deliveries) == ["sent", "skipped"]


# --- Content -------------------------------------------------------------------


def test_notification_email_includes_amounts_method_and_reference(fake_client, fake_resend):
    from app.services.collections import _apply_collection_success
    from app.services.merchant_notifications import upsert_notification_settings

    merchant = create_merchant(fake_client, business_name="Masanja Traders")
    merchant_id = uuid.UUID(merchant["id"])
    upsert_notification_settings(
        fake_client,
        merchant_id,
        primary_notification_email="owner@example.com",
        secondary_notification_email=None,
        collection_notifications_enabled=True,
        updated_by=None,
    )
    collection = {
        "id": str(uuid.uuid4()),
        "merchant_id": str(merchant_id),
        "amount": "1000.00",
        "currency": "TZS",
        "method": "STK_PUSH",
        "customer_phone": "+255700000000",
        "merchant_reference": "ORDER-42",
        "provider_reference": "SEL-REF-99",
        "payment_link_id": None,
        "invoice_id": None,
        "metadata": {"customer_name": "Grace Mwakalinga", "customer_email": "grace@example.com"},
    }
    transaction = {"id": "txn-1", "gross_amount": "1000.00", "fee_amount": "20.00", "net_amount": "980.00"}

    _apply_collection_success(fake_client, collection, transaction)

    call = next(c for c in fake_resend.calls if c["to"] == ["owner@example.com"])
    html = call["html"]
    assert "Masanja Traders" in html
    assert "TZS 1,000.00" in html  # gross
    assert "TZS 20.00" in html  # fee
    assert "TZS 980.00" in html  # net
    assert "Stk Push" in html  # method, title-cased
    assert "ORDER-42" in html
    assert "SEL-REF-99" in html
    assert "Grace Mwakalinga" in html
    assert "grace@example.com" in html
    assert "•••• 0000" in html  # masked phone — never the raw number
    assert "+255700000000" not in html
    assert "Successful" in html


def test_notification_email_uses_required_sender_and_reply_to(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _configure_notifications(admin_id, primary="owner@example.com")

    _stk_push_and_resolve(admin_id, merchant_id)

    call = next(c for c in fake_resend.calls if c["to"] == ["owner@example.com"])
    assert call["from"] == "InfinityPay <notification@infinitypay.me>"
    assert call["reply_to"] == "info@infinitypay.me"


# --- Payment Link (full HTTP flow) ----------------------------------------------


def test_notification_email_sends_for_payment_link(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _configure_notifications(admin_id, primary="owner@example.com")
    link = _create_link(merchant_id, admin_id)

    _collect(link["public_slug"])

    assert any(c["to"] == ["owner@example.com"] for c in fake_resend.calls)


# --- Invoice (full HTTP flow) ---------------------------------------------------


def test_notification_email_sends_for_invoice_collection(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _configure_notifications(admin_id, primary="owner@example.com")

    invoice_response = client.post(
        "/v1/invoices",
        headers=auth_headers(admin_id),
        json={
            "merchant_id": str(merchant_id),
            "customer_name": "Amina Hassan",
            "customer_phone": "+255700000000",
            "customer_email": "amina@example.com",
            "due_date": "2026-09-01",
            "items": [{"description": "Consulting services", "quantity": "2", "unit_price": "500.00"}],
        },
    )
    assert invoice_response.status_code == 201, invoice_response.text
    invoice = invoice_response.json()["data"]

    send_response = client.post(f"/v1/invoices/{invoice['id']}/send", headers=auth_headers(admin_id))
    assert send_response.status_code == 200, send_response.text

    link_response = client.post(f"/v1/invoices/{invoice['id']}/payment-link", headers=auth_headers(admin_id))
    assert link_response.status_code == 200, link_response.text
    link = link_response.json()["data"]

    _collect(link["public_slug"])

    assert any(c["to"] == ["owner@example.com"] for c in fake_resend.calls)


# --- Pay by Link (full HTTP flow) -----------------------------------------------


def test_notification_email_sends_for_pay_by_link(fake_client, fake_resend):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _configure_notifications(admin_id, primary="owner@example.com")

    create_response = client.post("/v1/merchant/pay-by-link", headers=auth_headers(admin_id), json={})
    assert create_response.status_code == 201, create_response.text

    checkout_response = client.post(
        "/public/pay-by-link/paul-masanja/checkout",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "first_name": "Grace",
            "last_name": "Mwakalinga",
            "email": "grace@example.com",
            "phone": "255747730270",
            "amount": "25000",
            "currency": "TZS",
            "description": "Order #42",
        },
    )
    assert checkout_response.status_code == 201, checkout_response.text
    slug = checkout_response.json()["data"]["redirect_url"].rsplit("/", 1)[-1]

    _collect(slug)

    assert any(c["to"] == ["owner@example.com"] for c in fake_resend.calls)


# --- API Collection (full HTTP flow, API-key authenticated) --------------------


def test_notification_email_sends_for_api_collection(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _configure_notifications(admin_id, primary="owner@example.com")
    raw_key, _ = make_api_key(fake_client, merchant_id)

    _stk_push_and_resolve(admin_id, merchant_id, headers={"X-API-Key": raw_key})

    assert any(c["to"] == ["owner@example.com"] for c in fake_resend.calls)


# --- Every other collection source funnels through the same chokepoint ---------


@pytest.mark.parametrize(
    "method",
    ["USSD_PUSH", "STK_PUSH", "SELCOM_PESA_PUSH", "DYNAMIC_QR", "HOSTED_CHECKOUT"],
)
def test_notification_email_sends_regardless_of_collection_method(fake_client, fake_resend, method):
    """Wallet Push, Push to Selcom Pesa, TanQR, and Invoice all ultimately
    resolve through resolve_collection()/finalize_pending_review_collection()
    calling _apply_collection_success() with a `collection` dict whose only
    difference is `method` (and, for Invoice, invoice_id/payment_link_id) —
    send_merchant_collection_notification_email itself never branches on
    method or source, so this proves the notification isn't accidentally
    scoped to one of them."""
    from app.services.collections import _apply_collection_success
    from app.services.merchant_notifications import upsert_notification_settings

    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    upsert_notification_settings(
        fake_client,
        merchant_id,
        primary_notification_email="owner@example.com",
        secondary_notification_email=None,
        collection_notifications_enabled=True,
        updated_by=None,
    )
    collection = {
        "id": str(uuid.uuid4()),
        "merchant_id": str(merchant_id),
        "amount": "1000.00",
        "currency": "TZS",
        "method": method,
        "payment_link_id": None,
        "invoice_id": None,
        "metadata": {},
    }
    transaction = {"id": "txn-1", "gross_amount": "1000.00", "fee_amount": "0", "net_amount": "1000.00"}

    _apply_collection_success(fake_client, collection, transaction)

    assert any(c["to"] == ["owner@example.com"] for c in fake_resend.calls)
