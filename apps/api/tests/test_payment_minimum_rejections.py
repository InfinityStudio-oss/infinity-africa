"""A payment refused before it starts should still leave a trace.

`assert_amount_allowed` rejects a push the network itself would refuse -
Mixx by Yas will not take below TZS 1,000 - before anything is created:
no collection, no transaction, no checkout order, no provider call. Right
behaviour, and it left nothing behind at all.

Production, 23 October: 153 refusals in one day across seven merchants,
107 for a single merchant. Grouped by time they were about twelve
customers, three of whom tried **16, 28 and 30 times** - one for thirteen
minutes - because the merchant's screen said "Pending" and never showed
the reason. Asked for those customers' numbers so they could be helped,
there was nothing to give.

Now each refusal writes an audit row with the amount, the network, the
minimum required, and the phone **masked to four digits** - enough to
confirm "is this your number?", not enough to be a customer database.

The recording must never change the outcome. A refused payment stays
refused, with the same error, whether or not the record could be written.
"""

import uuid
from decimal import Decimal

import pytest

from app.core.payment_minimums import AmountBelowOperatorMinimumError
from app.services.payment_rejections import (
    ACTION,
    assert_amount_allowed_recording,
    mask_phone,
)

TIGO = "255712345678"      # 071 -> Mixx by Yas, minimum TZS 1,000
VODACOM = "255754111222"   # 075 -> Vodacom, minimum TZS 200


def _rows(fake_client):
    return [r for r in fake_client.table("audit_logs")._table.rows if r["action"] == ACTION]


# --- masking -----------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("255712345678", "•••• 5678"),
        ("+255 712 345 678", "•••• 5678"),
        ("0712345678", "•••• 5678"),
    ],
)
def test_a_number_is_masked_to_its_last_four_digits(raw, expected):
    assert mask_phone(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "12", "abc"])
def test_nothing_maskable_returns_nothing(raw):
    assert mask_phone(raw) is None


def test_the_full_number_never_survives_masking():
    """The point of the mask. If the whole number came through, this would
    be a customer database rather than a support aid."""
    masked = mask_phone("255712345678")

    assert "255712345" not in masked
    assert masked.count("•") == 4


# --- the refusal is recorded -------------------------------------------


def test_a_refused_payment_is_recorded(fake_client):
    merchant_id = uuid.uuid4()

    with pytest.raises(AmountBelowOperatorMinimumError):
        assert_amount_allowed_recording(
            fake_client, Decimal("500"), merchant_id=merchant_id, customer_phone=TIGO
        )

    assert len(_rows(fake_client)) == 1


def test_the_record_carries_what_support_needs(fake_client):
    merchant_id = uuid.uuid4()

    with pytest.raises(AmountBelowOperatorMinimumError):
        assert_amount_allowed_recording(
            fake_client, Decimal("500"), merchant_id=merchant_id, customer_phone=TIGO
        )

    meta = _rows(fake_client)[0]["metadata"]
    assert meta["amount"] == "500"
    assert meta["customer_phone_masked"] == "•••• 5678"
    assert meta["minimum_required"] == "1000"
    assert meta["network"] is not None


def test_the_record_never_contains_the_full_number(fake_client):
    """Asserted against the whole row, not just the field, because a leak
    here would defeat the entire design."""
    with pytest.raises(AmountBelowOperatorMinimumError):
        assert_amount_allowed_recording(
            fake_client, Decimal("500"), merchant_id=uuid.uuid4(), customer_phone=TIGO
        )

    assert "255712345678" not in str(_rows(fake_client)[0])


def test_it_is_attributed_to_the_merchant_so_it_can_be_counted(fake_client):
    merchant_id = uuid.uuid4()

    with pytest.raises(AmountBelowOperatorMinimumError):
        assert_amount_allowed_recording(
            fake_client, Decimal("500"), merchant_id=merchant_id, customer_phone=TIGO
        )

    assert str(_rows(fake_client)[0]["merchant_id"]) == str(merchant_id)


def test_the_actor_is_the_system_not_a_user(fake_client):
    """Nobody did this - a rule did. Recording a user would put a person's
    id against a refusal they had no part in."""
    with pytest.raises(AmountBelowOperatorMinimumError):
        assert_amount_allowed_recording(
            fake_client, Decimal("500"), merchant_id=uuid.uuid4(), customer_phone=TIGO
        )

    row = _rows(fake_client)[0]
    assert row["actor_type"] == "system"
    assert row["actor_id"] is None


def test_each_retry_is_recorded_separately(fake_client):
    """One customer tried thirty times. Counting attempts is how that
    became visible, so they must not be collapsed."""
    merchant_id = uuid.uuid4()

    for _ in range(5):
        with pytest.raises(AmountBelowOperatorMinimumError):
            assert_amount_allowed_recording(
                fake_client, Decimal("500"), merchant_id=merchant_id, customer_phone=TIGO
            )

    assert len(_rows(fake_client)) == 5


# --- what must not change ----------------------------------------------


def test_an_allowed_payment_records_nothing(fake_client):
    """Only refusals. A row per successful payment would make this a log
    of every customer who ever paid."""
    assert_amount_allowed_recording(
        fake_client, Decimal("500"), merchant_id=uuid.uuid4(), customer_phone=VODACOM
    )

    assert _rows(fake_client) == []


def test_the_same_amount_is_allowed_on_a_network_that_takes_it(fake_client):
    """TZS 500 is refused on Mixx by Yas and fine on Vodacom - the rule is
    about the network, not the amount."""
    assert_amount_allowed_recording(
        fake_client, Decimal("500"), merchant_id=uuid.uuid4(), customer_phone=VODACOM
    )

    with pytest.raises(AmountBelowOperatorMinimumError):
        assert_amount_allowed_recording(
            fake_client, Decimal("500"), merchant_id=uuid.uuid4(), customer_phone=TIGO
        )


def test_a_failed_recording_still_refuses_the_payment(fake_client, monkeypatch):
    """The guarantee that matters. This records something about a request
    that is already being refused - letting the write turn a clean 400
    into a 500 would break the protection it reports on."""
    import app.services.payment_rejections as module

    def _explode(*_a, **_k):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(module, "write_audit_log_best_effort", _explode)

    with pytest.raises(AmountBelowOperatorMinimumError):
        assert_amount_allowed_recording(
            fake_client, Decimal("500"), merchant_id=uuid.uuid4(), customer_phone=TIGO
        )
