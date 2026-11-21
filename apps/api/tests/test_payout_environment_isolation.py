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

from app.services.ledger import post_payout_settlement, post_payout_wallet_funding
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


# --- the sandbox float ----------------------------------------------------


def _txn(fake_client, merchant_id, amount="10000.00"):
    return uuid.UUID(
        fake_client.seed(
            "transactions",
            {
                "merchant_id": str(merchant_id),
                "type": "adjustment",
                "status": "successful",
                "currency": "TZS",
                "gross_amount": amount,
                "net_amount": amount,
            },
        )["id"]
    )


def test_sandbox_funding_mints_play_money_instead_of_spending_real_money(fake_client):
    """The other half of the fix. Sandbox funding works again - but the
    shillings come from the platform float, not from anyone's balance."""
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
            "balance": "105240.13",
        },
    )

    post_payout_wallet_funding(
        fake_client,
        transaction_id=_txn(fake_client, merchant_id),
        merchant_id=merchant_id,
        amount=Decimal("10000.00"),
        currency="TZS",
        environment="sandbox",
    )

    accounts = _accounts(fake_client, merchant_id)
    assert str(accounts[("merchant_wallet", "live")]["balance"]) == "105240.13", (
        "the live Collections balance must not move when sandbox is funded"
    )
    assert Decimal(str(accounts[("payout_available", "sandbox")]["balance"])) == Decimal("10000.00")

    # The counter-entry: a platform account, negative by exactly what was
    # minted, in sandbox.
    floats = [
        a
        for a in fake_client.table("ledger_accounts")._table.rows
        if a.get("purpose") == "sandbox_float"
    ]
    assert len(floats) == 1
    assert floats[0].get("merchant_id") is None
    assert floats[0].get("environment") == "sandbox"
    assert Decimal(str(floats[0]["balance"])) == Decimal("-10000.00")


def test_live_funding_still_comes_out_of_the_merchants_own_balance(fake_client):
    """Unchanged, and it has to be: this is the real money path."""
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
            "balance": "50000.00",
        },
    )

    post_payout_wallet_funding(
        fake_client,
        transaction_id=_txn(fake_client, merchant_id),
        merchant_id=merchant_id,
        amount=Decimal("10000.00"),
        currency="TZS",
        environment="live",
    )

    accounts = _accounts(fake_client, merchant_id)
    assert Decimal(str(accounts[("merchant_wallet", "live")]["balance"])) == Decimal("40000.00")
    assert Decimal(str(accounts[("payout_available", "live")]["balance"])) == Decimal("10000.00")
    assert not [
        a for a in fake_client.table("ledger_accounts")._table.rows if a.get("purpose") == "sandbox_float"
    ], "a live transfer must never touch the sandbox float"


def test_a_settled_sandbox_payout_books_no_live_revenue(fake_client):
    """Play money must not reach the two accounts the business is read
    from. Both platform legs were defaulting to live."""
    merchant_id = uuid.uuid4()
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Payout Reserved (test)",
            "purpose": "payout_reserved",
            "account_type": "liability",
            "currency": "TZS",
            "environment": "sandbox",
            "balance": "1030.00",
        },
    )

    post_payout_settlement(
        fake_client,
        transaction_id=_txn(fake_client, merchant_id, "1030.00"),
        merchant_id=merchant_id,
        amount=Decimal("1000.00"),
        fee_amount=Decimal("30.00"),
        currency="TZS",
        environment="sandbox",
    )

    platform = {
        (a["purpose"], a.get("environment")): Decimal(str(a["balance"]))
        for a in fake_client.table("ledger_accounts")._table.rows
        if a.get("merchant_id") is None
    }
    assert platform.get(("platform_revenue", "sandbox")) == Decimal("30.00")
    # settlement_clearing is an asset, and an asset decreases on a credit
    # (post_ledger_entries: assets and expenses increase on debit). The
    # sign is the existing convention and identical for a live payout;
    # what this test is about is the environment it landed in.
    assert platform.get(("settlement_clearing", "sandbox")) == Decimal("-1000.00")
    assert ("platform_revenue", "live") not in platform, "a sandbox fee must not reach live revenue"
    assert ("settlement_clearing", "live") not in platform
