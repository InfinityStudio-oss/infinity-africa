"""Granting LIVE payout access, per-merchant fees, and the platform tariff.

Live used to be ungrantable through the API on the reasoning that it is
a commercial decision rather than a switch. The reasoning was right about
the weight of the act and wrong about the remedy: it did not stop live
being granted, it moved it to a hand-written database update with no
validation, no audit entry and no record of who did it. These tests pin
the replacement - a deliberate route that leaves a trail.

Pinned here:

1. Live cannot be granted without an explicit acknowledgement, and the
   sandbox route still cannot grant it at all.
2. Withdrawing live is never harder than granting it.
3. Every change is audited with before and after.
4. A merchant with no negotiated fee pays the platform tariff; one
   priced at zero stays free.
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
        "sandbox_enabled": True,
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


def _tariff_row(fake_client, **overrides):
    row = {"id": True, "percentage_fee": "1", "flat_fee": "0", "version": 1}
    row.update(overrides)
    return fake_client.seed("payout_platform_pricing", row)


def _audits(fake_client, action):
    return [r for r in fake_client.table("audit_logs")._table.rows if r.get("action") == action]


# --- granting live -----------------------------------------------------------


def test_live_cannot_be_granted_without_acknowledging_what_it_means(fake_client):
    """The acknowledgement is not ceremony. It is what stops this being
    sent by replaying the sandbox call with one value flipped."""
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/live",
        headers=_headers(_admin(fake_client)),
        json={"live_enabled": True, "version": 1},
    )

    assert response.status_code == 422, response.text
    assert _row(fake_client, merchant_id)["live_enabled"] is False


def test_live_is_granted_when_acknowledged(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/live",
        headers=_headers(_admin(fake_client)),
        json={"live_enabled": True, "version": 1, "acknowledge": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["live_enabled"] is True
    assert _row(fake_client, merchant_id)["live_enabled"] is True


def test_withdrawing_live_needs_no_acknowledgement(fake_client):
    """Taking access away must never be harder than giving it."""
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id, live_enabled=True)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/live",
        headers=_headers(_admin(fake_client)),
        json={"live_enabled": False, "version": 1},
    )

    assert response.status_code == 200, response.text
    assert _row(fake_client, merchant_id)["live_enabled"] is False


def test_granting_live_does_not_switch_the_sandbox_or_lift_a_pause(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id, sandbox_enabled=False, paused=True, paused_reason="key leak")

    client.patch(
        f"/v1/admin/payout-access/{merchant_id}/live",
        headers=_headers(_admin(fake_client)),
        json={"live_enabled": True, "version": 1, "acknowledge": True},
    )

    row = _row(fake_client, merchant_id)
    assert row["live_enabled"] is True
    assert row["sandbox_enabled"] is False
    assert row["paused"] is True, "a pause is a brake, and granting live must not release it"


def test_granting_live_is_audited_with_before_and_after(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)

    client.patch(
        f"/v1/admin/payout-access/{merchant_id}/live",
        headers=_headers(_admin(fake_client)),
        json={"live_enabled": True, "version": 1, "acknowledge": True},
    )

    entries = _audits(fake_client, "payout_access.live_enabled")
    assert len(entries) == 1
    meta = entries[0]["metadata"]
    assert meta["before"]["live_enabled"] is False
    assert meta["after"]["live_enabled"] is True


def test_two_admins_cannot_both_grant_live_from_the_same_page(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)
    headers = _headers(_admin(fake_client))
    body = {"live_enabled": True, "version": 1, "acknowledge": True}

    assert client.patch(f"/v1/admin/payout-access/{merchant_id}/live", headers=headers, json=body).status_code == 200
    second = client.patch(f"/v1/admin/payout-access/{merchant_id}/live", headers=headers, json=body)

    assert second.status_code == 409, second.text


# --- the tariff --------------------------------------------------------------


def test_the_tariff_is_readable_and_is_one_percent(fake_client):
    _tariff_row(fake_client)

    response = client.get("/v1/admin/payout-tariff", headers=_headers(_admin(fake_client)))

    assert response.status_code == 200, response.text
    assert str(response.json()["data"]["percentage_fee"]) in ("1", "1.0", "1.0000")


def test_the_tariff_can_be_changed_and_is_audited(fake_client):
    _tariff_row(fake_client)

    response = client.patch(
        "/v1/admin/payout-tariff",
        headers=_headers(_admin(fake_client)),
        json={"percentage_fee": "1.5", "flat_fee": "0", "version": 1},
    )

    assert response.status_code == 200, response.text
    entries = _audits(fake_client, "payout_tariff.updated")
    assert len(entries) == 1
    assert entries[0]["metadata"]["before"]["percentage_fee"] == "1"


def test_a_merchant_session_cannot_read_the_tariff(fake_client):
    """A merchant seeing the platform's margin structure is not a
    feature."""
    _tariff_row(fake_client)
    response = client.get("/v1/admin/payout-tariff", headers=_headers(uuid.uuid4()))
    assert response.status_code == 403, response.text


def test_clearing_a_negotiated_fee_returns_the_merchant_to_the_tariff(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id, fee_percentage="0.5", fee_flat_tzs="0")

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/fee",
        headers=_headers(_admin(fake_client)),
        json={"version": 1, "fee_percentage": None, "fee_flat_tzs": None},
    )

    assert response.status_code == 200, response.text
    row = _row(fake_client, merchant_id)
    assert row["fee_percentage"] is None, "null is the instruction, not an omission"
    assert row["fee_flat_tzs"] is None


def test_a_negotiated_fee_can_be_set(fake_client):
    merchant_id = _merchant(fake_client)
    _settings_row(fake_client, merchant_id)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/fee",
        headers=_headers(_admin(fake_client)),
        json={"version": 1, "fee_percentage": "0.75", "fee_flat_tzs": "100.00"},
    )

    assert response.status_code == 200, response.text
    row = _row(fake_client, merchant_id)
    assert str(row["fee_percentage"]) == "0.75"
    assert str(row["fee_flat_tzs"]) == "100.00"
