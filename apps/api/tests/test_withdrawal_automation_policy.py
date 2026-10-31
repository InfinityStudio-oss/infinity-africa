"""The Super Admin withdrawal automation policy: its precedence, its two
endpoints, and what it does and does not do to withdrawals.

tests/test_withdrawal_automation.py covers what happens to a withdrawal
once the automation answer is known. This file is about producing that
answer - which of the deployment flags, the deployment ceilings and the
database policy row wins, and what happens when the row cannot be read.

The thing worth stating up front, because it is the whole point of the
feature and the easiest thing to get wrong: **nothing here can turn
automation on by accident.** Every path that fails - a missing row, a
malformed amount, an unreadable table, an unset deployment flag, a stale
version - lands on manual approval.

What this file CANNOT prove: the per-merchant advisory lock. The fake
Supabase client is single-threaded and mirrors the SQL function's
*decisions*, not its locking, so the concurrency tests here prove the
decision rule that makes the lock useful (totals count only rows initiated
strictly before this one) rather than the serialization itself. The lock is
exercised against a real Postgres in
tests/test_withdrawal_automation_policy_postgres.py, which skips unless
TEST_DATABASE_URL is set.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.selcom_business.client import get_selcom_business_client
from app.services.withdrawal_policy import resolve_effective_policy
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
    make_super_admin,
)

client = TestClient(app)

POLICY_PATH = "/v1/admin/withdrawal-automation/policy"


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("SELCOM_BUSINESS_MODE", "mock")
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "0")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("AUTO_WITHDRAWAL_MAX_AMOUNT_TZS", "500000")
    monkeypatch.setenv("AUTO_WITHDRAWAL_DAILY_LIMIT_TZS", "1000000")
    # Off by default in every test, so a test that wants MFA enforcement
    # turns it on and the rest are not all writing aal2 headers.
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "false")
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()


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


def _permit_automation(monkeypatch):
    """The deployment half only. On its own this must never be enough."""
    monkeypatch.setenv("AUTO_WITHDRAWALS_ENABLED", "true")
    monkeypatch.setenv("REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS", "false")
    get_settings.cache_clear()


def _admin(fake_client):
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    fake_client.seed_auth_user(admin_id, email="admin@infinitypay.me", full_name="Platform Admin")
    return admin_id


def _merchant_and_admin(fake_client, **overrides):
    merchant = create_merchant(fake_client, **overrides)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    return merchant_id, user_id


def _fund_wallet(fake_client, merchant_id: uuid.UUID, amount: str) -> None:
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Merchant Wallet (test)",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": "TZS",
            "balance": amount,
        },
    )


def _request_withdrawal(merchant_id: uuid.UUID, user_id: uuid.UUID, amount: str, **overrides) -> dict:
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
        headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
        json=body,
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]


def _row(fake_client, disbursement_id: str) -> dict:
    rows = fake_client.table("disbursements")._table.rows
    return next(r for r in rows if r["id"] == disbursement_id)


def _auto(row: dict) -> bool:
    """disbursements.auto_approved defaults to false in the database and
    nothing writes it on the manual path, so a row that fell back has no
    key at all. Absent and false mean the same thing: no automation."""
    return bool(row.get("auto_approved"))


# --- 1. Fail closed ---------------------------------------------------------


def test_a_missing_policy_sends_every_withdrawal_to_manual_approval(fake_client, monkeypatch):
    """The deployment permits automation and the policy cannot be read.

    This is the case that has to be right: an unreadable control over
    money must mean "ask a human", never "carry on".
    """
    _permit_automation(monkeypatch)
    fake_client.break_withdrawal_automation_policy()

    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    data = _request_withdrawal(merchant_id, user_id, "5000")

    assert data["status"] == "PENDING_ADMIN_APPROVAL"
    assert data["auto_approved"] is False
    # A fault, not a decision. An operator must be able to tell a switch
    # somebody turned off from a policy nobody can read.
    assert _row(fake_client, data["id"])["auto_decision_code"] == "AUTO_POLICY_UNAVAILABLE"


def test_an_unreadable_policy_resolves_to_automation_off(fake_client, monkeypatch):
    """resolve_effective_policy's own contract, checked directly: the
    reason code says it was unavailable rather than merely switched off,
    so an operator can tell a fault from a decision."""
    _permit_automation(monkeypatch)
    fake_client.break_withdrawal_automation_policy()

    policy = resolve_effective_policy(fake_client)

    assert policy.automation_active is False
    assert policy.policy_unavailable is True
    assert policy.blocked_reason_code == "AUTO_POLICY_UNAVAILABLE"
    assert policy.max_amount_tzs == Decimal(0)


def test_a_malformed_amount_in_the_policy_resolves_to_automation_off(fake_client, monkeypatch):
    _permit_automation(monkeypatch)
    fake_client.enable_withdrawal_automation_policy()
    fake_client.table("withdrawal_automation_policy")._table.rows[0]["max_amount_tzs"] = "not-a-number"

    policy = resolve_effective_policy(fake_client)

    assert policy.automation_active is False
    assert policy.policy_unavailable is True


def test_the_policy_cannot_be_changed_while_it_cannot_be_read(fake_client, monkeypatch):
    """Writing a version we are guessing at would be worse than refusing."""
    _permit_automation(monkeypatch)
    fake_client.break_withdrawal_automation_policy()
    admin_id = _admin(fake_client)

    response = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "100000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
            "confirm": True,
        },
    )

    assert response.status_code == 422
    assert "could not be read" in response.json()["error"]["message"]


# --- 2. OFF is the default and routes to manual -----------------------------


def test_the_seeded_policy_is_off(fake_client):
    """Applying the migration must not switch any installation on."""
    policy = resolve_effective_policy(fake_client)

    assert policy.policy_enabled is False
    assert policy.automation_active is False
    assert policy.policy_unavailable is False


def test_policy_off_routes_a_fully_eligible_request_to_manual_approval(fake_client, monkeypatch):
    _permit_automation(monkeypatch)  # deployment says yes, policy says no

    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    data = _request_withdrawal(merchant_id, user_id, "5000")

    assert data["status"] == "PENDING_ADMIN_APPROVAL"
    assert data["auto_approved"] is False
    assert _row(fake_client, data["id"])["auto_decision_code"] == "AUTO_POLICY_DISABLED"


def test_policy_on_without_the_deployment_flags_still_means_manual(fake_client):
    """The environment is the deployment's permission for automation to
    exist. A policy row cannot grant itself that permission - otherwise
    the emergency override would not be an override."""
    fake_client.enable_withdrawal_automation_policy()

    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    data = _request_withdrawal(merchant_id, user_id, "5000")

    assert data["status"] == "PENDING_ADMIN_APPROVAL"
    assert data["auto_approved"] is False


def test_the_manual_only_override_beats_an_enabled_policy(fake_client, monkeypatch):
    """REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS is step 1 of the
    precedence: it wins over everything below it."""
    monkeypatch.setenv("AUTO_WITHDRAWALS_ENABLED", "true")
    monkeypatch.setenv("REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS", "true")
    get_settings.cache_clear()
    fake_client.enable_withdrawal_automation_policy()

    policy = resolve_effective_policy(fake_client)

    assert policy.policy_enabled is True
    assert policy.automation_active is False
    assert policy.manual_only_override is True
    assert "deployment override" in policy.blocked_explanation


# --- 3/4. The inclusive ceiling ---------------------------------------------


def _enable_both(fake_client, monkeypatch, *, max_amount="100000", rolling="1000000"):
    _permit_automation(monkeypatch)
    fake_client.enable_withdrawal_automation_policy(
        max_amount_tzs=max_amount, rolling_24h_limit_tzs=rolling
    )


@pytest.mark.parametrize(
    ("amount", "expect_auto"),
    [
        ("99999", True),   # below
        ("100000", True),  # exactly at - the inclusive boundary
        ("100001", False),  # above
    ],
)
def test_the_per_request_ceiling_is_inclusive(fake_client, monkeypatch, amount, expect_auto):
    """"TZS 100,000 or less may process automatically" is what the portal
    promises, so exactly 100,000 must process. The SQL compares with `>`
    and this pins that it stays `>` and never becomes `>=`."""
    _enable_both(fake_client, monkeypatch, max_amount="100000")

    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    data = _request_withdrawal(merchant_id, user_id, amount)
    row = _row(fake_client, data["id"])

    assert _auto(row) is expect_auto
    if expect_auto:
        assert row["auto_decision_code"] == "AUTO_ELIGIBLE"
        assert data["status"] != "PENDING_ADMIN_APPROVAL"
    else:
        assert row["auto_decision_code"] == "AUTO_AMOUNT_LIMIT_EXCEEDED"
        assert data["status"] == "PENDING_ADMIN_APPROVAL"


def test_the_deployment_ceiling_clamps_a_higher_policy_limit(fake_client, monkeypatch):
    """Step 4 of the precedence. The policy asks for 400,000 while the
    deployment caps automation at 50,000, so 60,000 must go to a human
    even though the portal's own number would have allowed it."""
    monkeypatch.setenv("AUTO_WITHDRAWAL_MAX_AMOUNT_TZS", "50000")
    _enable_both(fake_client, monkeypatch, max_amount="400000")

    policy = resolve_effective_policy(fake_client)
    assert policy.policy_max_amount_tzs == Decimal(400000)
    assert policy.max_amount_tzs == Decimal(50000)

    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    row = _row(fake_client, _request_withdrawal(merchant_id, user_id, "60000")["id"])
    assert _auto(row) is False
    assert row["auto_decision_code"] == "AUTO_AMOUNT_LIMIT_EXCEEDED"


def test_a_policy_limit_below_the_deployment_ceiling_is_the_one_that_applies(fake_client, monkeypatch):
    """Tightening from the portal has to work without a deploy - that is
    the feature. 10,000 policy under a 500,000 deployment cap means
    20,000 waits for a human."""
    _enable_both(fake_client, monkeypatch, max_amount="10000")

    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    row = _row(fake_client, _request_withdrawal(merchant_id, user_id, "20000")["id"])
    assert _auto(row) is False
    assert row["auto_decision_code"] == "AUTO_AMOUNT_LIMIT_EXCEEDED"


def test_an_eligible_request_records_the_policy_version_that_decided_it(fake_client, monkeypatch):
    """"Which policy paid this out" has to be answerable months later."""
    _enable_both(fake_client, monkeypatch)
    fake_client.table("withdrawal_automation_policy")._table.rows[0]["version"] = 7

    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    row = _row(fake_client, _request_withdrawal(merchant_id, user_id, "5000")["id"])

    assert _auto(row) is True
    assert row["auto_policy_version"] == 7
    assert row["auto_decided_at"] is not None
    # No human is credited for a decision no human took.
    assert row.get("approved_by") is None


# --- 5. Every other control still applies -----------------------------------


def test_an_unverified_merchant_cannot_auto_withdraw(fake_client, monkeypatch):
    _enable_both(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client, kyc_status="pending", status="pending")
    _fund_wallet(fake_client, merchant_id, "900000")

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "5000",
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "withdrawal_restricted"
    assert fake_client.table("disbursements")._table.rows == []


def test_a_suspended_merchant_cannot_auto_withdraw(fake_client, monkeypatch):
    _enable_both(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client, status="suspended")
    _fund_wallet(fake_client, merchant_id, "900000")

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "5000",
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )

    assert response.status_code in (403, 404, 409)


def test_an_open_high_risk_alert_blocks_automation_without_leaking_why(fake_client, monkeypatch):
    """A hard fraud block is not routed to ordinary approval and is not
    explained to the merchant."""
    _enable_both(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")
    fake_client.seed(
        "fraud_alerts",
        {"merchant_id": str(merchant_id), "risk_level": "CRITICAL", "status": "OPEN"},
    )

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "5000",
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "withdrawal_restricted"
    body = response.text.lower()
    for leak in ("critical", "fraud_alert", "risk_level", "score"):
        assert leak not in body


def test_insufficient_balance_is_refused_even_when_within_the_automatic_limit(fake_client, monkeypatch):
    """The per-request threshold applies to the payout principal; the
    balance check still has to cover the whole wallet debit including
    fees. 5,000 is well inside a 100,000 automatic ceiling and still must
    not pay out of a wallet holding 100."""
    _enable_both(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "100")

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "5000",
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "insufficient_balance"
    assert fake_client.table("disbursements")._table.rows == []


def test_the_platform_minimum_still_applies_under_automation(fake_client, monkeypatch):
    """A policy ceiling never lowers the floor."""
    _enable_both(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "100",
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "withdrawal_restricted"


# --- 6/7. Who may touch the policy ------------------------------------------


def test_a_merchant_session_cannot_read_the_policy(fake_client):
    _, user_id = _merchant_and_admin(fake_client)

    assert client.get(POLICY_PATH, headers=auth_headers(user_id)).status_code == 403


def test_a_merchant_session_cannot_change_the_policy(fake_client):
    _, user_id = _merchant_and_admin(fake_client)

    response = client.put(
        POLICY_PATH,
        headers=auth_headers(user_id),
        json={
            "enabled": True,
            "max_amount_tzs": "100000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
            "confirm": True,
        },
    )

    assert response.status_code == 403
    assert resolve_effective_policy(fake_client).policy_enabled is False


def test_an_unauthenticated_caller_cannot_read_or_change_the_policy(fake_client):
    assert client.get(POLICY_PATH).status_code in (401, 403)
    assert client.put(POLICY_PATH, json={}).status_code in (401, 403, 422)


def test_an_api_key_cannot_read_or_change_the_policy(fake_client):
    """A merchant's server credential is not a route into platform
    configuration. These endpoints never opt into API-key auth, so the key
    is simply not a credential here."""
    merchant_id, _ = _merchant_and_admin(fake_client)
    from app.auth import hash_api_key

    raw = "sk_live_policy_test_key_do_not_use"
    fake_client.seed(
        "api_keys",
        {
            "merchant_id": str(merchant_id),
            "name": "test",
            "key_prefix": "sk_live_policy",
            "hashed_key": hash_api_key(raw),
            "environment": "live",
            "status": "active",
            "scopes": ["collections:write"],
            "ip_whitelist_enabled": False,
        },
    )

    assert client.get(POLICY_PATH, headers={"X-API-Key": raw}).status_code in (401, 403)
    assert client.put(
        POLICY_PATH,
        headers={"X-API-Key": raw},
        json={
            "enabled": True,
            "max_amount_tzs": "100000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
            "confirm": True,
        },
    ).status_code in (401, 403)
    assert resolve_effective_policy(fake_client).policy_enabled is False


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_a_second_factor_is_required_when_mfa_is_enforced(fake_client, monkeypatch, method):
    """require_super_admin enforces aal2 on reads as well as writes, which
    is this codebase's sensitive-action convention."""
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "true")
    get_settings.cache_clear()
    admin_id = _admin(fake_client)
    body = {
        "enabled": False,
        "max_amount_tzs": "100000",
        "merchant_rolling_24h_limit_tzs": "500000",
        "version": 1,
    }

    without = client.request(method, POLICY_PATH, headers=auth_headers(admin_id), json=body)
    assert without.status_code == 403
    assert without.json()["error"]["code"] == "mfa_required"

    with_aal2 = client.request(method, POLICY_PATH, headers=auth_headers(admin_id, aal="aal2"), json=body)
    assert with_aal2.status_code == 200


# --- 8. Optimistic concurrency ----------------------------------------------


def test_a_stale_version_is_refused_with_a_conflict(fake_client, monkeypatch):
    """Two administrators, one policy. The second must not silently undo
    the first."""
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)
    other_admin = _admin(fake_client)

    first = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "50000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
            "confirm": True,
        },
    )
    assert first.status_code == 200
    assert first.json()["data"]["version"] == 2

    # Still holding version 1, which no longer exists.
    second = client.put(
        POLICY_PATH,
        headers=auth_headers(other_admin),
        json={
            "enabled": True,
            "max_amount_tzs": "400000",
            "merchant_rolling_24h_limit_tzs": "900000",
            "version": 1,
            "confirm": True,
        },
    )

    assert second.status_code == 409
    # The first administrator's numbers survived.
    policy = resolve_effective_policy(fake_client)
    assert policy.policy_max_amount_tzs == Decimal(50000)
    assert policy.policy_version == 2


def test_the_conflict_response_lets_the_page_recover(fake_client, monkeypatch):
    """A conflict has to be distinguishable from a validation failure, so
    the UI knows to reload rather than ask the operator to retype."""
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)

    response = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": False,
            "max_amount_tzs": "50000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 99,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


# --- Validation -------------------------------------------------------------


def test_enabling_requires_an_explicit_confirmation(fake_client, monkeypatch):
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)

    response = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "50000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
        },
    )

    assert response.status_code == 422
    message = response.json()["error"]["message"]
    # The confirmation has to summarize what it is confirming.
    assert "50000" in message
    assert "500000" in message
    assert resolve_effective_policy(fake_client).policy_enabled is False


def test_raising_a_limit_requires_confirmation(fake_client, monkeypatch):
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)
    client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "50000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
            "confirm": True,
        },
    )

    response = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "200000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 2,
        },
    )

    assert response.status_code == 422


def test_switching_off_never_needs_confirmation(fake_client, monkeypatch):
    """Someone reaching for the brake must not be asked twice."""
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)
    client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "50000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
            "confirm": True,
        },
    )

    response = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": False,
            "max_amount_tzs": "50000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["automation_active"] is False
    assert resolve_effective_policy(fake_client).automation_active is False


def test_lowering_a_limit_never_needs_confirmation(fake_client, monkeypatch):
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)
    client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "200000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
            "confirm": True,
        },
    )

    response = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "20000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["max_amount_tzs"] == "20000.00"


@pytest.mark.parametrize(
    ("body", "expect_in_message"),
    [
        ({"enabled": True, "max_amount_tzs": "0", "merchant_rolling_24h_limit_tzs": "500000"}, "greater than zero"),
        ({"enabled": True, "max_amount_tzs": "500", "merchant_rolling_24h_limit_tzs": "500000"}, "minimum"),
        (
            {"enabled": True, "max_amount_tzs": "9000000", "merchant_rolling_24h_limit_tzs": "9000000"},
            "per-request",
        ),
        (
            {"enabled": True, "max_amount_tzs": "100000.123", "merchant_rolling_24h_limit_tzs": "500000"},
            "decimal places",
        ),
        (
            {"enabled": True, "max_amount_tzs": "400000", "merchant_rolling_24h_limit_tzs": "100000"},
            "lower than the per-request maximum",
        ),
    ],
)
def test_amounts_are_validated_server_side(fake_client, monkeypatch, body, expect_in_message):
    """500 does not mean 500,000. A ceiling below the platform's own
    withdrawal minimum of 1,000 TZS could never match a single withdrawal,
    and is the specific mistake this message exists to catch."""
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)

    response = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={**body, "version": 1, "confirm": True},
    )

    assert response.status_code == 422
    assert expect_in_message in response.json()["error"]["message"]
    assert resolve_effective_policy(fake_client).policy_enabled is False


def test_a_negative_limit_is_refused(fake_client, monkeypatch):
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)

    response = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "-1",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
            "confirm": True,
        },
    )

    assert response.status_code == 422


def test_an_unknown_field_is_refused(fake_client, monkeypatch):
    """An operator who misspells a field and gets a 200 would reasonably
    believe the limit had changed."""
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)

    response = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "50000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
            "confirm": True,
            "max_amount": "999999999",
        },
    )

    assert response.status_code == 422


def test_a_client_supplied_administrator_id_is_not_trusted(fake_client, monkeypatch):
    """updated_by comes from the verified token, and the body has no way
    to say otherwise - extra="forbid" refuses the attempt outright."""
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)

    response = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": False,
            "max_amount_tzs": "50000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
            "updated_by": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 422

    ok = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": False,
            "max_amount_tzs": "50000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
        },
    )
    assert ok.status_code == 200
    assert ok.json()["data"]["updated_by"] == str(admin_id)


# --- 9/10/11. The rolling limit ---------------------------------------------


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
            "auto_decision_reason": decision_reason,
            "initiated_at": initiated_at,
        },
    )


def test_the_rolling_limit_uses_a_real_24_hour_window_not_a_calendar_day(fake_client, monkeypatch):
    """A payout 25 hours old is outside the window whatever the date is,
    and a payout 23 hours old is inside it even across midnight."""
    _enable_both(fake_client, monkeypatch, max_amount="100000", rolling="100000")
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    now = datetime.now(timezone.utc)
    _seed_competing_withdrawal(
        fake_client,
        merchant_id,
        amount="90000",
        initiated_at=(now - timedelta(hours=25)).isoformat(),
        auto_approved=True,
        status="SUCCESS",
        decision_reason="Eligible",
    )

    # Outside the window, so it does not consume the allowance.
    row = _row(fake_client, _request_withdrawal(merchant_id, user_id, "90000")["id"])
    assert _auto(row) is True


def test_an_auto_payout_inside_the_window_consumes_the_allowance(fake_client, monkeypatch):
    _enable_both(fake_client, monkeypatch, max_amount="100000", rolling="100000")
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    now = datetime.now(timezone.utc)
    _seed_competing_withdrawal(
        fake_client,
        merchant_id,
        amount="90000",
        initiated_at=(now - timedelta(hours=23)).isoformat(),
        auto_approved=True,
        status="SUCCESS",
        decision_reason="Eligible",
    )

    row = _row(fake_client, _request_withdrawal(merchant_id, user_id, "20000")["id"])
    assert _auto(row) is False
    assert row["auto_decision_code"] == "AUTO_ROLLING_LIMIT_EXCEEDED"


def test_an_in_flight_undecided_request_counts_against_the_rolling_limit(fake_client, monkeypatch):
    """The race the SQL's "auto_decision_reason is null" half exists for.
    Two concurrent requests must not each pass against the same remaining
    allowance, so an inserted-but-undecided earlier row is counted."""
    _enable_both(fake_client, monkeypatch, max_amount="100000", rolling="100000")
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    now = datetime.now(timezone.utc)
    _seed_competing_withdrawal(
        fake_client,
        merchant_id,
        amount="90000",
        initiated_at=(now - timedelta(minutes=1)).isoformat(),
        auto_approved=False,
        decision_reason=None,  # inserted, not yet decided
    )

    row = _row(fake_client, _request_withdrawal(merchant_id, user_id, "20000")["id"])
    assert _auto(row) is False
    assert row["auto_decision_code"] == "AUTO_ROLLING_LIMIT_EXCEEDED"


def test_toggling_the_policy_does_not_reset_a_consumed_allowance(fake_client, monkeypatch):
    """The allowance is derived from the withdrawals themselves, not stored
    on the policy, so turning the switch off and on cannot hand a merchant
    a fresh 24 hours."""
    _enable_both(fake_client, monkeypatch, max_amount="100000", rolling="100000")
    admin_id = _admin(fake_client)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    now = datetime.now(timezone.utc)
    _seed_competing_withdrawal(
        fake_client,
        merchant_id,
        amount="90000",
        initiated_at=(now - timedelta(hours=1)).isoformat(),
        auto_approved=True,
        status="SUCCESS",
        decision_reason="Eligible",
    )

    version = resolve_effective_policy(fake_client).policy_version
    for enabled in (False, True):
        response = client.put(
            POLICY_PATH,
            headers=auth_headers(admin_id),
            json={
                "enabled": enabled,
                "max_amount_tzs": "100000",
                "merchant_rolling_24h_limit_tzs": "100000",
                "version": version,
                "confirm": True,
            },
        )
        assert response.status_code == 200
        version = response.json()["data"]["version"]

    row = _row(fake_client, _request_withdrawal(merchant_id, user_id, "20000")["id"])
    assert _auto(row) is False
    assert row["auto_decision_code"] == "AUTO_ROLLING_LIMIT_EXCEEDED"


def test_lowering_the_limit_stops_new_automatic_authorizations_above_it(fake_client, monkeypatch):
    """The dispatch boundary reads the policy per withdrawal, so a lowered
    limit binds the very next request without a deploy or a restart."""
    _enable_both(fake_client, monkeypatch, max_amount="100000")
    admin_id = _admin(fake_client)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    before = _row(fake_client, _request_withdrawal(merchant_id, user_id, "50000")["id"])
    assert _auto(before) is True

    version = resolve_effective_policy(fake_client).policy_version
    lowered = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "10000",
            "merchant_rolling_24h_limit_tzs": "1000000",
            "version": version,
        },
    )
    assert lowered.status_code == 200

    after = _row(fake_client, _request_withdrawal(merchant_id, user_id, "50000")["id"])
    assert _auto(after) is False
    assert after["auto_decision_code"] == "AUTO_AMOUNT_LIMIT_EXCEEDED"


def test_switching_off_stops_the_next_automatic_authorization(fake_client, monkeypatch):
    """Disabling must be immediate and must not depend on a provider."""
    _enable_both(fake_client, monkeypatch)
    admin_id = _admin(fake_client)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    assert _auto(_row(fake_client, _request_withdrawal(merchant_id, user_id, "5000")["id"])) is True

    version = resolve_effective_policy(fake_client).policy_version
    off = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": False,
            "max_amount_tzs": "100000",
            "merchant_rolling_24h_limit_tzs": "1000000",
            "version": version,
        },
    )
    assert off.status_code == 200

    after = _row(fake_client, _request_withdrawal(merchant_id, user_id, "5000")["id"])
    assert _auto(after) is False
    assert after["auto_decision_code"] == "AUTO_POLICY_DISABLED"
    assert after["status"] == "PENDING_ADMIN_APPROVAL"


# --- 12/16. What enabling and disabling do NOT do ---------------------------


def test_requests_already_awaiting_approval_are_not_drained_by_enabling(fake_client, monkeypatch):
    """Turning automation ON is not a batch approval. Rows whose decision
    was already taken keep it, and keep waiting for a human."""
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    pending = _request_withdrawal(merchant_id, user_id, "5000")
    assert pending["status"] == "PENDING_ADMIN_APPROVAL"

    response = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "100000",
            "merchant_rolling_24h_limit_tzs": "1000000",
            "version": 1,
            "confirm": True,
        },
    )
    assert response.status_code == 200

    row = _row(fake_client, pending["id"])
    assert row["status"] == "PENDING_ADMIN_APPROVAL"
    assert _auto(row) is False
    assert row["auto_decision_code"] == "AUTO_POLICY_DISABLED"


def test_switching_off_does_not_cancel_or_refund_a_submitted_payout(fake_client, monkeypatch):
    """A payout already with the provider cannot be guaranteed cancellable,
    so disabling must not touch it and must not claim to have."""
    _enable_both(fake_client, monkeypatch)
    admin_id = _admin(fake_client)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    paid = _request_withdrawal(merchant_id, user_id, "5000")
    before = dict(_row(fake_client, paid["id"]))
    assert _auto(before) is True

    ledger_entries_before = len(fake_client.table("ledger_entries")._table.rows)

    version = resolve_effective_policy(fake_client).policy_version
    response = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": False,
            "max_amount_tzs": "100000",
            "merchant_rolling_24h_limit_tzs": "1000000",
            "version": version,
        },
    )
    assert response.status_code == 200
    # Nothing in the response claims anything was cancelled.
    assert "cancel" not in response.text.lower()

    after = _row(fake_client, paid["id"])
    assert after["status"] == before["status"]
    assert _auto(after) is True
    # No reversal, no double credit.
    assert len(fake_client.table("ledger_entries")._table.rows) == ledger_entries_before


def test_an_auto_processed_payout_keeps_its_ledger_and_fee_record_when_the_policy_changes(
    fake_client, monkeypatch
):
    """The financial record is independent of the policy that authorized
    it. Rollback must restore manual approval without erasing history."""
    _enable_both(fake_client, monkeypatch)
    admin_id = _admin(fake_client)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    paid = _request_withdrawal(merchant_id, user_id, "5000")
    row = _row(fake_client, paid["id"])
    frozen = {
        "amount": row["amount"],
        "total_charges": row["total_charges"],
        "total_reserved_amount": row["total_reserved_amount"],
        "recipient_net_amount": row["recipient_net_amount"],
    }

    version = resolve_effective_policy(fake_client).policy_version
    client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": False,
            "max_amount_tzs": "100000",
            "merchant_rolling_24h_limit_tzs": "1000000",
            "version": version,
        },
    )

    after = _row(fake_client, paid["id"])
    for field, value in frozen.items():
        assert after[field] == value
    assert after["auto_policy_version"] is not None


# --- 13. No duplicate payouts ----------------------------------------------


def test_a_repeated_request_with_the_same_idempotency_key_pays_out_once(fake_client, monkeypatch):
    """Automation does not get its own idempotency story: the route's
    run_idempotent returns the stored response rather than re-running the
    handler, so a client retry after a timeout cannot produce a second
    payout."""
    _enable_both(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    key = str(uuid.uuid4())
    body = {
        "merchant_id": str(merchant_id),
        "amount": "5000",
        "destination_name": "Jane Doe",
        "destination_identifier": "+255700000000",
        "destination_code": "MPESA",
    }
    headers = {**auth_headers(user_id), "Idempotency-Key": key}

    first = client.post("/v1/disbursements/mobile-money", headers=headers, json=body)
    second = client.post("/v1/disbursements/mobile-money", headers=headers, json=body)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert len(fake_client.table("disbursements")._table.rows) == 1


# --- 18. Audit --------------------------------------------------------------


def test_a_policy_change_is_audited_with_both_versions_and_a_correlation_id(fake_client, monkeypatch):
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)

    response = client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "50000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
            "confirm": True,
        },
    )
    assert response.status_code == 200

    rows = [
        r
        for r in fake_client.table("audit_logs")._table.rows
        if r["action"] == "withdrawal_automation_policy.updated"
    ]
    assert len(rows) == 1
    entry = rows[0]
    assert entry["actor_id"] == str(admin_id)
    metadata = entry["metadata"]
    assert metadata["previous"]["version"] == 1
    assert metadata["previous"]["enabled"] is False
    assert metadata["new"]["version"] == 2
    assert metadata["new"]["enabled"] is True
    assert metadata["new"]["max_amount_tzs"] == "50000.00"
    assert metadata["confirmed"] is True
    assert uuid.UUID(metadata["correlation_id"])
    # Amounts recorded as strings, never floats.
    for section in ("previous", "new", "effective"):
        for key, value in metadata[section].items():
            if "amount" in key or "limit" in key:
                assert isinstance(value, str), f"{section}.{key} must be a string"


def test_a_refused_policy_change_is_not_audited_as_a_change(fake_client, monkeypatch):
    """An audit trail that records attempts as changes is worse than none."""
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)

    client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "500",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
            "confirm": True,
        },
    )

    rows = [
        r
        for r in fake_client.table("audit_logs")._table.rows
        if r["action"] == "withdrawal_automation_policy.updated"
    ]
    assert rows == []


def test_the_audit_record_shows_what_the_deployment_ceiling_made_of_it(fake_client, monkeypatch):
    """A policy raised past the deployment cap is a real source of
    confusion later, so the record says what actually took effect."""
    monkeypatch.setenv("AUTO_WITHDRAWAL_MAX_AMOUNT_TZS", "30000")
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)

    client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": True,
            "max_amount_tzs": "200000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
            "confirm": True,
        },
    )

    entry = next(
        r
        for r in fake_client.table("audit_logs")._table.rows
        if r["action"] == "withdrawal_automation_policy.updated"
    )
    assert entry["metadata"]["new"]["max_amount_tzs"] == "200000.00"
    assert entry["metadata"]["effective"]["max_amount_tzs"] == "30000.00"


# --- The read endpoint ------------------------------------------------------


def test_the_read_endpoint_reports_the_effective_state_not_just_the_stored_one(fake_client, monkeypatch):
    """What the portal renders. The stored switch says ON; the deployment
    override means nothing is automatic, and the page has to say that
    rather than showing a green switch."""
    monkeypatch.setenv("AUTO_WITHDRAWALS_ENABLED", "true")
    monkeypatch.setenv("REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS", "true")
    get_settings.cache_clear()
    fake_client.enable_withdrawal_automation_policy()
    admin_id = _admin(fake_client)

    data = client.get(POLICY_PATH, headers=auth_headers(admin_id)).json()["data"]

    assert data["enabled"] is True
    assert data["automation_active"] is False
    assert data["manual_only_override"] is True
    assert data["blocked_reason_code"] == "AUTO_POLICY_DISABLED"
    assert "deployment override" in data["blocked_explanation"]


def test_every_amount_is_reported_at_two_decimal_places(fake_client, monkeypatch):
    """Seen in production on the day this shipped: the portal rendered
    "TZS 500,000.0 or less may process automatically".

    PostgREST serialises a numeric column as a JSON *number*, so
    500000.00 reaches the API as the float 500000.0 - which the fake,
    storing strings, never reproduced. A trailing single zero is noise on
    the one field where mistaking 500 for 500,000 is the whole hazard, and
    a limit that renders two different ways on one screen reads as a
    rendering fault.
    """
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)
    # Exactly what PostgREST hands back for numeric(14, 2).
    row = fake_client.table("withdrawal_automation_policy")._table.rows[0]
    row["max_amount_tzs"] = 500000.0
    row["merchant_rolling_24h_limit_tzs"] = 1000000.0

    data = client.get(POLICY_PATH, headers=auth_headers(admin_id)).json()["data"]

    assert data["max_amount_tzs"] == "500000.00"
    assert data["merchant_rolling_24h_limit_tzs"] == "1000000.00"
    for field in (
        "effective_max_amount_tzs",
        "effective_rolling_24h_limit_tzs",
        "hard_max_amount_tzs",
        "hard_rolling_24h_limit_tzs",
        "platform_min_withdrawal_amount_tzs",
        "platform_max_withdrawal_amount_tzs",
        "platform_rolling_24h_limit_tzs",
    ):
        _, _, fraction = data[field].partition(".")
        assert len(fraction) == 2, f"{field} came back as {data[field]!r}, not 2 decimal places"


def test_a_float_from_the_database_never_changes_the_decision(fake_client, monkeypatch):
    """The formatting fix must not quietly move a limit. A float that came
    from numeric(14, 2) recovers exactly, so the boundary stays where it
    was: 20,000 eligible, 20,000.01 not."""
    _permit_automation(monkeypatch)
    fake_client.enable_withdrawal_automation_policy()
    row = fake_client.table("withdrawal_automation_policy")._table.rows[0]
    row["max_amount_tzs"] = 20000.0
    row["merchant_rolling_24h_limit_tzs"] = 1000000.0

    policy = resolve_effective_policy(fake_client)
    assert policy.max_amount_tzs == Decimal("20000.00")

    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    assert _auto(_row(fake_client, _request_withdrawal(merchant_id, user_id, "20000")["id"])) is True
    assert _auto(_row(fake_client, _request_withdrawal(merchant_id, user_id, "20000.01")["id"])) is False


def test_the_read_endpoint_returns_amounts_as_strings(fake_client, monkeypatch):
    """Money crosses this boundary as text. A JSON number would hand the
    browser a float and put binary rounding between an operator and a
    limit that decides whether money moves."""
    _enable_both(fake_client, monkeypatch, max_amount="12345.67")
    admin_id = _admin(fake_client)

    data = client.get(POLICY_PATH, headers=auth_headers(admin_id)).json()["data"]

    for field in (
        "max_amount_tzs",
        "merchant_rolling_24h_limit_tzs",
        "effective_max_amount_tzs",
        "effective_rolling_24h_limit_tzs",
        "hard_max_amount_tzs",
        "platform_min_withdrawal_amount_tzs",
    ):
        assert isinstance(data[field], str), f"{field} came back as {type(data[field]).__name__}"
    assert data["max_amount_tzs"] == "12345.67"


def test_the_read_endpoint_names_the_administrator_who_last_changed_it(fake_client, monkeypatch):
    _permit_automation(monkeypatch)
    admin_id = _admin(fake_client)

    client.put(
        POLICY_PATH,
        headers=auth_headers(admin_id),
        json={
            "enabled": False,
            "max_amount_tzs": "50000",
            "merchant_rolling_24h_limit_tzs": "500000",
            "version": 1,
        },
    )
    data = client.get(POLICY_PATH, headers=auth_headers(admin_id)).json()["data"]

    assert data["updated_by"] == str(admin_id)
    assert data["updated_by_email"] == "admin@infinitypay.me"
    assert data["updated_at"] is not None


def test_the_read_endpoint_exposes_no_secrets(fake_client, monkeypatch):
    _enable_both(fake_client, monkeypatch)
    admin_id = _admin(fake_client)

    body = client.get(POLICY_PATH, headers=auth_headers(admin_id)).text.lower()

    for leak in ("secret", "api_key", "sk_live", "password", "token", "selcom"):
        assert leak not in body


# --- Deploying the API before the migration --------------------------------
#
# The migration says "apply me first" and somebody will not. These pin what
# happens then, because the failure without them lands on a merchant: the
# withdrawal row is already inserted when the RPC is called, so a hard
# failure there is a 500 on a request that had already half-succeeded.


class _OldDatabaseRpc:
    """A database that predates migration 20261031010000: only the
    five-argument finalize_withdrawal_limits exists, so PostgREST refuses
    the six-argument call with PGRST202 during function resolution."""

    def __init__(self, fake_client, *, fail_all=False):
        self._fake = fake_client
        self._real = fake_client.rpc
        self.calls: list[dict] = []
        self.fail_all = fail_all

    def __call__(self, fn_name: str, params: dict | None = None):
        params = params or {}
        if fn_name == "finalize_withdrawal_limits":
            self.calls.append(dict(params))
            if self.fail_all or "p_policy_version" in params:
                error = Exception(
                    "Could not find the function public.finalize_withdrawal_limits("
                    "p_auto_daily_limit, p_auto_max, p_automation_enabled, p_daily_limit, "
                    "p_disbursement_id, p_policy_version) in the schema cache"
                )
                error.code = "PGRST202"
                raise error
            params = {k: v for k, v in params.items() if k != "p_policy_version"}
        return self._real(fn_name, params)


def test_a_withdrawal_still_works_against_a_database_without_the_migration(
    fake_client, monkeypatch
):
    """The API deployed ahead of the migration must not break withdrawals.
    It falls back to the signature that does exist, and the withdrawal is
    created and left for a human exactly as before this feature."""
    _permit_automation(monkeypatch)
    # No policy table either, which is the real shape of that database.
    fake_client.break_withdrawal_automation_policy()
    rpc = _OldDatabaseRpc(fake_client)
    monkeypatch.setattr(fake_client, "rpc", rpc)

    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    data = _request_withdrawal(merchant_id, user_id, "5000")

    assert data["status"] == "PENDING_ADMIN_APPROVAL"
    assert data["auto_approved"] is False
    # Tried the new signature, then the old one. Twice, not more.
    attempts = [c for c in rpc.calls]
    assert len(attempts) == 2
    assert "p_policy_version" in attempts[0]
    assert "p_policy_version" not in attempts[1]
    # One withdrawal, decided once.
    assert len(fake_client.table("disbursements")._table.rows) == 1


def test_the_fallback_does_not_let_automation_run_on_an_unmigrated_database(
    fake_client, monkeypatch
):
    """Falling back must not become a way to auto-process without the
    policy. Without the table there is no policy to enable, so the call is
    made with automation off."""
    _permit_automation(monkeypatch)
    fake_client.break_withdrawal_automation_policy()
    rpc = _OldDatabaseRpc(fake_client)
    monkeypatch.setattr(fake_client, "rpc", rpc)

    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    row = _row(fake_client, _request_withdrawal(merchant_id, user_id, "5000")["id"])

    assert _auto(row) is False
    for attempt in rpc.calls:
        assert attempt["p_automation_enabled"] is False


def test_any_other_rpc_failure_is_never_retried(fake_client, monkeypatch):
    """The retry is safe only because PGRST202 happens before anything
    executes. A failure that could have run must be raised, not repeated -
    repeating it could decide the same row twice."""
    _enable_both(fake_client, monkeypatch)

    calls: list[dict] = []
    real_rpc = fake_client.rpc

    def exploding_rpc(fn_name: str, params: dict | None = None):
        if fn_name == "finalize_withdrawal_limits":
            calls.append(dict(params or {}))
            error = Exception("deadlock detected")
            error.code = "40P01"
            raise error
        return real_rpc(fn_name, params or {})

    monkeypatch.setattr(fake_client, "rpc", exploding_rpc)

    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    with pytest.raises(Exception, match="deadlock"):
        client.post(
            "/v1/disbursements/mobile-money",
            headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
            json={
                "merchant_id": str(merchant_id),
                "amount": "5000",
                "destination_name": "Jane Doe",
                "destination_identifier": "+255700000000",
                "destination_code": "MPESA",
            },
        )

    assert len(calls) == 1, "a failure that may have executed must not be retried"


def test_a_missing_function_entirely_is_not_swallowed(fake_client, monkeypatch):
    """If neither signature exists the error must surface. Silently
    continuing would mean a withdrawal that skipped the limit check."""
    _enable_both(fake_client, monkeypatch)
    rpc = _OldDatabaseRpc(fake_client, fail_all=True)
    monkeypatch.setattr(fake_client, "rpc", rpc)

    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "900000")

    with pytest.raises(Exception, match="Could not find the function"):
        client.post(
            "/v1/disbursements/mobile-money",
            headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
            json={
                "merchant_id": str(merchant_id),
                "amount": "5000",
                "destination_name": "Jane Doe",
                "destination_identifier": "+255700000000",
                "destination_code": "MPESA",
            },
        )

    # Tried both signatures, then gave up rather than continuing without a
    # limit check.
    assert len(rpc.calls) == 2
