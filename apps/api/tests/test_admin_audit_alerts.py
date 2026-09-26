"""Audit + alert coverage on the sensitive admin surfaces.

Checks the wiring at the endpoints themselves, not just the alert helper:
the helper being correct is worthless if a router forgets to call it.
"""

import uuid

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import security_alerts
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("SECURITY_ALERTS_ENABLED", "true")
    monkeypatch.setenv("SECURITY_ALERT_EMAIL", "security@infinitypay.me")
    get_settings.cache_clear()
    security_alerts._deduper = security_alerts._AlertDeduper()
    yield
    get_settings.cache_clear()


@pytest.fixture
def sent(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(
        resend.Emails, "send", lambda params: captured.append(params) or {"id": "resend-test-id"}
    )
    return captured


def _admin(fake_client) -> uuid.UUID:
    user_id = uuid.uuid4()
    make_super_admin(fake_client, user_id)
    return user_id


def _audit_actions(fake_client) -> list[str]:
    return [r["action"] for r in fake_client.table("audit_logs")._table.rows]


def _subjects(sent) -> list[str]:
    return [m["subject"] for m in sent]


# --- pricing: previously had no audit trail at all ----------------------


def test_creating_a_platform_pricing_rule_is_audited_and_alerted(fake_client, sent):
    admin = _admin(fake_client)

    response = client.post(
        "/v1/admin/pricing-rules/platform-fallback",
        headers=auth_headers(admin),
        json={"method": "SELCOM_PESA", "percentage_fee": "1.5", "flat_fee": "0"},
    )

    assert response.status_code in (200, 201), response.text
    assert "pricing_rule.created" in _audit_actions(fake_client)
    assert any("Platform pricing rule created" in s for s in _subjects(sent))


def test_deactivating_a_pricing_rule_is_audited_and_alerted(fake_client, sent):
    admin = _admin(fake_client)
    created = client.post(
        "/v1/admin/pricing-rules/platform-fallback",
        headers=auth_headers(admin),
        json={"method": "SELCOM_PESA", "percentage_fee": "1.5", "flat_fee": "0"},
    ).json()["data"]
    sent.clear()

    response = client.post(
        f"/v1/admin/pricing-rules/{created['id']}/deactivate", headers=auth_headers(admin)
    )

    assert response.status_code == 200, response.text
    assert "pricing_rule.deactivated" in _audit_actions(fake_client)
    assert any("Pricing rule deactivated" in s for s in _subjects(sent))


def test_a_pricing_alert_names_the_business_it_applies_to(fake_client, sent):
    admin = _admin(fake_client)
    merchant = create_merchant(fake_client)

    client.post(
        f"/v1/admin/merchants/{merchant['id']}/pricing-rules",
        headers=auth_headers(admin),
        json={"method": "SELCOM_PESA", "percentage_fee": "2.0", "flat_fee": "0"},
    )

    assert merchant["business_name"] in sent[0]["html"]


# --- denials -------------------------------------------------------------


def test_a_merchant_reaching_an_admin_route_is_audited_and_alerted(fake_client, sent):
    """The realistic probe: a genuine customer session pointed at the
    platform surface."""
    merchant = create_merchant(fake_client)
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), user_id, "MERCHANT_ADMIN")

    response = client.get("/v1/admin/merchants", headers=auth_headers(user_id))

    assert response.status_code == 403
    assert "super_admin.access_denied" in _audit_actions(fake_client)
    assert any("Non-admin attempted platform admin access" in s for s in _subjects(sent))


def test_repeated_probes_by_one_actor_alert_once(fake_client, sent):
    merchant = create_merchant(fake_client)
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), user_id, "MERCHANT_ADMIN")

    for _ in range(4):
        client.get("/v1/admin/merchants", headers=auth_headers(user_id))

    # Every attempt audited; one email.
    assert _audit_actions(fake_client).count("super_admin.access_denied") == 4
    assert len(sent) == 1


def test_an_admin_blocked_for_missing_mfa_is_audited_and_alerted(fake_client, sent, monkeypatch):
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "true")
    get_settings.cache_clear()
    admin = _admin(fake_client)

    response = client.get("/v1/admin/merchants", headers=auth_headers(admin, aal="aal1"))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "mfa_required"
    assert "super_admin.mfa.required_block" in _audit_actions(fake_client)
    assert any("second factor missing" in s for s in _subjects(sent))


# --- the alert must never break the action ------------------------------


def test_a_failing_alert_does_not_fail_the_pricing_change(fake_client, monkeypatch):
    """The rule was created. A broken notification about it must not turn a
    successful change into an error the admin sees."""
    def _boom(params):
        raise RuntimeError("email provider exploded")

    monkeypatch.setattr(resend.Emails, "send", _boom)
    admin = _admin(fake_client)

    response = client.post(
        "/v1/admin/pricing-rules/platform-fallback",
        headers=auth_headers(admin),
        json={"method": "SELCOM_PESA", "percentage_fee": "1.5", "flat_fee": "0"},
    )

    assert response.status_code in (200, 201), response.text
    assert "pricing_rule.created" in _audit_actions(fake_client)


def test_disabling_alerts_keeps_the_audit_trail(fake_client, sent, monkeypatch):
    """The audit log is the record; alerts are only the interruption. Muting
    one must never mute the other."""
    monkeypatch.setenv("SECURITY_ALERTS_ENABLED", "false")
    get_settings.cache_clear()
    admin = _admin(fake_client)

    client.post(
        "/v1/admin/pricing-rules/platform-fallback",
        headers=auth_headers(admin),
        json={"method": "SELCOM_PESA", "percentage_fee": "1.5", "flat_fee": "0"},
    )

    assert "pricing_rule.created" in _audit_actions(fake_client)
    assert sent == []
