"""Fraud/risk monitoring: rule triggers, alert visibility (merchant-own vs.
cross-tenant vs. admin-all), and the withdrawal-restriction gate. Rules are
only active when seeded via tests.factories.seed_fraud_rules — an empty
fraud_rules table (the default in every other test file) makes
evaluate_collection() a no-op, confirmed by the full suite passing unchanged
after these hooks were added.
"""

import uuid

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.fraud_monitoring_service import evaluate_collection
from app.services.selcom.client import get_selcom_client
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    create_transaction,
    make_merchant_member,
    seed_fraud_rules,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fake_resend(monkeypatch):
    """Withdrawal requests now send an OTP email before creating anything,
    and that send raises if it fails — so it has to be stubbed here."""
    monkeypatch.setattr(resend.Emails, "send", lambda params: {"id": "resend-test-message-id"})


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "0")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    get_settings.cache_clear()
    get_selcom_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_selcom_client.cache_clear()


def _merchant_and_admin(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    return merchant_id, user_id


def _push_collection(merchant_id: uuid.UUID, user_id: uuid.UUID, *, phone: str, amount: str, merchant_reference: str | None = None):
    body = {"merchant_id": str(merchant_id), "amount": amount, "customer_phone": phone}
    if merchant_reference:
        body["merchant_reference"] = merchant_reference
    return client.post(
        "/v1/collections/stk-push",
        headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
        json=body,
    )


# --- SAME_PHONE_SAME_AMOUNT_SECONDS -----------------------------------------


def test_same_phone_same_amount_within_seconds_creates_fraud_alert(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    seed_fraud_rules(fake_client, "SAME_PHONE_SAME_AMOUNT_SECONDS")

    first = _push_collection(merchant_id, user_id, phone="+255700000001", amount="5000.00")
    assert first.status_code == 202, first.text

    second = _push_collection(merchant_id, user_id, phone="+255700000001", amount="5000.00")
    assert second.status_code == 202, second.text

    alerts = fake_client.table("fraud_alerts")._table.rows
    matching = [a for a in alerts if a["rule_code"] == "SAME_PHONE_SAME_AMOUNT_SECONDS" and a["merchant_id"] == str(merchant_id)]
    assert len(matching) == 1
    assert matching[0]["status"] == "OPEN"
    assert matching[0]["customer_phone"] == "255700000001"  # normalized, no leading +


def test_different_amounts_do_not_trigger_same_phone_same_amount(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    seed_fraud_rules(fake_client, "SAME_PHONE_SAME_AMOUNT_SECONDS")

    _push_collection(merchant_id, user_id, phone="+255700000002", amount="1000.00")
    _push_collection(merchant_id, user_id, phone="+255700000002", amount="2000.00")

    alerts = fake_client.table("fraud_alerts")._table.rows
    assert not [a for a in alerts if a["rule_code"] == "SAME_PHONE_SAME_AMOUNT_SECONDS"]


# --- DUPLICATE_REFERENCE ----------------------------------------------------


def test_duplicate_merchant_reference_creates_fraud_alert(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    seed_fraud_rules(fake_client, "DUPLICATE_REFERENCE")

    first = _push_collection(merchant_id, user_id, phone="+255700000003", amount="1000.00", merchant_reference="ORDER-1")
    assert first.status_code == 202, first.text
    second = _push_collection(merchant_id, user_id, phone="+255700000004", amount="9000.00", merchant_reference="ORDER-1")
    assert second.status_code == 202, second.text

    alerts = fake_client.table("fraud_alerts")._table.rows
    matching = [a for a in alerts if a["rule_code"] == "DUPLICATE_REFERENCE"]
    assert len(matching) == 1


# --- HIGH_VALUE_TRANSACTION --------------------------------------------------


def test_high_value_transaction_creates_fraud_alert(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    seed_fraud_rules(fake_client, "HIGH_VALUE_TRANSACTION", config_overrides={"HIGH_VALUE_TRANSACTION": {"threshold_amount": 10000}})

    response = _push_collection(merchant_id, user_id, phone="+255700000005", amount="15000.00")
    assert response.status_code == 202, response.text

    alerts = fake_client.table("fraud_alerts")._table.rows
    matching = [a for a in alerts if a["rule_code"] == "HIGH_VALUE_TRANSACTION"]
    assert len(matching) == 1
    assert matching[0]["risk_level"] == "MEDIUM"


# --- PAYMENT_AFTER_LINK_EXPIRY (service-level: doesn't depend on real-time timing) ---


def test_payment_after_link_expiry_creates_fraud_alert(fake_client):
    merchant_id, _user_id = _merchant_and_admin(fake_client)
    seed_fraud_rules(fake_client, "PAYMENT_AFTER_LINK_EXPIRY")

    link = fake_client.seed(
        "payment_links",
        {
            "merchant_id": str(merchant_id),
            "amount": "5000.00",
            "currency": "TZS",
            "allowed_payment_methods": ["STK_PUSH"],
            "status": "ACTIVE",
            "public_slug": "test-slug",
            "expires_at": "2026-01-01T00:00:00+00:00",
        },
    )
    txn = create_transaction(fake_client, merchant_id)
    collection = fake_client.seed(
        "collections",
        {
            "merchant_id": str(merchant_id),
            "payment_link_id": link["id"],
            "method": "STK_PUSH",
            "amount": "5000.00",
            "currency": "TZS",
            "customer_phone": "+255700000006",
            "status": "successful",
            "completed_at": "2026-01-02T00:00:00+00:00",
        },
    )

    alerts = evaluate_collection(fake_client, collection=collection, transaction=txn, event="resolved")

    assert len(alerts) == 1
    assert alerts[0]["rule_code"] == "PAYMENT_AFTER_LINK_EXPIRY"


# --- Visibility --------------------------------------------------------------


def test_merchant_can_see_own_risk_alerts(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    fake_client.seed(
        "fraud_alerts",
        {
            "merchant_id": str(merchant_id),
            "rule_code": "HIGH_VALUE_TRANSACTION",
            "risk_level": "MEDIUM",
            "reason": "Transaction requires review.",
            "status": "OPEN",
            "metadata": {},
        },
    )

    response = client.get("/v1/merchant/risk-alerts", headers=auth_headers(user_id))
    assert response.status_code == 200
    assert len(response.json()["data"]) == 1


def test_merchant_cannot_see_another_merchants_risk_alerts(fake_client):
    other_merchant_id, _ = _merchant_and_admin(fake_client)
    fake_client.seed(
        "fraud_alerts",
        {
            "merchant_id": str(other_merchant_id),
            "rule_code": "HIGH_VALUE_TRANSACTION",
            "risk_level": "MEDIUM",
            "reason": "Transaction requires review.",
            "status": "OPEN",
            "metadata": {},
        },
    )
    _my_merchant_id, my_user_id = _merchant_and_admin(fake_client)

    response = client.get("/v1/merchant/risk-alerts", headers=auth_headers(my_user_id))
    assert response.status_code == 200
    assert response.json()["data"] == []


def test_admin_can_see_all_risk_alerts(fake_client):
    from tests.factories import make_super_admin

    merchant_a, _ = _merchant_and_admin(fake_client)
    merchant_b, _ = _merchant_and_admin(fake_client)
    for merchant_id in (merchant_a, merchant_b):
        fake_client.seed(
            "fraud_alerts",
            {
                "merchant_id": str(merchant_id),
                "rule_code": "HIGH_VALUE_TRANSACTION",
                "risk_level": "MEDIUM",
                "reason": "Transaction requires review.",
                "status": "OPEN",
                "metadata": {},
            },
        )
    admin_user_id = uuid.uuid4()
    make_super_admin(fake_client, admin_user_id)

    response = client.get("/v1/admin/risk-alerts", headers=auth_headers(admin_user_id))
    assert response.status_code == 200
    assert len(response.json()["data"]) == 2


# --- Withdrawal restriction --------------------------------------------------


def test_withdrawal_restricted_while_high_risk_alert_open(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    fake_client.seed(
        "fraud_alerts",
        {
            "merchant_id": str(merchant_id),
            "rule_code": "HIGH_VALUE_TRANSACTION",
            "risk_level": "HIGH",
            "reason": "Transaction requires review.",
            "status": "OPEN",
            "metadata": {},
        },
    )

    response = client.post(
        "/v1/merchant/withdrawals",
        headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "method": "SELCOM_PESA",
            "amount": "1000.00",
            "destination_phone": "+255700000000",
            "destination_code": "SELCOM",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "withdrawal_restricted"


def test_withdrawal_allowed_when_only_low_risk_alerts_open(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    fake_client.seed(
        "fraud_alerts",
        {
            "merchant_id": str(merchant_id),
            "rule_code": "SAME_PHONE_TOO_MANY_ATTEMPTS",
            "risk_level": "MEDIUM",
            "reason": "Transaction requires review.",
            "status": "OPEN",
            "metadata": {},
        },
    )
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Merchant Wallet (test)",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": "TZS",
            "balance": "100000",
        },
    )

    response = client.post(
        "/v1/merchant/withdrawals",
        headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "method": "SELCOM_PESA",
            "amount": "1000.00",
            "destination_phone": "+255700000000",
            "destination_code": "SELCOM",
        },
    )

    # A MEDIUM alert must not block the request. With OTP in front of every
    # withdrawal, "not blocked" means a challenge was issued — the
    # disbursement itself is created only after the code verifies.
    assert response.status_code == 202, response.text
    assert response.json()["data"]["otp_required"] is True
