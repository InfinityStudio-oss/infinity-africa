"""Invoices module: creation (auto invoice_number + computed totals), flat
list/get scoping, draft-only editing, send/cancel transitions, and
generating + paying a "Pay Now" payment link (which is what actually links
invoice status to payment status) — end to end against the in-memory
FakeSupabaseClient (see tests/fakes.py).
"""

import uuid
from decimal import Decimal

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
    make_api_key,
    make_merchant_member,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "0")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("INVOICE_EMAIL_FROM", "InfinityPay Invoices <invoice@infinitypay.me>")
    monkeypatch.setenv("EMAIL_FROM", "InfinityPay <notification@infinitypay.me>")
    get_settings.cache_clear()
    get_selcom_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_selcom_client.cache_clear()


class _FakeResend:
    """Stands in for resend.Emails.send — captures every call instead of
    making a real HTTP request. app/services/email.py calls
    resend.Emails.send(params) as a plain classmethod call (no
    instantiation), so patching the attribute with a bound method of this
    fake works: resend.Emails.send(params) then calls fake.send(params)."""

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
    """Autouse: every existing test that calls _send() now triggers a real
    (mocked) email send — patch it unconditionally rather than requiring
    every call site to opt in. Tests that care about the captured calls
    still request this fixture by name to get the fake instance."""
    fake = _FakeResend()
    monkeypatch.setattr(resend.Emails, "send", fake.send)
    return fake


def _merchant_and_admin(fake_client, **merchant_overrides):
    merchant = create_merchant(fake_client, **merchant_overrides)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    return merchant_id, admin_id


_DEFAULT_ITEMS = [{"description": "Consulting services", "quantity": "2", "unit_price": "500.00"}]


def _create_invoice(merchant_id: uuid.UUID, admin_id: uuid.UUID, **overrides) -> dict:
    body = {
        "merchant_id": str(merchant_id),
        "customer_name": "Amina Hassan",
        "customer_phone": "+255700000000",
        "customer_email": "amina@example.com",
        "due_date": "2026-09-01",
        "items": _DEFAULT_ITEMS,
        **overrides,
    }
    response = client.post("/v1/invoices", headers=auth_headers(admin_id), json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _row(fake_client, table: str, row_id: str) -> dict:
    return next(r for r in fake_client.table(table)._table.rows if r["id"] == row_id)


def _send(invoice_id: str, admin_id: uuid.UUID) -> dict:
    response = client.post(f"/v1/invoices/{invoice_id}/send", headers=auth_headers(admin_id))
    assert response.status_code == 200, response.text
    return response.json()["data"]


# --- creation ----------------------------------------------------------------


def test_create_invoice_generates_number_and_computes_totals(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)

    invoice = _create_invoice(
        merchant_id,
        admin_id,
        items=[
            {"description": "Design", "quantity": "1", "unit_price": "800.00"},
            {"description": "Delivery", "quantity": "1", "unit_price": "200.00"},
        ],
        tax_amount="50.00",
        discount_amount="25.00",
    )

    assert invoice["invoice_number"].startswith("INV-")
    assert invoice["status"] == "DRAFT"
    assert Decimal(invoice["subtotal"]) == Decimal("1000.00")
    assert Decimal(invoice["total_amount"]) == Decimal("1025.00")
    assert Decimal(invoice["amount_paid"]) == Decimal(0)
    assert len(invoice["items"]) == 2

    row = _row(fake_client, "invoices", invoice["id"])
    assert row["invoice_number"] == invoice["invoice_number"]


def test_create_invoice_is_rate_limited(fake_client):
    """Wiring test for app/core/rate_limit.py's invoice_create scope (added
    during the MVP-readiness rate-limiting sweep) — pre-fills the shared
    in-memory bucket directly rather than firing 30 real creates, then
    confirms one more real request is actually rejected."""
    from app.core.rate_limit import _limiter

    merchant_id, admin_id = _merchant_and_admin(fake_client)
    for _ in range(30):
        _limiter.check("invoice_create:testclient", limit=30, window_seconds=60)

    response = client.post(
        "/v1/invoices",
        headers=auth_headers(admin_id),
        json={
            "merchant_id": str(merchant_id),
            "customer_name": "Amina Hassan",
            "customer_phone": "+255700000000",
            "due_date": "2026-09-01",
            "items": _DEFAULT_ITEMS,
        },
    )
    assert response.status_code == 429


def test_create_invoice_via_api_key(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    raw_key, _ = make_api_key(fake_client, merchant_id)

    response = client.post(
        "/v1/invoices",
        headers={"X-API-Key": raw_key},
        json={
            "merchant_id": str(merchant_id),
            "due_date": "2026-09-01",
            "items": _DEFAULT_ITEMS,
        },
    )

    assert response.status_code == 201, response.text


def test_create_invoice_rejects_api_key_for_a_different_merchant(fake_client):
    merchant_id, _ = _merchant_and_admin(fake_client)
    other_merchant = create_merchant(fake_client)
    raw_key, _ = make_api_key(fake_client, uuid.UUID(other_merchant["id"]))

    response = client.post(
        "/v1/invoices",
        headers={"X-API-Key": raw_key},
        json={"merchant_id": str(merchant_id), "due_date": "2026-09-01", "items": _DEFAULT_ITEMS},
    )

    assert response.status_code == 403


def test_create_invoice_api_key_missing_scope_rejected(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    raw_key, _ = make_api_key(fake_client, merchant_id, scopes=["invoices:read"])

    response = client.post(
        "/v1/invoices",
        headers={"X-API-Key": raw_key},
        json={"merchant_id": str(merchant_id), "due_date": "2026-09-01", "items": _DEFAULT_ITEMS},
    )

    assert response.status_code == 403
    assert "invoices:write" in response.json()["error"]["message"]


def test_get_invoice_api_key_correct_scope_allowed(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    raw_key, _ = make_api_key(fake_client, merchant_id, scopes=["invoices:write", "invoices:read"])

    created = client.post(
        "/v1/invoices",
        headers={"X-API-Key": raw_key},
        json={"merchant_id": str(merchant_id), "due_date": "2026-09-01", "items": _DEFAULT_ITEMS},
    ).json()["data"]

    response = client.get(f"/v1/invoices/{created['id']}", headers={"X-API-Key": raw_key})

    assert response.status_code == 200, response.text


def test_create_invoice_rejects_negative_total(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)

    response = client.post(
        "/v1/invoices",
        headers=auth_headers(admin_id),
        json={
            "merchant_id": str(merchant_id),
            "due_date": "2026-09-01",
            "items": _DEFAULT_ITEMS,
            "discount_amount": "5000.00",
        },
    )

    assert response.status_code == 422


# --- list / get ----------------------------------------------------------------


def test_list_invoices_is_scoped_to_merchant_id_query_param(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    other_merchant_id, other_admin_id = _merchant_and_admin(fake_client)

    _create_invoice(merchant_id, admin_id)
    _create_invoice(other_merchant_id, other_admin_id)

    response = client.get(
        "/v1/invoices", headers=auth_headers(admin_id), params={"merchant_id": str(merchant_id)}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["merchant_id"] == str(merchant_id)


def test_get_invoice_not_found(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client)

    response = client.get(f"/v1/invoices/{uuid.uuid4()}", headers=auth_headers(admin_id))

    assert response.status_code == 404


def test_get_invoice_rejects_non_member(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)

    outsider_id = uuid.uuid4()
    response = client.get(f"/v1/invoices/{invoice['id']}", headers=auth_headers(outsider_id))

    assert response.status_code == 403


# --- update --------------------------------------------------------------------


def test_update_draft_invoice_recomputes_totals_on_new_items(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)

    response = client.patch(
        f"/v1/invoices/{invoice['id']}",
        headers=auth_headers(admin_id),
        json={
            "notes": "Net 30",
            "items": [{"description": "Retainer", "quantity": "1", "unit_price": "1500.00"}],
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["notes"] == "Net 30"
    assert Decimal(data["subtotal"]) == Decimal("1500.00")
    assert Decimal(data["total_amount"]) == Decimal("1500.00")
    assert len(data["items"]) == 1
    assert data["items"][0]["description"] == "Retainer"


def test_update_rejects_once_sent(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)
    _send(invoice["id"], admin_id)

    response = client.patch(
        f"/v1/invoices/{invoice['id']}", headers=auth_headers(admin_id), json={"notes": "too late"}
    )

    assert response.status_code == 422


# --- send / cancel ---------------------------------------------------------


def test_send_invoice_transitions_draft_to_sent(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)

    sent = _send(invoice["id"], admin_id)

    assert sent["status"] == "SENT"


def test_send_invoice_is_rate_limited(fake_client):
    """Wiring test for app/core/rate_limit.py's invoice_send scope (added
    during the MVP-readiness rate-limiting sweep) — pre-fills the shared
    in-memory bucket directly rather than firing 30 real sends, then
    confirms one more real request is actually rejected."""
    from app.core.rate_limit import _limiter

    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)
    for _ in range(30):
        _limiter.check("invoice_send:testclient", limit=30, window_seconds=60)

    response = client.post(f"/v1/invoices/{invoice['id']}/send", headers=auth_headers(admin_id))
    assert response.status_code == 429


def test_send_invoice_twice_rejected(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)
    _send(invoice["id"], admin_id)

    response = client.post(f"/v1/invoices/{invoice['id']}/send", headers=auth_headers(admin_id))

    assert response.status_code == 422


def test_cancel_invoice_is_idempotent(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)

    first = client.patch(f"/v1/invoices/{invoice['id']}/cancel", headers=auth_headers(admin_id))
    second = client.patch(f"/v1/invoices/{invoice['id']}/cancel", headers=auth_headers(admin_id))

    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["status"] == second.json()["data"]["status"] == "CANCELLED"


# --- send + invoice email (Resend) ------------------------------------------


def test_send_invoice_requires_customer_email(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id, customer_email=None)

    response = client.post(f"/v1/invoices/{invoice['id']}/send", headers=auth_headers(admin_id))

    assert response.status_code == 422, response.text
    assert "Customer email is required" in response.json()["error"]["message"]

    invoice_row = _row(fake_client, "invoices", invoice["id"])
    assert invoice_row["status"] == "DRAFT"


def test_send_invoice_creates_a_payment_link_and_sends_the_email(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)
    assert invoice["payment_link_id"] is None

    sent = _send(invoice["id"], admin_id)

    assert sent["status"] == "SENT"
    assert sent["sent_at"] is not None
    assert sent["payment_link_id"] is not None
    assert len(fake_resend.calls) == 1

    link_row = _row(fake_client, "payment_links", sent["payment_link_id"])
    assert link_row["merchant_id"] == str(merchant_id)


def test_send_invoice_reuses_the_existing_payment_link(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)
    _send(invoice["id"], admin_id)

    link_response = client.post(f"/v1/invoices/{invoice['id']}/payment-link", headers=auth_headers(admin_id))
    assert link_response.status_code == 200
    first_link_id = link_response.json()["data"]["id"]

    # Sending an already-SENT invoice is rejected (test_send_invoice_twice_rejected),
    # so "reuse" is exercised via the payment-link endpoint being called
    # again directly — same underlying generate_or_reuse_invoice_payment_link
    # helper the send flow itself calls.
    second_link_response = client.post(f"/v1/invoices/{invoice['id']}/payment-link", headers=auth_headers(admin_id))
    assert second_link_response.status_code == 200
    assert second_link_response.json()["data"]["id"] == first_link_id
    assert len(fake_client.table("payment_links")._table.rows) == 1


def test_invoice_email_uses_the_invoice_sender_address(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)

    _send(invoice["id"], admin_id)

    assert len(fake_resend.calls) == 1
    assert fake_resend.calls[0]["from"] == "InfinityPay Invoices <invoice@infinitypay.me>"
    assert fake_resend.calls[0]["to"] == ["amina@example.com"]
    assert fake_resend.calls[0]["subject"].startswith("Invoice from ")
    assert fake_resend.calls[0]["reply_to"] == "info@infinitypay.me"


def test_invoice_email_falls_back_to_email_from_when_invoice_email_from_is_unset(fake_client, fake_resend, monkeypatch):
    monkeypatch.setenv("INVOICE_EMAIL_FROM", "")
    monkeypatch.setenv("EMAIL_FROM", "InfinityPay <notification@infinitypay.me>")
    get_settings.cache_clear()

    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)

    _send(invoice["id"], admin_id)

    assert fake_resend.calls[0]["from"] == "InfinityPay <notification@infinitypay.me>"
    get_settings.cache_clear()


def test_invoice_email_html_includes_the_pay_now_link(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)

    sent = _send(invoice["id"], admin_id)
    link_row = _row(fake_client, "payment_links", sent["payment_link_id"])

    html = fake_resend.calls[0]["html"]
    assert link_row["public_slug"] in html
    assert "Pay Now" in html


def test_send_invoice_stays_draft_when_email_delivery_fails(fake_client, fake_resend):
    fake_resend.should_fail = True
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)

    response = client.post(f"/v1/invoices/{invoice['id']}/send", headers=auth_headers(admin_id))

    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "email_delivery_failed"

    invoice_row = _row(fake_client, "invoices", invoice["id"])
    assert invoice_row["status"] == "DRAFT"
    assert invoice_row.get("sent_at") is None


def test_send_invoice_records_an_email_delivery_log_on_success_and_failure(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)

    ok_invoice = _create_invoice(merchant_id, admin_id, customer_email="paid-on-time@example.com")
    _send(ok_invoice["id"], admin_id)

    fake_resend.should_fail = True
    failing_invoice = _create_invoice(merchant_id, admin_id, customer_email="bounces@example.com")
    client.post(f"/v1/invoices/{failing_invoice['id']}/send", headers=auth_headers(admin_id))

    deliveries = fake_client.table("email_deliveries")._table.rows
    assert len(deliveries) == 2

    ok_delivery = next(d for d in deliveries if d["recipient_email"] == "paid-on-time@example.com")
    assert ok_delivery["status"] == "sent"
    assert ok_delivery["email_type"] == "invoice_payment_request"
    assert ok_delivery["provider_message_id"]
    assert ok_delivery["related_resource_id"] == ok_invoice["id"]

    failed_delivery = next(d for d in deliveries if d["recipient_email"] == "bounces@example.com")
    assert failed_delivery["status"] == "failed"
    assert failed_delivery["error_message"]


# --- payment link generation ------------------------------------------------


def test_payment_link_requires_invoice_to_be_sent_first(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)  # still DRAFT

    response = client.post(f"/v1/invoices/{invoice['id']}/payment-link", headers=auth_headers(admin_id))

    assert response.status_code == 422


def test_generate_payment_link_for_sent_invoice(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)
    _send(invoice["id"], admin_id)

    response = client.post(f"/v1/invoices/{invoice['id']}/payment-link", headers=auth_headers(admin_id))

    assert response.status_code == 200, response.text
    link = response.json()["data"]
    assert link["status"] == "ACTIVE"
    assert Decimal(link["amount"]) == Decimal(invoice["total_amount"])
    assert link["currency"] == invoice["currency"]
    assert link["public_url"].endswith(f"/pay/{link['public_slug']}")

    invoice_row = _row(fake_client, "invoices", invoice["id"])
    assert invoice_row["payment_link_id"] == link["id"]

    # Regression: payment_links.allowed_payment_methods has its own DB
    # CHECK constraint that (deliberately) was never widened to include
    # HOSTED_CHECKOUT — see app/schemas/enums.py's
    # LEGACY_ALLOWED_PAYMENT_METHODS_DEFAULT. Building this list from the
    # full CollectionMethod enum instead of that constant 500s against a
    # real Postgres database (invisible to this fake client, which doesn't
    # enforce CHECK constraints) — assert the exact value here so a
    # regression is caught by shape, not just by a live DB crash.
    link_row = _row(fake_client, "payment_links", link["id"])
    assert link_row["allowed_payment_methods"] == ["USSD_PUSH", "STK_PUSH", "SELCOM_PESA_PUSH", "DYNAMIC_QR"]
    assert "HOSTED_CHECKOUT" not in link_row["allowed_payment_methods"]


def test_generate_payment_link_reuses_active_link(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)
    _send(invoice["id"], admin_id)

    first = client.post(f"/v1/invoices/{invoice['id']}/payment-link", headers=auth_headers(admin_id)).json()[
        "data"
    ]
    second = client.post(f"/v1/invoices/{invoice['id']}/payment-link", headers=auth_headers(admin_id)).json()[
        "data"
    ]

    assert first["id"] == second["id"]
    assert first["public_slug"] == second["public_slug"]
    assert len(fake_client.table("payment_links")._table.rows) == 1


def test_payment_link_rejected_for_cancelled_invoice(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    invoice = _create_invoice(merchant_id, admin_id)
    client.patch(f"/v1/invoices/{invoice['id']}/cancel", headers=auth_headers(admin_id))

    response = client.post(f"/v1/invoices/{invoice['id']}/payment-link", headers=auth_headers(admin_id))

    assert response.status_code == 422


# --- payment status linkage: paying the generated link marks the invoice ---


def test_paying_generated_payment_link_marks_invoice_paid(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client, webhook_url="https://merchant.example.com/hooks")
    invoice = _create_invoice(merchant_id, admin_id)
    _send(invoice["id"], admin_id)

    link = client.post(f"/v1/invoices/{invoice['id']}/payment-link", headers=auth_headers(admin_id)).json()[
        "data"
    ]

    collect = client.post(
        f"/public/payment-links/{link['public_slug']}/collect",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"method": "STK_PUSH", "customer_phone": "+255700000000"},
    )

    assert collect.status_code == 202
    assert collect.json()["data"]["status"] == "successful"

    invoice_row = _row(fake_client, "invoices", invoice["id"])
    assert invoice_row["status"] == "PAID"
    assert Decimal(invoice_row["amount_paid"]) == Decimal(invoice["total_amount"])

    link_row = _row(fake_client, "payment_links", link["id"])
    assert link_row["status"] == "PAID"

    events = fake_client.table("webhook_events")._table.rows
    assert any(e["event_name"] == "invoice.paid" for e in events)
    assert any(e["event_name"] == "payment_link.paid" for e in events)

    # Regression: collections.collections_single_source used to forbid
    # payment_link_id and invoice_id ever both being set, which is exactly
    # the shape every "pay an invoice's Pay Now link" collection legitimately
    # has (see app/services/collection_source.py::resolve_invoice_id_for_payment_link)
    # — 500ed against a real Postgres database on every single invoice
    # payment, invisible to this fake client since it doesn't enforce CHECK
    # constraints. Dropped in 20260829050000; assert the shape explicitly so
    # a regression is caught here, not just by a live-database crash.
    collection_row = next(r for r in fake_client.table("collections")._table.rows if r["payment_link_id"] == link["id"])
    assert collection_row["invoice_id"] == invoice["id"]


def test_paid_invoice_cannot_generate_a_new_payment_link(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client, webhook_url="https://merchant.example.com/hooks")
    invoice = _create_invoice(merchant_id, admin_id)
    _send(invoice["id"], admin_id)
    link = client.post(f"/v1/invoices/{invoice['id']}/payment-link", headers=auth_headers(admin_id)).json()[
        "data"
    ]
    client.post(
        f"/public/payment-links/{link['public_slug']}/collect",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"method": "STK_PUSH", "customer_phone": "+255700000000"},
    )

    response = client.post(f"/v1/invoices/{invoice['id']}/payment-link", headers=auth_headers(admin_id))

    assert response.status_code == 422


def test_paid_invoice_cannot_be_cancelled(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client, webhook_url="https://merchant.example.com/hooks")
    invoice = _create_invoice(merchant_id, admin_id)
    _send(invoice["id"], admin_id)
    link = client.post(f"/v1/invoices/{invoice['id']}/payment-link", headers=auth_headers(admin_id)).json()[
        "data"
    ]
    client.post(
        f"/public/payment-links/{link['public_slug']}/collect",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"method": "STK_PUSH", "customer_phone": "+255700000000"},
    )

    response = client.patch(f"/v1/invoices/{invoice['id']}/cancel", headers=auth_headers(admin_id))

    assert response.status_code == 409
