"""A sandbox payout must stay inside the sandbox.

Two places treated `environment` as decoration, and both moved real
money:

  * dispatch asked SELCOM_BUSINESS_MODE which Selcom to use. Any
    deployment that pays real withdrawals runs that in `live`, so a
    payout marked `sandbox` was sent to Selcom production - a real
    payment, to a real phone number.
  * funding credited the sandbox payout wallet but debited the LIVE
    Collections balance, because the debit leg never passed the
    environment through.

Both are one argument. Tests, because one argument is exactly the kind
of thing that gets dropped again - it was dropped once already when key
rotation stopped carrying key_type.
"""

import uuid
from decimal import Decimal

import pytest

from app.services.ledger import post_payout_wallet_funding
from app.services.selcom_business.client import (
    SelcomBusinessMisconfiguredError,
    get_selcom_business_client,
)

SANDBOX_URL = "https://sandbox.example.invalid"
LIVE_URL = "https://live.example.invalid"


@pytest.fixture(autouse=True)
def _clean_client_cache():
    get_selcom_business_client.cache_clear()
    yield
    get_selcom_business_client.cache_clear()


@pytest.fixture
def live_mode(monkeypatch):
    """A deployment configured the way production actually is."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SELCOM_BUSINESS_MODE", "live")
    monkeypatch.setenv("SELCOM_BUSINESS_PRODUCTION_BASE_URL", LIVE_URL)
    monkeypatch.setenv("SELCOM_BUSINESS_SANDBOX_BASE_URL", SANDBOX_URL)
    yield
    get_settings.cache_clear()


def test_a_sandbox_payout_never_reaches_production_selcom(live_mode):
    """The bug, stated as a test. The deployment says live; the payout
    says sandbox; the payout wins."""
    client = get_selcom_business_client("sandbox")
    assert client._base_url == SANDBOX_URL


def test_a_live_payout_reaches_production_selcom(live_mode):
    assert get_selcom_business_client("live")._base_url == LIVE_URL


def test_a_withdrawal_still_follows_the_deployment_mode(live_mode):
    """Withdrawals have no environment of their own and must keep
    behaving exactly as they did - they are the live money path that
    works today."""
    assert get_selcom_business_client()._base_url == LIVE_URL
    assert get_selcom_business_client(None)._base_url == LIVE_URL


def test_an_unknown_environment_is_refused_rather_than_guessed(live_mode):
    with pytest.raises(SelcomBusinessMisconfiguredError):
        get_selcom_business_client("staging")


def test_a_live_payout_is_not_answered_by_sandbox_when_the_mode_is_sandbox(monkeypatch):
    """The mirror of the first test. A sandbox Selcom happily reports
    COMPLETED for money nobody sent; crediting a live payout on that
    answer would tell a merchant they were paid when they were not."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SELCOM_BUSINESS_MODE", "sandbox")
    monkeypatch.setenv("SELCOM_BUSINESS_PRODUCTION_BASE_URL", LIVE_URL)
    monkeypatch.setenv("SELCOM_BUSINESS_SANDBOX_BASE_URL", SANDBOX_URL)
    try:
        assert get_selcom_business_client("live")._base_url == LIVE_URL
    finally:
        get_settings.cache_clear()


# --- funding --------------------------------------------------------------


def _accounts(fake, merchant_id):
    return {
        (a["purpose"], a.get("environment")): a
        for a in fake.table("ledger_accounts")._table.rows
        if a.get("merchant_id") == str(merchant_id)
    }


def test_funding_a_sandbox_wallet_does_not_touch_the_live_balance(fake_client):
    """The whole point. Before the fix this debited merchant_wallet in
    `live` and the merchant's real settled money left their balance."""
    merchant_id = uuid.uuid4()
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Merchant Wallet (test)",
            "purpose": "merchant_wallet",
            "account_type": "liability",
            "currency": "TZS",
            "environment": "live",
            "balance": "100000.00",
        },
    )

    # A real transactions row: ledger_entries has a foreign key to it, and
    # without one this fails on the FK before it ever reaches the balance
    # check the test is actually about.
    transaction_id = uuid.UUID(
        fake_client.seed(
            "transactions",
            {
                "merchant_id": str(merchant_id),
                "type": "adjustment",
                "status": "successful",
                "currency": "TZS",
                "gross_amount": "10000.00",
                "net_amount": "10000.00",
            },
        )["id"]
    )

    with pytest.raises(Exception) as excinfo:
        post_payout_wallet_funding(
            fake_client,
            transaction_id=transaction_id,
            merchant_id=merchant_id,
            amount=Decimal("10000.00"),
            currency="TZS",
            environment="sandbox",
        )

    # Refused, because the SANDBOX wallet holds nothing - not silently
    # served from the live one.
    assert "INSUFFICIENT_BALANCE" in str(excinfo.value).upper() or "BALANCE" in str(excinfo.value).upper()

    live_wallet = _accounts(fake_client, merchant_id)[("merchant_wallet", "live")]
    assert str(live_wallet["balance"]) == "100000.00", "the live balance must be untouched"
