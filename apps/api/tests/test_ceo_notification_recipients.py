"""CEO_EMAIL as a recipient list.

Internal alerts — new inquiries, new merchant signups, and withdrawal
requests awaiting approval — go to CEO_EMAIL. A second Super Admin only
receives them if they are named there: being in platform_admins grants
authorisation, not notifications, and the two are deliberately separate so
that adding an admin never silently starts mailing a new address.
"""

import pytest
import resend

from app.config import get_settings
from app.services.email import send_email


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def sent(monkeypatch):
    captured: list[dict] = []

    def _send(params):
        captured.append(params)
        return {"id": "resend-test-message-id"}

    monkeypatch.setattr(resend.Emails, "send", _send)
    return captured


def _emails(monkeypatch, value: str) -> list[str]:
    monkeypatch.setenv("CEO_EMAIL", value)
    get_settings.cache_clear()
    return get_settings().ceo_emails


def test_single_address_still_works(monkeypatch):
    assert _emails(monkeypatch, "ceo@infinitypay.me") == ["ceo@infinitypay.me"]


def test_two_addresses_are_both_returned(monkeypatch):
    assert _emails(monkeypatch, "ceo@infinitypay.me,second@icloud.com") == [
        "ceo@infinitypay.me",
        "second@icloud.com",
    ]


def test_surrounding_whitespace_is_ignored(monkeypatch):
    """Typing the value into a Railway field tends to leave spaces, and a
    leading space would otherwise make the address invalid."""
    assert _emails(monkeypatch, " ceo@infinitypay.me , second@icloud.com ") == [
        "ceo@infinitypay.me",
        "second@icloud.com",
    ]


def test_trailing_comma_does_not_produce_a_blank_recipient(monkeypatch):
    assert _emails(monkeypatch, "ceo@infinitypay.me,") == ["ceo@infinitypay.me"]


def test_a_repeated_address_is_not_mailed_twice(monkeypatch):
    assert _emails(monkeypatch, "ceo@infinitypay.me,ceo@infinitypay.me") == ["ceo@infinitypay.me"]


def test_unset_means_no_recipients_so_callers_skip_the_send(monkeypatch):
    """Every CEO notification guards on this being empty — an unset
    CEO_EMAIL must stay a no-op, not an attempt to mail "" ."""
    assert _emails(monkeypatch, "") == []


def test_send_email_delivers_to_every_recipient(monkeypatch, sent):
    send_email(
        to=["ceo@infinitypay.me", "second@icloud.com"],
        subject="Withdrawal request awaiting approval",
        html="<p>x</p>",
        sender="InfinityPay <noreply@infinitypay.me>",
    )

    assert sent[0]["to"] == ["ceo@infinitypay.me", "second@icloud.com"]


def test_send_email_still_accepts_a_plain_string(monkeypatch, sent):
    """Every merchant- and customer-facing send passes one address; that
    must keep working unchanged."""
    send_email(
        to="merchant@example.com",
        subject="Your withdrawal code",
        html="<p>x</p>",
        sender="InfinityPay <noreply@infinitypay.me>",
    )

    assert sent[0]["to"] == ["merchant@example.com"]
