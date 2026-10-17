"""How often we ask Selcom about one pending payment.

The sweep interval and the provider load were the same dial until
2026-10-17: each sweep selected every pending row and asked about all of
them, so halving the interval doubled the questions asked about every
payment - including the ones that were never going to resolve.

Measured on 4,024 real collections from 10-17 October:

    flat 120s         15,482 provider calls    3.8 per collection
    flat  30s         57,529                  14.3   (the interval then)
    flat  10s        175,706                  43.7
    tiered 10->300s   50,214                  12.5

58% resolve within two minutes; the p90 is 1,909 seconds, which is an
abandoned push waiting out collection_push_expiry_minutes. That is why a
flat ten second sweep costs three times what thirty did and learns almost
nothing extra - and why the tiered schedule can run every ten seconds and
still cost less than today.

These tests are about *when we ask*, never about what the answer means.
Nothing here can resolve a payment.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.reconciliation_schedule import interval_for_age, next_check_at

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)


def _seconds_until(result: str, now: datetime = NOW) -> float:
    return (datetime.fromisoformat(result) - now).total_seconds()


# --- the shape of the schedule -----------------------------------------


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (0, 10),
        (30, 10),
        (119, 10),
        (120, 30),
        (299, 30),
        (300, 120),
        (899, 120),
        (900, 300),
        (2399, 300),
    ],
)
def test_the_interval_grows_as_a_payment_ages(age, expected):
    assert interval_for_age(age) == expected


def test_a_young_payment_is_asked_about_at_the_sweep_interval(fake_client):
    """The part a merchant notices. A payment under two minutes old is
    checked about every ten seconds, which is the whole point of running
    the sweep that often."""
    created = NOW - timedelta(seconds=5)

    assert 10 <= _seconds_until(next_check_at(created, now=NOW)) <= 12


def test_an_abandoned_push_backs_off_instead_of_being_hammered(fake_client):
    """At twenty minutes old this is almost certainly a prompt nobody
    answered, waiting out the thirty minute expiry. Asking every ten
    seconds would be 190 questions with the same answer."""
    created = NOW - timedelta(minutes=20)

    assert _seconds_until(next_check_at(created, now=NOW)) >= 300


def test_the_schedule_never_abandons_a_payment_entirely(fake_client):
    """Backing off must not become never. A row that somehow escapes
    expiry still gets asked about."""
    created = NOW - timedelta(days=2)

    wait = _seconds_until(next_check_at(created, now=NOW))
    assert 900 <= wait <= 1100


# --- transient provider failures ---------------------------------------


def test_a_failing_provider_backs_off_on_top_of_the_age_tier(fake_client):
    """A timeout or a 5xx is not an answer of "still pending". Repeating
    a question the provider cannot currently answer spends the same
    budget a healthy payment needs."""
    created = NOW - timedelta(seconds=5)

    first = _seconds_until(next_check_at(created, now=NOW, attempt=0))
    second = _seconds_until(next_check_at(created, now=NOW, attempt=1))
    third = _seconds_until(next_check_at(created, now=NOW, attempt=2))

    assert first < second < third


def test_backoff_is_capped(fake_client):
    created = NOW - timedelta(seconds=5)

    assert _seconds_until(next_check_at(created, now=NOW, attempt=99)) <= 1000


def test_a_failing_young_payment_still_returns_sooner_than_a_failing_old_one(fake_client):
    """The backoff multiplies the tier rather than replacing it, so
    urgency survives failure."""
    young = _seconds_until(next_check_at(NOW - timedelta(seconds=5), now=NOW, attempt=2))
    old = _seconds_until(next_check_at(NOW - timedelta(minutes=20), now=NOW, attempt=2))

    assert young < old


# --- jitter -------------------------------------------------------------


def test_payments_created_together_do_not_stay_in_lockstep(fake_client):
    """Without jitter, a burst created in the same second arrives at the
    provider as a clump on every subsequent check, forever."""
    created = NOW - timedelta(seconds=5)
    waits = {
        _seconds_until(next_check_at(created, now=NOW.replace(microsecond=us)), NOW.replace(microsecond=us))
        for us in (0, 150_000, 300_000, 450_000, 600_000, 750_000, 900_000)
    }

    assert len(waits) > 1, "every payment would be checked at the same instant"


def test_jitter_only_ever_delays(fake_client):
    """Never earlier than the tier says. Jitter that could pull a check
    forward would let a burst beat its own interval."""
    created = NOW - timedelta(seconds=5)

    for us in (0, 250_000, 500_000, 999_999):
        now = NOW.replace(microsecond=us)
        assert _seconds_until(next_check_at(created, now=now), now) >= 10


# --- what it cannot do --------------------------------------------------


def test_the_schedule_decides_nothing_financial(fake_client):
    """It answers "when should we ask again", never "what is the
    answer". Both functions take a timestamp and return a timestamp -
    there is no payment, no amount and no status anywhere in the
    signature."""
    import inspect

    from app.services import reconciliation_schedule

    source = inspect.getsource(reconciliation_schedule)
    for forbidden in ("successful", "credit", "ledger", "resolve_collection", "post_"):
        assert forbidden not in source, f"scheduling must not reference {forbidden}"


def test_a_string_timestamp_is_accepted(fake_client):
    """The sweeps hand it whatever PostgREST returned, which is a
    string."""
    created = (NOW - timedelta(seconds=5)).isoformat()

    assert 10 <= _seconds_until(next_check_at(created, now=NOW)) <= 12


def test_a_payment_from_the_future_does_not_produce_a_negative_wait(fake_client):
    """Clock skew between the database and the worker is not an error
    worth crashing a sweep over."""
    created = NOW + timedelta(seconds=30)

    assert _seconds_until(next_check_at(created, now=NOW)) >= 10
