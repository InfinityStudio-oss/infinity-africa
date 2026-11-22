"""A funding code must outlive the page that asked for it.

The code lives on the server; the box to type it into lived only in
React state. A merchant who requested a code and then reloaded - or
closed the form, or opened their email in the same tab - had a valid
code in their inbox and nowhere to put it, and nothing told them
anything was outstanding.

That is not hypothetical. The first two real funding attempts both died
exactly there: emails sent, attempts = 0, money never moved, and the
page showed a zero balance with no sign anything was pending.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.withdrawal_otp import PAYOUT_FUNDING, find_live_challenge
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_real_mail(monkeypatch):
    monkeypatch.setattr(resend.Emails, "send", lambda params: {"id": "test"})


def _ready(fake_client):
    merchant_id = uuid.UUID(create_merchant(fake_client, contact_email="owner@shop.co.tz")["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    fake_client.seed(
        "merchant_payout_settings",
        {
            "merchant_id": str(merchant_id),
            "sandbox_enabled": True,
            "live_enabled": False,
            "paused": False,
            "version": 1,
        },
    )
    return merchant_id, user_id


def _challenge(fake_client, merchant_id, user_id, **overrides):
    row = {
        "merchant_id": str(merchant_id),
        "requested_by": str(user_id),
        "purpose": PAYOUT_FUNDING,
        "withdrawal_payload": {"amount": "5000", "currency": "TZS", "environment": "sandbox"},
        "payload_hash": "h",
        "otp_hash": "h",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "max_attempts": 5,
    }
    row.update(overrides)
    return fake_client.seed("merchant_withdrawal_otp_challenges", row)


def test_the_wallet_reports_an_outstanding_code(fake_client):
    """The fix. Without this the page cannot offer the box again."""
    merchant_id, user_id = _ready(fake_client)
    challenge = _challenge(fake_client, merchant_id, user_id)

    response = client.get("/v1/merchant/payout-wallet", headers=auth_headers(user_id))

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["pending_funding_challenge_id"] == challenge["id"]
    assert body["pending_funding_amount"] == "5000"
    # Masked, never the full address.
    assert body["pending_funding_masked_email"]
    assert "@" in body["pending_funding_masked_email"]


def test_no_outstanding_code_reports_nothing(fake_client):
    _merchant_id, user_id = _ready(fake_client)

    body = client.get("/v1/merchant/payout-wallet", headers=auth_headers(user_id)).json()["data"]

    assert body["pending_funding_challenge_id"] is None


def test_a_used_code_is_not_offered_again(fake_client):
    merchant_id, user_id = _ready(fake_client)
    _challenge(fake_client, merchant_id, user_id, used_at=datetime.now(timezone.utc).isoformat())

    assert find_live_challenge(fake_client, merchant_id=merchant_id, purpose=PAYOUT_FUNDING) is None


def test_a_locked_code_is_not_offered_again(fake_client):
    merchant_id, user_id = _ready(fake_client)
    _challenge(fake_client, merchant_id, user_id, locked_at=datetime.now(timezone.utc).isoformat())

    assert find_live_challenge(fake_client, merchant_id=merchant_id, purpose=PAYOUT_FUNDING) is None


def test_an_expired_code_is_not_offered_again(fake_client):
    """A dead challenge must never resurrect a code box - the merchant
    would type a code that cannot work and be told it is invalid."""
    merchant_id, user_id = _ready(fake_client)
    _challenge(
        fake_client,
        merchant_id,
        user_id,
        expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
    )

    assert find_live_challenge(fake_client, merchant_id=merchant_id, purpose=PAYOUT_FUNDING) is None


def test_a_withdrawal_code_is_not_a_funding_code(fake_client):
    merchant_id, user_id = _ready(fake_client)
    _challenge(fake_client, merchant_id, user_id, purpose="withdrawal")

    assert find_live_challenge(fake_client, merchant_id=merchant_id, purpose=PAYOUT_FUNDING) is None
