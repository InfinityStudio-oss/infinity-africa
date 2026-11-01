"""One email a day instead of 540.

Measured on 2026-11-01: 30,135 merchant collection notification emails in
thirty days across 70 businesses, 16,215 of them to one merchant — 540 a
day, one every two and a half minutes. Merchants asked for it to stop,
and five had already switched themselves off entirely, which costs them
every email view of money arriving.

So `collection_notification_frequency = 'daily_summary'` suppresses the
per-payment email and a sweep sends one message the next morning.

The things worth pinning here are the ones that would be expensive to get
wrong: sending twice, sending somebody else's figures, using the wrong
day boundary, and continuing to send to a merchant who was switched off
while the sweep was running.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import resend

from app.config import get_settings
from app.core.time import dar_es_salaam_day_start_utc
from app.services.daily_notification_summary import send_daily_collection_summaries
from tests.factories import create_merchant

EAT = timezone(timedelta(hours=3))

# Mid-month and mid-week, fixed. A sweep that derives its window from the
# real clock is a test that tests something different every day.
NOW = datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("EMAIL_FROM", "InfinityPay <notification@infinitypay.me>")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakeResend:
    def __init__(self):
        self.calls: list[dict] = []

    def send(self, params: dict) -> dict:
        self.calls.append(params)
        return {"id": "resend-test-message-id"}


@pytest.fixture(autouse=True)
def fake_resend(monkeypatch):
    fake = _FakeResend()
    monkeypatch.setattr(resend.Emails, "send", fake.send)
    return fake


def _yesterday_window() -> tuple[str, str]:
    today = dar_es_salaam_day_start_utc(NOW)
    start = datetime.fromisoformat(today.replace("Z", "+00:00")) - timedelta(days=1)
    return start.isoformat().replace("+00:00", "Z"), today


def _merchant_on_daily(fake_client, *, name="Busy Shop", email="owner@shop.co.tz", primary=None):
    merchant = create_merchant(fake_client, business_name=name, contact_email=email)
    fake_client.seed(
        "merchant_notification_settings",
        {
            "merchant_id": merchant["id"],
            "collection_notifications_enabled": True,
            "collection_notification_frequency": "daily_summary",
            "primary_notification_email": primary,
        },
    )
    return merchant


def _payment(fake_client, merchant_id, amount, when):
    fake_client.seed(
        "transactions",
        {
            "merchant_id": str(merchant_id),
            "type": "collection",
            "status": "successful",
            "gross_amount": amount,
            "fee_amount": "0",
            "net_amount": amount,
            "currency": "TZS",
            "created_at": when,
        },
    )


def _summaries(fake_client):
    return fake_client.table("merchant_daily_notification_summaries")._table.rows


# --- It sends, once, with the right figures ---------------------------------


def test_one_email_covers_the_whole_day(fake_client, fake_resend):
    merchant = _merchant_on_daily(fake_client)
    start, _end = _yesterday_window()
    for amount in ("1000", "2500", "500"):
        _payment(fake_client, merchant["id"], amount, start)

    result = send_daily_collection_summaries(fake_client, now=NOW)

    assert result["sent"] == 1
    assert len(fake_resend.calls) == 1
    body = fake_resend.calls[0]["html"]
    assert "3" in fake_resend.calls[0]["subject"]
    assert "4,000" in body


def test_the_same_day_is_never_sent_twice(fake_client, fake_resend):
    """The failure this whole table exists to prevent. The sweep runs on
    a timer across replicas, so "did we already send?" cannot live in
    process memory — claiming the day is an insert, and the second one
    loses."""
    merchant = _merchant_on_daily(fake_client)
    start, _end = _yesterday_window()
    _payment(fake_client, merchant["id"], "1000", start)

    send_daily_collection_summaries(fake_client, now=NOW)
    second = send_daily_collection_summaries(fake_client, now=NOW)

    assert len(fake_resend.calls) == 1
    assert second["sent"] == 0
    assert len(_summaries(fake_client)) == 1


def test_a_merchant_only_sees_their_own_payments(fake_client, fake_resend):
    """The one mistake that would be unrecoverable: telling a merchant
    somebody else's takings."""
    mine = _merchant_on_daily(fake_client, name="Mine")
    theirs = create_merchant(fake_client, business_name="Theirs")
    start, _end = _yesterday_window()
    _payment(fake_client, mine["id"], "1000", start)
    _payment(fake_client, theirs["id"], "999999", start)

    send_daily_collection_summaries(fake_client, now=NOW)

    body = fake_resend.calls[0]["html"]
    assert "1,000" in body
    assert "999,999" not in body


# --- The day boundary is the merchant's -------------------------------------


def test_the_window_is_the_tanzanian_day_not_the_utc_one(fake_client, fake_resend):
    """Tanzania is UTC+3, so a local day runs 21:00 to 21:00 UTC.
    Summarising a UTC day would push the first three hours of every
    evening into the wrong report — and a merchant reconciling against
    their own records would find the total nearly, but not quite,
    right."""
    merchant = _merchant_on_daily(fake_client)
    start, end = _yesterday_window()

    # 22:00 EAT yesterday = inside the reported day, outside the UTC one.
    late_local = datetime.fromisoformat(end.replace("Z", "+00:00")) - timedelta(hours=1)
    _payment(fake_client, merchant["id"], "7000", late_local.isoformat().replace("+00:00", "Z"))
    # One second before the window opened: the day before, excluded.
    before = datetime.fromisoformat(start.replace("Z", "+00:00")) - timedelta(seconds=1)
    _payment(fake_client, merchant["id"], "123456", before.isoformat().replace("+00:00", "Z"))

    send_daily_collection_summaries(fake_client, now=NOW)

    body = fake_resend.calls[0]["html"]
    assert "7,000" in body
    assert "123,456" not in body


def test_todays_payments_are_not_in_yesterdays_summary(fake_client, fake_resend):
    merchant = _merchant_on_daily(fake_client)
    start, end = _yesterday_window()
    _payment(fake_client, merchant["id"], "1000", start)
    # After this morning's local midnight.
    _payment(fake_client, merchant["id"], "555555", end)

    send_daily_collection_summaries(fake_client, now=NOW)

    assert "555,555" not in fake_resend.calls[0]["html"]


# --- Who gets one, and who does not -----------------------------------------


def test_a_merchant_on_per_payment_gets_no_summary(fake_client, fake_resend):
    merchant = create_merchant(fake_client, business_name="Per Payment Co")
    fake_client.seed(
        "merchant_notification_settings",
        {
            "merchant_id": merchant["id"],
            "collection_notifications_enabled": True,
            "collection_notification_frequency": "per_payment",
        },
    )
    start, _end = _yesterday_window()
    _payment(fake_client, merchant["id"], "1000", start)

    result = send_daily_collection_summaries(fake_client, now=NOW)

    assert result["sent"] == 0
    assert fake_resend.calls == []


def test_a_switched_off_merchant_gets_no_summary(fake_client, fake_resend):
    """Off means off. The frequency is not a second on-switch."""
    merchant = create_merchant(fake_client, business_name="Switched Off")
    fake_client.seed(
        "merchant_notification_settings",
        {
            "merchant_id": merchant["id"],
            "collection_notifications_enabled": False,
            "collection_notification_frequency": "daily_summary",
        },
    )
    start, _end = _yesterday_window()
    _payment(fake_client, merchant["id"], "1000", start)

    assert send_daily_collection_summaries(fake_client, now=NOW)["sent"] == 0
    assert fake_resend.calls == []


def test_a_quiet_day_sends_nothing(fake_client, fake_resend):
    """"You received nothing yesterday" is how people learn to stop
    reading the ones that matter. The day is still claimed, so it is not
    reconsidered on every tick."""
    _merchant_on_daily(fake_client)

    result = send_daily_collection_summaries(fake_client, now=NOW)

    assert fake_resend.calls == []
    assert result["skipped"] == 1
    assert _summaries(fake_client)[0]["status"] == "skipped"


# --- Recipients --------------------------------------------------------------


def test_it_uses_the_configured_address(fake_client, fake_resend):
    merchant = _merchant_on_daily(fake_client, primary="finance@shop.co.tz")
    start, _end = _yesterday_window()
    _payment(fake_client, merchant["id"], "1000", start)

    send_daily_collection_summaries(fake_client, now=NOW)

    assert fake_resend.calls[0]["to"] == ["finance@shop.co.tz"]


def test_it_falls_back_to_the_account_email(fake_client, fake_resend):
    """Same rule as the per-payment email. A merchant moving between the
    two frequencies must not find their mail going somewhere else."""
    merchant = _merchant_on_daily(fake_client, email="owner@shop.co.tz", primary=None)
    start, _end = _yesterday_window()
    _payment(fake_client, merchant["id"], "1000", start)

    send_daily_collection_summaries(fake_client, now=NOW)

    assert fake_resend.calls[0]["to"] == ["owner@shop.co.tz"]


# --- It does not fall over ---------------------------------------------------


def test_one_bad_merchant_does_not_stop_the_others(fake_client, fake_resend):
    """Sixty-nine other businesses are waiting behind the one with no
    address."""
    broken = _merchant_on_daily(fake_client, name="No Address", email="", primary=None)
    fine = _merchant_on_daily(fake_client, name="Fine Shop", email="ok@shop.co.tz")
    start, _end = _yesterday_window()
    _payment(fake_client, broken["id"], "1000", start)
    _payment(fake_client, fine["id"], "2000", start)

    result = send_daily_collection_summaries(fake_client, now=NOW)

    assert result["sent"] == 1
    assert result["skipped"] == 1
    assert fake_resend.calls[0]["to"] == ["ok@shop.co.tz"]


def test_a_send_failure_still_claims_the_day(fake_client, fake_resend, monkeypatch):
    """Claimed before sending, deliberately. The other order risks a
    second copy on the next tick, and a merchant receiving the same
    summary twice is worse than missing one — the miss is visible in the
    table, the duplicate is only visible in their inbox."""
    merchant = _merchant_on_daily(fake_client)
    start, _end = _yesterday_window()
    _payment(fake_client, merchant["id"], "1000", start)

    def explode(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(resend.Emails, "send", explode)

    send_daily_collection_summaries(fake_client, now=NOW)

    assert len(_summaries(fake_client)) == 1
    # And the next tick does not try again.
    monkeypatch.setattr(resend.Emails, "send", fake_resend.send)
    send_daily_collection_summaries(fake_client, now=NOW)
    assert fake_resend.calls == []


def test_unreadable_settings_send_nothing(fake_client, monkeypatch, fake_resend):
    """A read failure is not a reason to email 70 businesses."""
    real_table = fake_client.table

    def broken(name: str):
        if name == "merchant_notification_settings":
            raise RuntimeError("postgrest is down")
        return real_table(name)

    monkeypatch.setattr(fake_client, "table", broken)

    result = send_daily_collection_summaries(fake_client, now=NOW)

    assert result["sent"] == 0
    assert fake_resend.calls == []


# --- The per-payment path respects the choice --------------------------------


def test_the_per_payment_email_is_suppressed_for_daily_merchants(fake_client, fake_resend):
    """Checked in the send path too, not only in the sweep — this is the
    code that runs 540 times a day for the busiest merchant."""
    from app.services.email import send_merchant_collection_notification_email

    merchant = _merchant_on_daily(fake_client, primary="finance@shop.co.tz")

    result = send_merchant_collection_notification_email(
        fake_client,
        merchant=merchant,
        transaction={"gross_amount": "1000", "currency": "TZS"},
        collection={"id": str(uuid.uuid4()), "amount": "1000"},
    )

    assert result == []
    assert fake_resend.calls == []


def test_an_unreadable_frequency_keeps_the_per_payment_email(fake_client, fake_resend):
    """Fail toward the behaviour that existed before the setting did. A
    column that failed to read must not silently move a merchant onto a
    daily email they never asked for."""
    from app.services.email import send_merchant_collection_notification_email

    merchant = create_merchant(fake_client, business_name="No Frequency", contact_email="o@s.co.tz")
    fake_client.seed(
        "merchant_notification_settings",
        {
            "merchant_id": merchant["id"],
            "collection_notifications_enabled": True,
            # Column absent, as it is on every row written before
            # migration 20261101010000.
        },
    )

    send_merchant_collection_notification_email(
        fake_client,
        merchant=merchant,
        transaction={"gross_amount": "1000", "currency": "TZS"},
        collection={"id": str(uuid.uuid4()), "amount": "1000"},
    )

    assert len(fake_resend.calls) == 1


def test_the_summary_reports_the_amount_without_a_float(fake_client, fake_resend):
    merchant = _merchant_on_daily(fake_client)
    start, _end = _yesterday_window()
    _payment(fake_client, merchant["id"], "1000.10", start)
    _payment(fake_client, merchant["id"], "2000.20", start)

    send_daily_collection_summaries(fake_client, now=NOW)

    assert "3,000.30" in fake_resend.calls[0]["html"]
    stored = _summaries(fake_client)[0]
    assert Decimal(str(stored["gross_amount"])) == Decimal("3000.30")


def test_the_database_refuses_a_second_claim_for_the_same_day(fake_client, fake_resend):
    """The guarantee under the guarantee.

    The sweep's own "have we sent this?" read is a courtesy — two
    replicas waking together would both get "no". What actually holds is
    the unique (merchant_id, summary_date) row, so this asserts the
    constraint directly rather than trusting the check above it.
    """
    merchant = _merchant_on_daily(fake_client)
    start, _end = _yesterday_window()
    _payment(fake_client, merchant["id"], "1000", start)
    send_daily_collection_summaries(fake_client, now=NOW)

    with pytest.raises(Exception, match="unique constraint"):
        fake_client.table("merchant_daily_notification_summaries")._table.insert(
            {
                "merchant_id": merchant["id"],
                "summary_date": _summaries(fake_client)[0]["summary_date"],
                "collection_count": 1,
            }
        )


def test_a_claim_lost_to_another_replica_sends_nothing(fake_client, fake_resend, monkeypatch):
    """The race itself: this replica passed its "already sent?" check,
    then lost the insert. It must not go on to email anyway."""
    merchant = _merchant_on_daily(fake_client)
    start, _end = _yesterday_window()
    _payment(fake_client, merchant["id"], "1000", start)

    import app.services.daily_notification_summary as sweep

    monkeypatch.setattr(sweep, "_already_claimed", lambda *a, **k: False)
    real_insert = fake_client.table("merchant_daily_notification_summaries")._table.insert

    def lose(row):
        error = Exception("duplicate key value violates unique constraint")
        error.code = "23505"
        raise error

    fake_client.table("merchant_daily_notification_summaries")._table.insert = lose
    try:
        result = send_daily_collection_summaries(fake_client, now=NOW)
    finally:
        fake_client.table("merchant_daily_notification_summaries")._table.insert = real_insert

    assert result["sent"] == 0
    assert fake_resend.calls == []
