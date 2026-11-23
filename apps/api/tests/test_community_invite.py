"""The InfinityPay WhatsApp community invitation.

One server-side setting (MERCHANT_COMMUNITY_WHATSAPP_URL), appended to
exactly two merchant notifications - approval and a CONFIRMED successful
withdrawal - on the two channels a merchant actually receives (email and
SMS). Pinned here:

1. Only an https chat.whatsapp.com link is ever sent; anything else is
   omitted and the notification still goes out unchanged.
2. Each message carries the invitation exactly once, and the HTML and
   plain-text parts both point at the exact configured destination.
3. Nothing that is not a confirmed success - pending, rejected, failed,
   processing - receives success wording or the invitation.
4. A duplicate callback cannot send a second confirmation.
5. Recipients are unchanged: the business's own notification address and
   number, never a customer, a payout recipient or a developer webhook.

Everything is mocked: Resend is patched, SMS rows are only queued (no
dispatch worker runs), and the provider is the in-repo mock client.
"""

import html as html_lib
import json
import re
import uuid
from decimal import Decimal

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.community_invite import (
    community_invite_url,
    validate_community_url,
)
from app.services.selcom_business.client import get_selcom_business_client
from app.services.sms_text import (
    message_cost,
    render_welcome,
    render_withdrawal_complete,
)
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
    make_super_admin,
)

INVITE = "https://chat.whatsapp.com/Ku5UwtoPC5ZFzeL2DXWSfg?s=cl&p=i&iam=2"
SMS_LINE = f"Jiunge na jumuiya ya InfinityPay: {INVITE}"
EMAIL_LINE = "Join the InfinityPay WhatsApp community for service updates, support and ideas:"
SUCCESS_SUBJECT = "Your InfinityPay withdrawal is successful"
WELCOME_SUBJECT = "Your InfinityPay account has been approved"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("SELCOM_BUSINESS_MODE", "mock")
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "0")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("CEO_EMAIL", "ceo@infinitypay.me")
    monkeypatch.setenv("SEND_MERCHANT_WITHDRAWAL_EMAILS", "true")
    monkeypatch.setenv("OASIS_SMS_ENABLED", "true")
    monkeypatch.setenv("OASIS_SMS_WELCOME_ENABLED", "true")
    monkeypatch.setenv("OASIS_SMS_WITHDRAWAL_ENABLED", "true")
    monkeypatch.setenv("OASIS_SMS_SENDER_ID", "INFINITYPAY")
    monkeypatch.setenv("OASIS_SMS_API_KEY", "test-key-not-real")
    monkeypatch.setenv("MERCHANT_COMMUNITY_WHATSAPP_URL", INVITE)
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()


def _set_invite(monkeypatch, value: str | None):
    if value is None:
        monkeypatch.delenv("MERCHANT_COMMUNITY_WHATSAPP_URL", raising=False)
    else:
        monkeypatch.setenv("MERCHANT_COMMUNITY_WHATSAPP_URL", value)
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


def _emails(fake_resend, subject):
    return [c for c in fake_resend.calls if c["subject"] == subject]


def _sms(fake_client, purpose):
    return [r for r in fake_client.table("sms_messages")._table.rows if r["purpose"] == purpose]


def _hrefs(markup: str) -> list[str]:
    """Every href in the email, decoded the way a mail client decodes it."""
    return [html_lib.unescape(h) for h in re.findall(r'href="([^"]+)"', markup)]


# --- 1. validation --------------------------------------------------------------


def test_the_configured_link_is_returned_exactly_as_written():
    assert validate_community_url(INVITE) == INVITE


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "http://chat.whatsapp.com/Ku5UwtoPC5ZFzeL2DXWSfg",  # not https
        "https://chat.whatsapp.com.evil.example/Ku5UwtoPC5ZFzeL2DXWSfg",  # lookalike host
        "https://evil.example/chat.whatsapp.com/Ku5UwtoPC5ZFzeL2DXWSfg",
        "https://wa.me/255700000000",  # a WhatsApp host, but not the community one
        "https://user:pw@chat.whatsapp.com/Ku5UwtoPC5ZFzeL2DXWSfg",  # credentials
        "https://chat.whatsapp.com:8443/Ku5UwtoPC5ZFzeL2DXWSfg",  # odd port
        "https://chat.whatsapp.com/",  # no invite code
        "https://chat.whatsapp.com/Ku5 UwtoPC5",  # whitespace
        "https://chat.whatsapp.com/Ku5UwtoPC5\nZFzeL2",  # control character
        "javascript:alert(1)//chat.whatsapp.com/x",
        "https://chat.whatsapp.com/" + "a" * 300,  # absurd length
    ],
)
def test_anything_but_an_https_chat_whatsapp_link_is_refused(value):
    assert validate_community_url(value) is None


def test_a_missing_setting_means_no_invitation(monkeypatch):
    _set_invite(monkeypatch, None)
    assert community_invite_url() is None


def test_an_invalid_setting_means_no_invitation(monkeypatch):
    _set_invite(monkeypatch, "http://chat.whatsapp.com/Ku5UwtoPC5ZFzeL2DXWSfg")
    assert community_invite_url() is None


# --- 2. SMS text ------------------------------------------------------------------


def test_without_a_link_both_sms_texts_are_byte_for_byte_unchanged():
    assert render_welcome() == render_welcome(community_url=None)
    plain = render_withdrawal_complete(
        amount=Decimal(50000), fee_amount=Decimal(1500), closing_balance=Decimal("161638.13"), reference="TXN-1"
    )
    assert "chat.whatsapp.com" not in plain
    assert "chat.whatsapp.com" not in render_welcome()


def test_the_sms_invitation_is_appended_once_after_every_transaction_detail():
    text = render_withdrawal_complete(
        amount=Decimal(50000),
        fee_amount=Decimal(1500),
        closing_balance=Decimal("161638.13"),
        reference="TXN-20261123-ABCD1234",
        community_url=INVITE,
    )
    assert text.count(INVITE) == 1
    assert text.endswith(SMS_LINE)
    # Nothing transactional was shortened to make room.
    for fragment in ("TZS 50,000", "Ada: TZS 1,500", "TZS 161,638.13", "Kumb: TXN-20261123-ABCD1234", "255747730270"):
        assert fragment in text


def test_sms_segment_impact_is_what_the_docs_say():
    """Reported, not hidden: the welcome goes from one part to two; the
    payout confirmation was already two and stays two. Both stay GSM-7 -
    nothing in the link forces the expensive encoding."""
    welcome = message_cost(render_welcome(community_url=INVITE))
    payout = message_cost(
        render_withdrawal_complete(
            amount=Decimal("999999999.99"),
            fee_amount=Decimal("99999.99"),
            closing_balance=Decimal("999999999.99"),
            reference="TXN-20261123-ABCD1234",
            community_url=INVITE,
        )
    )
    assert message_cost(render_welcome())["segments"] == 1
    assert welcome == {"encoding": "GSM-7", "length": 221, "segments": 2}
    assert payout["encoding"] == "GSM-7"
    assert payout["segments"] == 2, "even the largest realistic payout must not reach a third part"


# --- helpers for the real flows ---------------------------------------------------


def _merchant_with_admin(fake_client, **overrides):
    merchant = create_merchant(
        fake_client,
        contact_email="owner@biashara.co.tz",
        contact_phone="255713000001",
        **overrides,
    )
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Merchant Wallet (test)",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": "TZS",
            "balance": "1000000.00",
        },
    )
    return merchant_id, admin_id


def _request_withdrawal(merchant_id, admin_id, amount="50000.00"):
    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": amount,
            "destination_name": "Jane Doe",
            "destination_identifier": "+255712345678",
            "destination_code": "MPESA",
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]


def _super_admin(fake_client):
    admin = uuid.uuid4()
    make_super_admin(fake_client, admin)
    return admin


def _assert_one_email_invite(call: dict):
    markup = call["html"]
    # Exactly one block, one button, and the visible copy of the link.
    assert markup.count(html_lib.escape(EMAIL_LINE)) == 1
    assert markup.count("Join WhatsApp Community") == 1
    invite_hrefs = [h for h in _hrefs(markup) if "chat.whatsapp.com" in h]
    assert invite_hrefs == [INVITE, INVITE], "button + visible link, both to the exact destination"
    # The query string is escaped in the markup and nowhere left raw.
    assert "&amp;p=i&amp;iam=2" in markup
    assert "?s=cl&p=i" not in markup
    # The plain-text part carries the real, unescaped link once.
    assert call["text"].count(INVITE) == 1
    assert EMAIL_LINE in call["text"]


# --- 3. approval -------------------------------------------------------------------


def _submit_and_seed(fake_client):
    from tests.test_admin_onboarding import _seed_required_documents, _valid_payload

    user_id = uuid.uuid4()
    response = client.post("/v1/onboarding/merchant-account", headers=auth_headers(user_id), json=_valid_payload())
    assert response.status_code == 201, response.text
    merchant_id = response.json()["data"]["merchant"]["id"]
    _seed_required_documents(fake_client, merchant_id)
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )
    return merchant_id, submission_id


@pytest.mark.parametrize("route", ["post_by_submission", "patch_by_merchant"])
def test_approval_carries_the_invitation_once_on_email_and_sms(fake_client, fake_resend, route):
    """Both approval routes reach the same notification code."""
    merchant_id, submission_id = _submit_and_seed(fake_client)
    fake_resend.calls.clear()
    admin = _super_admin(fake_client)

    if route == "post_by_submission":
        response = client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin))
    else:
        response = client.patch(f"/v1/admin/onboarding/{merchant_id}/approve", headers=auth_headers(admin))
    assert response.status_code == 200, response.text

    welcome = _emails(fake_resend, WELCOME_SUBJECT)
    assert len(welcome) == 1
    # Same single recipient as before - the business's own address.
    assert welcome[0]["to"] == ["user@example.com"]
    _assert_one_email_invite(welcome[0])
    # Nothing in the approval email suggests the Payout API came with it.
    assert "payout api" not in welcome[0]["html"].lower()

    sms = _sms(fake_client, "welcome")
    assert len(sms) == 1
    assert sms[0]["body"].count(INVITE) == 1
    assert sms[0]["body"].endswith(SMS_LINE)
    assert sms[0]["segments"] == 2

    # No other email that went out on approval carries the invitation.
    others = [c for c in fake_resend.calls if c["subject"] != WELCOME_SUBJECT]
    assert all(INVITE not in c["html"] and INVITE not in (c.get("text") or "") for c in others)


def test_a_retried_approval_does_not_queue_a_second_welcome_sms(fake_client, fake_resend):
    _merchant_id, submission_id = _submit_and_seed(fake_client)
    admin = _super_admin(fake_client)
    client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin))
    client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin))

    sms = _sms(fake_client, "welcome")
    assert len(sms) == 1
    assert sms[0]["body"].count(INVITE) == 1


@pytest.mark.parametrize("value", [None, "http://chat.whatsapp.com/Ku5UwtoPC5ZFzeL2DXWSfg"])
def test_approval_without_a_usable_link_still_sends_both_messages(fake_client, fake_resend, monkeypatch, value):
    _set_invite(monkeypatch, value)
    _merchant_id, submission_id = _submit_and_seed(fake_client)
    fake_resend.calls.clear()
    admin = _super_admin(fake_client)

    response = client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin))
    assert response.status_code == 200, response.text

    welcome = _emails(fake_resend, WELCOME_SUBJECT)
    assert len(welcome) == 1
    assert "chat.whatsapp.com" not in welcome[0]["html"]
    assert "chat.whatsapp.com" not in welcome[0]["text"]
    assert "WhatsApp" not in welcome[0]["html"]
    sms = _sms(fake_client, "welcome")
    assert len(sms) == 1
    assert sms[0]["body"] == render_welcome()


# --- 4. confirmed withdrawals --------------------------------------------------------


def _assert_success_once(fake_client, fake_resend, merchant_id):
    success = _emails(fake_resend, SUCCESS_SUBJECT)
    assert len(success) == 1
    assert success[0]["to"] == ["owner@biashara.co.tz"]
    _assert_one_email_invite(success[0])
    # Existing details kept: amount, reference row, masked destination.
    assert "TZS 50,000.00" in success[0]["html"]
    assert "+255712345678" not in success[0]["html"]
    assert "•••• 5678" in success[0]["html"]

    sms = _sms(fake_client, "withdrawal_complete")
    assert len(sms) == 1
    assert sms[0]["merchant_id"] == str(merchant_id)
    assert sms[0]["recipient_phone"] == "255713000001"
    assert sms[0]["body"].count(INVITE) == 1
    assert sms[0]["body"].startswith("Imethibitishwa.")


def test_a_manually_approved_withdrawal_carries_the_invitation_once(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_with_admin(fake_client)
    body = _request_withdrawal(merchant_id, admin_id)
    response = client.post(
        f"/v1/admin/withdrawals/{body['id']}/approve", headers=auth_headers(_super_admin(fake_client))
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "SUCCESS"
    _assert_success_once(fake_client, fake_resend, merchant_id)


def test_an_automated_withdrawal_carries_the_invitation_once(fake_client, fake_resend, monkeypatch):
    monkeypatch.setenv("AUTO_WITHDRAWALS_ENABLED", "true")
    monkeypatch.setenv("REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS", "false")
    monkeypatch.setenv("AUTO_WITHDRAWAL_MAX_AMOUNT_TZS", "500000")
    monkeypatch.setenv("AUTO_WITHDRAWAL_DAILY_LIMIT_TZS", "1000000")
    get_settings.cache_clear()
    fake_client.enable_withdrawal_automation_policy()

    merchant_id, admin_id = _merchant_with_admin(fake_client)
    body = _request_withdrawal(merchant_id, admin_id)

    assert body["status"] == "SUCCESS"
    assert body["auto_approved"] is True
    _assert_success_once(fake_client, fake_resend, merchant_id)
    # The operator's "paid out automatically" email is internal and gets
    # no invitation.
    internal = [c for c in fake_resend.calls if c["to"] == ["ceo@infinitypay.me"]]
    assert all("chat.whatsapp.com" not in c["html"] for c in internal)


def _processing_then(monkeypatch):
    """The provider accepts the payout but has not confirmed it yet."""
    from app.services.selcom_business.client import SelcomBusinessResult
    from app.services.selcom_business.mock_client import MockSelcomBusinessClient

    async def _processing(self, *, trans_id: str, **kwargs):
        return SelcomBusinessResult(transaction_id=trans_id, status="processing")

    monkeypatch.setattr(MockSelcomBusinessClient, "process_transaction", _processing)


def test_a_processing_withdrawal_gets_no_success_wording_and_no_invitation(fake_client, fake_resend, monkeypatch):
    _processing_then(monkeypatch)
    merchant_id, admin_id = _merchant_with_admin(fake_client)
    body = _request_withdrawal(merchant_id, admin_id)
    response = client.post(
        f"/v1/admin/withdrawals/{body['id']}/approve", headers=auth_headers(_super_admin(fake_client))
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "PROCESSING"

    assert _emails(fake_resend, SUCCESS_SUBJECT) == []
    assert _sms(fake_client, "withdrawal_complete") == []
    assert all("chat.whatsapp.com" not in (c["html"] + (c.get("text") or "")) for c in fake_resend.calls)


def test_a_confirmed_callback_then_a_duplicate_callback_sends_one_confirmation(fake_client, fake_resend, monkeypatch):
    from app.services.disbursements import resolve_disbursement_from_callback

    _processing_then(monkeypatch)
    merchant_id, admin_id = _merchant_with_admin(fake_client)
    body = _request_withdrawal(merchant_id, admin_id)
    approved = client.post(
        f"/v1/admin/withdrawals/{body['id']}/approve", headers=auth_headers(_super_admin(fake_client))
    ).json()["data"]
    reference = approved["provider_reference"]

    first = resolve_disbursement_from_callback(
        fake_client, provider_reference=reference, status="successful", failure_reason=None
    )
    second = resolve_disbursement_from_callback(
        fake_client, provider_reference=reference, status="successful", failure_reason=None
    )

    assert first["status"] == "SUCCESS"
    assert second is None
    _assert_success_once(fake_client, fake_resend, merchant_id)


def test_the_success_email_itself_refuses_a_repeat_for_the_same_withdrawal(fake_client, fake_resend):
    """The backstop for a callback racing the reconciliation sweep: even
    if two SUCCESS branches run for one payout, the second email is not
    sent. (The SMS has a unique index for the same job.)"""
    from app.services.email import send_withdrawal_success_email

    merchant = create_merchant(fake_client, contact_email="owner@biashara.co.tz")
    disbursement = fake_client.seed(
        "disbursements",
        {
            "merchant_id": merchant["id"],
            "amount": "50000.00",
            "currency": "TZS",
            "status": "SUCCESS",
            "destination_identifier": "+255712345678",
            "provider_reference": "SB-1",
        },
    )

    assert send_withdrawal_success_email(fake_client, merchant=merchant, disbursement=disbursement) is not None
    assert send_withdrawal_success_email(fake_client, merchant=merchant, disbursement=disbursement) is None
    assert len(_emails(fake_resend, SUCCESS_SUBJECT)) == 1


@pytest.mark.parametrize(
    "status", ["PENDING_ADMIN_APPROVAL", "APPROVED", "PROCESSING", "NEEDS_RECONCILIATION", "FAILED", "REVERSED"]
)
def test_no_success_email_or_sms_for_anything_but_success(fake_client, fake_resend, status):
    """Defence in depth: both senders check the status themselves, so a
    future caller cannot describe a pending or unknown payout as paid."""
    from app.services.email import send_withdrawal_success_email
    from app.services.sms_messages import enqueue_withdrawal_complete_sms

    merchant = create_merchant(fake_client, contact_email="owner@biashara.co.tz", contact_phone="255713000001")
    disbursement = fake_client.seed(
        "disbursements",
        {"merchant_id": merchant["id"], "amount": "50000.00", "currency": "TZS", "status": status},
    )

    assert send_withdrawal_success_email(fake_client, merchant=merchant, disbursement=disbursement) is None
    assert enqueue_withdrawal_complete_sms(fake_client, disbursement=disbursement, transaction=None) is None
    assert fake_resend.calls == []
    assert _sms(fake_client, "withdrawal_complete") == []


def test_a_failed_withdrawal_gets_no_invitation_anywhere(fake_client, fake_resend, monkeypatch):
    from app.services.selcom_business.client import SelcomBusinessResult
    from app.services.selcom_business.mock_client import MockSelcomBusinessClient

    async def _fail(self, *, trans_id: str, **kwargs):
        return SelcomBusinessResult(transaction_id=trans_id, status="failed", failure_reason="Invalid account")

    monkeypatch.setattr(MockSelcomBusinessClient, "process_transaction", _fail)
    merchant_id, admin_id = _merchant_with_admin(fake_client)
    body = _request_withdrawal(merchant_id, admin_id)
    response = client.post(
        f"/v1/admin/withdrawals/{body['id']}/approve", headers=auth_headers(_super_admin(fake_client))
    )
    assert response.json()["data"]["status"] == "FAILED"

    assert _emails(fake_resend, SUCCESS_SUBJECT) == []
    assert _sms(fake_client, "withdrawal_complete") == []
    assert all("chat.whatsapp.com" not in (c["html"] + (c.get("text") or "")) for c in fake_resend.calls)


def test_a_confirmed_withdrawal_without_a_link_is_sent_exactly_as_before(fake_client, fake_resend, monkeypatch):
    _set_invite(monkeypatch, "https://chat.whatsapp.com.evil.example/x")
    merchant_id, admin_id = _merchant_with_admin(fake_client)
    body = _request_withdrawal(merchant_id, admin_id)
    client.post(f"/v1/admin/withdrawals/{body['id']}/approve", headers=auth_headers(_super_admin(fake_client)))

    success = _emails(fake_resend, SUCCESS_SUBJECT)
    assert len(success) == 1
    assert "WhatsApp" not in success[0]["html"]
    assert "whatsapp" not in success[0]["text"].lower()
    sms = _sms(fake_client, "withdrawal_complete")
    assert len(sms) == 1
    assert "whatsapp" not in sms[0]["body"].lower()


def test_developer_webhooks_and_in_app_notifications_never_carry_the_invitation(fake_client, fake_resend):
    merchant_id, admin_id = _merchant_with_admin(fake_client)
    fake_client.table("merchants").update({"webhook_url": "https://merchant.example/hooks"}).eq(
        "id", str(merchant_id)
    ).execute()
    body = _request_withdrawal(merchant_id, admin_id)
    client.post(f"/v1/admin/withdrawals/{body['id']}/approve", headers=auth_headers(_super_admin(fake_client)))

    events = fake_client.table("webhook_events")._table.rows
    assert any(e["event_name"] == "disbursement.success" for e in events)
    assert all("whatsapp" not in json.dumps(e["payload"]).lower() for e in events)
    notes = fake_client.table("notifications")._table.rows
    assert all("whatsapp" not in (n.get("body") or "").lower() for n in notes)
