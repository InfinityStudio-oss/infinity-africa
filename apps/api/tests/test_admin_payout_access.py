"""Super Admin control over who may use the Disbursement API.

This is the screen that decides which merchants can move money through
an API key with no person approving each call, so the tests are mostly
about who may touch it and whether the record of a change survives.

Pinned here:

1. Only a Super Admin with a second factor reaches any of it. A merchant
   admin cannot, and an API key cannot.
2. Live access cannot be granted from this screen at all - the write
   schemas refuse the field rather than ignoring it.
3. Every write is audited with before AND after values.
4. Two administrators cannot silently overwrite each other.
5. Pausing stops new payouts and does not disturb reserved funds.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_api_key,
    make_merchant_member,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _admin(fake_client):
    user_id = uuid.uuid4()
    make_super_admin(fake_client, user_id)
    return user_id


def _headers(user_id):
    return auth_headers(user_id, aal="aal2")


def _merchant(fake_client):
    return uuid.UUID(create_merchant(fake_client)["id"])


def _settings_row(fake_client, merchant_id, **overrides):
    row = {
        "merchant_id": str(merchant_id),
        "sandbox_enabled": False,
        "live_enabled": False,
        "paused": False,
        "version": 1,
    }
    row.update(overrides)
    return fake_client.seed("merchant_payout_settings", row)


def _row(fake_client, merchant_id):
    return next(
        r
        for r in fake_client.table("merchant_payout_settings")._table.rows
        if r["merchant_id"] == str(merchant_id)
    )


def _audits(fake_client, action=None):
    rows = fake_client.table("audit_logs")._table.rows
    return [r for r in rows if action is None or r.get("action") == action]


# --- who may reach this screen -----------------------------------------------


def test_a_merchant_admin_cannot_reach_the_admin_screen(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")

    response = client.get("/v1/admin/payout-access", headers=_headers(user_id))

    assert response.status_code == 403, response.text


def test_an_api_key_cannot_reach_the_admin_screen(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)
    raw_key, _row = make_api_key(
        fake_client, merchant_id, scopes=["payouts:read"], key_type="payout"
    )

    response = client.get("/v1/admin/payout-access", headers={"X-API-Key": raw_key})

    assert response.status_code in (401, 403), response.text


def test_a_super_admin_without_the_second_factor_is_refused(fake_client):
    """require_super_admin enforces aal2 on every /v1/admin call, reads
    included. A money control is exactly what that is for."""
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)
    admin_id = _admin(fake_client)

    response = client.get("/v1/admin/payout-access", headers=auth_headers(admin_id))

    assert response.status_code == 403, response.text


def test_a_super_admin_with_mfa_can_read(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)
    admin_id = _admin(fake_client)

    response = client.get("/v1/admin/payout-access", headers=_headers(admin_id))

    assert response.status_code == 200, response.text
    assert len(response.json()["data"]) == 1


@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("patch", "/sandbox", {"sandbox_enabled": True, "version": 1}),
        ("patch", "/pause", {"paused": True, "version": 1, "reason": "Suspected leak"}),
        ("post", "", None),
    ],
)
def test_every_write_needs_a_super_admin(fake_client, method, suffix, body):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)
    outsider = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, outsider, "MERCHANT_ADMIN")

    kwargs = {"headers": _headers(outsider)}
    if body is not None:
        kwargs["json"] = body
    response = getattr(client, method)(f"/v1/admin/payout-access/{merchant_id}{suffix}", **kwargs)

    assert response.status_code == 403, response.text


# --- live access cannot be granted here --------------------------------------


def test_live_access_cannot_be_granted_from_this_screen(fake_client):
    """Refused, not ignored. An operator who sends live_enabled and gets
    a 200 would reasonably believe live payouts are on."""
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)
    admin_id = _admin(fake_client)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/sandbox",
        headers=_headers(admin_id),
        json={"sandbox_enabled": True, "live_enabled": True, "version": 1},
    )

    assert response.status_code == 422, response.text
    assert _row(fake_client, merchant_id)["live_enabled"] is False


def test_enabling_the_sandbox_leaves_live_off(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)
    admin_id = _admin(fake_client)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/sandbox",
        headers=_headers(admin_id),
        json={"sandbox_enabled": True, "version": 1},
    )

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["sandbox_enabled"] is True
    # `enabled` is derived from the two environment flags, not stored.
    assert body["enabled"] is True
    assert body["live_enabled"] is False


def test_a_new_settings_row_starts_with_everything_off(fake_client):
    """Creating the row makes a merchant visible on this screen. It is
    not itself a grant."""
    merchant_id = _merchant(fake_client)
    admin_id = _admin(fake_client)

    response = client.post(
        f"/v1/admin/payout-access/{merchant_id}", headers=_headers(admin_id)
    )

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["enabled"] is False
    assert body["sandbox_enabled"] is False
    assert body["live_enabled"] is False
    assert body["paused"] is False


def test_creating_twice_is_a_conflict(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)
    admin_id = _admin(fake_client)

    response = client.post(
        f"/v1/admin/payout-access/{merchant_id}", headers=_headers(admin_id)
    )

    assert response.status_code == 409, response.text


# --- the audit trail ---------------------------------------------------------


def test_enabling_the_sandbox_is_audited_with_before_and_after(fake_client):
    """"enabled: true" on its own does not say whether this call changed
    anything. The before value is what makes the entry answerable."""
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)
    admin_id = _admin(fake_client)

    client.patch(
        f"/v1/admin/payout-access/{merchant_id}/sandbox",
        headers=_headers(admin_id),
        json={"sandbox_enabled": True, "version": 1},
    )

    entries = _audits(fake_client, "payout_access.sandbox_enabled")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["actor_id"] == str(admin_id)
    assert entry["merchant_id"] == str(merchant_id)
    assert entry["metadata"]["before"]["sandbox_enabled"] is False
    assert entry["metadata"]["after"]["sandbox_enabled"] is True


def test_disabling_the_sandbox_is_audited_separately(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id, sandbox_enabled=True)
    admin_id = _admin(fake_client)

    client.patch(
        f"/v1/admin/payout-access/{merchant_id}/sandbox",
        headers=_headers(admin_id),
        json={"sandbox_enabled": False, "version": 1},
    )

    assert len(_audits(fake_client, "payout_access.sandbox_disabled")) == 1
    assert _row(fake_client, merchant_id)["sandbox_enabled"] is False


def test_pausing_and_resuming_are_both_audited(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id, sandbox_enabled=True)
    admin_id = _admin(fake_client)

    client.patch(
        f"/v1/admin/payout-access/{merchant_id}/pause",
        headers=_headers(admin_id),
        json={"paused": True, "version": 1, "reason": "Suspected key leak"},
    )
    version = _row(fake_client, merchant_id)["version"]
    client.patch(
        f"/v1/admin/payout-access/{merchant_id}/pause",
        headers=_headers(admin_id),
        json={"paused": False, "version": version},
    )

    assert len(_audits(fake_client, "payout_access.paused")) == 1
    assert len(_audits(fake_client, "payout_access.resumed")) == 1
    assert _row(fake_client, merchant_id)["paused"] is False
    assert _row(fake_client, merchant_id)["paused_reason"] is None


def test_the_audit_metadata_is_json_serialisable(fake_client):
    """A Decimal in audit metadata fails the insert, and a failed audit
    on a money control is worse than a clumsy type."""
    import json

    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)
    admin_id = _admin(fake_client)

    client.patch(
        f"/v1/admin/payout-access/{merchant_id}/sandbox",
        headers=_headers(admin_id),
        json={"sandbox_enabled": True, "version": 1, "daily_limit_tzs": "250000.50"},
    )

    entry = _audits(fake_client, "payout_access.sandbox_enabled")[0]
    json.dumps(entry["metadata"])  # must not raise
    assert entry["metadata"]["after"]["daily_limit_tzs"] == "250000.50"


# --- pausing requires a reason, and does not recall funds --------------------


def test_pausing_without_a_reason_is_refused(fake_client):
    """A pause nobody can explain is one the next operator cannot safely
    lift, and the merchant is shown this text."""
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id, sandbox_enabled=True)
    admin_id = _admin(fake_client)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/pause",
        headers=_headers(admin_id),
        json={"paused": True, "version": 1},
    )

    assert response.status_code == 422, response.text
    assert _row(fake_client, merchant_id)["paused"] is False


def test_resuming_needs_no_reason(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(
        fake_client, merchant_id, sandbox_enabled=True, paused=True, paused_reason="x"
    )
    admin_id = _admin(fake_client)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/pause",
        headers=_headers(admin_id),
        json={"paused": False, "version": 1},
    )

    assert response.status_code == 200, response.text


def test_pausing_leaves_reserved_funds_alone(fake_client):
    """Pause stops new payouts. Abandoning an in-flight one is how a
    payout ends up paid and unaccounted for, so the reserve is
    untouched - and the screen reports it so an operator can see what is
    still committed."""
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id, sandbox_enabled=True)
    for purpose, balance in (("payout_available", "10000.00"), ("payout_reserved", "51500.00")):
        fake_client.seed(
            "ledger_accounts",
            {
                "merchant_id": str(merchant_id),
                "name": purpose,
                "account_type": "liability",
                "purpose": purpose,
                "currency": "TZS",
                "environment": "sandbox",
                "balance": balance,
            },
        )
    admin_id = _admin(fake_client)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/pause",
        headers=_headers(admin_id),
        json={"paused": True, "version": 1, "reason": "Runaway integration"},
    )

    body = response.json()["data"]
    assert Decimal(body["wallet_reserved"]) == Decimal("51500.00")
    assert Decimal(body["wallet_available"]) == Decimal("10000.00")


# --- two administrators ------------------------------------------------------


def test_a_stale_version_is_refused(fake_client):
    """Both operators loaded version 1. The second must be told to
    re-read rather than quietly undoing the first."""
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)
    admin_id = _admin(fake_client)

    first = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/sandbox",
        headers=_headers(admin_id),
        json={"sandbox_enabled": True, "version": 1},
    )
    second = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/sandbox",
        headers=_headers(admin_id),
        json={"sandbox_enabled": False, "version": 1},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert _row(fake_client, merchant_id)["sandbox_enabled"] is True


def test_the_version_is_required(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)
    admin_id = _admin(fake_client)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/sandbox",
        headers=_headers(admin_id),
        json={"sandbox_enabled": True},
    )

    assert response.status_code == 422, response.text


def test_a_merchant_with_no_settings_row_is_a_404(fake_client):
    merchant_id = _merchant(fake_client)
    admin_id = _admin(fake_client)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/sandbox",
        headers=_headers(admin_id),
        json={"sandbox_enabled": True, "version": 1},
    )

    assert response.status_code == 404, response.text


# --- the control actually binds the API --------------------------------------


def test_pausing_stops_the_partner_api_creating_payouts(fake_client):
    """The screen is only worth having if the switch reaches the money
    path. This drives the admin control and then the partner API."""
    merchant_id = _merchant(fake_client)
    _settings_row(
        fake_client, merchant_id, sandbox_enabled=True, daily_limit_tzs="1000000.00"
    )
    beneficiary_id = fake_client.seed(
        "payout_beneficiaries",
        {
            "merchant_id": str(merchant_id),
            "environment": "sandbox",
            "name": "Recipient",
            "method": "MOBILE_MONEY",
            "destination_code": "MPESA",
            "destination_identifier": "255700000000",
            "status": "active",
        },
    )["id"]
    for purpose, balance in (("payout_available", "100000.00"), ("payout_reserved", "0")):
        fake_client.seed(
            "ledger_accounts",
            {
                "merchant_id": str(merchant_id),
                "name": purpose,
                "account_type": "liability",
                "purpose": purpose,
                "currency": "TZS",
                "environment": "sandbox",
                "balance": balance,
            },
        )
    raw_key, _key = make_api_key(
        fake_client,
        merchant_id,
        scopes=["payouts:create", "payouts:read"],
        key_type="payout",
        environment="sandbox",
    )
    admin_id = _admin(fake_client)

    before = client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json={"beneficiary_id": str(beneficiary_id), "amount": "1000.00"},
    )
    assert before.status_code == 201, before.text

    client.patch(
        f"/v1/admin/payout-access/{merchant_id}/pause",
        headers=_headers(admin_id),
        json={"paused": True, "version": 1, "reason": "Suspected key leak"},
    )

    after = client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json={"beneficiary_id": str(beneficiary_id), "amount": "1000.00"},
    )

    assert after.status_code == 409, after.text
    assert "paused" in after.json()["error"]["message"].lower()


def test_disabling_the_sandbox_stops_the_partner_api(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id, sandbox_enabled=True)
    beneficiary_id = fake_client.seed(
        "payout_beneficiaries",
        {
            "merchant_id": str(merchant_id),
            "environment": "sandbox",
            "name": "Recipient",
            "method": "MOBILE_MONEY",
            "destination_code": "MPESA",
            "destination_identifier": "255700000000",
            "status": "active",
        },
    )["id"]
    raw_key, _key = make_api_key(
        fake_client,
        merchant_id,
        scopes=["payouts:create", "payouts:read"],
        key_type="payout",
        environment="sandbox",
    )
    admin_id = _admin(fake_client)

    client.patch(
        f"/v1/admin/payout-access/{merchant_id}/sandbox",
        headers=_headers(admin_id),
        json={"sandbox_enabled": False, "version": 1},
    )

    response = client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json={"beneficiary_id": str(beneficiary_id), "amount": "1000.00"},
    )

    assert response.status_code >= 400, response.text
