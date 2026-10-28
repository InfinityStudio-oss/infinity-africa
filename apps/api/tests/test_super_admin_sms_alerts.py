"""Super Admin SMS: a business registering, and a withdrawal waiting.

Two alerts addressed to an operator rather than to a merchant, carried by
the SMS queue that already exists. What makes them correct is mostly what
they must NOT do:

  * not fire on a resubmission, which updates an existing merchant and
    returns before any merchants row is inserted;
  * not fire on a withdrawal that was rejected, auto-processed, or
    repeated through the idempotency key - "linasubiri idhini yako" must
    never be sent about a payout already on its way;
  * not be able to fail a registration or a withdrawal, both of which are
    committed before either alert is composed;
  * not reach a merchant, and not be reachable by one.

Money is read from the committed row and rendered through the same
format_amount every other money message uses, so it never passes through
a float.
"""

import uuid
from decimal import Decimal

import pytest

from app.config import get_settings
from app.services.sms_messages import (
    SKIP_NO_ADMIN_RECIPIENT,
    enqueue_admin_new_merchant_sms,
    enqueue_admin_withdrawal_request_sms,
)
from app.services.sms_text import (
    message_cost,
    render_new_merchant_admin,
    render_withdrawal_request_admin,
    sanitise_for_sms,
)

RECIPIENT = "255700000001"
SECOND = "255700000002"


@pytest.fixture
def on(monkeypatch):
    """Both alerts enabled with one synthetic recipient. Never a real number."""
    monkeypatch.setenv("SUPER_ADMIN_SMS_ENABLED", "true")
    monkeypatch.setenv("SUPER_ADMIN_SMS_NEW_MERCHANT_ENABLED", "true")
    monkeypatch.setenv("SUPER_ADMIN_SMS_WITHDRAWAL_REQUEST_ENABLED", "true")
    monkeypatch.setenv("SUPER_ADMIN_SMS_RECIPIENTS", RECIPIENT)
    monkeypatch.setenv("OASIS_SMS_SENDER_ID", "INFINITYPAY")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _withdrawal(merchant_id, *, status="PENDING_ADMIN_APPROVAL", amount="150000.00"):
    return {
        "id": str(uuid.uuid4()),
        "merchant_id": str(merchant_id),
        "status": status,
        "amount": amount,
        "provider_reference": None,
    }


def _queued(fake_client, purpose=None):
    rows = [r for r in fake_client.table("sms_messages")._table.rows]
    return [r for r in rows if purpose is None or r["purpose"] == purpose]


# --- 1. a registration queues exactly one per recipient -----------------


def test_a_new_merchant_queues_one_alert(fake_client, on):
    merchant_id = uuid.uuid4()

    rows = enqueue_admin_new_merchant_sms(
        fake_client, merchant_id=merchant_id, business_name="Juma Traders Ltd"
    )

    assert len(rows) == 1
    assert rows[0]["purpose"] == "admin_new_merchant"
    assert rows[0]["status"] == "queued"


def test_it_is_addressed_to_the_operator_not_the_merchant(fake_client, on):
    """merchant_id is the SUBJECT here. recipient_role is what says who it
    is for, and it is what any merchant-facing reader must filter on."""
    merchant_id = uuid.uuid4()

    rows = enqueue_admin_new_merchant_sms(fake_client, merchant_id=merchant_id, business_name="X")

    assert rows[0]["recipient_role"] == "super_admin"
    assert rows[0]["recipient_phone"] == RECIPIENT
    assert rows[0]["merchant_id"] == str(merchant_id)


def test_a_second_recipient_gets_their_own_copy(fake_client, on, monkeypatch):
    """The recipient is in the idempotency key precisely so configuring a
    second operator number delivers a second message rather than being
    swallowed as a duplicate of the first."""
    monkeypatch.setenv("SUPER_ADMIN_SMS_RECIPIENTS", f"{RECIPIENT},{SECOND}")
    get_settings.cache_clear()

    rows = enqueue_admin_new_merchant_sms(fake_client, merchant_id=uuid.uuid4(), business_name="X")

    assert {r["recipient_phone"] for r in rows} == {RECIPIENT, SECOND}
    assert len({r["idempotency_key"] for r in rows}) == 2


# --- 2 & 5. duplicates, enforced by the database ------------------------


def test_the_same_merchant_twice_queues_one(fake_client, on):
    """Atomic, not a check-then-insert: the unique index on
    idempotency_key is what loses the race, so a concurrent second attempt
    cannot produce a second message."""
    merchant_id = uuid.uuid4()

    first = enqueue_admin_new_merchant_sms(fake_client, merchant_id=merchant_id, business_name="X")
    second = enqueue_admin_new_merchant_sms(fake_client, merchant_id=merchant_id, business_name="X")

    assert len(first) == 1
    assert second == []
    assert len(_queued(fake_client, "admin_new_merchant")) == 1


def test_the_same_withdrawal_twice_queues_one(fake_client, on):
    withdrawal = _withdrawal(uuid.uuid4())

    enqueue_admin_withdrawal_request_sms(fake_client, disbursement=withdrawal, business_name="X", available_balance=Decimal("2450000.00"))
    again = enqueue_admin_withdrawal_request_sms(fake_client, disbursement=withdrawal, business_name="X", available_balance=Decimal("2450000.00"))

    assert again == []
    assert len(_queued(fake_client, "admin_withdrawal_request")) == 1


def test_two_different_merchants_each_get_one(fake_client, on):
    """Dedupe must be per subject, not global."""
    for _ in range(2):
        enqueue_admin_new_merchant_sms(fake_client, merchant_id=uuid.uuid4(), business_name="X")

    assert len(_queued(fake_client, "admin_new_merchant")) == 2


# --- 3, 4 & 6. only a withdrawal genuinely awaiting approval ------------


def test_a_withdrawal_awaiting_approval_queues_one(fake_client, on):
    rows = enqueue_admin_withdrawal_request_sms(
        fake_client, disbursement=_withdrawal(uuid.uuid4()), business_name="Juma Traders Ltd",
        available_balance=Decimal("2450000.00"),
    )

    assert len(rows) == 1
    assert rows[0]["purpose"] == "admin_withdrawal_request"


@pytest.mark.parametrize("status", ["PROCESSING", "SUCCESS", "FAILED", "REJECTED", "INFO_REQUESTED"])
def test_a_withdrawal_not_awaiting_approval_queues_nothing(fake_client, on, status):
    """An auto-processed or rejected payout never rests at
    PENDING_ADMIN_APPROVAL, so it must never produce a message claiming it
    is waiting for one."""
    rows = enqueue_admin_withdrawal_request_sms(
        fake_client, disbursement=_withdrawal(uuid.uuid4(), status=status), business_name="X",
        available_balance=Decimal("2450000.00"),
    )

    assert rows == []
    assert _queued(fake_client, "admin_withdrawal_request") == []


# --- 7. a failure here must not touch money or accounts -----------------


def test_a_broken_queue_does_not_raise_into_the_registration(fake_client, on, monkeypatch):
    """The registration is committed before this runs. A message about it
    must not be able to undo it, or even surface as an error."""
    import app.services.sms_messages as module

    monkeypatch.setattr(
        module, "_admin_rows", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("queue down"))
    )

    assert enqueue_admin_new_merchant_sms(fake_client, merchant_id=uuid.uuid4(), business_name="X") == []


def test_a_broken_queue_does_not_raise_into_the_withdrawal(fake_client, on, monkeypatch):
    import app.services.sms_messages as module

    monkeypatch.setattr(
        module, "_admin_rows", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("queue down"))
    )

    assert enqueue_admin_withdrawal_request_sms(
        fake_client, disbursement=_withdrawal(uuid.uuid4()), business_name="X",
        available_balance=Decimal("2450000.00"),
    ) == []


# --- 9. flags and configuration -----------------------------------------


def test_the_master_switch_stops_everything(fake_client, on, monkeypatch):
    monkeypatch.setenv("SUPER_ADMIN_SMS_ENABLED", "false")
    get_settings.cache_clear()

    assert enqueue_admin_new_merchant_sms(fake_client, merchant_id=uuid.uuid4(), business_name="X") == []
    assert enqueue_admin_withdrawal_request_sms(
        fake_client, disbursement=_withdrawal(uuid.uuid4()), business_name="X",
        available_balance=Decimal("2450000.00"),
    ) == []
    assert _queued(fake_client) == []


def test_each_event_can_be_turned_off_independently(fake_client, on, monkeypatch):
    """Turning one category off must not silence the other."""
    monkeypatch.setenv("SUPER_ADMIN_SMS_NEW_MERCHANT_ENABLED", "false")
    get_settings.cache_clear()

    assert enqueue_admin_new_merchant_sms(fake_client, merchant_id=uuid.uuid4(), business_name="X") == []
    assert len(
        enqueue_admin_withdrawal_request_sms(
            fake_client, disbursement=_withdrawal(uuid.uuid4()), business_name="X",
            available_balance=Decimal("2450000.00"),
        )
    ) == 1


def test_no_recipient_records_a_visible_skip(fake_client, on, monkeypatch):
    """Missing configuration must be visible to an operator without
    breaking a registration — a skip row with a reason, not silence."""
    monkeypatch.setenv("SUPER_ADMIN_SMS_RECIPIENTS", "")
    get_settings.cache_clear()

    rows = enqueue_admin_new_merchant_sms(fake_client, merchant_id=uuid.uuid4(), business_name="X")

    assert len(rows) == 1
    assert rows[0]["status"] == "skipped"
    assert rows[0]["skipped_reason"] == SKIP_NO_ADMIN_RECIPIENT
    assert rows[0]["recipient_phone"] == ""


def test_an_unusable_number_records_a_visible_skip(fake_client, on, monkeypatch):
    monkeypatch.setenv("SUPER_ADMIN_SMS_RECIPIENTS", "not-a-phone-number")
    get_settings.cache_clear()

    rows = enqueue_admin_new_merchant_sms(fake_client, merchant_id=uuid.uuid4(), business_name="X")

    assert rows[0]["status"] == "skipped"
    assert rows[0]["skipped_reason"]


# --- 11 & 6. what the message may not contain ---------------------------


def test_the_withdrawal_alert_carries_no_payout_destination(fake_client, on):
    """An operator decides by opening the queue. A destination account in
    a mailbox is a worse thing to have than a slightly less useful SMS."""
    withdrawal = {
        **_withdrawal(uuid.uuid4()),
        "destination_identifier": "255799888777",
        "destination_name": "Account Holder",
        "bank_name": "Some Bank",
    }

    rows = enqueue_admin_withdrawal_request_sms(
        fake_client, disbursement=withdrawal, business_name="X", available_balance=Decimal("2450000.00"))

    body = rows[0]["body"]
    for forbidden in ("255799888777", "Account Holder", "Some Bank"):
        assert forbidden not in body


def test_the_withdrawal_alert_quotes_the_available_balance(fake_client, on):
    """Added at the owner's explicit request, against the original brief's
    "do not include wallet balances". It is what lets an operator judge
    whether a payout can be covered without opening the queue, and it is
    the same figure the approval email already carries.

    Display-only: nothing reads this back to authorize anything."""
    rows = enqueue_admin_withdrawal_request_sms(
        fake_client,
        disbursement=_withdrawal(uuid.uuid4()),
        business_name="X",
        available_balance=Decimal("2450000.00"),
    )

    assert "Bal: TZS 2,450,000" in rows[0]["body"]


def test_neither_message_carries_a_customer_number(fake_client, on):
    merchant_id = uuid.uuid4()
    a = enqueue_admin_new_merchant_sms(fake_client, merchant_id=merchant_id, business_name="X")[0]
    b = enqueue_admin_withdrawal_request_sms(
        fake_client, disbursement=_withdrawal(merchant_id), business_name="X",
        available_balance=Decimal("2450000.00"),
    )[0]

    for body in (a["body"], b["body"]):
        assert "+255" not in body


def test_the_portal_link_is_a_login_not_an_action(fake_client, on):
    rows = enqueue_admin_new_merchant_sms(fake_client, merchant_id=uuid.uuid4(), business_name="X")

    assert "admin-login" in rows[0]["body"]
    for forbidden in ("token=", "approve="):
        assert forbidden not in rows[0]["body"]


# --- 12. templates, money and segments ----------------------------------


def test_the_message_says_the_merchant_is_not_yet_approved():
    """Registered is status='pending', kyc_status='unverified'. An operator
    reading this on a phone must not come away thinking otherwise."""
    assert "Not yet approved" in render_new_merchant_admin(business_name="X")


def test_money_is_rendered_from_decimal_not_float():
    body = render_withdrawal_request_admin(
        business_name="X", amount=Decimal("1234567.89"), reference="DIS-1",
        available_balance=Decimal(2450000)
    )

    assert "1,234,567.89" in body


def test_a_whole_amount_has_no_trailing_decimals():
    body = render_withdrawal_request_admin(
        business_name="X", amount=Decimal("150000.00"), reference="DIS-1",
        available_balance=Decimal(2450000)
    )

    # Asserts the property, not the punctuation around it. Two earlier
    # versions of this test broke on a template reword because they
    # matched a trailing space or full stop that had nothing to do with
    # how money is formatted.
    assert "150,000" in body
    assert "150,000.00" not in body


def test_a_long_business_name_cannot_run_up_the_segment_count():
    """A name is the one field here an outsider controls, and it decides
    the cost. Capped, so the worst case is bounded rather than unbounded."""
    body = render_new_merchant_admin(business_name="W" * 500)

    assert message_cost(body)["segments"] <= 2


def test_control_characters_are_removed_from_a_business_name():
    """A newline would make one message read as two; a zero-width
    character changes the segment count without changing anything
    visible."""
    cleaned = sanitise_for_sms("Bad\nName\r\twith\u200b control", limit=64)

    assert "\n" not in cleaned
    assert "\r" not in cleaned
    assert "\u200b" not in cleaned


def test_an_empty_business_name_does_not_leave_a_hole():
    assert sanitise_for_sms("", limit=32) == "-"
    assert sanitise_for_sms(None, limit=32) == "-"


def test_both_templates_stay_gsm7():
    """Unicode would halve the characters per segment and double the cost."""
    for body in (
        render_new_merchant_admin(business_name="Juma Traders Ltd"),
        render_withdrawal_request_admin(
            business_name="Juma Traders Ltd",
            amount=Decimal(150000),
            reference="85275081",
            available_balance=Decimal(2450000),
        ),
    ):
        assert message_cost(body)["encoding"] == "GSM-7"


def test_both_messages_lead_with_the_brand_on_its_own_line():
    """The layout the owner asked for: INFINITYPAY, then the news, then
    where to go. Pinned because a reword could collapse it back to one
    run-on line without any test noticing — and because a newline is a
    plain GSM-7 character, so the structure costs nothing to keep."""
    for body in (
        render_new_merchant_admin(business_name="Juma Traders Ltd"),
        render_withdrawal_request_admin(
            business_name="Juma Traders Ltd",
            amount=Decimal(150000),
            reference="85275081",
            available_balance=Decimal(2450000),
        ),
    ):
        lines = body.split("\n")
        assert lines[0] == "INFINITYPAY"
        assert len(lines) >= 3
        assert lines[-1].startswith("Review")
        # Still one message, not several: the newlines are layout, and the
        # encoding must not have slipped to UCS-2 because of them.
        assert message_cost(body)["encoding"] == "GSM-7"
