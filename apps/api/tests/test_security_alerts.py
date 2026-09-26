"""Security alert emails.

Two properties matter more than the content: an alert must never break the
action it reports, and it must stay worth reading. Both get explicit tests
here, because both fail silently in production if they regress.
"""

import uuid
from decimal import Decimal

import pytest
import resend

from app.config import get_settings
from app.core.errors import EmailDeliveryError
from app.services import security_alerts
from app.services.security_alerts import mask_phone, notify_security_event


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("SECURITY_ALERTS_ENABLED", "true")
    monkeypatch.setenv("SECURITY_ALERT_EMAIL", "security@infinitypay.me")
    monkeypatch.setenv("SECURITY_ALERT_DEDUPE_WINDOW_SECONDS", "600")
    get_settings.cache_clear()
    # A fresh deduper per test — otherwise one test's suppression window
    # silently swallows the next test's alert.
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


# --- delivery -----------------------------------------------------------


def test_sends_to_the_configured_security_address(fake_client, sent):
    notify_security_event(fake_client, event="test.event", title="Withdrawal approved")

    assert len(sent) == 1
    assert sent[0]["to"] == ["security@infinitypay.me"]
    assert sent[0]["subject"] == "InfinityPay Security Alert: Withdrawal approved"


def test_falls_back_to_the_ceo_address_when_no_security_address_is_set(fake_client, sent, monkeypatch):
    monkeypatch.setenv("SECURITY_ALERT_EMAIL", "")
    monkeypatch.setenv("CEO_EMAIL", "ceo@infinitypay.me,second@example.com")
    get_settings.cache_clear()

    notify_security_event(fake_client, event="test.event", title="Pricing changed")

    assert sent[0]["to"] == ["ceo@infinitypay.me"]


def test_sends_nothing_when_no_recipient_is_configured_anywhere(fake_client, sent, monkeypatch):
    monkeypatch.setenv("SECURITY_ALERT_EMAIL", "")
    monkeypatch.setenv("CEO_EMAIL", "")
    get_settings.cache_clear()

    assert notify_security_event(fake_client, event="test.event", title="X") is False
    assert sent == []


def test_disabling_alerts_stops_email_without_touching_anything_else(fake_client, sent, monkeypatch):
    """SECURITY_ALERTS_ENABLED=false silences email only. The audit trail is
    written by the callers and is unaffected — that separation is the point
    of the flag."""
    monkeypatch.setenv("SECURITY_ALERTS_ENABLED", "false")
    get_settings.cache_clear()

    assert notify_security_event(fake_client, event="test.event", title="X") is False
    assert sent == []


# --- must never break the caller ---------------------------------------


def test_a_provider_failure_is_swallowed(fake_client, monkeypatch):
    """A withdrawal that was approved has been approved. A failed
    notification about it must not surface as an error."""
    def _boom(params):
        raise EmailDeliveryError("provider down")

    monkeypatch.setattr(resend.Emails, "send", _boom)

    assert notify_security_event(fake_client, event="test.event", title="Withdrawal approved") is False


def test_an_unexpected_error_is_swallowed_too(fake_client, monkeypatch):
    def _boom(params):
        raise RuntimeError("something entirely unexpected")

    monkeypatch.setattr(resend.Emails, "send", _boom)

    assert notify_security_event(fake_client, event="test.event", title="X") is False


def test_a_failed_send_is_still_recorded_in_email_deliveries(fake_client, monkeypatch):
    def _boom(params):
        raise EmailDeliveryError("provider down")

    monkeypatch.setattr(resend.Emails, "send", _boom)
    notify_security_event(fake_client, event="test.event", title="X")

    rows = fake_client.table("email_deliveries")._table.rows
    assert [r["status"] for r in rows] == ["failed"]
    assert rows[0]["email_type"] == "security_alert"


# --- dedupe -------------------------------------------------------------


def test_repeated_suspicious_events_from_one_actor_send_once(fake_client, sent):
    """Sixty identical alerts is an inbox nobody reads, which is the same as
    having no alerts."""
    for _ in range(5):
        notify_security_event(
            fake_client, event="super_admin.mfa.required_block", title="Blocked", dedupe_key="user-1"
        )

    assert len(sent) == 1


def test_a_different_actor_is_not_suppressed(fake_client, sent):
    notify_security_event(fake_client, event="e", title="Blocked", dedupe_key="user-1")
    notify_security_event(fake_client, event="e", title="Blocked", dedupe_key="user-2")

    assert len(sent) == 2


def test_a_different_event_for_the_same_actor_is_not_suppressed(fake_client, sent):
    notify_security_event(fake_client, event="mfa_block", title="A", dedupe_key="user-1")
    notify_security_event(fake_client, event="ip_rejected", title="B", dedupe_key="user-1")

    assert len(sent) == 2


def test_money_events_are_never_deduplicated(fake_client, sent):
    """Each approval is a separate decision about real funds. Two identical
    approvals must produce two emails."""
    for _ in range(3):
        notify_security_event(
            fake_client, event="super_admin.withdrawal.approved", title="Withdrawal approved"
        )

    assert len(sent) == 3


# --- masking ------------------------------------------------------------


def test_the_destination_is_masked_in_the_email(fake_client, sent):
    notify_security_event(
        fake_client,
        event="super_admin.withdrawal.approved",
        title="Withdrawal approved",
        amount=Decimal(250000),
        destination="255712345678",
        actor_email="admin@infinitypay.me",
    )

    html = sent[0]["html"]
    assert "255712345678" not in html
    assert "5678" in html
    assert "TZS 250,000.00" in html


def test_mask_phone_keeps_only_the_last_four():
    assert mask_phone("255712345678").endswith("5678")
    assert "25571234" not in mask_phone("255712345678")
    assert mask_phone(None) == "—"


def test_no_token_or_secret_shape_reaches_the_body(fake_client, sent):
    notify_security_event(
        fake_client,
        event="super_admin.mfa.required_block",
        title="Blocked",
        actor_id=uuid.uuid4(),
        ip_address="41.86.0.10",
        user_agent="Mozilla/5.0",
        extra={"Path": "/v1/admin/merchants"},
    )

    html = sent[0]["html"]
    for forbidden in ("Bearer ", "eyJ", "sk_live_", "sk_test_", "inf_live_", "inf_sandbox_"):
        assert forbidden not in html


def test_a_long_user_agent_is_truncated(fake_client, sent):
    notify_security_event(fake_client, event="e", title="T", user_agent="U" * 500)

    assert "U" * 200 not in sent[0]["html"]
