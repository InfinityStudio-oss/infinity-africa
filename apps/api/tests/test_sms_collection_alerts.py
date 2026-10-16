"""Merchant SMS alerts for successful collections.

The money is already correct by the time any of this runs. What these
tests protect is everything that could make the SMS wrong *about* the
money, or make the SMS the reason something else breaks:

  * a payer receiving a message intended for a merchant
  * a balance in the text that is not the balance after that payment
  * two alerts for one payment, from the callback and the sweep racing
  * an SMS failure taking a payment or a webhook down with it

The alert quotes a closing balance, and a balance is the kind of number a
merchant checks against their own records. One that is merely plausible
is worse than none.
"""

import uuid
from decimal import Decimal

import pytest

from app.config import get_settings
from app.services.sms_messages import (
    SKIP_MERCHANT_DISABLED,
    SKIP_NO_BALANCE_SNAPSHOT,
    SKIP_NO_NUMBER,
    enqueue_collection_alert,
    resolve_recipient,
)
from app.services.sms_text import message_cost, render_collection_alert
from tests.factories import create_merchant


@pytest.fixture(autouse=True)
def _sms_on(monkeypatch):
    monkeypatch.setenv("OASIS_SMS_ENABLED", "true")
    monkeypatch.setenv("OASIS_SMS_SENDER_ID", "INFINITYPAY")
    monkeypatch.setenv("OASIS_SMS_API_KEY", "test-key-not-real")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _setup(fake_client, *, sms_enabled=True, phone="255712000001", merchant_phone="255712000001"):
    merchant = create_merchant(fake_client, contact_phone=merchant_phone)
    fake_client.seed(
        "merchant_notification_settings",
        {
            "merchant_id": merchant["id"],
            "collection_sms_enabled": sms_enabled,
            "announcement_sms_enabled": True,
            "sms_notification_phone": phone,
        },
    )
    return merchant


def _collection(merchant, *, customer_phone="255799888777"):
    return {
        "id": str(uuid.uuid4()),
        "merchant_id": merchant["id"],
        "customer_phone": customer_phone,
        "status": "successful",
    }


def _transaction(*, gross="10000.00", fee="230.00", net="9770.00", reference="TXN-ABC123"):
    return {
        "id": str(uuid.uuid4()),
        "gross_amount": gross,
        "fee_amount": fee,
        "net_amount": net,
        "currency": "TZS",
        "reference": reference,
    }


def _rows(fake_client):
    return fake_client.table("sms_messages")._table.rows


# --- who receives ------------------------------------------------------


def test_the_merchant_is_the_recipient_never_the_payer(fake_client):
    """The whole feature in one assertion. The payer's number is right
    there on the collection, and it must never be what we send to."""
    merchant = _setup(fake_client, phone="255712000001")
    collection = _collection(merchant, customer_phone="255799888777")

    enqueue_collection_alert(
        fake_client,
        collection=collection,
        transaction=_transaction(),
        closing_balance=Decimal("59770.00"),
    )

    row = _rows(fake_client)[0]
    assert row["recipient_phone"] == "255712000001"
    assert "255799888777" not in row["recipient_phone"]
    assert "255799888777" not in row["body"]


def test_the_designated_number_wins_over_the_contact_number(fake_client):
    merchant = _setup(fake_client, phone="255713111111", merchant_phone="255714222222")

    phone, reason = resolve_recipient(fake_client, uuid.UUID(merchant["id"]))

    assert phone == "255713111111"
    assert reason is None


def test_the_contact_number_is_the_fallback(fake_client):
    """Without a fallback the feature would arrive switched off for all
    60 merchants until each one set a second number."""
    merchant = create_merchant(fake_client, contact_phone="0714222222")

    phone, reason = resolve_recipient(fake_client, uuid.UUID(merchant["id"]))

    assert phone == "255714222222", "should normalise to E.164"
    assert reason is None


def test_a_merchant_with_no_number_is_skipped_with_a_reason(fake_client):
    merchant = create_merchant(fake_client, contact_phone=None)
    fake_client.seed(
        "merchant_notification_settings",
        {"merchant_id": merchant["id"], "collection_sms_enabled": True},
    )

    enqueue_collection_alert(
        fake_client,
        collection=_collection(merchant),
        transaction=_transaction(),
        closing_balance=Decimal("100.00"),
    )

    row = _rows(fake_client)[0]
    assert row["status"] == "skipped"
    assert row["skipped_reason"] == SKIP_NO_NUMBER


def test_a_merchant_who_never_opted_in_produces_no_row_at_all(fake_client):
    """Not even a skipped one.

    SMS starts off for every merchant, and 3,748 payments succeeded in
    the first sixteen days of October. A row per payment saying "this
    merchant has SMS off" would add thousands a month that say nothing,
    and would bury the skips that do mean something.
    """
    merchant = _setup(fake_client, sms_enabled=False)

    enqueue_collection_alert(
        fake_client,
        collection=_collection(merchant),
        transaction=_transaction(),
        closing_balance=Decimal("100.00"),
    )

    assert _rows(fake_client) == []


def test_a_skipped_row_always_means_somebody_wanted_an_alert(fake_client):
    """The property that makes the Super Admin skip list worth reading:
    every row in it is a merchant who asked for alerts and did not get
    one."""
    merchant = create_merchant(fake_client, contact_phone=None)
    fake_client.seed(
        "merchant_notification_settings",
        {"merchant_id": merchant["id"], "collection_sms_enabled": True},
    )

    enqueue_collection_alert(
        fake_client,
        collection=_collection(merchant),
        transaction=_transaction(),
        closing_balance=Decimal("100.00"),
    )

    row = _rows(fake_client)[0]
    assert row["status"] == "skipped"
    assert row["skipped_reason"] == SKIP_NO_NUMBER
    assert SKIP_MERCHANT_DISABLED != row["skipped_reason"]


def test_nothing_is_queued_at_all_while_the_feature_is_off(fake_client, monkeypatch):
    """Not even a skipped row. Rows accumulating while SMS is dark would
    either be noise forever or, if left queued, blast a backlog of
    historical payments the moment it is switched on - the backfill the
    brief rules out."""
    monkeypatch.setenv("OASIS_SMS_ENABLED", "false")
    get_settings.cache_clear()
    merchant = _setup(fake_client)

    enqueue_collection_alert(
        fake_client,
        collection=_collection(merchant),
        transaction=_transaction(),
        closing_balance=Decimal("100.00"),
    )

    assert _rows(fake_client) == []


# --- what it says ------------------------------------------------------


def test_the_message_matches_the_brief_exactly(fake_client):
    text = render_collection_alert(
        gross_amount=Decimal("10000.00"),
        fee_amount=Decimal("230.00"),
        net_amount=Decimal("9770.00"),
        closing_balance=Decimal("59770.00"),
        reference="TXN-XXXX",
    )

    assert text == (
        "InfinityPay: Umepokea TZS 10,000. "
        "Makato: TZS 230. "
        "Kiasi halisi: TZS 9,770. "
        "Salio baada ya muamala: TZS 59,770. "
        "Kumbukumbu: TXN-XXXX."
    )


def test_the_figures_come_from_the_transaction_and_are_not_recomputed(fake_client):
    """net is read, never derived. If the renderer computed gross - fee it
    would silently disagree with the ledger the moment a pricing rule
    rounded differently, and the SMS would contradict the portal."""
    merchant = _setup(fake_client)

    enqueue_collection_alert(
        fake_client,
        collection=_collection(merchant),
        # Deliberately inconsistent: net is NOT gross - fee here.
        transaction=_transaction(gross="5000.00", fee="100.00", net="4321.00"),
        closing_balance=Decimal("4321.00"),
    )

    row = _rows(fake_client)[0]
    assert "TZS 4,321" in row["body"]
    assert row["net_amount"] == "4321.00"


def test_a_fractional_amount_is_never_truncated(fake_client):
    text = render_collection_alert(
        gross_amount=Decimal("10000.50"),
        fee_amount=Decimal("230.25"),
        net_amount=Decimal("9770.25"),
        closing_balance=Decimal("59770.75"),
        reference="TXN-1",
    )

    assert "TZS 10,000.50" in text
    assert "TZS 59,770.75" in text


def test_the_closing_balance_is_the_one_handed_down_not_a_later_balance(fake_client):
    """The brief's sharpest rule. The queued row must quote the balance
    this payment produced, and a wallet read at send time would return
    whatever is there after the next payment or withdrawal."""
    merchant = _setup(fake_client)

    enqueue_collection_alert(
        fake_client,
        collection=_collection(merchant),
        transaction=_transaction(),
        closing_balance=Decimal("59770.00"),
    )

    row = _rows(fake_client)[0]
    assert row["closing_balance"] == "59770.00"
    assert "Salio baada ya muamala: TZS 59,770." in row["body"]


def test_a_later_balance_change_does_not_alter_a_queued_message(fake_client):
    """The frozen snapshot, demonstrated: the body is already text, so
    nothing that happens to the wallet afterwards can reach it."""
    merchant = _setup(fake_client)
    enqueue_collection_alert(
        fake_client,
        collection=_collection(merchant),
        transaction=_transaction(),
        closing_balance=Decimal("59770.00"),
    )
    before = _rows(fake_client)[0]["body"]

    # A withdrawal empties the wallet.
    fake_client.seed("ledger_accounts", {"merchant_id": merchant["id"], "balance": "0.00"})

    assert _rows(fake_client)[0]["body"] == before
    assert "59,770" in _rows(fake_client)[0]["body"]


def test_no_snapshot_means_no_message_rather_than_a_guessed_balance(fake_client):
    """Postings predating the snapshot columns have no closing balance,
    and the migration that added them says there is no sound way to
    reconstruct one. Saying nothing beats stating a number we inferred."""
    merchant = _setup(fake_client)

    enqueue_collection_alert(
        fake_client,
        collection=_collection(merchant),
        transaction=_transaction(),
        closing_balance=None,
    )

    row = _rows(fake_client)[0]
    assert row["status"] == "skipped"
    assert row["skipped_reason"] == SKIP_NO_BALANCE_SNAPSHOT
    assert row["body"] == ""


def test_the_message_makes_no_claim_about_service_activation(fake_client):
    """We do not know whether the ISP activated anything. BEACH WiFi's
    customers were not connected despite a successful payment, and an SMS
    promising otherwise would have made that worse."""
    text = render_collection_alert(
        gross_amount=Decimal("1000"),
        fee_amount=Decimal("0"),
        net_amount=Decimal("1000"),
        closing_balance=Decimal("1000"),
        reference="TXN-1",
    )
    lowered = text.lower()

    for claim in ("intaneti", "voucher", "umeunganishwa", "activated"):
        assert claim not in lowered


# --- cost --------------------------------------------------------------


def test_a_receipt_is_not_assumed_to_fit_one_part(fake_client):
    """It usually does, but with four amounts and a long reference it can
    tip over 160 characters, and the cost of that should be visible
    rather than discovered on an invoice."""
    long_reference = "TXN-" + "9" * 60
    text = render_collection_alert(
        gross_amount=Decimal("1000000.00"),
        fee_amount=Decimal("23000.00"),
        net_amount=Decimal("977000.00"),
        closing_balance=Decimal("98765432.00"),
        reference=long_reference,
    )

    cost = message_cost(text)
    assert cost["segments"] >= 2
    assert long_reference in text, "a reference must never be shortened to save a part"


def test_the_alert_stays_in_the_cheap_encoding(fake_client):
    """One decorative character would drop the part size from 160 to 70
    and roughly double the cost of every receipt."""
    text = render_collection_alert(
        gross_amount=Decimal("10000"),
        fee_amount=Decimal("230"),
        net_amount=Decimal("9770"),
        closing_balance=Decimal("59770"),
        reference="TXN-XXXX",
    )

    assert message_cost(text)["encoding"] == "GSM-7"
    assert message_cost(text)["segments"] == 1


def test_unicode_is_counted_as_unicode():
    assert message_cost("habari")["encoding"] == "GSM-7"
    assert message_cost("habari — njema")["encoding"] == "UCS-2"
    assert message_cost("a" * 161)["segments"] == 2
    assert message_cost("—" * 71)["segments"] == 2


# --- duplicate protection ----------------------------------------------


def test_one_collection_produces_one_alert(fake_client):
    """The Selcom callback and the reconciliation sweep routinely resolve
    the same collection at once. Both reach this function; the unique
    index decides."""
    merchant = _setup(fake_client)
    collection = _collection(merchant)
    transaction = _transaction()

    first = enqueue_collection_alert(
        fake_client, collection=collection, transaction=transaction, closing_balance=Decimal("1")
    )
    second = enqueue_collection_alert(
        fake_client, collection=collection, transaction=transaction, closing_balance=Decimal("1")
    )

    assert first is not None
    assert second is None, "the second signal must not create a second alert"
    assert len(_rows(fake_client)) == 1


def test_the_idempotency_key_is_stable_for_a_collection(fake_client):
    """A retry must carry the key the first attempt used, or the provider
    cannot tell a retry from a second message."""
    merchant = _setup(fake_client)
    collection = _collection(merchant)

    enqueue_collection_alert(
        fake_client,
        collection=collection,
        transaction=_transaction(),
        closing_balance=Decimal("1"),
    )

    key = _rows(fake_client)[0]["idempotency_key"]
    assert key == f"ipay-c-{uuid.UUID(collection['id']).hex}"
    assert " " not in key
    assert 1 <= len(key) <= 64, "provider documents 1-64 visible ASCII characters"


# --- it must never break a payment -------------------------------------


def test_a_broken_database_does_not_raise_into_the_payment_path(fake_client):
    """This runs inside resolve_collection, after the money has moved. An
    exception escaping here would turn a completed payment into a request
    that appears to have failed."""

    class _Broken:
        def table(self, _name):
            raise RuntimeError("supabase unreachable")

    result = enqueue_collection_alert(
        _Broken(),
        collection={"id": str(uuid.uuid4()), "merchant_id": str(uuid.uuid4())},
        transaction=_transaction(),
        closing_balance=Decimal("1"),
    )

    assert result is None


def test_nothing_here_writes_to_a_financial_table(fake_client):
    merchant = _setup(fake_client)

    enqueue_collection_alert(
        fake_client,
        collection=_collection(merchant),
        transaction=_transaction(),
        closing_balance=Decimal("1"),
    )

    for table in ("ledger_entries", "ledger_accounts", "transactions", "collections"):
        assert fake_client.table(table)._table.rows == [], f"{table} was written to"
