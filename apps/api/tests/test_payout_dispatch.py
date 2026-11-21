"""The worker, against a mock provider only.

One question runs through all of this: **when may the reserve be let
go?** The answer is only on evidence - a confirmed payment settles it, a
confirmed refusal returns it, and anything else leaves it exactly where
it is. The tests are organised around the ways that can go wrong rather
than around the functions.

The expensive mistake is releasing a reserve for a payout that was
actually paid: the merchant can then spend money that has already left,
and the platform covers the difference out of its own pocket. So a
timeout, a dropped connection, a `processing` answer and an `ambiguous`
answer all do the same thing here, and it is not "fail".

Nothing in this file can reach a real provider. The mock is the only
client constructed, and get_selcom_business_client refuses to build it
outside ENVIRONMENT=development - so a test that accidentally dropped
the monkeypatch would raise rather than quietly call Selcom. One test
pins that.
"""

import uuid
from decimal import Decimal

import pytest

from app.config import get_settings
from app.services.payout_dispatch import (
    apply_provider_result,
    dispatch_payout,
    reconcile_payout,
    sweep_payouts,
)
from app.services.selcom_business import client as client_module
from app.services.selcom_business.schemas import SelcomBusinessResult
from tests.factories import create_merchant

CUR = "TZS"


class _MockProvider:
    """Answers exactly what a test tells it to, and records what it was
    asked. The recording is the point for the duplicate-send tests."""

    def __init__(self, result=None, raises: Exception | None = None):
        self.result = result
        self.raises = raises
        self.process_calls: list[str] = []
        self.query_calls: list[str] = []
        # Which environment the code asked the factory for, in order.
        self.asked_for_environments: list[str | None] = []

    async def process_transaction(self, *, trans_id, **_kwargs):
        self.process_calls.append(trans_id)
        if self.raises:
            raise self.raises
        return self.result

    async def query_transaction(self, *, trans_id):
        self.query_calls.append(trans_id)
        if self.raises:
            raise self.raises
        return self.result


def _result(status, *, receipt=None, reason=None):
    return SelcomBusinessResult(
        provider="mock_selcom_business",
        transaction_id="PRV-1",
        status=status,
        receipt=receipt,
        failure_reason=reason,
    )


@pytest.fixture
def provider(monkeypatch):
    """Installed in place of the real factory, so nothing here can dial
    out even if a setting were wrong."""
    holder = _MockProvider()

    def _factory(environment=None):
        # Records which environment dispatch asked for. The real factory
        # uses it to choose between Selcom sandbox and Selcom production,
        # so a stub that ignored it would hide the whole question.
        holder.asked_for_environments.append(environment)
        return holder

    monkeypatch.setattr("app.services.payout_dispatch.get_selcom_business_client", _factory)
    return holder


@pytest.fixture
def world(fake_client):
    """A merchant with 100,000 funded and one payout of 51,500 already
    authorised - which is the state the worker always finds."""
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    beneficiary_id = fake_client.seed(
        "payout_beneficiaries",
        {
            "merchant_id": str(merchant_id),
            "environment": "live",
            "name": "Demo Recipient",
            "method": "MOBILE_MONEY",
            "destination_code": "MPESA",
            "destination_identifier": "255700111222",
            "status": "active",
        },
    )["id"]
    for purpose, balance in (("payout_available", "48500.00"), ("payout_reserved", "51500.00")):
        fake_client.seed(
            "ledger_accounts",
            {
                "merchant_id": str(merchant_id),
                "name": purpose,
                "account_type": "liability",
                "purpose": purpose,
                "currency": CUR,
                "environment": "live",
                "balance": balance,
            },
        )
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": None,
            "name": "Settlement",
            "account_type": "asset",
            "purpose": "settlement_clearing",
            "currency": CUR,
            "environment": "live",
            "balance": "0",
        },
    )
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": None,
            "name": "Platform revenue",
            "account_type": "revenue",
            "purpose": "platform_revenue",
            "currency": CUR,
            "environment": "live",
            "balance": "0",
        },
    )
    payout = fake_client.seed(
        "payouts",
        {
            "merchant_id": str(merchant_id),
            "environment": "live",
            "beneficiary_id": beneficiary_id,
            "amount": "50000.00",
            "fee_amount": "1500.00",
            "total_debit": "51500.00",
            "currency": CUR,
            "status": "processing",
            "provider_reference": "PO-TEST-0001",
            "dispatch_attempts": 0,
        },
    )
    fake_client.seed(
        "transactions",
        {
            "merchant_id": str(merchant_id),
            "reference": "PO-TEST-0001",
            "type": "payout",
            "method": "MOBILE_MONEY",
            "payout_id": payout["id"],
            "gross_amount": "51500.00",
            "fee_amount": "1500.00",
            "net_amount": "50000.00",
            "currency": CUR,
            "status": "processing",
        },
    )
    return merchant_id, payout


def _bal(fake_client, purpose, merchant_id=None):
    for row in fake_client.table("ledger_accounts")._table.rows:
        if row["purpose"] != purpose:
            continue
        if merchant_id is not None and row.get("merchant_id") != str(merchant_id):
            continue
        return Decimal(str(row["balance"]))
    return Decimal(0)


def _payout(fake_client, payout_id):
    return next(r for r in fake_client.table("payouts")._table.rows if r["id"] == str(payout_id))


# --- a confirmed payment -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_confirmed_payment_settles_the_reserve(fake_client, world, provider):
    merchant_id, payout = world
    provider.result = _result("successful", receipt="RCPT-99")

    outcome = await dispatch_payout(fake_client, payout)

    assert outcome == "successful"
    row = _payout(fake_client, payout["id"])
    assert row["status"] == "successful"
    assert row["provider_transid"] == "RCPT-99"
    assert row["completed_at"] is not None
    assert _bal(fake_client, "payout_reserved", merchant_id) == Decimal(0)
    assert _bal(fake_client, "payout_available", merchant_id) == Decimal("48500.00")
    assert _bal(fake_client, "platform_revenue") == Decimal("1500.00")


@pytest.mark.asyncio
async def test_settling_twice_does_not_debit_the_reserve_twice(fake_client, world, provider):
    """A duplicate callback, carrying the status the sender saw.

    `stale` is a real copy taken before dispatch, not the live row. That
    matters: the fake hands out rows by reference, so passing the same
    dict back would already say "successful" and the terminal-status
    check would answer. A genuine duplicate callback does not know the
    payout moved on, so the compare-and-set in _transition is what has
    to stop it - and with a copy, that is what this test exercises.
    """
    merchant_id, payout = world
    stale = dict(payout)
    provider.result = _result("successful", receipt="RCPT-99")

    await dispatch_payout(fake_client, payout)
    reserved_after_first = _bal(fake_client, "payout_reserved", merchant_id)

    again = apply_provider_result(fake_client, payout=stale, result=provider.result)

    assert again == "processing", "the duplicate should report it changed nothing"
    assert _bal(fake_client, "payout_reserved", merchant_id) == reserved_after_first
    assert _bal(fake_client, "platform_revenue") == Decimal("1500.00"), "the fee was booked twice"


# --- a confirmed refusal -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_confirmed_failure_releases_the_reserve_once(fake_client, world, provider):
    merchant_id, payout = world
    provider.result = _result("failed", reason="Invalid recipient account")

    outcome = await dispatch_payout(fake_client, payout)

    assert outcome == "failed"
    row = _payout(fake_client, payout["id"])
    assert row["status"] == "failed"
    assert row["failure_code"] == "provider_declined"
    assert _bal(fake_client, "payout_reserved", merchant_id) == Decimal(0)
    assert _bal(fake_client, "payout_available", merchant_id) == Decimal("100000.00")


@pytest.mark.asyncio
async def test_a_repeated_failure_callback_releases_nothing_further(fake_client, world, provider):
    """The reserve goes back exactly once. A second release would credit
    the wallet with money that was never held."""
    merchant_id, payout = world
    stale = dict(payout)
    provider.result = _result("failed", reason="Invalid recipient account")

    await dispatch_payout(fake_client, payout)
    apply_provider_result(fake_client, payout=stale, result=provider.result)

    assert _bal(fake_client, "payout_available", merchant_id) == Decimal("100000.00")
    assert _bal(fake_client, "payout_reserved", merchant_id) == Decimal(0)


# --- the unknown outcome: funds STAY held ------------------------------------


@pytest.mark.asyncio
async def test_a_timeout_leaves_the_reserve_held(fake_client, world, provider):
    """The invariant this module exists for.

    A provider exception is not evidence the payout failed - it may have
    been received and paid. Releasing here is how a merchant comes to
    spend money that has already left the platform.
    """
    merchant_id, payout = world
    provider.raises = TimeoutError("read timed out")

    outcome = await dispatch_payout(fake_client, payout)

    assert outcome == "needs_reconciliation"
    row = _payout(fake_client, payout["id"])
    assert row["status"] == "needs_reconciliation"
    assert row["failure_code"] == "provider_unreachable"
    assert row["next_check_at"] is not None
    assert _bal(fake_client, "payout_reserved", merchant_id) == Decimal("51500.00")
    assert _bal(fake_client, "payout_available", merchant_id) == Decimal("48500.00")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["processing", "ambiguous"])
async def test_an_unresolved_answer_leaves_the_reserve_held(fake_client, world, provider, status):
    merchant_id, payout = world
    provider.result = _result(status)

    outcome = await dispatch_payout(fake_client, payout)

    assert outcome == "needs_reconciliation"
    assert _bal(fake_client, "payout_reserved", merchant_id) == Decimal("51500.00")


@pytest.mark.asyncio
async def test_needs_reconciliation_is_not_a_failure_state(fake_client, world, provider):
    """It must never be presented as one, nor count as refunded. The
    rolling limit counts it as spent for exactly this reason."""
    _merchant_id, payout = world
    provider.raises = TimeoutError("read timed out")

    await dispatch_payout(fake_client, payout)
    row = _payout(fake_client, payout["id"])

    assert row["status"] == "needs_reconciliation"
    # .get rather than [], because the fake does not materialise columns
    # nothing has written. Either way the assertion is the same: this
    # payout is not complete.
    assert row.get("completed_at") is None, "a payout with funds still held is not complete"


# --- a late success ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_late_success_settles_from_reconciliation(fake_client, world, provider):
    """The payout timed out, was parked, and the provider later confirms
    it did pay. The reserve becomes a real outflow - it must not have
    been released in the meantime, or there is nothing left to settle."""
    merchant_id, payout = world
    provider.raises = TimeoutError("read timed out")
    await dispatch_payout(fake_client, payout)
    assert _bal(fake_client, "payout_reserved", merchant_id) == Decimal("51500.00")

    provider.raises = None
    provider.result = _result("successful", receipt="RCPT-LATE")
    parked = _payout(fake_client, payout["id"])

    outcome = await reconcile_payout(fake_client, parked)

    assert outcome == "successful"
    assert _bal(fake_client, "payout_reserved", merchant_id) == Decimal(0)
    assert _bal(fake_client, "platform_revenue") == Decimal("1500.00")
    assert _payout(fake_client, payout["id"])["provider_transid"] == "RCPT-LATE"


@pytest.mark.asyncio
async def test_a_late_confirmed_failure_releases_from_reconciliation(fake_client, world, provider):
    merchant_id, payout = world
    provider.raises = TimeoutError("read timed out")
    await dispatch_payout(fake_client, payout)

    provider.raises = None
    provider.result = _result("failed", reason="Recipient account closed")
    parked = _payout(fake_client, payout["id"])

    outcome = await reconcile_payout(fake_client, parked)

    assert outcome == "failed"
    assert _bal(fake_client, "payout_available", merchant_id) == Decimal("100000.00")


@pytest.mark.asyncio
async def test_reconciliation_asks_rather_than_resends(fake_client, world, provider):
    """The one action that can genuinely pay twice is re-sending a payout
    whose outcome is unknown. Reconciliation must only ever query."""
    _merchant_id, payout = world
    provider.raises = TimeoutError("read timed out")
    await dispatch_payout(fake_client, payout)
    sends_after_dispatch = len(provider.process_calls)

    provider.raises = None
    provider.result = _result("processing")
    await reconcile_payout(fake_client, _payout(fake_client, payout["id"]))

    assert len(provider.process_calls) == sends_after_dispatch, "reconciliation re-sent the payout"
    assert provider.query_calls == ["PO-TEST-0001"]


@pytest.mark.asyncio
async def test_a_still_unresolved_reconciliation_backs_off(fake_client, world, provider):
    _merchant_id, payout = world
    provider.raises = TimeoutError("read timed out")
    await dispatch_payout(fake_client, payout)
    first_check = _payout(fake_client, payout["id"])["next_check_at"]

    provider.raises = None
    provider.result = _result("ambiguous")
    await reconcile_payout(fake_client, _payout(fake_client, payout["id"]))

    assert _payout(fake_client, payout["id"])["next_check_at"] >= first_check


# --- no duplicate sends ------------------------------------------------------


@pytest.mark.asyncio
async def test_two_workers_cannot_both_send_one_payout(fake_client, world, provider):
    """Both read the row, both try to dispatch. Only one may reach the
    provider - otherwise the provider's own idempotency is the only thing
    preventing a double payment."""
    _merchant_id, payout = world
    provider.result = _result("successful", receipt="RCPT-1")

    stale = dict(payout)
    await dispatch_payout(fake_client, payout)
    await dispatch_payout(fake_client, stale)  # the row the second worker read

    assert provider.process_calls == ["PO-TEST-0001"]


def test_two_claims_on_one_still_processing_payout_only_one_wins(fake_client, world):
    """The claim itself, not the dispatch around it.

    The test above passes even with the attempt counter removed, because
    by the time the second worker tries, the first has already moved the
    payout off `processing`. The dangerous interleaving is both workers
    claiming BEFORE either resolves - which a single-threaded fake cannot
    stage through dispatch_payout, so this calls the claim directly.
    Two claims against the same read must not both succeed, or both
    workers send the payout and only the provider's idempotency stands
    between that and paying twice.
    """
    from app.services.payout_dispatch import _claim_for_dispatch

    _merchant_id, payout = world
    read_by_worker_a = dict(payout)
    read_by_worker_b = dict(payout)

    first = _claim_for_dispatch(fake_client, read_by_worker_a)
    second = _claim_for_dispatch(fake_client, read_by_worker_b)

    assert first is not None, "the first worker should win the claim"
    assert second is None, "the second worker claimed a payout already in flight"
    assert _payout(fake_client, payout["id"])["dispatch_attempts"] == 1


@pytest.mark.asyncio
async def test_a_terminal_payout_is_never_dispatched(fake_client, world, provider):
    _merchant_id, payout = world
    row = _payout(fake_client, payout["id"])
    row["status"] = "cancelled"
    provider.result = _result("successful")

    outcome = await dispatch_payout(fake_client, row)

    assert provider.process_calls == []
    assert outcome == "cancelled"


# --- the sweep ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_sweep_dispatches_what_is_authorised(fake_client, world, provider):
    _merchant_id, _payout = world
    provider.result = _result("successful", receipt="RCPT-1")

    counts = await sweep_payouts(fake_client)

    assert counts.get("successful") == 1
    assert provider.process_calls == ["PO-TEST-0001"]


@pytest.mark.asyncio
async def test_the_sweep_leaves_queued_payouts_alone(fake_client, world, provider):
    """`queued` means not yet authorised, so nothing is reserved behind
    it. Dispatching one would send money that was never held."""
    _merchant_id, payout = world
    _payout(fake_client, payout["id"])["status"] = "queued"
    provider.result = _result("successful")

    await sweep_payouts(fake_client)

    assert provider.process_calls == []


# --- the sandbox has no path to a live provider ------------------------------


def test_the_mock_provider_refuses_to_exist_outside_development(monkeypatch):
    """The guard that makes "mock only" true rather than intended. A
    misconfigured deploy must fail loudly, not quietly fake real
    payouts - or, worse, quietly send them."""
    from app.services.selcom_business.client import (
        SelcomBusinessMisconfiguredError,
        get_selcom_business_client,
    )

    monkeypatch.setenv("SELCOM_BUSINESS_MODE", "mock")
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    client_module.get_selcom_business_client.cache_clear()

    with pytest.raises(SelcomBusinessMisconfiguredError):
        get_selcom_business_client()

    get_settings.cache_clear()
    client_module.get_selcom_business_client.cache_clear()
