"""A merchant whose onboarding a Super Admin hasn't approved yet
(merchants.status != 'active') cannot move money — start a collection,
issue a payment link or an invoice. Withdrawals have their own gate,
covered in tests/test_disbursements.py.

See app/services/merchant_gate.py.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.selcom.client import get_selcom_client
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    create_pricing_rule,
    make_merchant_member,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "0")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    get_settings.cache_clear()
    get_selcom_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_selcom_client.cache_clear()


def _pending_merchant(fake_client):
    merchant = create_merchant(fake_client, status="pending", kyc_status="unverified")
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    create_pricing_rule(fake_client, merchant_id=merchant_id)
    return merchant_id, user_id


def _approved_merchant(fake_client):
    merchant = create_merchant(fake_client)  # factory default: active / verified
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    create_pricing_rule(fake_client, merchant_id=merchant_id)
    return merchant_id, user_id


def _idem() -> str:
    return uuid.uuid4().hex


# --- pending merchant is blocked -------------------------------------------


def test_pending_merchant_cannot_create_payment_link(fake_client):
    _merchant_id, user_id = _pending_merchant(fake_client)
    response = client.post(
        "/v1/merchant/payment-links",
        headers={**auth_headers(user_id), "Idempotency-Key": _idem()},
        json={"amount": "1000", "currency": "TZS"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "merchant_not_approved"
    assert fake_client.table("payment_links")._table.rows == []


def test_pending_merchant_cannot_create_invoice(fake_client):
    _merchant_id, user_id = _pending_merchant(fake_client)
    response = client.post(
        "/v1/merchant/invoices",
        headers=auth_headers(user_id),
        json={
            "customer_name": "Asha",
            "customer_email": "asha@example.com",
            "due_date": "2026-12-01",
            "items": [{"description": "Consulting", "quantity": "1", "unit_price": "5000"}],
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "merchant_not_approved"
    assert fake_client.table("invoices")._table.rows == []


def test_pending_merchant_cannot_initiate_a_collection(fake_client):
    _merchant_id, user_id = _pending_merchant(fake_client)
    response = client.post(
        "/v1/merchant/collections/stk-push",
        headers={**auth_headers(user_id), "Idempotency-Key": _idem()},
        json={"amount": "1000.00", "customer_phone": "+255700000000"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "merchant_not_approved"
    assert fake_client.table("collections")._table.rows == []


def test_pending_merchant_cannot_create_an_api_key(fake_client, monkeypatch):
    monkeypatch.setenv("ENABLE_MERCHANT_API_KEYS", "true")
    get_settings.cache_clear()
    _merchant_id, user_id = _pending_merchant(fake_client)
    response = client.post(
        "/v1/merchant/api-keys",
        headers=auth_headers(user_id),
        json={"name": "test key", "environment": "sandbox"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "merchant_not_approved"
    assert fake_client.table("api_keys")._table.rows == []


def test_pending_merchant_cannot_activate_pay_by_link(fake_client):
    _merchant_id, user_id = _pending_merchant(fake_client)
    response = client.post(
        "/v1/merchant/pay-by-link",
        headers=auth_headers(user_id),
        json={"display_name": "My Shop"},
    )
    assert response.status_code == 409  # ensure_merchant_accepts_payments -> ConflictError
    assert fake_client.table("merchant_pay_links")._table.rows == []


# --- approved merchant is unaffected -------------------------------------


def test_approved_merchant_can_still_create_payment_link(fake_client):
    merchant_id, user_id = _approved_merchant(fake_client)
    response = client.post(
        "/v1/merchant/payment-links",
        headers={**auth_headers(user_id), "Idempotency-Key": _idem()},
        json={"amount": "1000", "currency": "TZS"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["merchant_id"] == str(merchant_id)


def test_approved_merchant_can_still_initiate_a_collection(fake_client):
    _merchant_id, user_id = _approved_merchant(fake_client)
    response = client.post(
        "/v1/merchant/collections/stk-push",
        headers={**auth_headers(user_id), "Idempotency-Key": _idem()},
        json={"amount": "1000.00", "customer_phone": "+255700000000"},
    )
    assert response.status_code == 202, response.text


# --- suspended merchant is blocked ----------------------------------------
#
# Approval and suspension both land on merchants.status, so the gate reads
# the same for a business that was never approved and one whose approval a
# Super Admin revoked. These tests exist because that equivalence is the
# whole safety argument and nothing was pinning it: every test above used a
# 'pending' merchant, so a regression that only let suspended merchants
# through would have gone unnoticed.
#
# Since 2026-10-11 the refusal happens earlier - get_own_merchant rejects a
# suspended business for the whole /v1/merchant/* surface - so these assert
# 403 without insisting on the merchant_not_approved code, which belongs to
# the later, per-endpoint gate. What matters is the door being shut.


def _suspended_merchant(fake_client):
    """A business that *was* trading and has been shut off: active-era
    kyc_status, suspended status. Not the same shape as a pending merchant,
    and the difference is what used to slip through."""
    merchant = create_merchant(fake_client, status="suspended", kyc_status="verified")
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    create_pricing_rule(fake_client, merchant_id=merchant_id)
    return merchant_id, user_id


def test_suspended_merchant_cannot_create_payment_link(fake_client):
    _merchant_id, user_id = _suspended_merchant(fake_client)
    response = client.post(
        "/v1/merchant/payment-links",
        headers={**auth_headers(user_id), "Idempotency-Key": _idem()},
        json={"amount": "1000", "currency": "TZS"},
    )
    assert response.status_code == 403, response.text
    assert fake_client.table("payment_links")._table.rows == []


def test_suspended_merchant_cannot_create_invoice(fake_client):
    _merchant_id, user_id = _suspended_merchant(fake_client)
    response = client.post(
        "/v1/merchant/invoices",
        headers=auth_headers(user_id),
        json={
            "customer_name": "Asha",
            "customer_email": "asha@example.com",
            "due_date": "2026-12-01",
            "items": [{"description": "Consulting", "quantity": "1", "unit_price": "5000"}],
        },
    )
    assert response.status_code == 403, response.text
    assert fake_client.table("invoices")._table.rows == []


def test_suspended_merchant_cannot_initiate_a_collection(fake_client):
    _merchant_id, user_id = _suspended_merchant(fake_client)
    response = client.post(
        "/v1/merchant/collections/stk-push",
        headers={**auth_headers(user_id), "Idempotency-Key": _idem()},
        json={"amount": "1000.00", "customer_phone": "+255700000000"},
    )
    assert response.status_code == 403, response.text
    assert fake_client.table("collections")._table.rows == []


def test_suspended_merchant_cannot_create_an_api_key(fake_client, monkeypatch):
    monkeypatch.setenv("ENABLE_MERCHANT_API_KEYS", "true")
    get_settings.cache_clear()
    _merchant_id, user_id = _suspended_merchant(fake_client)
    response = client.post(
        "/v1/merchant/api-keys",
        headers=auth_headers(user_id),
        json={"name": "test key", "environment": "sandbox"},
    )
    assert response.status_code == 403, response.text
    assert fake_client.table("api_keys")._table.rows == []


def test_suspended_merchant_cannot_request_a_withdrawal(fake_client):
    """Money *out* was never covered by this file - withdrawals have their
    own gate (_check_merchant_is_verified, WithdrawalRestrictedError). It
    belongs here anyway: suspension has to close every door in one list,
    and a reader checking that list should not have to know which endpoint
    is guarded by which mechanism."""
    _merchant_id, user_id = _suspended_merchant(fake_client)
    response = client.post(
        "/v1/merchant/withdrawals",
        headers={**auth_headers(user_id), "Idempotency-Key": _idem()},
        json={
            "method": "SELCOM_PESA",
            "amount": "1000.00",
            "destination_phone": "+255700000000",
            "destination_code": "SELCOM",
        },
    )
    assert response.status_code == 403, response.text
    assert fake_client.table("withdrawals")._table.rows == []


def test_a_closed_merchant_is_blocked_the_same_way(fake_client):
    """'closed' is not a softer 'suspended'. One representative path is
    enough - the gate reads merchants.status once, for all of them."""
    merchant = create_merchant(fake_client, status="closed", kyc_status="verified")
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    create_pricing_rule(fake_client, merchant_id=merchant_id)

    response = client.post(
        "/v1/merchant/payment-links",
        headers={**auth_headers(user_id), "Idempotency-Key": _idem()},
        json={"amount": "1000", "currency": "TZS"},
    )
    assert response.status_code == 403, response.text
