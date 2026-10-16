"""Merchant SMS after the 2026-10-17 cost policy: two messages, not one
per payment.

The collection alert worked - proven end to end in production on
2026-10-16, correct to the cent - and was withdrawn the next day for
cost. 3,748 payments in the first sixteen days of October is roughly 230
messages a day and rising, for something the merchant already receives by
email. What is left is a welcome on approval and a confirmation on a
completed payout: two messages in a merchant's life with us.

The sharp edges here are not the happy paths. They are:

  * a successful payment must now send nothing, while its email still goes
  * a welcome must not fire on signup, on a retried approval, or when a
    suspended merchant is reactivated
  * a withdrawal message must quote the balance the *reservation*
    produced, because the wallet is debited at approval and the provider
    confirms later
  * a fee of zero must only ever be stated when the fee really was zero
"""

import uuid
from decimal import Decimal

import pytest

from app.config import get_settings
from app.services.sms_messages import (
    SKIP_NO_BALANCE_SNAPSHOT,
    SKIP_NO_NUMBER,
    enqueue_welcome_sms,
    enqueue_withdrawal_complete_sms,
    withdrawals_are_free,
)
from app.services.sms_text import (
    message_cost,
    render_welcome,
    render_withdrawal_complete,
)
from tests.factories import create_merchant


@pytest.fixture(autouse=True)
def _sms_on(monkeypatch):
    monkeypatch.setenv("OASIS_SMS_ENABLED", "true")
    monkeypatch.setenv("OASIS_SMS_WELCOME_ENABLED", "true")
    monkeypatch.setenv("OASIS_SMS_WITHDRAWAL_ENABLED", "true")
    monkeypatch.setenv("OASIS_SMS_SENDER_ID", "INFINITYPAY")
    monkeypatch.setenv("OASIS_SMS_API_KEY", "test-key-not-real")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _merchant(fake_client, phone="255713000001"):
    return create_merchant(fake_client, contact_phone=phone)


def _rows(fake_client, purpose=None):
    rows = fake_client.table("sms_messages")._table.rows
    return [r for r in rows if purpose is None or r["purpose"] == purpose]


def _payout(fake_client, merchant, *, amount="50000.00", charges="0", opening="161638.13"):
    """A payout whose wallet debit has already been posted - which is
    what approval does, long before the provider confirms."""
    transaction = fake_client.seed(
        "transactions",
        {
            "merchant_id": merchant["id"],
            "reference": "TXN-20261017-ABCD1234",
            "type": "disbursement",
            "method": "MOBILE_MONEY",
            "gross_amount": amount,
            "fee_amount": charges,
            "net_amount": amount,
            "currency": "TZS",
            "status": "successful",
        },
    )
    account = fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": merchant["id"],
            "purpose": "merchant_wallet",
            "account_type": "liability",
            "currency": "TZS",
            "balance": opening,
        },
    )
    closing = str(Decimal(opening) - Decimal(amount) - Decimal(charges))
    fake_client.seed(
        "ledger_entries",
        {
            "transaction_id": transaction["id"],
            "ledger_account_id": account["id"],
            "direction": "debit",
            "amount": str(Decimal(amount) + Decimal(charges)),
            "currency": "TZS",
            "balance_before": opening,
            "balance_after": closing,
        },
    )
    disbursement = fake_client.seed(
        "disbursements",
        {
            "merchant_id": merchant["id"],
            "amount": amount,
            "total_charges": charges,
            "currency": "TZS",
            "method": "MOBILE_MONEY",
            "destination_code": "MPESA",
            "status": "SUCCESS",
        },
    )
    return disbursement, transaction, closing


# --- the collection alert is gone --------------------------------------


def test_the_collection_enqueue_no_longer_exists(fake_client):
    """Removed outright rather than switched off, so no flag can bring it
    back by accident."""
    import app.services.sms_messages as module

    assert not hasattr(module, "enqueue_collection_alert")

    import app.services.collections as collections_module

    assert not hasattr(collections_module, "enqueue_collection_alert")


def test_the_worker_never_claims_a_cancelled_message(fake_client, monkeypatch):
    """Queued collection alerts are cancelled by the migration. The
    worker's claim query must ignore that state, or cancelling them would
    not stop the spend."""
    from app.services.sms_dispatch import dispatch_pending_sms

    merchant = _merchant(fake_client)
    fake_client.seed(
        "sms_messages",
        {
            "merchant_id": merchant["id"],
            "purpose": "collection_alert",
            "recipient_phone": "255713000001",
            "sender_id": "INFINITYPAY",
            "body": "retired",
            "status": "cancelled",
            "idempotency_key": f"ipay-c-{uuid.uuid4().hex}",
        },
    )
    calls = []
    monkeypatch.setattr(
        "app.services.sms_dispatch.send_sms", lambda **kw: calls.append(kw) or None
    )

    dispatch_pending_sms(fake_client)

    assert calls == [], "a cancelled message must never be offered to the provider"


# --- welcome -----------------------------------------------------------


def test_a_welcome_is_queued_once(fake_client):
    merchant = _merchant(fake_client)

    first = enqueue_welcome_sms(fake_client, merchant_id=uuid.UUID(merchant["id"]))
    second = enqueue_welcome_sms(fake_client, merchant_id=uuid.UUID(merchant["id"]))

    assert first is not None
    assert second is None, "a retried approval must not send a second welcome"
    assert len(_rows(fake_client, "welcome")) == 1


def test_a_reactivated_merchant_is_not_welcomed_again(fake_client):
    """Suspended and later reactivated is not a new merchant. The unique
    index covers all time, not a window."""
    merchant = _merchant(fake_client)
    enqueue_welcome_sms(fake_client, merchant_id=uuid.UUID(merchant["id"]))

    enqueue_welcome_sms(fake_client, merchant_id=uuid.UUID(merchant["id"]))

    assert len(_rows(fake_client, "welcome")) == 1


def test_signup_alone_sends_nothing(fake_client):
    """An account that exists is not an account that can trade. Nothing
    in the signup path may reach the welcome."""
    import inspect

    from app.services import onboarding

    source = inspect.getsource(onboarding.signup_merchant)
    assert "enqueue_welcome_sms" not in source


def test_the_welcome_is_sent_from_the_approval_path(fake_client):
    import inspect

    from app.services import onboarding

    assert "enqueue_welcome_sms" in inspect.getsource(onboarding.approve_onboarding_submission)


def test_the_welcome_stays_in_the_cheap_encoding_and_carries_no_secret(fake_client):
    """Two parts since the referral and support lines were added on
    2026-10-17 - a deliberate trade, and cheap at once per merchant.
    What must not slip is the encoding: one curly quote or emoji would
    drop the part size from 160 characters to 70 and take this to four
    parts."""
    text = render_welcome(withdrawals_are_free=True)
    cost = message_cost(text)

    assert cost["encoding"] == "GSM-7"
    assert cost["segments"] == 2
    for leak in ("sk_live", "inf_live", "secret", "whsec"):
        assert leak not in text.lower()


def test_the_free_withdrawal_claim_is_dropped_when_withdrawals_cost_money(fake_client):
    """The claim this message must never get wrong."""
    free = render_welcome(withdrawals_are_free=True)
    paid = render_welcome(withdrawals_are_free=False)

    assert "bila ada" in free
    assert "bila ada" not in paid
    assert "benki au simu" in paid, "the destinations are still true, only the fee claim goes"


def test_the_fee_claim_is_checked_against_the_real_calculator(fake_client):
    """Not a constant. Today withdrawals are free by policy, and this is
    what proves the message follows the policy rather than asserting it."""
    merchant = _merchant(fake_client)

    assert withdrawals_are_free(fake_client, uuid.UUID(merchant["id"])) is True

    enqueue_welcome_sms(fake_client, merchant_id=uuid.UUID(merchant["id"]))
    assert "bila ada" in _rows(fake_client, "welcome")[0]["body"]


def test_a_broken_fee_lookup_drops_the_claim_rather_than_guessing(fake_client, monkeypatch):
    """Patched at the calculator rather than the database on purpose.

    calculate_withdrawal_fee deliberately consults nothing - it returns
    zero unconditionally under the MVP pricing policy - so a broken
    client never reaches it and would answer True quite correctly. The
    guard exists for the day that calculator starts reading pricing
    rules again, and this is what exercises it.
    """
    import app.services.withdrawals.fee_calculator as fee_module

    def _explode(*_args, **_kwargs):
        raise RuntimeError("pricing lookup down")

    monkeypatch.setattr(fee_module, "calculate_withdrawal_fee", _explode)

    assert withdrawals_are_free(fake_client, uuid.uuid4()) is False


def test_the_fee_claim_survives_a_database_outage(fake_client):
    """Today the answer needs no database at all, so an unreachable one
    cannot make the welcome message wrong."""
    class _Broken:
        def table(self, _name):
            raise RuntimeError("down")

    assert withdrawals_are_free(_Broken(), uuid.uuid4()) is True


def test_the_welcome_respects_its_own_switch(fake_client, monkeypatch):
    monkeypatch.setenv("OASIS_SMS_WELCOME_ENABLED", "false")
    get_settings.cache_clear()
    merchant = _merchant(fake_client)

    enqueue_welcome_sms(fake_client, merchant_id=uuid.UUID(merchant["id"]))

    assert _rows(fake_client) == []


def test_a_merchant_with_no_number_is_skipped_with_a_reason(fake_client):
    merchant = create_merchant(fake_client, contact_phone=None)

    enqueue_welcome_sms(fake_client, merchant_id=uuid.UUID(merchant["id"]))

    row = _rows(fake_client, "welcome")[0]
    assert row["status"] == "skipped"
    assert row["skipped_reason"] == SKIP_NO_NUMBER


# --- completed withdrawal ----------------------------------------------


def test_a_confirmed_payout_is_queued_once(fake_client):
    merchant = _merchant(fake_client)
    disbursement, transaction, _closing = _payout(fake_client, merchant)

    first = enqueue_withdrawal_complete_sms(
        fake_client, disbursement=disbursement, transaction=transaction
    )
    second = enqueue_withdrawal_complete_sms(
        fake_client, disbursement=disbursement, transaction=transaction
    )

    assert first is not None
    assert second is None, "a callback and the sweep must not both send"
    assert len(_rows(fake_client, "withdrawal_complete")) == 1


def test_the_balance_is_the_one_the_reservation_produced(fake_client):
    """The sharpest rule here. The wallet is debited at approval; the
    provider confirms later. Reading the wallet now would report whatever
    collections have landed since."""
    merchant = _merchant(fake_client)
    disbursement, transaction, closing = _payout(
        fake_client, merchant, amount="50000.00", opening="161638.13"
    )

    enqueue_withdrawal_complete_sms(
        fake_client, disbursement=disbursement, transaction=transaction
    )

    row = _rows(fake_client, "withdrawal_complete")[0]
    assert Decimal(row["closing_balance"]) == Decimal(closing) == Decimal("111638.13")
    assert "Salio baada ya muamala: TZS 111,638.13." in row["body"]


def test_a_later_collection_does_not_change_a_queued_message(fake_client):
    merchant = _merchant(fake_client)
    disbursement, transaction, _closing = _payout(fake_client, merchant)
    enqueue_withdrawal_complete_sms(
        fake_client, disbursement=disbursement, transaction=transaction
    )
    before = _rows(fake_client, "withdrawal_complete")[0]["body"]

    wallet = next(
        a
        for a in fake_client.table("ledger_accounts")._table.rows
        if a.get("purpose") == "merchant_wallet"
    )
    wallet["balance"] = "999999.00"

    assert _rows(fake_client, "withdrawal_complete")[0]["body"] == before


def test_a_zero_fee_is_only_stated_when_it_really_is_zero(fake_client):
    merchant = _merchant(fake_client)
    disbursement, transaction, _c = _payout(fake_client, merchant, amount="1000.00", charges="0")

    enqueue_withdrawal_complete_sms(
        fake_client, disbursement=disbursement, transaction=transaction
    )

    assert "Ada: TZS 0." in _rows(fake_client, "withdrawal_complete")[0]["body"]


def test_a_real_fee_is_never_described_as_free(fake_client):
    """20 of the 74 payouts in production were charged between TZS 5 and
    530, before the zero-fee policy. If charging ever returns, this
    message must say so."""
    merchant = _merchant(fake_client)
    disbursement, transaction, _c = _payout(
        fake_client, merchant, amount="1000.00", charges="105"
    )

    enqueue_withdrawal_complete_sms(
        fake_client, disbursement=disbursement, transaction=transaction
    )

    body = _rows(fake_client, "withdrawal_complete")[0]["body"]
    assert "Ada: TZS 105." in body
    assert "Ada: TZS 0" not in body


def test_the_amount_and_reference_come_from_committed_records(fake_client):
    merchant = _merchant(fake_client)
    disbursement, transaction, _c = _payout(fake_client, merchant, amount="22000.00")

    enqueue_withdrawal_complete_sms(
        fake_client, disbursement=disbursement, transaction=transaction
    )

    row = _rows(fake_client, "withdrawal_complete")[0]
    assert row["gross_amount"] == "22000.00"
    assert row["reference"] == transaction["reference"]
    assert "Umepokea TZS 22,000 kutoka INFINITYPAY." in row["body"]
    assert transaction["reference"] in row["body"]


def test_no_snapshot_means_no_message_rather_than_a_guess(fake_client):
    merchant = _merchant(fake_client)
    disbursement, transaction, _c = _payout(fake_client, merchant)
    for e in fake_client.table("ledger_entries")._table.rows:
        e["balance_after"] = None

    enqueue_withdrawal_complete_sms(
        fake_client, disbursement=disbursement, transaction=transaction
    )

    row = _rows(fake_client, "withdrawal_complete")[0]
    assert row["status"] == "skipped"
    assert row["skipped_reason"] == SKIP_NO_BALANCE_SNAPSHOT


def test_the_withdrawal_message_respects_its_own_switch(fake_client, monkeypatch):
    monkeypatch.setenv("OASIS_SMS_WITHDRAWAL_ENABLED", "false")
    get_settings.cache_clear()
    merchant = _merchant(fake_client)
    disbursement, transaction, _c = _payout(fake_client, merchant)

    enqueue_withdrawal_complete_sms(
        fake_client, disbursement=disbursement, transaction=transaction
    )

    assert _rows(fake_client) == []


def test_the_two_switches_are_independent(fake_client, monkeypatch):
    """A platform sending welcomes must be able to not send payout
    confirmations, and the other way round."""
    monkeypatch.setenv("OASIS_SMS_WITHDRAWAL_ENABLED", "false")
    get_settings.cache_clear()
    merchant = _merchant(fake_client)
    disbursement, transaction, _c = _payout(fake_client, merchant)

    enqueue_welcome_sms(fake_client, merchant_id=uuid.UUID(merchant["id"]))
    enqueue_withdrawal_complete_sms(
        fake_client, disbursement=disbursement, transaction=transaction
    )

    assert len(_rows(fake_client, "welcome")) == 1
    assert _rows(fake_client, "withdrawal_complete") == []


def test_the_withdrawal_message_stays_in_the_cheap_encoding(fake_client):
    """Two parts since the referral and support lines were added on
    2026-10-17. The encoding is what must not slip: one curly quote or
    emoji drops the part size from 160 characters to 70 and doubles this
    again."""
    text = render_withdrawal_complete(
        amount=Decimal(1000000),
        fee_amount=Decimal(0),
        closing_balance=Decimal("98765432.10"),
        reference="TXN-20261017-ABCD1234",
    )

    cost = message_cost(text)
    assert cost["encoding"] == "GSM-7"
    assert cost["segments"] == 2






def test_the_referral_and_support_tail_is_on_both_messages(fake_client):
    """Added 2026-10-17. Referrals are a real feature, so the commission
    offer is not an empty promise, and the support number is the one
    route a merchant has when something looks wrong."""
    from app.services.sms_text import MESSAGE_TAIL

    welcome = render_welcome(withdrawals_are_free=True)
    payout = render_withdrawal_complete(
        amount=Decimal(1000),
        fee_amount=Decimal(0),
        closing_balance=Decimal(500),
        reference="TXN-1",
    )

    for text in (welcome, payout):
        assert MESSAGE_TAIL in text
        assert "255747730270" in text
        assert "help@infinitypay.me" in text


# --- it must never touch money -----------------------------------------


def test_nothing_here_writes_to_a_financial_table(fake_client):
    merchant = _merchant(fake_client)
    disbursement, transaction, _c = _payout(fake_client, merchant)
    before = {
        t: len(fake_client.table(t)._table.rows)
        for t in ("ledger_entries", "ledger_accounts", "transactions", "disbursements")
    }

    enqueue_welcome_sms(fake_client, merchant_id=uuid.UUID(merchant["id"]))
    enqueue_withdrawal_complete_sms(
        fake_client, disbursement=disbursement, transaction=transaction
    )

    after = {t: len(fake_client.table(t)._table.rows) for t in before}
    assert after == before, "the wallet must not be debited a second time"


def test_a_broken_database_does_not_raise_into_a_payout(fake_client):
    class _Broken:
        def table(self, _name):
            raise RuntimeError("supabase unreachable")

    assert enqueue_welcome_sms(_Broken(), merchant_id=uuid.uuid4()) is None
    assert (
        enqueue_withdrawal_complete_sms(
            _Broken(),
            disbursement={"id": str(uuid.uuid4()), "merchant_id": str(uuid.uuid4()), "amount": "1"},
            transaction={"id": str(uuid.uuid4()), "reference": "TXN-1"},
        )
        is None
    )
