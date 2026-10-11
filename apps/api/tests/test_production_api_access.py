"""Self-service production (`live`) API key creation. Business decision
(amended 2026-08-26): production keys are self-service — no per-key or
per-merchant Super Admin approval — once a merchant is approved, KYC-
verified, has a resolvable pricing rule, and isn't API-access-suspended.
Sandbox keys are never gated (except by suspension). See
app/services/api_access.py.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    create_pricing_rule,
    make_api_key,
    make_merchant_member,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _merchant_admin(fake_client, **merchant_overrides):
    merchant = create_merchant(fake_client, **merchant_overrides)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    return merchant, merchant_id, user_id


def _approved_merchant_with_pricing(fake_client, **merchant_overrides):
    merchant, merchant_id, user_id = _merchant_admin(
        fake_client, status="active", kyc_status="verified", **merchant_overrides
    )
    create_pricing_rule(fake_client, merchant_id=merchant_id)
    return merchant, merchant_id, user_id


def test_sandbox_key_creation_blocked_for_unapproved_merchant(fake_client):
    """Pending/unapproved merchants can't mint ANY API key (sandbox or
    live) — see app/services/merchant_gate.py::require_approved_merchant,
    applied in create_my_api_key before the environment split."""
    _merchant, _merchant_id, user_id = _merchant_admin(fake_client, status="pending", kyc_status="unverified")

    response = client.post(
        "/v1/merchant/api-keys",
        headers=auth_headers(user_id),
        json={"name": "Sandbox key", "environment": "sandbox", "scopes": ["collections:write"]},
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "merchant_not_approved"
    assert fake_client.table("api_keys")._table.rows == []


def test_live_key_creation_blocked_for_unapproved_merchant(fake_client):
    """An unapproved merchant is stopped at the require_approved_merchant
    gate (which runs before the environment split), so a live-key request
    fails the same way a sandbox one does — merchant_not_approved."""
    _merchant, _merchant_id, user_id = _merchant_admin(fake_client, status="pending", kyc_status="unverified")

    response = client.post(
        "/v1/merchant/api-keys",
        headers=auth_headers(user_id),
        json={"name": "Live key", "environment": "live", "scopes": ["collections:write"]},
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "merchant_not_approved"


def test_live_key_creation_blocked_when_approved_but_no_pricing_rule_resolves(fake_client):
    """status=active + kyc_status=verified alone isn't enough — a pricing
    rule (merchant-specific or platform fallback) must also resolve. No
    Super Admin toggle exists anymore; this is the one remaining automatic
    check beyond approval/KYC."""
    _merchant, _merchant_id, user_id = _merchant_admin(fake_client, status="active", kyc_status="verified")

    response = client.post(
        "/v1/merchant/api-keys",
        headers=auth_headers(user_id),
        json={"name": "Live key", "environment": "live", "scopes": ["collections:write"]},
    )
    assert response.status_code == 403, response.text


def test_live_key_creation_succeeds_self_service_once_approved_verified_and_priced(fake_client):
    """No Super Admin action of any kind is required here — this is the
    core self-service behavior change."""
    _merchant, _merchant_id, user_id = _approved_merchant_with_pricing(fake_client)

    response = client.post(
        "/v1/merchant/api-keys",
        headers=auth_headers(user_id),
        json={"name": "Live key", "environment": "live", "scopes": ["collections:write"]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["environment"] == "live"


def test_live_key_creation_succeeds_via_platform_fallback_pricing_rule(fake_client):
    _merchant, _merchant_id, user_id = _merchant_admin(fake_client, status="active", kyc_status="verified")
    create_pricing_rule(fake_client, merchant_id=None)  # platform fallback, no merchant-specific rule

    response = client.post(
        "/v1/merchant/api-keys",
        headers=auth_headers(user_id),
        json={"name": "Live key", "environment": "live", "scopes": ["collections:write"]},
    )
    assert response.status_code == 201, response.text


def test_rotating_a_live_key_re_checks_eligibility(fake_client):
    _merchant, merchant_id, user_id = _approved_merchant_with_pricing(fake_client)
    _raw_key, key_row = make_api_key(fake_client, merchant_id, environment="live")

    # Eligibility revoked after the key already existed.
    fake_client.table("merchants").update({"status": "suspended"}).eq("id", str(merchant_id)).execute()

    response = client.post(f"/v1/merchant/api-keys/{key_row['id']}/rotate", headers=auth_headers(user_id))
    assert response.status_code == 403, response.text


def test_suspended_merchant_cannot_self_service_a_sandbox_or_live_key(fake_client):
    _merchant, _merchant_id, user_id = _approved_merchant_with_pricing(fake_client, api_access_suspended=True)

    for environment in ("sandbox", "live"):
        response = client.post(
            "/v1/merchant/api-keys",
            headers=auth_headers(user_id),
            json={"name": f"{environment} key", "environment": environment, "scopes": ["collections:write"]},
        )
        assert response.status_code == 403, response.text


def test_super_admin_suspend_blocks_further_self_service_key_creation(fake_client):
    _merchant, merchant_id, user_id = _approved_merchant_with_pricing(fake_client)
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    suspend_response = client.post(
        f"/v1/admin/merchants/{merchant_id}/api-access/suspend", headers=auth_headers(admin_id)
    )
    assert suspend_response.status_code == 200, suspend_response.text
    assert suspend_response.json()["data"]["api_access_suspended"] is True

    create_response = client.post(
        "/v1/merchant/api-keys",
        headers=auth_headers(user_id),
        json={"name": "Live key", "environment": "live", "scopes": ["collections:write"]},
    )
    assert create_response.status_code == 403, create_response.text


def test_super_admin_reinstate_restores_self_service_key_creation(fake_client):
    _merchant, merchant_id, user_id = _approved_merchant_with_pricing(fake_client, api_access_suspended=True)
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    reinstate_response = client.post(
        f"/v1/admin/merchants/{merchant_id}/api-access/reinstate", headers=auth_headers(admin_id)
    )
    assert reinstate_response.status_code == 200, reinstate_response.text
    assert reinstate_response.json()["data"]["api_access_suspended"] is False

    create_response = client.post(
        "/v1/merchant/api-keys",
        headers=auth_headers(user_id),
        json={"name": "Live key", "environment": "live", "scopes": ["collections:write"]},
    )
    assert create_response.status_code == 201, create_response.text


def test_only_super_admin_can_suspend_api_access(fake_client):
    _merchant, merchant_id, _user_id = _merchant_admin(fake_client)
    response = client.post(
        f"/v1/admin/merchants/{merchant_id}/api-access/suspend", headers=auth_headers(uuid.uuid4())
    )
    assert response.status_code == 403


def test_admin_merchant_response_reports_computed_production_eligibility(fake_client):
    _merchant, merchant_id, _user_id = _approved_merchant_with_pricing(fake_client)
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    response = client.get(f"/v1/admin/merchants/{merchant_id}", headers=auth_headers(admin_id))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["production_api_eligible"] is True


def _wallet_push_with_key(raw_key: str, merchant_id):
    """The Direct Wallet Push route partners integrate against - the one
    path that actually takes a customer's money."""
    return client.post(
        "/v1/collections/wallet-push",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "5000",
            "phone": "255744000001",
            "currency": "TZS",
        },
    )


def test_a_suspended_merchants_api_key_stops_collecting(fake_client):
    """Suspension has to mean suspended everywhere.

    Until 2026-10-11 the API-key path checked only api_access_suspended,
    never merchants.status. So a merchant a Super Admin had suspended was
    refused by the portal and by every session route, while the one route
    that moves customers' money kept working for them.
    """
    _merchant, merchant_id, _user_id = _approved_merchant_with_pricing(fake_client)
    raw_key, _ = make_api_key(fake_client, merchant_id)

    # Works while the account is active.
    assert _wallet_push_with_key(raw_key, merchant_id).status_code != 403

    fake_client.table("merchants").update({"status": "suspended"}).eq(
        "id", str(merchant_id)
    ).execute()

    response = _wallet_push_with_key(raw_key, merchant_id)
    assert response.status_code == 403, response.text
    assert "not active" in response.text


def test_a_closed_merchants_api_key_stops_collecting(fake_client):
    """'closed' is not 'active' either - the check is on being active, not
    on being any particular flavour of stopped."""
    _merchant, merchant_id, _user_id = _approved_merchant_with_pricing(fake_client)
    raw_key, _ = make_api_key(fake_client, merchant_id)
    fake_client.table("merchants").update({"status": "closed"}).eq("id", str(merchant_id)).execute()

    assert _wallet_push_with_key(raw_key, merchant_id).status_code == 403


def test_an_active_merchants_api_key_is_untouched(fake_client):
    """The guard must not cost a working integration. 23 merchants held a
    live key when this shipped and every one was active."""
    _merchant, merchant_id, _user_id = _approved_merchant_with_pricing(fake_client)
    raw_key, _ = make_api_key(fake_client, merchant_id)

    assert _wallet_push_with_key(raw_key, merchant_id).status_code != 403


# --- Suspension ends the portal session too ----------------------------------


def test_a_suspended_merchant_loses_the_whole_portal(fake_client):
    """get_own_merchant refuses a suspended business, so every
    /v1/merchant/* route goes with it.

    Before 2026-10-11 the only gate was require_approved_merchant on the
    write paths: a suspended merchant still had a working dashboard, and
    only the buttons failed. The account-level decision has to end the
    session, not just the actions.
    """
    _merchant, merchant_id, user_id = _approved_merchant_with_pricing(fake_client)

    assert client.get("/v1/merchant/api-keys", headers=auth_headers(user_id)).status_code == 200

    fake_client.table("merchants").update({"status": "suspended"}).eq(
        "id", str(merchant_id)
    ).execute()

    response = client.get("/v1/merchant/api-keys", headers=auth_headers(user_id))
    assert response.status_code == 403, response.text
    assert "suspended" in response.text


def test_a_closed_merchant_loses_the_whole_portal(fake_client):
    _merchant, merchant_id, user_id = _approved_merchant_with_pricing(fake_client)
    fake_client.table("merchants").update({"status": "closed"}).eq("id", str(merchant_id)).execute()

    assert client.get("/v1/merchant/api-keys", headers=auth_headers(user_id)).status_code == 403


def test_a_pending_merchant_keeps_the_portal(fake_client):
    """The one status deliberately left through. A business waiting for
    review uses this same surface to see where its application stands, so
    blocking 'pending' here would lock every new signup out of the portal
    the moment they finished signing up.

    403 would be this guard; 200 is the route answering normally for a
    merchant that simply has no keys yet.
    """
    _merchant, _merchant_id, user_id = _merchant_admin(
        fake_client, status="pending", kyc_status="unverified"
    )

    response = client.get("/v1/merchant/api-keys", headers=auth_headers(user_id))
    assert response.status_code == 200, response.text
