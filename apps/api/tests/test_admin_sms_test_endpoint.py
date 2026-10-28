"""Proving the Super Admin SMS path without waiting for a merchant.

"Configured" and "configured wrongly" are indistinguishable until a
registration or a withdrawal happens to occur. Checked production at
06:16 one morning: zero alert rows, and also zero new merchants and zero
withdrawals in six hours, so the silence meant nothing either way.

Three steps, each proving strictly more than the last, and only the final
one reaching a handset or costing anything:

    preview   renders the message, resolves and masks the recipient,
              reports each flag and where it came from. No provider call.
    dry_run   the provider validates the message without sending it.
    send      one real message.

What matters most is that the first two cannot send, that the recipient
always comes from configuration rather than the request, and that no
response or audit row carries the operator's number in clear.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

import app.routers.admin_diagnostics as module
from app.config import get_settings
from app.main import app
from app.services.sms_provider import SmsResult
from tests.factories import TEST_JWT_SECRET, auth_headers, make_super_admin

URL = "/v1/admin/diagnostics/test-sms"
client = TestClient(app)
NUMBER = "255700000001"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("SUPER_ADMIN_SMS_RECIPIENTS", NUMBER)
    monkeypatch.setenv("OASIS_SMS_SENDER_ID", "INFINITYPAY")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def admin(fake_client):
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    return admin_id


@pytest.fixture
def sent(monkeypatch):
    """Every provider call, so a test can prove one did NOT happen."""
    calls: list[dict] = []

    def _send(*, to, sender, message, idempotency_key, dry_run=False):
        calls.append({"to": to, "sender": sender, "message": message, "dry_run": dry_run})
        return SmsResult(outcome="dry_run" if dry_run else "sent", status_code=200, segments=1)

    monkeypatch.setattr(module, "send_sms", _send)
    return calls


def _post(admin_id, mode="preview"):
    return client.post(URL, headers=auth_headers(admin_id), json={"mode": mode})


# --- preview reaches no provider ---------------------------------------


def test_preview_sends_nothing(fake_client, admin, sent):
    response = _post(admin, "preview")

    assert response.status_code == 200, response.text
    assert sent == []
    assert "nothing was sent" in response.json()["data"]["result"]


def test_preview_is_the_default(fake_client, admin, sent):
    """A request with no mode must not send. The safe option is the one
    you get by not choosing."""
    response = client.post(URL, headers=auth_headers(admin), json={})

    assert response.status_code == 200
    assert sent == []


def test_preview_reports_each_flag_and_where_it_came_from(fake_client, admin, sent, monkeypatch):
    """`default` is what an absent, misspelled or wrong-service variable
    looks like — the distinction this endpoint exists to make."""
    monkeypatch.setenv("SUPER_ADMIN_SMS_ENABLED", "true")
    get_settings.cache_clear()

    flags = _post(admin, "preview").json()["data"]["flags"]

    assert flags["super_admin_sms_enabled"] == {"value": True, "source": "env"}
    assert flags["super_admin_sms_new_merchant_enabled"]["source"] == "default"


def test_preview_shows_the_real_message_and_its_cost(fake_client, admin, sent):
    body = _post(admin, "preview").json()["data"]

    assert body["sample_message"].startswith("INFINITYPAY\n")
    assert body["segments"] == 1
    assert body["encoding"] == "GSM-7"


# --- the number never travels in clear ---------------------------------


def test_the_recipient_is_masked_in_the_response(fake_client, admin, sent):
    """A diagnostics response is read in a browser and pasted into chats."""
    response = _post(admin, "preview")

    assert NUMBER not in response.text
    assert response.json()["data"]["recipients_configured"] == 1


def test_the_recipient_is_masked_in_the_audit_row(fake_client, admin, sent):
    _post(admin, "dry_run")

    rows = [r for r in fake_client.table("audit_logs")._table.rows if "sms_test" in str(r.get("action"))]
    assert rows
    assert NUMBER not in str(rows[0])


def test_the_request_cannot_choose_the_recipient(fake_client, admin, sent):
    """The number comes from configuration. Nothing in the body may
    redirect it, or this becomes a way to send from the platform."""
    response = client.post(
        URL, headers=auth_headers(admin), json={"mode": "dry_run", "to": "255799999999"}
    )

    assert response.status_code in (200, 422)
    for call in sent:
        assert call["to"] != "255799999999"


# --- dry run validates without sending ---------------------------------


def test_dry_run_asks_the_provider_but_does_not_send(fake_client, admin, sent):
    body = _post(admin, "dry_run").json()["data"]

    assert len(sent) == 1
    assert sent[0]["dry_run"] is True
    assert "nothing was sent" in body["result"]


def test_send_actually_sends(fake_client, admin, sent):
    body = _post(admin, "send").json()["data"]

    assert len(sent) == 1
    assert sent[0]["dry_run"] is False
    assert "handed to the provider" in body["result"]


# --- misconfiguration is reported, not raised --------------------------


def test_no_recipient_is_reported_clearly(fake_client, admin, sent, monkeypatch):
    monkeypatch.setenv("SUPER_ADMIN_SMS_RECIPIENTS", "")
    get_settings.cache_clear()

    body = _post(admin, "send").json()["data"]

    assert sent == [], "nothing may be sent when no recipient is configured"
    assert "SUPER_ADMIN_SMS_RECIPIENTS" in body["result"]


def test_an_unusable_number_is_reported_not_sent(fake_client, admin, sent, monkeypatch):
    monkeypatch.setenv("SUPER_ADMIN_SMS_RECIPIENTS", "not-a-number")
    get_settings.cache_clear()

    body = _post(admin, "send").json()["data"]

    assert sent == []
    assert "not a valid" in body["result"]


def test_a_provider_configuration_failure_is_reported_not_raised(fake_client, admin, monkeypatch):
    from app.services.sms_provider import SmsNotConfigured

    def _boom(**_kw):
        raise SmsNotConfigured("OASIS_SMS_API_KEY is not configured")

    monkeypatch.setattr(module, "send_sms", _boom)

    response = _post(admin, "send")

    assert response.status_code == 200
    assert "provider not configured" in response.json()["data"]["result"]


# --- authorization ------------------------------------------------------


def test_a_merchant_user_cannot_reach_it(fake_client, sent):
    """Super Admin only. A merchant must not be able to make the platform
    send, or to read the operator's configuration."""
    response = client.post(URL, headers=auth_headers(uuid.uuid4()), json={"mode": "send"})

    assert response.status_code in (401, 403)
    assert sent == []


def test_an_unauthenticated_caller_cannot_reach_it(fake_client, sent):
    response = client.post(URL, json={"mode": "send"})

    assert response.status_code in (401, 403)
    assert sent == []
