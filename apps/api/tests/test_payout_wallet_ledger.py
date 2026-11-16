"""The Payout Wallet's ledger postings, and the isolation they exist for.

Two pockets, both the merchant's: `merchant_wallet` holds collections and
is what Withdrawals spend; `payout_available` holds prefunded payout money
and is what the Disbursement API spends. The point of separating them is
that a payout key cannot reach collections and a withdrawal cannot reach
payout funds, so much of this file is about what must NOT be reachable.

A caveat this file cannot escape: FakeSupabaseClient is single-threaded,
so "two concurrent requests race for the same balance" is not provable
here - a correct `for update` and a missing one look identical. What IS
provable, and is what these assert, is that each posting path refuses an
overdraw at all, and that a refusal leaves nothing behind. The genuine
concurrency proof needs real Postgres on separate connections, and a skip
there is not a pass.
"""

import uuid
from decimal import Decimal

import pytest

from app.core.errors import InsufficientBalanceError
from app.services.ledger import (
    get_payout_wallet_balances,
    get_wallet_balance,
    post_payout_release,
    post_payout_reservation,
    post_payout_settlement,
    post_payout_wallet_funding,
)

CUR = "TZS"


def _seed_wallet(fake_client, merchant_id, amount):
    return fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Merchant Wallet (test)",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": CUR,
            "balance": str(amount),
        },
    )


def _tx(fake_client, merchant_id):
    return uuid.UUID(
        fake_client.seed(
            "transactions",
            {
                "merchant_id": str(merchant_id),
                "type": "payout",
                "status": "successful",
                "currency": CUR,
                "gross_amount": "0",
                "net_amount": "0",
            },
        )["id"]
    )


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


def _entries(fake_client):
    return fake_client.table("ledger_entries")._table.rows


def _accounts(fake_client, merchant_id, purpose):
    return [
        a
        for a in fake_client.table("ledger_accounts")._table.rows
        if a.get("merchant_id") == str(merchant_id) and a.get("purpose") == purpose
    ]


# --- funding --------------------------------------------------------------


def test_funding_moves_money_between_the_two_pockets(fake_client):
    mid = uuid.uuid4()
    _seed_wallet(fake_client, mid, "100000.00")

    post_payout_wallet_funding(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        amount=Decimal("30000.00"),
        currency=CUR,
        environment="live",
    )

    assert _bal(fake_client, mid, "merchant_wallet") == Decimal("70000.00")
    assert _bal(fake_client, mid, "payout_available") == Decimal("30000.00")


def test_funding_is_balanced(fake_client):
    """Debits must equal credits. In production a deferred trigger refuses
    the transaction outright; here it is asserted directly so a one-sided
    posting cannot slip through the fake."""
    mid = uuid.uuid4()
    _seed_wallet(fake_client, mid, "50000.00")
    tx = _tx(fake_client, mid)

    post_payout_wallet_funding(
        fake_client,
        transaction_id=tx,
        merchant_id=mid,
        amount=Decimal("20000.00"),
        currency=CUR,
        environment="live",
    )

    rows = [e for e in _entries(fake_client) if e["transaction_id"] == str(tx)]
    debits = sum(Decimal(str(e["amount"])) for e in rows if e["direction"] == "debit")
    credits = sum(Decimal(str(e["amount"])) for e in rows if e["direction"] == "credit")
    assert debits == credits == Decimal("20000.00")


def test_funding_charges_no_fee(fake_client):
    """Moving money between a merchant's own two pockets earns the
    platform nothing. Booking revenue here would charge for money that
    has not been paid out and may never be."""
    mid = uuid.uuid4()
    _seed_wallet(fake_client, mid, "50000.00")

    post_payout_wallet_funding(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        amount=Decimal("20000.00"),
        currency=CUR,
        environment="live",
    )

    revenue = [
        a for a in fake_client.table("ledger_accounts")._table.rows
        if a.get("purpose") == "platform_revenue"
    ]
    assert all(Decimal(str(a["balance"])) == 0 for a in revenue)


def test_cannot_fund_more_than_the_collections_balance(fake_client):
    mid = uuid.uuid4()
    _seed_wallet(fake_client, mid, "10000.00")

    with pytest.raises(InsufficientBalanceError):
        post_payout_wallet_funding(
            fake_client,
            transaction_id=_tx(fake_client, mid),
            merchant_id=mid,
            amount=Decimal("10000.01"),
            currency=CUR,
            environment="live",
        )

    assert _bal(fake_client, mid, "merchant_wallet") == Decimal("10000.00")


def test_a_refused_funding_leaves_nothing_behind(fake_client):
    """The whole batch is rejected, not the offending leg. A credit to the
    payout wallet surviving a rejected debit would create money."""
    mid = uuid.uuid4()
    _seed_wallet(fake_client, mid, "1000.00")
    before = len(_entries(fake_client))

    with pytest.raises(InsufficientBalanceError):
        post_payout_wallet_funding(
            fake_client,
            transaction_id=_tx(fake_client, mid),
            merchant_id=mid,
            amount=Decimal("5000.00"),
            currency=CUR,
            environment="live",
        )

    assert len(_entries(fake_client)) == before
    assert (_bal(fake_client, mid, "payout_available") or Decimal(0)) == Decimal(0)


# --- isolation: the reason the two pockets exist --------------------------


def test_funding_does_not_change_what_a_withdrawal_can_spend_twice(fake_client):
    """Funding the payout wallet must REDUCE the collections balance. If
    it did not, the same shilling would be spendable by a withdrawal and
    by a payout - the exact double-spend the split exists to prevent."""
    mid = uuid.uuid4()
    _seed_wallet(fake_client, mid, "100000.00")

    post_payout_wallet_funding(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        amount=Decimal("100000.00"),
        currency=CUR,
        environment="live",
    )

    assert get_wallet_balance(fake_client, merchant_id=mid, currency=CUR) == Decimal(0)


def test_payout_funds_are_invisible_to_the_collections_balance(fake_client):
    """A withdrawal validates against get_wallet_balance. Payout money
    must not inflate it, or a withdrawal could spend reserved payout
    funds."""
    mid = uuid.uuid4()
    _seed_wallet(fake_client, mid, "60000.00")

    post_payout_wallet_funding(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        amount=Decimal("50000.00"),
        currency=CUR,
        environment="live",
    )

    assert get_wallet_balance(fake_client, merchant_id=mid, currency=CUR) == Decimal("10000.00")


def test_sandbox_and_live_payout_wallets_are_different_accounts(fake_client):
    mid = uuid.uuid4()
    _seed_wallet(fake_client, mid, "100000.00")

    post_payout_wallet_funding(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        amount=Decimal("10000.00"),
        currency=CUR,
        environment="live",
    )

    live_avail, _ = get_payout_wallet_balances(
        fake_client, merchant_id=mid, currency=CUR, environment="live"
    )
    sandbox_avail, _ = get_payout_wallet_balances(
        fake_client, merchant_id=mid, currency=CUR, environment="sandbox"
    )

    assert live_avail == Decimal("10000.00")
    assert sandbox_avail == Decimal(0)
    assert len(_accounts(fake_client, mid, "payout_available")) == 2


def test_one_merchants_payout_wallet_is_not_anothers(fake_client):
    a, b = uuid.uuid4(), uuid.uuid4()
    _seed_wallet(fake_client, a, "50000.00")
    _seed_wallet(fake_client, b, "50000.00")

    post_payout_wallet_funding(
        fake_client,
        transaction_id=_tx(fake_client, a),
        merchant_id=a,
        amount=Decimal("40000.00"),
        currency=CUR,
        environment="live",
    )

    assert _bal(fake_client, a, "payout_available") == Decimal("40000.00")
    avail_b, _ = get_payout_wallet_balances(
        fake_client, merchant_id=b, currency=CUR, environment="live"
    )
    assert avail_b == Decimal(0)
    assert _bal(fake_client, b, "merchant_wallet") == Decimal("50000.00")


# --- reserve / release / settle -------------------------------------------


def _funded(fake_client, mid, amount="100000.00", fund="80000.00"):
    _seed_wallet(fake_client, mid, amount)
    post_payout_wallet_funding(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        amount=Decimal(fund),
        currency=CUR,
        environment="live",
    )


def test_reserving_moves_available_into_reserved(fake_client):
    mid = uuid.uuid4()
    _funded(fake_client, mid)

    post_payout_reservation(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        total_debit=Decimal("25000.00"),
        currency=CUR,
        environment="live",
    )

    assert _bal(fake_client, mid, "payout_available") == Decimal("55000.00")
    assert _bal(fake_client, mid, "payout_reserved") == Decimal("25000.00")


def test_cannot_reserve_more_than_is_available(fake_client):
    mid = uuid.uuid4()
    _funded(fake_client, mid)

    with pytest.raises(InsufficientBalanceError):
        post_payout_reservation(
            fake_client,
            transaction_id=_tx(fake_client, mid),
            merchant_id=mid,
            total_debit=Decimal("80000.01"),
            currency=CUR,
            environment="live",
        )

    assert _bal(fake_client, mid, "payout_available") == Decimal("80000.00")
    assert (_bal(fake_client, mid, "payout_reserved") or Decimal(0)) == Decimal(0)


def test_reserving_cannot_reach_the_collections_wallet(fake_client):
    """A payout bigger than the payout wallet must fail even when the
    collections wallet could cover it. This is the single most important
    assertion in the file: it is what stops a payout key spending
    collections money."""
    mid = uuid.uuid4()
    _seed_wallet(fake_client, mid, "1000000.00")
    post_payout_wallet_funding(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        amount=Decimal("5000.00"),
        currency=CUR,
        environment="live",
    )

    with pytest.raises(InsufficientBalanceError):
        post_payout_reservation(
            fake_client,
            transaction_id=_tx(fake_client, mid),
            merchant_id=mid,
            total_debit=Decimal("6000.00"),
            currency=CUR,
            environment="live",
        )

    assert _bal(fake_client, mid, "merchant_wallet") == Decimal("995000.00")


def test_releasing_returns_the_exact_reservation(fake_client):
    mid = uuid.uuid4()
    _funded(fake_client, mid)
    post_payout_reservation(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        total_debit=Decimal("25000.00"),
        currency=CUR,
        environment="live",
    )

    post_payout_release(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        total_debit=Decimal("25000.00"),
        currency=CUR,
        environment="live",
    )

    assert _bal(fake_client, mid, "payout_available") == Decimal("80000.00")
    assert _bal(fake_client, mid, "payout_reserved") == Decimal(0)


def test_releasing_twice_is_refused(fake_client):
    """A double release would invent money: more returned than was ever
    committed. payout_reserved going negative is exactly that, and the
    database refuses it."""
    mid = uuid.uuid4()
    _funded(fake_client, mid)
    post_payout_reservation(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        total_debit=Decimal("25000.00"),
        currency=CUR,
        environment="live",
    )
    post_payout_release(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        total_debit=Decimal("25000.00"),
        currency=CUR,
        environment="live",
    )

    with pytest.raises(InsufficientBalanceError):
        post_payout_release(
            fake_client,
            transaction_id=_tx(fake_client, mid),
            merchant_id=mid,
            total_debit=Decimal("25000.00"),
            currency=CUR,
            environment="live",
        )

    assert _bal(fake_client, mid, "payout_available") == Decimal("80000.00")


def test_settlement_books_the_outflow_and_the_fee(fake_client):
    mid = uuid.uuid4()
    _funded(fake_client, mid)
    post_payout_reservation(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        total_debit=Decimal("10500.00"),
        currency=CUR,
        environment="live",
    )
    tx = _tx(fake_client, mid)

    post_payout_settlement(
        fake_client,
        transaction_id=tx,
        merchant_id=mid,
        amount=Decimal("10000.00"),
        currency=CUR,
        environment="live",
        fee_amount=Decimal("500.00"),
    )

    assert _bal(fake_client, mid, "payout_reserved") == Decimal(0)
    rows = [e for e in _entries(fake_client) if e["transaction_id"] == str(tx)]
    debits = sum(Decimal(str(e["amount"])) for e in rows if e["direction"] == "debit")
    credits = sum(Decimal(str(e["amount"])) for e in rows if e["direction"] == "credit")
    assert debits == credits == Decimal("10500.00")

    revenue = next(
        a for a in fake_client.table("ledger_accounts")._table.rows
        if a.get("purpose") == "platform_revenue"
    )
    assert Decimal(str(revenue["balance"])) == Decimal("500.00")


def test_settling_twice_is_refused(fake_client):
    """Money must move exactly once. The second settlement would drive
    payout_reserved negative, which the balance guard rejects."""
    mid = uuid.uuid4()
    _funded(fake_client, mid)
    post_payout_reservation(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        total_debit=Decimal("10500.00"),
        currency=CUR,
        environment="live",
    )
    kwargs = {
        "merchant_id": mid,
        "amount": Decimal("10000.00"),
        "currency": CUR,
        "environment": "live",
        "fee_amount": Decimal("500.00"),
    }
    post_payout_settlement(fake_client, transaction_id=_tx(fake_client, mid), **kwargs)

    with pytest.raises(InsufficientBalanceError):
        post_payout_settlement(fake_client, transaction_id=_tx(fake_client, mid), **kwargs)


def test_a_settled_payout_cannot_then_be_released(fake_client):
    """The two terminal paths are mutually exclusive. Releasing after a
    settlement would hand back money that has already left."""
    mid = uuid.uuid4()
    _funded(fake_client, mid)
    post_payout_reservation(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        total_debit=Decimal("10000.00"),
        currency=CUR,
        environment="live",
    )
    post_payout_settlement(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        amount=Decimal("10000.00"),
        currency=CUR,
        environment="live",
    )

    with pytest.raises(InsufficientBalanceError):
        post_payout_release(
            fake_client,
            transaction_id=_tx(fake_client, mid),
            merchant_id=mid,
            total_debit=Decimal("10000.00"),
            currency=CUR,
            environment="live",
        )


def test_balances_reported_to_the_dashboard_match_the_accounts(fake_client):
    mid = uuid.uuid4()
    _funded(fake_client, mid)
    post_payout_reservation(
        fake_client,
        transaction_id=_tx(fake_client, mid),
        merchant_id=mid,
        total_debit=Decimal("12000.00"),
        currency=CUR,
        environment="live",
    )

    available, reserved = get_payout_wallet_balances(
        fake_client, merchant_id=mid, currency=CUR, environment="live"
    )

    assert available == Decimal("68000.00")
    assert reserved == Decimal("12000.00")


def test_reading_balances_never_invents_a_balance(fake_client):
    """A merchant who has never funded one sees zero, not an error and not
    a number borrowed from their collections wallet."""
    mid = uuid.uuid4()
    _seed_wallet(fake_client, mid, "999999.00")

    available, reserved = get_payout_wallet_balances(
        fake_client, merchant_id=mid, currency=CUR, environment="live"
    )

    assert available == Decimal(0)
    assert reserved == Decimal(0)
