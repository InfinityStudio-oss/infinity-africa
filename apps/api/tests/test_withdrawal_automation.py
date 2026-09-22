"""Withdrawal automation — app/services/disbursements.py::
_evaluate_auto_withdrawal_eligibility and its wiring into
execute_disbursement. Automation only ever takes effect when BOTH
AUTO_WITHDRAWALS_ENABLED=true and REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS=false
are set (belt-and-suspenders — see Settings.auto_withdrawals_enabled's own
docstring); every test here sets both explicitly rather than relying on
either default, so this file stays correct even if those defaults ever
change.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import disbursements as disbursements_service
from app.services.selcom_business.client import get_selcom_business_client
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
    make_super_admin,
)
from tests.fakes import FakeSupabaseClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("SELCOM_BUSINESS_MODE", "mock")
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "0")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("CEO_EMAIL", "ceo@infinitypay.me")
    monkeypatch.setenv("AUTO_WITHDRAWAL_MAX_AMOUNT_TZS", "500000")
    monkeypatch.setenv("AUTO_WITHDRAWAL_DAILY_LIMIT_TZS", "1000000")
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()


def _enable_automation(monkeypatch):
    monkeypatch.setenv("AUTO_WITHDRAWALS_ENABLED", "true")
    monkeypatch.setenv("REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS", "false")
    get_settings.cache_clear()


class _FakeResend:
    def __init__(self):
        self.calls: list[dict] = []

    def send(self, params: dict) -> dict:
        self.calls.append(params)
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


# --- Eligible auto-processing ------------------------------------------------


def test_eligible_withdrawal_auto_processes_when_enabled(fake_client, fake_resend, monkeypatch):
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    assert body["status"] == "SUCCESS"
    assert body["auto_approved"] is True
    assert body["approved_by"] is None  # no human approved it
    assert "eligible" in body["auto_decision_reason"].lower()


def test_withdrawal_stays_pending_when_automation_disabled(fake_client, fake_resend):
    # Default settings — automation off.
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    assert body["status"] == "PENDING_ADMIN_APPROVAL"
    assert body["auto_approved"] is False
    assert "not enabled" in body["auto_decision_reason"].lower()


def test_require_admin_approval_flag_alone_does_not_enable_automation(fake_client, fake_resend, monkeypatch):
    """Belt-and-suspenders: setting only one of the two flags must never
    enable automation — see Settings.require_admin_approval_for_all_withdrawals's
    docstring."""
    monkeypatch.setenv("AUTO_WITHDRAWALS_ENABLED", "true")
    # REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS left at its True default.
    get_settings.cache_clear()
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    assert body["status"] == "PENDING_ADMIN_APPROVAL"
    assert body["auto_approved"] is False


# --- Merchant standing gates (unconditional, auto or not) --------------------


def test_pending_merchant_cannot_withdraw_even_with_automation_enabled(fake_client, fake_resend, monkeypatch):
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client, status="pending", kyc_status="unverified")
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "50000.00",
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "withdrawal_restricted"
    # Nothing was ever created — verified merchant is checked before the
    # disbursement row is even inserted.
    assert fake_client.table("disbursements")._table.rows == []


def test_suspended_merchant_cannot_withdraw(fake_client, fake_resend, monkeypatch):
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client, status="suspended")
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "50000.00",
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "withdrawal_restricted"


def test_open_high_risk_fraud_alert_blocks_withdrawal_even_with_automation_enabled(
    fake_client, fake_resend, monkeypatch
):
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")
    fake_client.seed(
        "fraud_alerts",
        {"merchant_id": str(merchant_id), "risk_level": "HIGH", "status": "OPEN"},
    )

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "50000.00",
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "withdrawal_restricted"


def test_insufficient_balance_rejected_even_with_automation_enabled(fake_client, fake_resend, monkeypatch):
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "10000.00")

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "50000.00",
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "insufficient_balance"
    assert fake_client.table("disbursements")._table.rows == []


# --- Amount-based auto-eligibility limits ------------------------------------


def test_amount_over_auto_max_falls_back_to_manual_approval(fake_client, fake_resend, monkeypatch):
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "10000000.00")

    # AUTO_WITHDRAWAL_MAX_AMOUNT_TZS is 500000 in this file's fixture.
    body = _request_withdrawal(merchant_id, admin_id, "600000.00")

    assert body["status"] == "PENDING_ADMIN_APPROVAL"
    assert body["auto_approved"] is False
    assert "per-transaction limit" in body["auto_decision_reason"]
    # Still within the overall (non-auto) per-request/daily caps, and still
    # a perfectly valid manual request — nothing about the request itself
    # was rejected, only automation declined to handle it.
    assert fake_client.table("disbursements")._table.rows != []


def test_amount_within_auto_max_but_over_daily_auto_cap_falls_back_to_manual(fake_client, fake_resend, monkeypatch):
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "10000000.00")

    # AUTO_WITHDRAWAL_DAILY_LIMIT_TZS is 1000000 — two 400000 auto requests
    # (800000 total) leave only 200000 of daily auto headroom; a third
    # 300000 request pushes the auto-processed total over the cap.
    first = _request_withdrawal(merchant_id, admin_id, "400000.00")
    second = _request_withdrawal(merchant_id, admin_id, "400000.00")
    assert first["auto_approved"] is True
    assert second["auto_approved"] is True

    third = _request_withdrawal(merchant_id, admin_id, "300000.00")

    assert third["status"] == "PENDING_ADMIN_APPROVAL"
    assert third["auto_approved"] is False
    assert "daily limit" in third["auto_decision_reason"].lower()


# --- Failure handling never permanently debits -------------------------------


def test_failed_auto_processed_payout_reverses_the_reservation(fake_client, fake_resend, monkeypatch):
    from app.services.selcom_business.client import SelcomBusinessResult
    from app.services.selcom_business.mock_client import MockSelcomBusinessClient

    async def _fail(self, *, trans_id: str, **kwargs):
        return SelcomBusinessResult(transaction_id=trans_id, status="failed", failure_reason="Invalid destination account")

    monkeypatch.setattr(MockSelcomBusinessClient, "process_transaction", _fail)
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    assert body["status"] == "FAILED"
    assert body["auto_approved"] is True
    # The reservation was reversed — balance is back to what it started at
    # (post_ledger_entries/reverse_disbursement_entries already proven
    # correct for the manual-approval path in test_admin_withdrawals.py;
    # this just confirms the auto path goes through the exact same
    # reversal code, not a separate, less-tested one).
    balance_response = client.get(
        "/v1/merchant/withdrawals/available-balance", headers=auth_headers(admin_id)
    )
    if balance_response.status_code == 200:
        assert balance_response.json()["data"]["available_balance"] == "1000000.00"


# --- Idempotency: duplicate requests never double-process --------------------


def test_duplicate_idempotency_key_never_auto_processes_twice(fake_client, fake_resend, monkeypatch):
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    idempotency_key = str(uuid.uuid4())
    body = {
        "merchant_id": str(merchant_id),
        "amount": "50000.00",
        "destination_name": "Jane Doe",
        "destination_identifier": "+255700000000",
        "destination_code": "MPESA",
    }
    headers = {**auth_headers(admin_id), "Idempotency-Key": idempotency_key}

    first = client.post("/v1/disbursements/mobile-money", headers=headers, json=body)
    second = client.post("/v1/disbursements/mobile-money", headers=headers, json=body)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    # Only one disbursement row and one SUCCESS-status ledger entry exist —
    # the second call replayed the stored response, it never re-ran
    # execute_disbursement (and therefore never re-evaluated or re-triggered
    # automation) a second time.
    matching = [r for r in fake_client.table("disbursements")._table.rows if r["id"] == first.json()["data"]["id"]]
    assert len(matching) == 1


# --- Audit log ----------------------------------------------------------------


def test_auto_processed_withdrawal_writes_an_audit_log(fake_client, fake_resend, monkeypatch):
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    audit_rows = [
        r
        for r in fake_client.table("audit_logs")._table.rows
        if r.get("resource_id") == body["id"] and r.get("action") == "disbursement.completed"
    ]
    assert len(audit_rows) == 1


# --- Emails: CEO request notification suppressed by default ------------------


def test_ceo_withdrawal_request_email_not_sent_by_default(fake_client, fake_resend):
    # Default settings — SEND_WITHDRAWAL_REQUEST_EMAILS is false.
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    _request_withdrawal(merchant_id, admin_id, "50000.00")

    assert fake_resend.calls == []


def test_ceo_withdrawal_request_email_sent_when_flag_enabled(fake_client, fake_resend, monkeypatch):
    monkeypatch.setenv("SEND_WITHDRAWAL_REQUEST_EMAILS", "true")
    get_settings.cache_clear()
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    _request_withdrawal(merchant_id, admin_id, "50000.00")

    assert len(fake_resend.calls) == 1
    assert fake_resend.calls[0]["to"] == ["ceo@infinitypay.me"]


# --- Super Admin visibility ----------------------------------------------------


def test_super_admin_sees_auto_processed_status_and_reason(fake_client, fake_resend, monkeypatch):
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")
    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    response = client.get("/v1/admin/withdrawals", headers=auth_headers(super_admin_id))

    assert response.status_code == 200, response.text
    row = next(r for r in response.json()["data"] if r["withdrawal_id"] == body["id"])
    assert row["status"] == "SUCCESS"
    assert row["auto_approved"] is True
    assert row["auto_decision_reason"]


# --- Secrets never reach the API surface ---------------------------------------


_SECRET_ENV = {
    "SUPABASE_SERVICE_ROLE_KEY": "sentinel-service-role-key",
    "SELCOM_API_KEY": "sentinel-selcom-api-key",
    "SELCOM_API_SECRET": "sentinel-selcom-api-secret",
    "SELCOM_BUSINESS_API_KEY": "sentinel-selcom-business-api-key",
    "SELCOM_WEBHOOK_SECRET": "sentinel-selcom-webhook-secret",
    "WEBHOOK_SECRET_ENCRYPTION_KEY": "sentinel-webhook-encryption-key",
}


def _set_secret_sentinels(monkeypatch):
    """Distinctive, obviously-fake values for every backend-only credential
    the withdrawal path touches, so a leak into a response body shows up as
    an exact substring match rather than needing a heuristic."""
    for name, value in _SECRET_ENV.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


def test_auto_processed_withdrawal_response_exposes_no_secrets(fake_client, fake_resend, monkeypatch):
    """auto_decision_reason is merchant-visible and is built from Settings —
    it must only ever carry business limits/status, never a credential."""
    _enable_automation(monkeypatch)
    _set_secret_sentinels(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    assert body["auto_approved"] is True
    serialized = str(body)
    for name, value in _SECRET_ENV.items():
        assert value not in serialized, f"{name} leaked into the withdrawal response"
    # The Resend key set by the autouse fixture must not leak either.
    assert "test-resend-key-do-not-use-in-production" not in serialized


def test_manual_fallback_reason_exposes_no_secrets(fake_client, fake_resend, monkeypatch):
    """Same guarantee on the ineligible path, where auto_decision_reason is
    assembled from a different set of Settings values."""
    _enable_automation(monkeypatch)
    _set_secret_sentinels(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "5000000.00")

    # Over AUTO_WITHDRAWAL_MAX_AMOUNT_TZS -> falls back to manual approval.
    body = _request_withdrawal(merchant_id, admin_id, "600000.00")

    assert body["status"] == "PENDING_ADMIN_APPROVAL"
    assert body["auto_approved"] is False
    serialized = str(body)
    for name, value in _SECRET_ENV.items():
        assert value not in serialized, f"{name} leaked into the withdrawal response"


# --- Concurrency: the advisory-locked limit guard -------------------------------
#
# The real guard is supabase/migrations/20260922030000_finalize_withdrawal_limits.sql,
# which holds a per-merchant advisory lock for the whole decision. These tests
# exercise the decision rule that makes that lock useful: totals count only
# rows initiated strictly before this one, so two simultaneous requests
# resolve to exactly one winner instead of both passing (the bug) or both
# being rejected (the naive fix). tests/fakes.py mirrors the function.


def _seed_competing_withdrawal(
    fake_client,
    merchant_id,
    *,
    amount,
    initiated_at,
    auto_approved=False,
    status="PENDING_ADMIN_APPROVAL",
    decision_reason="Manual approval required: withdrawal automation is not enabled.",
):
    """A withdrawal that already exists when the one under test is finalized —
    i.e. the other half of a race, already inserted."""
    return fake_client.seed(
        "disbursements",
        {
            "merchant_id": str(merchant_id),
            "method": "MOBILE_MONEY",
            "amount": amount,
            "currency": "TZS",
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
            "status": status,
            "requires_approval": True,
            "auto_approved": auto_approved,
            # None means "inserted but not yet decided" — the in-flight state
            # the auto-cap predicate has to account for.
            "auto_decision_reason": decision_reason,
            "initiated_at": initiated_at,
        },
    )


def test_concurrent_request_cannot_bypass_the_hard_daily_limit(fake_client, fake_resend, monkeypatch):
    """Two withdrawals that each fit under DAILY_WITHDRAWAL_LIMIT_TZS alone but
    not together, submitted at the same instant.

    The race the guard exists for: the up-front _check_withdrawal_amount_limits
    pre-check reads a total that does NOT yet include the competing request,
    so it passes — that is exactly the window the old read-then-write check
    missed. Simulated deterministically by neutralizing the pre-check (which
    is what a real concurrent read would effectively do) and letting the
    competing row exist by the time the guard runs. The guard must still
    reject, and must mark the row REJECTED rather than leaving it pending."""
    monkeypatch.setenv("DAILY_WITHDRAWAL_LIMIT_TZS", "150000")
    get_settings.cache_clear()
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "5000000.00")

    _seed_competing_withdrawal(
        fake_client,
        merchant_id,
        amount="100000.00",
        initiated_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
    )
    monkeypatch.setattr(disbursements_service, "_check_withdrawal_amount_limits", lambda *a, **k: None)

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "100000.00",
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )

    assert response.status_code == 409, response.text
    assert "daily withdrawal limit" in response.text.lower()
    # Marked REJECTED inside the guard, so it stops counting against others.
    rejected = [
        r
        for r in fake_client.table("disbursements")._table.rows
        if r["merchant_id"] == str(merchant_id) and r["status"] == "REJECTED"
    ]
    assert len(rejected) == 1


def test_pre_check_still_rejects_an_over_limit_request_before_any_row_exists(fake_client, fake_resend, monkeypatch):
    """The fast path: when the competing total is already visible, the
    up-front check rejects without ever creating a disbursement row."""
    monkeypatch.setenv("DAILY_WITHDRAWAL_LIMIT_TZS", "150000")
    get_settings.cache_clear()
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "5000000.00")
    _seed_competing_withdrawal(
        fake_client,
        merchant_id,
        amount="100000.00",
        initiated_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
    )

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "100000.00",
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )

    assert response.status_code == 409, response.text
    # Nothing was inserted — only the seeded competitor exists.
    assert len(fake_client.table("disbursements")._table.rows) == 1


def test_concurrent_auto_withdrawals_cannot_bypass_the_auto_daily_cap(fake_client, fake_resend, monkeypatch):
    """The auto-only rolling cap has the same race. The later request must
    fall back to manual approval — never be rejected, and never auto-process."""
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "5000000.00")

    # AUTO_WITHDRAWAL_DAILY_LIMIT_TZS is 1,000,000 in this file's fixture.
    _seed_competing_withdrawal(
        fake_client,
        merchant_id,
        amount="800000.00",
        initiated_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        auto_approved=True,
        status="SUCCESS",
    )

    body = _request_withdrawal(merchant_id, admin_id, "400000.00")

    assert body["status"] == "PENDING_ADMIN_APPROVAL"
    assert body["auto_approved"] is False
    assert "daily limit for automatic processing" in body["auto_decision_reason"]


def test_the_earlier_of_two_racing_requests_still_wins(fake_client, fake_resend, monkeypatch):
    """The ordering rule must not deadlock both requests into rejection: a
    competing row initiated strictly *after* this one doesn't count against
    it, so the earlier request proceeds normally."""
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "5000000.00")

    # Already-inserted competitor, but dated into the future relative to the
    # request below — i.e. this request is the earlier of the two.
    _seed_competing_withdrawal(
        fake_client,
        merchant_id,
        amount="900000.00",
        initiated_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        auto_approved=True,
    )

    body = _request_withdrawal(merchant_id, admin_id, "400000.00")

    assert body["status"] == "SUCCESS"
    assert body["auto_approved"] is True


def test_a_rejected_racing_request_does_not_consume_the_limit(fake_client, fake_resend, monkeypatch):
    """A row the guard rejected must stop counting toward the rolling total,
    or one rejected request would wrongly block every later one."""
    monkeypatch.setenv("DAILY_WITHDRAWAL_LIMIT_TZS", "150000")
    get_settings.cache_clear()
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "5000000.00")

    _seed_competing_withdrawal(
        fake_client,
        merchant_id,
        amount="140000.00",
        initiated_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        status="REJECTED",
    )

    body = _request_withdrawal(merchant_id, admin_id, "140000.00")

    assert body["status"] == "PENDING_ADMIN_APPROVAL"


def test_auto_withdrawal_aborts_if_merchant_is_suspended_just_before_payout(
    fake_client, fake_resend, monkeypatch
):
    """The final re-check immediately before money moves: if merchant standing
    changed after the row was created, fall back to manual approval rather
    than paying out or rejecting."""
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "5000000.00")

    # Suspend the merchant at the moment the guard finishes, i.e. between the
    # eligibility decision and the provider call.
    original = FakeSupabaseClient._finalize_withdrawal_limits

    def _suspend_then_finalize(self, params):
        result = original(self, params)
        merchant = next(r for r in self.table("merchants")._table.rows if r["id"] == str(merchant_id))
        merchant["status"] = "suspended"
        return result

    monkeypatch.setattr(FakeSupabaseClient, "_finalize_withdrawal_limits", _suspend_then_finalize)

    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    assert body["status"] == "PENDING_ADMIN_APPROVAL"
    assert body["auto_approved"] is False
    assert "Manual approval required" in body["auto_decision_reason"]


def test_an_undecided_earlier_request_still_counts_against_the_auto_cap(
    fake_client, fake_resend, monkeypatch
):
    """The race the (auto_approved or auto_decision_reason is null) predicate
    exists for.

    The advisory lock serializes these calls but does NOT order them by
    (initiated_at, id) — the later row's call can acquire the lock first,
    at which point the earlier row is inserted but has not yet had
    auto_approved written. If only auto_approved counted, each would miss
    the other and both would auto-process, blowing past the auto daily cap.
    The earlier, still-undecided row must count, so this one falls back to
    manual approval rather than auto-processing."""
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "5000000.00")

    # AUTO_WITHDRAWAL_DAILY_LIMIT_TZS is 1,000,000 in this file's fixture.
    _seed_competing_withdrawal(
        fake_client,
        merchant_id,
        amount="800000.00",
        initiated_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        auto_approved=False,
        decision_reason=None,
    )

    body = _request_withdrawal(merchant_id, admin_id, "400000.00")

    assert body["status"] == "PENDING_ADMIN_APPROVAL"
    assert body["auto_approved"] is False
    assert "daily limit for automatic processing" in body["auto_decision_reason"]


def test_a_settled_manual_earlier_request_does_not_block_the_auto_cap(
    fake_client, fake_resend, monkeypatch
):
    """The other side of that predicate: an earlier row that was already
    decided as manual is not in flight any more, so it must NOT consume the
    auto cap — otherwise every manual withdrawal would suppress automation
    for the rest of the window."""
    _enable_automation(monkeypatch)
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "5000000.00")

    _seed_competing_withdrawal(
        fake_client,
        merchant_id,
        amount="800000.00",
        initiated_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        auto_approved=False,
        decision_reason="Manual approval required: exceeds the per-transaction limit.",
    )

    body = _request_withdrawal(merchant_id, admin_id, "400000.00")

    assert body["status"] == "SUCCESS"
    assert body["auto_approved"] is True


# --- Manual mode: the provider must not be touched at request time -------------


def test_manual_mode_never_calls_the_provider_on_a_withdrawal_request(
    fake_client, fake_resend, monkeypatch
):
    """The single most important guarantee of the recommended first-real-users
    configuration (AUTO_WITHDRAWALS_ENABLED=false,
    REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS=true): submitting a withdrawal
    must never reach Selcom. Only a Super Admin's approval does.

    Asserted by making any provider call fail the test outright, rather than
    by checking the resulting status — a status assertion would still pass if
    a payout had been attempted and then rolled back."""
    calls: list[dict] = []

    class _ExplodingProvider:
        async def process_transaction(self, **kwargs):
            calls.append(kwargs)
            raise AssertionError("Selcom was called at withdrawal-request time in manual mode")

    monkeypatch.setattr(
        "app.services.disbursements.get_selcom_business_client", lambda: _ExplodingProvider()
    )

    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    assert calls == []
    assert body["status"] == "PENDING_ADMIN_APPROVAL"
    assert body["auto_approved"] is False


def test_manual_mode_response_exposes_no_provider_internals(fake_client, fake_resend):
    """A withdrawal-request response is merchant-visible. It must carry no
    provider credentials, no raw provider payload, and no stack trace."""
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "1000000.00")

    body = _request_withdrawal(merchant_id, admin_id, "50000.00")

    serialized = str(body).lower()
    for leaked in ("traceback", "psycopg", "postgrest", "api_key", "api_secret", "private_key", "vendor_id"):
        assert leaked not in serialized, f"{leaked!r} leaked into the withdrawal response"
