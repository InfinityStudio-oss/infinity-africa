"""Creating a payout: who may, to whom, for how much, and funded first.

The invariants worth stating plainly, because each is a way real money
goes wrong:

  * an absent settings row means NO. Default-off has to fail closed, or
    the feature turns itself on for every merchant at once.
  * a payout reaches only a beneficiary the merchant had approved, in the
    same environment.
  * a payout that gets a row has its funds already reserved. There is no
    window where the worker could find a queued payout with nothing
    behind it.
  * the Collections balance is never reachable, however large it is.

What these do NOT prove is concurrency: the fake is single-threaded, so
two callers racing the same balance cannot be simulated. The loser-side
behaviour IS covered (test_a_payout_that_loses_the_race...), by making
the reservation fail the way a lost race makes it fail.
"""

import uuid
from decimal import Decimal

import pytest

from app.core.errors import (
    ConflictError,
    InsufficientBalanceError,
    NotFoundError,
    ValidationAPIError,
)
from app.services.ledger import post_payout_wallet_funding
from app.services.payouts import (
    PayoutSettings,
    create_payout,
    load_payout_settings,
    quote_fee,
)

CUR = "TZS"


def _merchant(fake_client):
    return uuid.UUID(
        fake_client.seed("merchants", {"business_name": "Test", "contact_email": f"{uuid.uuid4()}@e.com"})["id"]
    )


def _settings(fake_client, merchant_id, **overrides):
    row = {
        "merchant_id": str(merchant_id),
        "sandbox_enabled": True,
        "live_enabled": True,
        "paused": False,
        "paused_reason": None,
        "per_payout_limit_tzs": None,
        "daily_limit_tzs": None,
        "fee_flat_tzs": "0",
        "fee_percentage": "0",
        "version": 1,
    }
    row.update(overrides)
    return fake_client.seed("merchant_payout_settings", row)


def _beneficiary(fake_client, merchant_id, environment="live", status="active"):
    return fake_client.seed(
        "payout_beneficiaries",
        {
            "merchant_id": str(merchant_id),
            "environment": environment,
            "name": "Jane Doe",
            "method": "MOBILE_MONEY",
            "destination_code": "MPESA",
            "destination_identifier": "255700000000",
            "status": status,
        },
    )


def _fund(fake_client, merchant_id, amount, environment="live"):
    # One merchant_wallet PER ENVIRONMENT. The unique index is on
    # (merchant_id, purpose, currency, environment), so a sandbox wallet
    # is a distinct legal row, not the duplicate this helper used to
    # assume - and it has to be, because funding now takes both legs from
    # the same environment. Funding a sandbox payout wallet out of the
    # live Collections balance was the bug: real settled money, moved
    # into a wallet whose payouts are make-believe.
    existing = next(
        (
            a
            for a in fake_client.table("ledger_accounts")._table.rows
            if a.get("merchant_id") == str(merchant_id)
            and a.get("purpose") == "merchant_wallet"
            and (a.get("environment") or "live") == environment
        ),
        None,
    )
    if existing:
        existing["balance"] = str(Decimal(str(existing["balance"])) + Decimal(str(amount)))
    else:
        fake_client.seed(
            "ledger_accounts",
            {
                "merchant_id": str(merchant_id),
                "name": "Merchant Wallet (test)",
                "account_type": "liability",
                "purpose": "merchant_wallet",
                "currency": CUR,
                "environment": environment,
                "balance": str(amount),
            },
        )
    tx = fake_client.seed(
        "transactions",
        {
            "merchant_id": str(merchant_id),
            "type": "payout_wallet_funding",
            "status": "successful",
            "currency": CUR,
            "gross_amount": "0",
            "net_amount": "0",
        },
    )["id"]
    post_payout_wallet_funding(
        fake_client,
        transaction_id=uuid.UUID(tx),
        merchant_id=merchant_id,
        amount=Decimal(str(amount)),
        currency=CUR,
        environment=environment,
    )


def _ready(fake_client, *, funded="100000.00", environment="live", **settings_overrides):
    mid = _merchant(fake_client)
    _settings(fake_client, mid, **settings_overrides)
    ben = _beneficiary(fake_client, mid, environment=environment)
    _fund(fake_client, mid, funded, environment=environment)
    return mid, uuid.UUID(ben["id"])


def _bal(fake_client, merchant_id, purpose, environment="live"):
    row = next(
        (
            a
            for a in fake_client.table("ledger_accounts")._table.rows
            if a.get("merchant_id") == str(merchant_id)
            and a.get("purpose") == purpose
            and a.get("environment", "live") == environment
        ),
        None,
    )
    return Decimal(str(row["balance"])) if row else None


# --- access ---------------------------------------------------------------


def test_no_settings_row_means_no_access(fake_client):
    """The default state for every merchant. It must fail closed."""
    mid = _merchant(fake_client)
    ben = _beneficiary(fake_client, mid)
    _fund(fake_client, mid, "100000.00")

    assert load_payout_settings(fake_client, merchant_id=mid, environment="live") is None

    with pytest.raises(ValidationAPIError, match="not enabled"):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=uuid.UUID(ben["id"]),
            amount=Decimal("1000.00"),
            currency=CUR,
            api_key_id=None,
        )


def test_sandbox_enabled_does_not_enable_live(fake_client):
    """Two independent switches. A merchant testing must not be live."""
    mid = _merchant(fake_client)
    _settings(fake_client, mid, sandbox_enabled=True, live_enabled=False)
    ben = _beneficiary(fake_client, mid, environment="live")
    _fund(fake_client, mid, "100000.00")

    with pytest.raises(ValidationAPIError, match="not enabled"):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=uuid.UUID(ben["id"]),
            amount=Decimal("1000.00"),
            currency=CUR,
            api_key_id=None,
        )


def test_a_pause_refuses_new_payouts(fake_client):
    mid, ben = _ready(fake_client, paused=True, paused_reason="provider incident")

    with pytest.raises(ConflictError, match="paused"):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=ben,
            amount=Decimal("1000.00"),
            currency=CUR,
            api_key_id=None,
        )


def test_a_pause_reserves_nothing(fake_client):
    mid, ben = _ready(fake_client, paused=True)
    before = _bal(fake_client, mid, "payout_available")

    with pytest.raises(ConflictError):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=ben,
            amount=Decimal("1000.00"),
            currency=CUR,
            api_key_id=None,
        )

    assert _bal(fake_client, mid, "payout_available") == before
    assert fake_client.table("payouts")._table.rows == []


# --- beneficiaries --------------------------------------------------------


def test_another_merchants_beneficiary_is_not_found(fake_client):
    """404, not 403. Telling a key that an id exists but belongs to
    someone else is an enumeration oracle over other merchants'
    destinations."""
    mine, _ = _ready(fake_client)
    theirs = _merchant(fake_client)
    their_ben = _beneficiary(fake_client, theirs)

    with pytest.raises(NotFoundError):
        create_payout(
            fake_client,
            merchant_id=mine,
            environment="live",
            beneficiary_id=uuid.UUID(their_ben["id"]),
            amount=Decimal("1000.00"),
            currency=CUR,
            api_key_id=None,
        )


def test_a_sandbox_beneficiary_cannot_be_paid_live(fake_client):
    mid = _merchant(fake_client)
    _settings(fake_client, mid)
    sandbox_ben = _beneficiary(fake_client, mid, environment="sandbox")
    _fund(fake_client, mid, "100000.00")

    with pytest.raises(NotFoundError):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=uuid.UUID(sandbox_ben["id"]),
            amount=Decimal("1000.00"),
            currency=CUR,
            api_key_id=None,
        )


def test_a_disabled_beneficiary_cannot_be_paid(fake_client):
    mid = _merchant(fake_client)
    _settings(fake_client, mid)
    ben = _beneficiary(fake_client, mid, status="disabled")
    _fund(fake_client, mid, "100000.00")

    with pytest.raises(NotFoundError):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=uuid.UUID(ben["id"]),
            amount=Decimal("1000.00"),
            currency=CUR,
            api_key_id=None,
        )


# --- pricing --------------------------------------------------------------


def test_fee_is_flat_plus_percentage():
    settings = PayoutSettings(
        enabled=True,
        paused=False,
        paused_reason=None,
        per_payout_limit_tzs=None,
        daily_limit_tzs=None,
        fee_flat_tzs=Decimal(500),
        fee_percentage=Decimal("1.5"),
    )

    assert quote_fee(settings, Decimal("10000.00")) == Decimal("650.00")


def test_fee_rounds_half_up_not_down():
    """A fee rounded DOWN is revenue lost on every single payout. The
    opposite direction from a withdrawal ceiling, which rounds down
    because a lower ceiling is the safe side there."""
    settings = PayoutSettings(
        enabled=True,
        paused=False,
        paused_reason=None,
        per_payout_limit_tzs=None,
        daily_limit_tzs=None,
        fee_flat_tzs=Decimal(0),
        fee_percentage=Decimal(1),
    )

    assert quote_fee(settings, Decimal("1005.00")) == Decimal("10.05")
    assert quote_fee(settings, Decimal("1000.50")) == Decimal("10.01")


def test_the_fee_is_reserved_along_with_the_amount(fake_client):
    """A merchant must have the fee in hand at reservation time, not
    discover at settlement that they cannot cover it."""
    mid, ben = _ready(fake_client, funded="10000.00", fee_flat_tzs="500")

    payout = create_payout(
        fake_client,
        merchant_id=mid,
        environment="live",
        beneficiary_id=ben,
        amount=Decimal("1000.00"),
        currency=CUR,
        api_key_id=None,
    )

    assert Decimal(payout["fee_amount"]) == Decimal("500.00")
    assert Decimal(payout["total_debit"]) == Decimal("1500.00")
    assert _bal(fake_client, mid, "payout_reserved") == Decimal("1500.00")
    assert _bal(fake_client, mid, "payout_available") == Decimal("8500.00")


def test_per_payout_limit_is_enforced(fake_client):
    mid, ben = _ready(fake_client, per_payout_limit_tzs="5000")

    with pytest.raises(ValidationAPIError, match="per-payout limit"):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=ben,
            amount=Decimal("5000.01"),
            currency=CUR,
            api_key_id=None,
        )


def test_a_zero_or_negative_amount_is_refused(fake_client):
    mid, ben = _ready(fake_client)

    for bad in (Decimal(0), Decimal(-100)):
        with pytest.raises(ValidationAPIError):
            create_payout(
                fake_client,
                merchant_id=mid,
                environment="live",
                beneficiary_id=ben,
                amount=bad,
                currency=CUR,
                api_key_id=None,
            )


# --- funding --------------------------------------------------------------


def test_a_created_payout_is_already_funded(fake_client):
    """No window exists where the worker could find a funded payout with
    nothing reserved behind it.

    `processing` is the marker: authorize_payout sets it in the same
    transaction as the reservation, so the status and the money are
    always in step and a second authorisation cannot reserve again.
    """
    mid, ben = _ready(fake_client, funded="50000.00")

    payout = create_payout(
        fake_client,
        merchant_id=mid,
        environment="live",
        beneficiary_id=ben,
        amount=Decimal("20000.00"),
        currency=CUR,
        api_key_id=None,
    )

    assert payout["status"] == "processing"
    assert _bal(fake_client, mid, "payout_reserved") == Decimal("20000.00")


def test_a_payout_beyond_the_wallet_is_refused(fake_client):
    mid, ben = _ready(fake_client, funded="1000.00")

    with pytest.raises(InsufficientBalanceError, match="Fund the payout wallet"):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=ben,
            amount=Decimal("1000.01"),
            currency=CUR,
            api_key_id=None,
        )

    assert fake_client.table("payouts")._table.rows == []


def test_the_collections_balance_is_unreachable_however_large(fake_client):
    """The single most important assertion about this API. A merchant
    with a million in Collections and a thousand in the Payout Wallet can
    send a thousand."""
    mid = _merchant(fake_client)
    _settings(fake_client, mid)
    ben = _beneficiary(fake_client, mid)
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(mid),
            "name": "Merchant Wallet (test)",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": CUR,
            "balance": "1000000.00",
        },
    )
    tx = fake_client.seed(
        "transactions",
        {
            "merchant_id": str(mid), "type": "f", "status": "successful",
            "currency": CUR, "gross_amount": "0", "net_amount": "0",
        },
    )["id"]
    post_payout_wallet_funding(
        fake_client,
        transaction_id=uuid.UUID(tx),
        merchant_id=mid,
        amount=Decimal("1000.00"),
        currency=CUR,
        environment="live",
    )

    with pytest.raises(InsufficientBalanceError):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=uuid.UUID(ben["id"]),
            amount=Decimal("1001.00"),
            currency=CUR,
            api_key_id=None,
        )

    assert _bal(fake_client, mid, "merchant_wallet") == Decimal("999000.00")


def test_a_payout_that_loses_the_race_is_cancelled_not_left_queued(fake_client, monkeypatch):
    """The friendly balance check can pass and the reservation still fail,
    when another payout takes the funds in between. The row must not
    survive as `queued`: the worker would dispatch money nothing is
    holding.

    Modelled by making the pre-check read a balance the wallet does not
    have, which is exactly what a stale read IS - the check sees funds
    that another payout has already taken. authorize_payout then refuses
    under its lock, which is the authoritative answer.
    """
    mid, ben = _ready(fake_client, funded="500.00")

    import app.services.payouts as payouts_module

    monkeypatch.setattr(
        payouts_module,
        "get_payout_wallet_balances",
        lambda *_a, **_k: (Decimal("999999.00"), Decimal(0)),
    )

    with pytest.raises(InsufficientBalanceError):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=ben,
            amount=Decimal("1000.00"),
            currency=CUR,
            api_key_id=None,
        )

    rows = fake_client.table("payouts")._table.rows
    assert len(rows) == 1
    assert rows[0]["status"] == "cancelled"
    assert rows[0]["failure_code"] == "insufficient_funds"


# --- the record ------------------------------------------------------------


def test_the_provider_reference_is_set_once_at_creation(fake_client):
    """It is the provider's idempotency handle. If it were regenerated on
    retry, a retry after an ambiguous dispatch would start a second
    payout instead of asking about the first."""
    mid, ben = _ready(fake_client)

    payout = create_payout(
        fake_client,
        merchant_id=mid,
        environment="live",
        beneficiary_id=ben,
        amount=Decimal("1000.00"),
        currency=CUR,
        api_key_id=None,
    )

    assert payout["provider_reference"]
    assert payout["provider_reference"].startswith("PO-")


def test_two_payouts_get_different_references(fake_client):
    mid, ben = _ready(fake_client)
    refs = {
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=ben,
            amount=Decimal("100.00"),
            currency=CUR,
            api_key_id=None,
        )["provider_reference"]
        for _ in range(5)
    }

    assert len(refs) == 5


def test_the_calling_key_is_recorded(fake_client):
    """So revoking a key can be followed by "what did it send"."""
    mid, ben = _ready(fake_client)
    key_id = uuid.uuid4()

    payout = create_payout(
        fake_client,
        merchant_id=mid,
        environment="live",
        beneficiary_id=ben,
        amount=Decimal("1000.00"),
        currency=CUR,
        api_key_id=key_id,
    )

    assert payout["api_key_id"] == str(key_id)


# --- the rolling 24h limit ------------------------------------------------
#
# Decided inside authorize_payout, under a per-merchant advisory lock,
# together with the reservation. These tests prove the DECISION: which
# payouts the limit refuses, what counts against the allowance, and that
# a refusal reserves nothing. They prove nothing about the race itself -
# the fake is single-threaded, so there is never a second caller for the
# lock to make wait. That needs real Postgres on two connections.


def test_payouts_inside_the_daily_limit_are_allowed(fake_client):
    mid, ben = _ready(fake_client, funded="100000.00", daily_limit_tzs="10000")

    for _ in range(4):
        payout = create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=ben,
            amount=Decimal("2500.00"),
            currency=CUR,
            api_key_id=None,
        )
        assert payout["status"] == "processing"

    assert _bal(fake_client, mid, "payout_reserved") == Decimal("10000.00")


def test_the_payout_that_crosses_the_daily_limit_is_refused(fake_client):
    mid, ben = _ready(fake_client, funded="100000.00", daily_limit_tzs="10000")
    for _ in range(4):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=ben,
            amount=Decimal("2500.00"),
            currency=CUR,
            api_key_id=None,
        )

    with pytest.raises(ConflictError, match="24-hour"):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=ben,
            amount=Decimal("0.01"),
            currency=CUR,
            api_key_id=None,
        )

    # The refusal cost nothing: still exactly the four that were allowed.
    assert _bal(fake_client, mid, "payout_reserved") == Decimal("10000.00")


def test_a_limit_refusal_cancels_the_row_rather_than_leaving_it_queued(fake_client):
    mid, ben = _ready(fake_client, funded="100000.00", daily_limit_tzs="1000")

    with pytest.raises(ConflictError):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=ben,
            amount=Decimal("5000.00"),
            currency=CUR,
            api_key_id=None,
        )

    rows = fake_client.table("payouts")._table.rows
    assert len(rows) == 1
    assert rows[0]["status"] == "cancelled"
    assert rows[0]["failure_code"] == "daily_limit_exceeded"


def test_the_fee_counts_against_the_daily_limit(fake_client):
    """total_debit, not amount. A limit that ignored fees would let a
    merchant exceed it by exactly the fees they paid."""
    mid, ben = _ready(
        fake_client, funded="100000.00", daily_limit_tzs="1000", fee_flat_tzs="100"
    )

    with pytest.raises(ConflictError):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=ben,
            amount=Decimal("950.00"),  # 950 + 100 fee = 1050 > 1000
            currency=CUR,
            api_key_id=None,
        )


def test_refunded_payouts_do_not_count_against_the_limit(fake_client):
    """failed, cancelled and reversed gave their funds back, so they are
    not money the merchant has sent."""
    mid, ben = _ready(fake_client, funded="100000.00", daily_limit_tzs="5000")
    spent = create_payout(
        fake_client,
        merchant_id=mid,
        environment="live",
        beneficiary_id=ben,
        amount=Decimal("5000.00"),
        currency=CUR,
        api_key_id=None,
    )

    fake_client.table("payouts").update({"status": "failed"}).eq("id", spent["id"]).execute()

    allowed = create_payout(
        fake_client,
        merchant_id=mid,
        environment="live",
        beneficiary_id=ben,
        amount=Decimal("5000.00"),
        currency=CUR,
        api_key_id=None,
    )
    assert allowed["status"] == "processing"


def test_in_flight_payouts_do_count_against_the_limit(fake_client):
    """processing and needs_reconciliation are money that is out of the
    door until proven otherwise. Not counting them would let a merchant
    exceed the limit during exactly the window where nobody knows what
    happened."""
    mid, ben = _ready(fake_client, funded="100000.00", daily_limit_tzs="5000")
    sent = create_payout(
        fake_client,
        merchant_id=mid,
        environment="live",
        beneficiary_id=ben,
        amount=Decimal("3000.00"),
        currency=CUR,
        api_key_id=None,
    )
    fake_client.table("payouts").update({"status": "needs_reconciliation"}).eq(
        "id", sent["id"]
    ).execute()

    with pytest.raises(ConflictError, match="24-hour"):
        create_payout(
            fake_client,
            merchant_id=mid,
            environment="live",
            beneficiary_id=ben,
            amount=Decimal("2500.00"),
            currency=CUR,
            api_key_id=None,
        )


def test_the_limit_is_per_environment(fake_client):
    """Sandbox traffic must not consume a live allowance."""
    mid = _merchant(fake_client)
    _settings(fake_client, mid, daily_limit_tzs="5000")
    live_ben = _beneficiary(fake_client, mid, environment="live")
    sandbox_ben = _beneficiary(fake_client, mid, environment="sandbox")
    _fund(fake_client, mid, "50000.00", environment="live")
    _fund(fake_client, mid, "50000.00", environment="sandbox")

    create_payout(
        fake_client,
        merchant_id=mid,
        environment="sandbox",
        beneficiary_id=uuid.UUID(sandbox_ben["id"]),
        amount=Decimal("5000.00"),
        currency=CUR,
        api_key_id=None,
    )

    live = create_payout(
        fake_client,
        merchant_id=mid,
        environment="live",
        beneficiary_id=uuid.UUID(live_ben["id"]),
        amount=Decimal("5000.00"),
        currency=CUR,
        api_key_id=None,
    )
    assert live["status"] == "processing"


def test_the_limit_is_per_merchant(fake_client):
    a, ben_a = _ready(fake_client, funded="50000.00", daily_limit_tzs="5000")
    b, ben_b = _ready(fake_client, funded="50000.00", daily_limit_tzs="5000")

    create_payout(
        fake_client, merchant_id=a, environment="live", beneficiary_id=ben_a,
        amount=Decimal("5000.00"), currency=CUR, api_key_id=None,
    )
    other = create_payout(
        fake_client, merchant_id=b, environment="live", beneficiary_id=ben_b,
        amount=Decimal("5000.00"), currency=CUR, api_key_id=None,
    )

    assert other["status"] == "processing"


def test_no_daily_limit_configured_means_no_daily_limit(fake_client):
    """Null is 'no merchant-specific limit', not 'zero'. Reading it as
    zero would silently refuse every payout for every merchant whose
    limit was never set."""
    mid, ben = _ready(fake_client, funded="100000.00", daily_limit_tzs=None)

    for _ in range(5):
        payout = create_payout(
            fake_client, merchant_id=mid, environment="live", beneficiary_id=ben,
            amount=Decimal("10000.00"), currency=CUR, api_key_id=None,
        )
        assert payout["status"] == "processing"
