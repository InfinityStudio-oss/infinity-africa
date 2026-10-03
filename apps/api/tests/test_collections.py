"""Collection initiation endpoints (/v1/collections/{method}): auth,
validation, idempotency, PROCESSING status, Dynamic QR payload/expiry, and
payment_link_id cross-validation — end to end against the in-memory
FakeSupabaseClient (see tests/fakes.py).
"""

import json
import uuid
from decimal import Decimal

import pytest
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
    get_settings.cache_clear()
    get_selcom_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_selcom_client.cache_clear()


def _post_selcom_webhook(
    *, event_type: str, provider_reference: str, failure_reason: str | None = None
):
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


def _merchant_and_admin(fake_client, **merchant_overrides):
    merchant = create_merchant(fake_client, **merchant_overrides)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    return merchant_id, admin_id


def _create_payment_link(merchant_id: uuid.UUID, admin_id: uuid.UUID, **overrides) -> dict:
    body = {"merchant_id": str(merchant_id), "amount": "1000.00", "currency": "TZS", **overrides}
    response = client.post(
        "/v1/payment-links",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


# --- auth --------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["ussd-push", "stk-push", "selcom-pesa-push", "dynamic-qr"]
)
def test_initiate_without_auth_is_401(fake_client, path):
    merchant = create_merchant(fake_client)

    response = client.post(
        f"/v1/collections/{path}",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": merchant["id"], "amount": "1000.00", "customer_phone": "+255700000000"},
    )

    assert response.status_code == 401


def test_developer_role_cannot_initiate_collection(fake_client):
    """DEVELOPER is scoped to api_keys only — not general merchant data."""
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    dev_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, dev_id, "DEVELOPER")

    response = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(dev_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"},
    )

    assert response.status_code == 403


def test_api_key_can_initiate_collection(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    raw_key, _ = make_api_key(fake_client, merchant_id)

    response = client.post(
        "/v1/collections/stk-push",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"},
    )

    assert response.status_code == 202, response.text


def test_api_key_can_authenticate_via_authorization_bearer_header(fake_client):
    """Docs show `Authorization: Bearer <INFINITY_API_KEY>` — an API key
    (distinguished from a JWT by its inf_ prefix) must work there too, not
    only via X-API-Key."""
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    raw_key, _ = make_api_key(fake_client, merchant_id)

    response = client.post(
        "/v1/collections/stk-push",
        headers={"Authorization": f"Bearer {raw_key}", "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"},
    )

    assert response.status_code == 202, response.text


def test_api_key_missing_scope_is_rejected(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    raw_key, _ = make_api_key(fake_client, merchant_id, scopes=["invoices:read"])

    response = client.post(
        "/v1/collections/stk-push",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"},
    )

    assert response.status_code == 403
    assert "collections:write" in response.json()["error"]["message"]


def test_revoked_api_key_cannot_initiate_collection(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    raw_key, row = make_api_key(fake_client, merchant_id)
    row["status"] = "revoked"

    response = client.post(
        "/v1/collections/stk-push",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"},
    )

    assert response.status_code == 401


def test_api_key_use_updates_last_used_at(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    raw_key, row = make_api_key(fake_client, merchant_id)
    assert row.get("last_used_at") is None

    response = client.post(
        "/v1/collections/stk-push",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"},
    )

    assert response.status_code == 202, response.text
    refreshed = next(r for r in fake_client.table("api_keys")._table.rows if r["id"] == row["id"])
    assert refreshed["last_used_at"] is not None


def test_api_key_for_different_merchant_is_rejected(fake_client):
    merchant_a = create_merchant(fake_client, contact_email="a@example.com")
    merchant_b = create_merchant(fake_client, contact_email="b@example.com")
    raw_key, _ = make_api_key(fake_client, uuid.UUID(merchant_a["id"]))

    response = client.post(
        "/v1/collections/stk-push",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": merchant_b["id"], "amount": "1000.00", "customer_phone": "+255700000000"},
    )

    assert response.status_code == 403


# --- validation ----------------------------------------------------------------


def test_amount_must_be_positive(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)

    response = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "0", "customer_phone": "+255700000000"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_push_methods_require_phone_number(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)

    response = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00"},
    )

    assert response.status_code == 422


def test_push_methods_reject_invalid_phone_format(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)

    response = client.post(
        "/v1/collections/ussd-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "not-a-phone"},
    )

    assert response.status_code == 422


def test_dynamic_qr_does_not_require_phone_number(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)

    response = client.post(
        "/v1/collections/dynamic-qr",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00"},
    )

    assert response.status_code == 202, response.text


def test_merchant_reference_too_long_is_rejected(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)

    response = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "1000.00",
            "customer_phone": "+255700000000",
            "merchant_reference": "x" * 101,
        },
    )

    assert response.status_code == 422


def test_idempotency_key_is_required(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)

    response = client.post(
        "/v1/collections/stk-push",
        headers=auth_headers(admin_id),
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- payment_link_id cross-validation -------------------------------------


def test_payment_link_id_from_another_merchant_is_rejected(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    other_merchant_id, other_admin_id = _merchant_and_admin(fake_client, contact_email="other@example.com")
    other_link = _create_payment_link(other_merchant_id, other_admin_id)

    response = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "1000.00",
            "customer_phone": "+255700000000",
            "payment_link_id": other_link["id"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_payment_link_id_not_active_is_rejected(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    link = _create_payment_link(merchant_id, admin_id)
    client.patch(f"/v1/payment-links/{link['id']}/cancel", headers=auth_headers(admin_id))

    response = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "1000.00",
            "customer_phone": "+255700000000",
            "payment_link_id": link["id"],
        },
    )

    assert response.status_code == 409


def test_payment_link_id_disallowed_method_is_rejected(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    link = _create_payment_link(merchant_id, admin_id, allowed_payment_methods=["DYNAMIC_QR"])

    response = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "1000.00",
            "customer_phone": "+255700000000",
            "payment_link_id": link["id"],
        },
    )

    assert response.status_code == 422


def test_payment_link_id_valid_is_accepted(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    link = _create_payment_link(merchant_id, admin_id, allowed_payment_methods=["STK_PUSH"])

    response = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "1000.00",
            "customer_phone": "+255700000000",
            "payment_link_id": link["id"],
        },
    )

    assert response.status_code == 202, response.text
    assert response.json()["data"]["payment_link_id"] == link["id"]


# --- success: creates collection + transaction, both PROCESSING ------------


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("ussd-push", "USSD_PUSH"),
        ("stk-push", "STK_PUSH"),
        ("selcom-pesa-push", "SELCOM_PESA_PUSH"),
    ],
)
def test_push_collection_sets_processing_and_creates_transaction(fake_client, path, method):
    merchant_id, admin_id = _merchant_and_admin(fake_client)

    response = client.post(
        f"/v1/collections/{path}",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "1000.00",
            "customer_phone": "+255700000000",
            "merchant_reference": "order-42",
        },
    )

    assert response.status_code == 202, response.text
    data = response.json()["data"]
    assert data["status"] == "processing"
    assert data["method"] == method
    assert data["merchant_reference"] == "order-42"
    assert data["provider_reference"].startswith("MOCK-SELCOM-")

    transactions = fake_client.table("transactions")._table.rows
    assert len(transactions) == 1
    txn = transactions[0]
    assert txn["status"] == "processing"
    assert txn["collection_id"] == data["id"]
    assert txn["provider_reference"] == data["provider_reference"]
    assert Decimal(txn["net_amount"]) + Decimal(txn["fee_amount"]) == Decimal(txn["gross_amount"])

    # No ledger entries yet — nothing is confirmed while still processing.
    assert fake_client.table("ledger_entries")._table.rows == []


def test_dynamic_qr_returns_qr_payload_and_expiry(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)

    response = client.post(
        "/v1/collections/dynamic-qr",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "2500.00"},
    )

    assert response.status_code == 202, response.text
    data = response.json()["data"]
    assert data["status"] == "processing"
    assert data["method"] == "DYNAMIC_QR"
    assert data["qr_payload"]
    assert "2500" in data["qr_payload"]
    assert data["qr_expires_at"]

    transactions = fake_client.table("transactions")._table.rows
    assert len(transactions) == 1
    assert transactions[0]["status"] == "processing"


# --- idempotency -----------------------------------------------------------


def test_initiate_is_idempotent_on_retry(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    headers = {**auth_headers(admin_id), "Idempotency-Key": "retry-key"}
    body = {"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"}

    first = client.post("/v1/collections/stk-push", headers=headers, json=body)
    second = client.post("/v1/collections/stk-push", headers=headers, json=body)

    assert first.status_code == second.status_code == 202
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert len(fake_client.table("collections")._table.rows) == 1
    assert len(fake_client.table("transactions")._table.rows) == 1


# --- resolution via the provider callback -----------------------------------


def test_resolve_via_callback_marks_successful_and_posts_ledger(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client, webhook_url="https://merchant.example.com/hooks")

    initiate = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"},
    ).json()["data"]
    assert initiate["status"] == "processing"

    callback = _post_selcom_webhook(
        event_type="collection.success", provider_reference=initiate["provider_reference"]
    )
    assert callback.status_code == 200
    assert callback.json()["data"]["resolved"] == "collection"

    collection_row = next(
        r for r in fake_client.table("collections")._table.rows if r["id"] == initiate["id"]
    )
    assert collection_row["status"] == "successful"

    transaction = next(
        t for t in fake_client.table("transactions")._table.rows if t["collection_id"] == initiate["id"]
    )
    assert transaction["status"] == "successful"

    entries = [
        e for e in fake_client.table("ledger_entries")._table.rows if e["transaction_id"] == transaction["id"]
    ]
    debits = sum(Decimal(e["amount"]) for e in entries if e["direction"] == "debit")
    credits = sum(Decimal(e["amount"]) for e in entries if e["direction"] == "credit")
    assert debits == credits > 0

    events = fake_client.table("webhook_events")._table.rows
    assert any(e["event_name"] == "collection.success" for e in events)

    # Regression: resolve_collection() — the single chokepoint every
    # crediting path (webhook, manual refresh, scheduled reconciliation)
    # funnels through — never wrote an audit_logs row until the MVP-
    # readiness audit-log sweep found the gap.
    audit_events = [a for a in fake_client.table("audit_logs")._table.rows if a["action"] == "collection.credited"]
    assert len(audit_events) == 1
    assert audit_events[0]["actor_type"] == "system"
    assert audit_events[0]["merchant_id"] == str(merchant_id)


def test_a_broken_analytics_client_still_credits_the_wallet(fake_client, monkeypatch):
    """The reason product analytics is safe to put on this path at all.

    resolve_collection() reports a `collection_resolved` event. If PostHog
    being down could propagate out of that call, an analytics outage would
    become a payment outage -- the collection would not credit, and the
    merchant would be told their customer's money had not arrived. So:
    break the analytics client outright and assert the money still moves.

    Verified to fail if the swallow in analytics.track() is removed, so
    this is testing something real rather than passing vacuously.
    """
    from app.core import analytics

    class ExplodingClient:
        def capture(self, **_kwargs):
            raise RuntimeError("posthog is down")

    monkeypatch.setattr(analytics, "_client", ExplodingClient())

    merchant_id, admin_id = _merchant_and_admin(fake_client)
    initiate = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"},
    ).json()["data"]

    callback = _post_selcom_webhook(
        event_type="collection.success", provider_reference=initiate["provider_reference"]
    )
    assert callback.status_code == 200

    collection_row = next(
        r for r in fake_client.table("collections")._table.rows if r["id"] == initiate["id"]
    )
    assert collection_row["status"] == "successful"

    transaction = next(
        t for t in fake_client.table("transactions")._table.rows if t["collection_id"] == initiate["id"]
    )
    entries = [
        e for e in fake_client.table("ledger_entries")._table.rows if e["transaction_id"] == transaction["id"]
    ]
    debits = sum(Decimal(e["amount"]) for e in entries if e["direction"] == "debit")
    credits = sum(Decimal(e["amount"]) for e in entries if e["direction"] == "credit")
    assert debits == credits > 0


def test_resolve_via_callback_marks_failed_without_ledger_entries(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client, webhook_url="https://merchant.example.com/hooks")

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
    assert callback.status_code == 200

    collection_row = next(
        r for r in fake_client.table("collections")._table.rows if r["id"] == initiate["id"]
    )
    assert collection_row["status"] == "failed"

    transaction = next(
        t for t in fake_client.table("transactions")._table.rows if t["collection_id"] == initiate["id"]
    )
    assert transaction["status"] == "failed"

    assert fake_client.table("ledger_entries")._table.rows == []

    events = fake_client.table("webhook_events")._table.rows
    assert any(e["event_name"] == "collection.failed" for e in events)

    audit_events = [a for a in fake_client.table("audit_logs")._table.rows if a["action"] == "collection.failed"]
    assert len(audit_events) == 1
    assert audit_events[0]["actor_type"] == "system"
    assert audit_events[0]["merchant_id"] == str(merchant_id)


def test_resolve_collection_leaves_a_processing_result_unchanged(fake_client):
    """Regression test: resolve_collection() used to treat any non-
    "successful" provider status as failed, including a legitimate
    "processing" result (e.g. a real push the customer hasn't approved
    yet). It must now leave the collection/transaction PROCESSING and do
    nothing else — no ledger entries, no webhook event — until a later
    check_collection_status call or the /v1/webhooks/selcom callback
    actually resolves it."""
    from app.services.collections import resolve_collection
    from app.services.selcom.schemas import CollectionResult

    merchant_id, admin_id = _merchant_and_admin(fake_client)

    initiate = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"},
    ).json()["data"]

    result = CollectionResult(
        provider="selcom", provider_reference=initiate["provider_reference"], status="processing"
    )
    resolved = resolve_collection(fake_client, collection_id=uuid.UUID(initiate["id"]), result=result)

    assert resolved["status"] == "processing"

    transaction = next(
        t for t in fake_client.table("transactions")._table.rows if t["collection_id"] == initiate["id"]
    )
    assert transaction["status"] == "processing"
    assert fake_client.table("ledger_entries")._table.rows == []
    assert fake_client.table("webhook_events")._table.rows == []


def test_resolving_a_collection_linked_to_a_payment_link_marks_it_paid(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client, webhook_url="https://merchant.example.com/hooks")
    link = _create_payment_link(merchant_id, admin_id, allowed_payment_methods=["STK_PUSH"])

    initiate = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "1000.00",
            "customer_phone": "+255700000000",
            "payment_link_id": link["id"],
        },
    ).json()["data"]

    _post_selcom_webhook(event_type="collection.success", provider_reference=initiate["provider_reference"])

    link_row = next(r for r in fake_client.table("payment_links")._table.rows if r["id"] == link["id"])
    assert link_row["status"] == "PAID"


# --- read-back (merchant-scoped, unaffected by the flat initiation routes) -


def test_list_and_get_initiated_collection(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)

    created = client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(merchant_id), "amount": "1000.00", "customer_phone": "+255700000000"},
    ).json()["data"]

    list_response = client.get(f"/v1/merchants/{merchant_id}/collections", headers=auth_headers(admin_id))
    assert list_response.status_code == 200
    assert list_response.json()["meta"]["total"] == 1

    get_response = client.get(
        f"/v1/merchants/{merchant_id}/collections/{created['id']}", headers=auth_headers(admin_id)
    )
    assert get_response.status_code == 200
    assert get_response.json()["data"]["id"] == created["id"]
