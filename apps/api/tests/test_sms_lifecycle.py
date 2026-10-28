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
)
from app.services.sms_provider import SmsResult
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


def test_the_worker_actually_sends_every_purpose_it_is_given(fake_client, monkeypatch):
    """The gap that let a real payout confirmation sit queued.

    The enqueue side was changed to welcome/withdrawal_complete and the
    worker's purpose list was left naming the retired collection_alert,
    so both new kinds were written correctly and then never claimed by
    anyone. Every enqueue test passed throughout - they only ever checked
    that a row appeared.

    This asserts the two halves agree, for each purpose in turn.
    """
    from app.services.sms_dispatch import DISPATCHED_PURPOSES, dispatch_pending_sms

    sent: list[str] = []
    monkeypatch.setattr(
        "app.services.sms_dispatch.send_sms",
        lambda **kw: sent.append(kw["message"]) or SmsResult(outcome="sent", status_code=200),
    )

    for purpose in DISPATCHED_PURPOSES:
        merchant = create_merchant(fake_client, contact_phone="255713000009")
        fake_client.seed(
            "sms_messages",
            {
                "merchant_id": merchant["id"],
                "purpose": purpose,
                "recipient_phone": "255713000009",
                "sender_id": "INFINITYPAY",
                "body": f"body for {purpose}",
                "status": "queued",
                "idempotency_key": f"ipay-x-{uuid.uuid4().hex}",
            },
        )

    dispatch_pending_sms(fake_client)

    for purpose in DISPATCHED_PURPOSES:
        assert f"body for {purpose}" in sent, f"{purpose} was queued and never dispatched"


def test_the_worker_dispatches_a_real_welcome_end_to_end(fake_client, monkeypatch):
    """Enqueue and dispatch together, through the real functions rather
    than a seeded row."""
    from app.services.sms_dispatch import dispatch_pending_sms

    sent: list[str] = []
    monkeypatch.setattr(
        "app.services.sms_dispatch.send_sms",
        lambda **kw: sent.append(kw["message"]) or SmsResult(outcome="sent", status_code=200),
    )
    merchant = _merchant(fake_client)

    enqueue_welcome_sms(fake_client, merchant_id=uuid.UUID(merchant["id"]))
    dispatch_pending_sms(fake_client)

    assert len(sent) == 1
    assert "Karibu InfinityPay!" in sent[0]
    assert _rows(fake_client, "welcome")[0]["status"] == "sent"


def test_the_worker_dispatches_a_real_payout_confirmation_end_to_end(fake_client, monkeypatch):
    from app.services.sms_dispatch import dispatch_pending_sms

    sent: list[str] = []
    monkeypatch.setattr(
        "app.services.sms_dispatch.send_sms",
        lambda **kw: sent.append(kw["message"]) or SmsResult(outcome="sent", status_code=200),
    )
    merchant = _merchant(fake_client)
    disbursement, transaction, _c = _payout(fake_client, merchant)

    enqueue_withdrawal_complete_sms(
        fake_client, disbursement=disbursement, transaction=transaction
    )
    dispatch_pending_sms(fake_client)

    assert len(sent) == 1
    assert "Umepokea TZS" in sent[0]
    assert _rows(fake_client, "withdrawal_complete")[0]["status"] == "sent"


def test_a_retired_purpose_is_not_dispatched(fake_client, monkeypatch):
    """collection_alert rows that somehow survive must not be sent."""
    from app.services.sms_dispatch import DISPATCHED_PURPOSES

    assert "collection_alert" not in DISPATCHED_PURPOSES


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


def test_the_welcome_fits_one_part_and_carries_no_secret(fake_client):
    """Back to a single part on 2026-10-17, once the referral line, the
    support email and the withdrawal sentence came out. One part is half
    the cost of two, on a message every approved merchant receives."""
    text = render_welcome()
    cost = message_cost(text)

    assert cost["encoding"] == "GSM-7"
    assert cost["segments"] == 1
    for leak in ("sk_live", "inf_live", "secret", "whsec"):
        assert leak not in text.lower()


def test_the_welcome_makes_no_claim_about_fees(fake_client):
    """It used to end "bila ada", which was only true while withdrawals
    were free and needed the real fee calculator consulted at send time
    to stay honest. The sentence is gone, so there is nothing left to get
    wrong - and nothing may quietly reintroduce it."""
    text = render_welcome()

    # "bila ada", not "ada" - the support line contains "msaada", which
    # a substring check on "ada" matches. Caught by this test failing on
    # its own first draft.
    assert "bila ada" not in text.lower()
    assert "bure" not in text.lower()

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






def test_the_support_number_is_on_both_messages(fake_client):
    """All that is left of the tail. A referral invitation and a support
    email address were here on 2026-10-17 and came out the same day:
    between them they pushed both messages past 160 GSM-7 characters, so
    each cost two parts instead of one. The number is what a merchant
    reaches for when something looks wrong."""
    from app.services.sms_text import MESSAGE_TAIL

    welcome = render_welcome()
    payout = render_withdrawal_complete(
        amount=Decimal(1000),
        fee_amount=Decimal(0),
        closing_balance=Decimal(500),
        reference="TXN-1",
    )

    for text in (welcome, payout):
        assert MESSAGE_TAIL in text
        assert "255747730270" in text
        # Removed for cost; neither may creep back without this failing.
        assert "@" not in text
        assert "kamisheni" not in text.lower()

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


def test_every_purpose_the_enqueue_layer_can_write_is_actually_dispatched():
    """The guard the test above cannot be.

    test_the_worker_actually_sends_every_purpose_it_is_given loops over
    DISPATCHED_PURPOSES, so it proves the worker drains what it already
    knows about - and passes perfectly while a purpose is missing from
    that list entirely. Both times a purpose has been missed, that test
    was green.

    This compares the worker's list against the other half: the enqueue
    functions, which are the only things that put a purpose into the
    table. A new enqueue_* function fails here until someone has decided
    what dispatching it means.
    """
    import inspect

    from app.services import sms_messages
    from app.services.sms_dispatch import DISPATCHED_PURPOSES

    writes = {
        "enqueue_welcome_sms": "welcome",
        "enqueue_withdrawal_complete_sms": "withdrawal_complete",
        "enqueue_admin_new_merchant_sms": "admin_new_merchant",
        "enqueue_admin_withdrawal_request_sms": "admin_withdrawal_request",
    }
    defined = {
        name
        for name, obj in inspect.getmembers(sms_messages, inspect.isfunction)
        if name.startswith("enqueue_") and obj.__module__ == sms_messages.__name__
    }
    assert defined == set(writes), (
        "an enqueue function was added or renamed - name the purpose it writes here, "
        "then make sure app/services/sms_dispatch.py::_DISPATCH_ORDER drains it"
    )
    for name, purpose in sorted(writes.items()):
        assert purpose in DISPATCHED_PURPOSES, (
            f"{name} writes {purpose!r}, which no sweep ever asks the database for - "
            "those rows queue and are never sent"
        )


def test_every_idempotency_key_fits_the_format_the_provider_documents():
    """What the provider found out for us, at the cost of an alert.

    'admin_withdrawal_request' spelled out in full, with the prefix, a
    32-character anchor and a recipient's digits, is 75 characters. The
    provider rejects anything over 64, so the first live operator alert
    could not be sent - and because the key is derived, every retry
    rebuilt the identical invalid key, so it failed five times and
    stopped. Nothing locally had ever measured a key; the function's own
    docstring asserted it fit.

    The rule is the provider's, so it is checked here against the rule
    rather than against a monkeypatched send.
    """
    from app.services.sms_messages import _admin_idempotency_key, _idempotency_key

    anchor = uuid.uuid4()
    # Separators a number can really be configured with, and a long one.
    phones = ("255762474101", "+255 762 474 101", "+255-762-474-101", "0" * 20)

    keys = [_idempotency_key(p, anchor) for p in ("welcome", "withdrawal_complete")]
    keys += [
        _admin_idempotency_key(p, anchor, phone)
        for p in ("admin_new_merchant", "admin_withdrawal_request")
        for phone in phones
    ]
    # A purpose long enough to overflow must still produce a usable key,
    # not a rejected one.
    keys.append(_admin_idempotency_key("a" * 80, anchor, "255762474101"))

    for key in keys:
        assert 1 <= len(key) <= 64, f"{key!r} is {len(key)} characters; the provider allows 64"
        assert key.isascii(), f"{key!r} is not ASCII"
        assert key.isprintable() and " " not in key, f"{key!r} is not visible ASCII without spaces"


def test_an_idempotency_key_is_the_same_every_time_it_is_built():
    """A key that changed between attempts would turn a retry into a
    second charged message, which is what deriving it prevents."""
    from app.services.sms_messages import _admin_idempotency_key

    anchor = uuid.uuid4()
    long_purpose = "a" * 80  # the digest branch, where sameness is easiest to lose

    assert _admin_idempotency_key(long_purpose, anchor, "255762474101") == (
        _admin_idempotency_key(long_purpose, anchor, "255762474101")
    )
    assert _admin_idempotency_key(long_purpose, anchor, "255762474101") != (
        _admin_idempotency_key(long_purpose, anchor, "255762474102")
    ), "a second operator number must get its own copy, not be deduplicated away"
