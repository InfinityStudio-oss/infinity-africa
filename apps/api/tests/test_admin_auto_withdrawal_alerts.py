"""Telling an operator that money left without them.

Written after the first real automatic payout, on 2026-10-31 at 19:30
EAT. It worked: TZS 1,000 reached Selcom under policy v4 with
auto_approved=true and approved_by null. The merchant got their SMS 27
seconds later, as always. The operator got nothing useful, because two
correct decisions met badly:

* ``admin_withdrawal_request`` only fires at PENDING_ADMIN_APPROVAL,
  since its text says the withdrawal is awaiting approval and saying that
  about a payout already gone is worse than silence.
* The approval email fired for every request and its button read "Review
  Withdrawal", so for an automatic payout it asked a human to approve
  money that had already left.

Each was right while every withdrawal needed a human. Together, with
automation on, they left an operator blind to roughly five payouts a day.

The rule these tests hold to: **exactly one of the two operator
notifications describes any given withdrawal.** A withdrawal is either
waiting for an operator or it is not, so none may produce both and none
may produce neither.
"""

import uuid
from decimal import Decimal

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.selcom_business.client import get_selcom_business_client
from app.services.sms_text import message_cost, render_withdrawal_auto_admin
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
)

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
    # Operator SMS on, both event flags on, so these tests are about the
    # routing rather than about the switches.
    monkeypatch.setenv("SUPER_ADMIN_SMS_ENABLED", "true")
    monkeypatch.setenv("SUPER_ADMIN_SMS_WITHDRAWAL_REQUEST_ENABLED", "true")
    monkeypatch.setenv("SUPER_ADMIN_SMS_WITHDRAWAL_AUTO_ENABLED", "true")
    monkeypatch.setenv("SUPER_ADMIN_SMS_RECIPIENTS", "255700000111")
    monkeypatch.setenv("OASIS_SMS_SENDER_ID", "INFINITYPAY")
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


def _enable_automation(fake_client, monkeypatch, *, max_amount="100000"):
    monkeypatch.setenv("AUTO_WITHDRAWALS_ENABLED", "true")
    monkeypatch.setenv("REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS", "false")
    get_settings.cache_clear()
    fake_client.enable_withdrawal_automation_policy(max_amount_tzs=max_amount)


def _merchant_and_admin(fake_client, **overrides):
    merchant = create_merchant(fake_client, business_name="BennyWiFi", **overrides)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    return merchant_id, user_id


def _fund_wallet(fake_client, merchant_id, amount="900000"):
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


def _request_withdrawal(merchant_id, user_id, amount):
    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": amount,
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]


def _sms(fake_client, purpose):
    return [r for r in fake_client.table("sms_messages")._table.rows if r["purpose"] == purpose]


def _emails(fake_resend, needle):
    return [c for c in fake_resend.calls if needle.lower() in str(c.get("subject", "")).lower()]


# --- The rule: exactly one of the two -------------------------------------


def test_an_automatic_payout_alerts_the_operator(fake_client, fake_resend, monkeypatch):
    """The gap this closes. Before, this payout produced no SMS at all."""
    _enable_automation(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    data = _request_withdrawal(merchant_id, user_id, "45000")
    assert data["auto_approved"] is True

    auto = _sms(fake_client, "admin_withdrawal_auto")
    assert len(auto) == 1
    assert auto[0]["recipient_role"] == "super_admin"
    body = auto[0]["body"]
    assert "paid out automatically" in body
    assert "No approval needed" in body
    # Never the words that made the old alert wrong here.
    assert "Awaiting approval" not in body


def test_an_automatic_payout_never_sends_the_awaiting_approval_alert(
    fake_client, fake_resend, monkeypatch
):
    """The message says a withdrawal is waiting for you. It is not."""
    _enable_automation(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    _request_withdrawal(merchant_id, user_id, "45000")

    assert _sms(fake_client, "admin_withdrawal_request") == []


def test_a_manual_withdrawal_still_sends_the_approval_alert_and_not_the_automatic_one(
    fake_client, fake_resend, monkeypatch
):
    """Nothing about the existing path changes when automation is off."""
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    data = _request_withdrawal(merchant_id, user_id, "45000")
    assert data["status"] == "PENDING_ADMIN_APPROVAL"

    assert len(_sms(fake_client, "admin_withdrawal_request")) == 1
    assert _sms(fake_client, "admin_withdrawal_auto") == []


def test_a_withdrawal_above_the_limit_is_treated_as_manual(fake_client, fake_resend, monkeypatch):
    """Automation on, but this one fell back. It is waiting for a human,
    so it gets the waiting-for-a-human alert."""
    _enable_automation(fake_client, monkeypatch, max_amount="10000")
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    data = _request_withdrawal(merchant_id, user_id, "45000")
    assert data["status"] == "PENDING_ADMIN_APPROVAL"

    assert len(_sms(fake_client, "admin_withdrawal_request")) == 1
    assert _sms(fake_client, "admin_withdrawal_auto") == []


@pytest.mark.parametrize("automation", [True, False])
def test_every_withdrawal_produces_exactly_one_operator_alert(
    fake_client, fake_resend, monkeypatch, automation
):
    """The invariant, stated directly: never both, never neither."""
    if automation:
        _enable_automation(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    _request_withdrawal(merchant_id, user_id, "45000")

    total = len(_sms(fake_client, "admin_withdrawal_request")) + len(
        _sms(fake_client, "admin_withdrawal_auto")
    )
    assert total == 1


# --- The email ------------------------------------------------------------


def test_the_automatic_payout_email_does_not_ask_anyone_to_approve_it(
    fake_client, fake_resend, monkeypatch
):
    """The bug in words: an email headed "New withdrawal request" with a
    button reading "Review Withdrawal", for money already gone."""
    _enable_automation(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    _request_withdrawal(merchant_id, user_id, "45000")

    assert _emails(fake_resend, "New withdrawal request") == []
    paid = _emails(fake_resend, "paid automatically")
    assert len(paid) == 1
    html = paid[0]["html"]
    assert "Review Withdrawal" not in html
    assert "No action is needed" in html
    # It answers "why did this not need me?"
    assert "Automation Policy" in html
    assert "AUTO_ELIGIBLE" in html


def test_a_manual_withdrawal_still_gets_the_approval_email(fake_client, fake_resend, monkeypatch):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    _request_withdrawal(merchant_id, user_id, "45000")

    assert len(_emails(fake_resend, "New withdrawal request")) == 1
    assert _emails(fake_resend, "paid automatically") == []


def test_a_withdrawal_rejected_on_the_hard_limit_notifies_nobody(
    fake_client, fake_resend, monkeypatch
):
    """Nothing happened and nothing is waiting, so there is nothing to
    say. The merchant was told by the error on their own request."""
    _enable_automation(fake_client, monkeypatch)
    monkeypatch.setenv("DAILY_WITHDRAWAL_LIMIT_TZS", "10000")
    get_settings.cache_clear()
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": "45000",
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )
    assert response.status_code == 409

    assert _sms(fake_client, "admin_withdrawal_auto") == []
    assert _sms(fake_client, "admin_withdrawal_request") == []


# --- The switches ---------------------------------------------------------


def test_the_master_switch_silences_the_automatic_alert(fake_client, fake_resend, monkeypatch):
    """SUPER_ADMIN_SMS_ENABLED is the rollback for all operator SMS."""
    _enable_automation(fake_client, monkeypatch)
    monkeypatch.setenv("SUPER_ADMIN_SMS_ENABLED", "false")
    get_settings.cache_clear()
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    data = _request_withdrawal(merchant_id, user_id, "45000")

    assert data["auto_approved"] is True, "the payout must still happen"
    assert _sms(fake_client, "admin_withdrawal_auto") == []


def test_the_automatic_alert_has_its_own_switch(fake_client, fake_resend, monkeypatch):
    _enable_automation(fake_client, monkeypatch)
    monkeypatch.setenv("SUPER_ADMIN_SMS_WITHDRAWAL_AUTO_ENABLED", "false")
    get_settings.cache_clear()
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    _request_withdrawal(merchant_id, user_id, "45000")

    assert _sms(fake_client, "admin_withdrawal_auto") == []


def test_the_automatic_alert_is_on_by_default(monkeypatch):
    """Unlike its two siblings. They describe something waiting for an
    operator, where a miss costs a delay; this one describes money already
    gone, where a miss costs the operator their only live view of
    unattended payouts. Silence is the dangerous state, so the safe
    default is on."""
    # Both unset, so this reads the real defaults rather than the fixture
    # above, which turns operator SMS on for every other test in the file.
    monkeypatch.delenv("SUPER_ADMIN_SMS_WITHDRAWAL_AUTO_ENABLED", raising=False)
    monkeypatch.delenv("SUPER_ADMIN_SMS_ENABLED", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.super_admin_sms_withdrawal_auto_enabled is True
    # And the master switch still gates it, so a deployment that has never
    # turned on operator SMS stays silent.
    assert settings.super_admin_sms_enabled is False


# --- Nothing a merchant should see ----------------------------------------


def test_the_automatic_alert_leaks_nothing_about_the_destination(
    fake_client, fake_resend, monkeypatch
):
    """Same rule as the request alert: the destination, the account name
    and the bank are decided by opening the queue, and are a worse thing
    to leave sitting in a mailbox."""
    _enable_automation(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    _request_withdrawal(merchant_id, user_id, "45000")

    body = _sms(fake_client, "admin_withdrawal_auto")[0]["body"]
    for leak in ("255700000000", "Jane Doe", "MPESA"):
        assert leak not in body


def test_the_automatic_alert_is_addressed_to_an_operator_not_the_merchant(
    fake_client, fake_resend, monkeypatch
):
    _enable_automation(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    _request_withdrawal(merchant_id, user_id, "45000")

    row = _sms(fake_client, "admin_withdrawal_auto")[0]
    assert row["recipient_role"] == "super_admin"
    # The merchant's own completion SMS is a separate row and is
    # unaffected by any of this.
    assert row["purpose"] != "withdrawal_complete"


# --- The message itself ---------------------------------------------------


def test_the_message_costs_one_segment_for_a_normal_business_name():
    """Measured, not assumed. The same property the request alert has."""
    body = render_withdrawal_auto_admin(
        business_name="BennyWiFi", amount=Decimal(45000), reference="A223A1FE"
    )

    cost = message_cost(body)
    assert cost["encoding"] == "GSM-7"
    assert cost["segments"] == 1


def test_a_very_long_business_name_still_costs_at_most_two_segments():
    body = render_withdrawal_auto_admin(
        business_name="K" * 60,
        amount=Decimal("1234567.89"),
        reference="DIS-20261031-A223A1FE",
    )

    assert message_cost(body)["segments"] <= 2


def test_the_amount_never_passes_through_a_float():
    body = render_withdrawal_auto_admin(
        business_name="BennyWiFi", amount=Decimal("1000.10"), reference="A223A1FE"
    )

    assert "1,000.10" in body


# --- The queue actually sends it ------------------------------------------


def test_the_dispatcher_knows_about_the_new_purpose():
    """The bug that shipped with the first operator alerts: a purpose
    absent from the dispatch list leaves its rows queued forever, looking
    perfectly healthy in the database. Twenty-nine tests passed with that
    bug present because they all stopped at the queue."""
    from app.services.sms_dispatch import DISPATCHED_PURPOSES

    assert "admin_withdrawal_auto" in DISPATCHED_PURPOSES


def test_the_idempotency_key_fits_the_providers_limit(fake_client, fake_resend, monkeypatch):
    """The other bug that shipped with them: a 75-character key the
    provider rejected five times in a row, identically."""
    _enable_automation(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    _request_withdrawal(merchant_id, user_id, "45000")

    key = _sms(fake_client, "admin_withdrawal_auto")[0]["idempotency_key"]
    assert len(key) <= 64
    assert key.isascii()


def test_the_same_payout_never_alerts_twice(fake_client, fake_resend, monkeypatch):
    """A client retry after a timeout returns the stored response rather
    than re-running the handler, so one payout is one alert."""
    _enable_automation(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    key = str(uuid.uuid4())
    body = {
        "merchant_id": str(merchant_id),
        "amount": "45000",
        "destination_name": "Jane Doe",
        "destination_identifier": "+255700000000",
        "destination_code": "MPESA",
    }
    headers = {**auth_headers(user_id), "Idempotency-Key": key}
    client.post("/v1/disbursements/mobile-money", headers=headers, json=body)
    client.post("/v1/disbursements/mobile-money", headers=headers, json=body)

    assert len(_sms(fake_client, "admin_withdrawal_auto")) == 1


# --- A failed alert never costs a payout ----------------------------------


def test_a_failing_alert_does_not_fail_the_withdrawal(fake_client, fake_resend, monkeypatch):
    """The payout is committed before any of this runs. A message about it
    must not be able to undo it."""
    _enable_automation(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    import app.services.disbursements as disbursements_service

    def explode(*args, **kwargs):
        raise RuntimeError("sms provider is down")

    monkeypatch.setattr(disbursements_service, "enqueue_admin_auto_withdrawal_sms", explode)

    data = _request_withdrawal(merchant_id, user_id, "45000")

    assert data["auto_approved"] is True
    assert data["status"] in ("PROCESSING", "SUCCESS")


# --- A payout that was authorized but never went -------------------------


def _fail_the_provider(monkeypatch):
    from app.services.selcom_business.client import SelcomBusinessResult
    from app.services.selcom_business.mock_client import MockSelcomBusinessClient

    async def _fail(self, *, trans_id: str, **kwargs):
        return SelcomBusinessResult(
            transaction_id=trans_id, status="failed", failure_reason="Invalid destination account"
        )

    monkeypatch.setattr(MockSelcomBusinessClient, "process_transaction", _fail)


def test_a_failed_automatic_payout_is_never_announced_as_paid(
    fake_client, fake_resend, monkeypatch
):
    """auto_approved is set inside the advisory lock, the instant
    eligibility is decided - which is BEFORE the provider is called. So a
    payout that was authorized and then failed still carries the flag.
    Gating on it alone would email an operator to say money went out when
    it did not, which is the one thing these messages must never say
    wrongly."""
    _fail_the_provider(monkeypatch)
    _enable_automation(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    data = _request_withdrawal(merchant_id, user_id, "45000")

    assert data["status"] == "FAILED"
    assert data["auto_approved"] is True, "the precondition that makes this test worth having"
    assert _emails(fake_resend, "paid automatically") == []
    assert _sms(fake_client, "admin_withdrawal_auto") == []


def test_a_failed_automatic_payout_still_reaches_an_operator(
    fake_client, fake_resend, monkeypatch
):
    """Silence would be worse here than anywhere else: nobody is waiting
    for it in the approval queue, and an unattended payout that failed is
    not something to discover from a dashboard days later."""
    _fail_the_provider(monkeypatch)
    _enable_automation(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    _request_withdrawal(merchant_id, user_id, "45000")

    alerts = [
        c
        for c in fake_resend.calls
        if "did not reach the provider" in str(c.get("subject", "")).lower()
        or "did not reach the provider" in str(c.get("html", "")).lower()
    ]
    assert alerts, "a failed automatic payout must tell somebody"


def test_a_failed_automatic_payout_does_not_fail_the_request(fake_client, fake_resend, monkeypatch):
    """The withdrawal request itself succeeded; the payout is what
    failed. The merchant must not be told their request broke."""
    _fail_the_provider(monkeypatch)
    _enable_automation(fake_client, monkeypatch)
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id)

    data = _request_withdrawal(merchant_id, user_id, "45000")

    assert data["status"] == "FAILED"
