"""Withdrawal-triggered emails — app/services/disbursements.py calling
app/services/email.py::send_withdrawal_request_notification_email (to the
CEO, right after a withdrawal request is saved) and
send_withdrawal_success_email (to the merchant, only once a withdrawal
genuinely reaches SUCCESS). Same FakeSupabaseClient pattern as
tests/test_admin_withdrawals.py, plus the fake_resend fixture from
tests/test_payment_receipt_email.py.
"""

import uuid

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.selcom_business.client import get_selcom_business_client
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("SELCOM_BUSINESS_MODE", "mock")
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "0")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("CEO_EMAIL", "ceo@infinitypay.me")
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()


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


def _fund_wallet(fake_client, merchant_id: uuid.UUID, amount: str, currency: str = "TZS") -> None:
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Merchant Wallet (test)",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": currency,
            "balance": amount,
        },
    )


def _request_withdrawal(merchant_id: uuid.UUID, admin_id: uuid.UUID, amount: str, **overrides) -> dict:
    body = {
        "merchant_id": str(merchant_id),
        "amount": amount,
        "destination_name": "Jane Doe",
        "destination_identifier": "+255700000000",
        "destination_code": "MPESA",
        **overrides,
    }
    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json=body,
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]


def _approve(withdrawal_id: str, super_admin_id: uuid.UUID):
    return client.post(f"/v1/admin/withdrawals/{withdrawal_id}/approve", headers=auth_headers(super_admin_id))


def _reject(withdrawal_id: str, super_admin_id: uuid.UUID, reason: str = "Suspicious destination account"):
    return client.post(
        f"/v1/admin/withdrawals/{withdrawal_id}/reject",
        headers=auth_headers(super_admin_id),
        json={"rejection_reason": reason},
    )


# --- Withdrawal request notification (to CEO) -----------------------------------


def test_ceo_email_sent_when_merchant_requests_withdrawal(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Masanja Traders")
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    _request_withdrawal(merchant_id, admin_id, "50000.00")

    assert len(fake_resend.calls) == 1
    assert fake_resend.calls[0]["to"] == ["ceo@infinitypay.me"]
    assert fake_resend.calls[0]["subject"] == "New withdrawal request from Masanja Traders"
    assert "Masanja Traders" in fake_resend.calls[0]["html"]


def test_withdrawal_request_masks_the_destination_account(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    _request_withdrawal(merchant_id, admin_id, "50000.00", destination_identifier="+255712345678")

    html = fake_resend.calls[0]["html"]
    assert "+255712345678" not in html
    assert "5678" in html


def test_withdrawal_request_saved_even_when_ceo_email_fails(fake_client, fake_resend):
    fake_resend.should_fail = True
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    response_body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    assert response_body["status"] == "PENDING_ADMIN_APPROVAL"
    rows = fake_client.table("disbursements")._table.rows
    assert any(d["id"] == response_body["id"] for d in rows)


def test_withdrawal_request_email_delivery_is_logged(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    deliveries = fake_client.table("email_deliveries")._table.rows
    request_deliveries = [d for d in deliveries if d["email_type"] == "withdrawal_request_notification"]
    assert len(request_deliveries) == 1
    assert request_deliveries[0]["status"] == "sent"
    assert request_deliveries[0]["recipient_email"] == "ceo@infinitypay.me"
    assert request_deliveries[0]["related_resource_id"] == body["id"]


def test_withdrawal_request_delivery_logged_as_failed_when_email_fails(fake_client, fake_resend):
    fake_resend.should_fail = True
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    _request_withdrawal(merchant_id, admin_id, "50000.00")

    deliveries = fake_client.table("email_deliveries")._table.rows
    request_deliveries = [d for d in deliveries if d["email_type"] == "withdrawal_request_notification"]
    assert len(request_deliveries) == 1
    assert request_deliveries[0]["status"] == "failed"


# --- Withdrawal success (to merchant) --------------------------------------------


def test_merchant_email_sent_once_withdrawal_succeeds(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client, contact_email="owner@masanjatraders.co.tz")
    _fund_wallet(fake_client, merchant_id, "1000000.00")
    body = _request_withdrawal(merchant_id, admin_id, "50000.00")
    fake_resend.calls.clear()  # drop the CEO request-notification call above

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    response = _approve(body["id"], super_admin_id)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "SUCCESS"
    assert len(fake_resend.calls) == 1
    assert fake_resend.calls[0]["to"] == ["owner@masanjatraders.co.tz"]
    assert fake_resend.calls[0]["subject"] == "Your InfinityPay withdrawal is successful"


def test_no_success_email_while_still_pending_approval(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")
    _request_withdrawal(merchant_id, admin_id, "50000.00")
    fake_resend.calls.clear()

    # Still PENDING_ADMIN_APPROVAL — nothing approved it.
    assert len(fake_resend.calls) == 0


def test_no_success_email_for_a_rejected_withdrawal(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")
    body = _request_withdrawal(merchant_id, admin_id, "50000.00")
    fake_resend.calls.clear()

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    response = _reject(body["id"], super_admin_id)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "REJECTED"
    assert len(fake_resend.calls) == 0


def test_no_success_email_when_the_provider_call_fails(fake_client, fake_resend, monkeypatch):
    """A rejected/failed provider call reverses the reservation and marks
    the disbursement FAILED — never SUCCESS, so no success email either."""
    from app.services.selcom_business.client import SelcomBusinessResult
    from app.services.selcom_business.mock_client import MockSelcomBusinessClient

    async def _fail(self, *, trans_id: str, **kwargs):
        return SelcomBusinessResult(
            transaction_id=trans_id, status="failed", failure_reason="Invalid destination account"
        )

    monkeypatch.setattr(MockSelcomBusinessClient, "process_transaction", _fail)

    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")
    body = _request_withdrawal(merchant_id, admin_id, "50000.00")
    fake_resend.calls.clear()

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    response = _approve(body["id"], super_admin_id)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "FAILED"
    assert len(fake_resend.calls) == 0


def test_withdrawal_completes_even_when_success_email_delivery_fails(fake_client, fake_resend):
    """The core business requirement: a broken email provider must never
    take down an already-successful withdrawal."""
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")
    body = _request_withdrawal(merchant_id, admin_id, "50000.00")
    fake_resend.should_fail = True

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    response = _approve(body["id"], super_admin_id)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "SUCCESS"


def test_withdrawal_success_email_delivery_is_logged(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")
    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    _approve(body["id"], super_admin_id)

    deliveries = fake_client.table("email_deliveries")._table.rows
    success_deliveries = [d for d in deliveries if d["email_type"] == "withdrawal_success"]
    assert len(success_deliveries) == 1
    assert success_deliveries[0]["status"] == "sent"
    assert success_deliveries[0]["related_resource_id"] == body["id"]


def test_email_deliveries_never_store_the_rendered_email_body(fake_client, fake_resend):
    """email_deliveries stores only metadata (recipient, subject, status,
    provider message id) — never the rendered HTML, which is where the
    destination account/masked identifier actually appear."""
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")
    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    _approve(body["id"], super_admin_id)

    deliveries = fake_client.table("email_deliveries")._table.rows
    assert len(deliveries) >= 2  # request notification + success
    for row in deliveries:
        assert "html" not in row
        assert "body" not in row


# --- Super Admin: email delivery status on the withdrawals list -----------------


def test_super_admin_sees_both_email_statuses_on_the_withdrawals_list(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")
    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    _approve(body["id"], super_admin_id)

    response = client.get("/v1/admin/withdrawals", headers=auth_headers(super_admin_id))
    assert response.status_code == 200, response.text
    row = next(r for r in response.json()["data"] if r["withdrawal_id"] == body["id"])
    assert row["request_email_status"] == "sent"
    assert row["success_email_status"] == "sent"


def test_super_admin_sees_no_success_email_status_before_approval(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")
    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)

    response = client.get("/v1/admin/withdrawals", headers=auth_headers(super_admin_id))
    row = next(r for r in response.json()["data"] if r["withdrawal_id"] == body["id"])
    assert row["request_email_status"] == "sent"
    assert row["success_email_status"] is None


# --- Super Admin: current available balance on the withdrawals list -------------


def test_super_admin_sees_current_available_balance_not_a_request_time_snapshot(fake_client, fake_resend):
    """available_balance (app/services/admin_directory.py::batch_wallet_balances)
    reflects the merchant's *current* wallet balance, not whatever it was
    when the withdrawal was requested — so a reviewer sees accurate,
    up-to-date context, not stale data."""
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")
    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)

    # Balance moves after the request was submitted, before it's reviewed.
    for row in fake_client.table("ledger_accounts")._table.rows:
        if row["merchant_id"] == str(merchant_id):
            row["balance"] = "750000.00"

    response = client.get("/v1/admin/withdrawals", headers=auth_headers(super_admin_id))
    row = next(r for r in response.json()["data"] if r["withdrawal_id"] == body["id"])
    assert row["available_balance"] == "750000.00"


def test_super_admin_sees_zero_balance_for_a_merchant_with_no_wallet_account_yet(fake_client, fake_resend):
    """A brand-new merchant with no ledger_accounts row at all must show
    0, not null or an error — same "missing means zero" convention as
    get_wallet_balance's own documented behavior."""
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "50000.00")
    body = _request_withdrawal(merchant_id, admin_id, "1000.00")

    # Remove the ledger account entirely to simulate "never had one".
    fake_client.table("ledger_accounts")._table.rows.clear()

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)

    response = client.get("/v1/admin/withdrawals", headers=auth_headers(super_admin_id))
    row = next(r for r in response.json()["data"] if r["withdrawal_id"] == body["id"])
    assert row["available_balance"] == "0"
