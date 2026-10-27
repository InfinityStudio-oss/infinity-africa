"""Five attempts in ten minutes, not fifty-one.

The schedule was [0, 60, 300, 900, 1800] - five attempts spread over 51
minutes. The long tail bought nothing. Measured against production on
2026-10-27 across 379 given-up deliveries: every one failed all five
times, and 96 of that day's 103 failures returned the identical status
code on every attempt. These failures are deterministic - a handler that
throws on a payload throws on it an hour later too - so the extra 41
minutes only delayed the moment anyone found out.

Ten minutes still covers what a backoff is for: a receiver restart or a
brief outage. What it stops costing is time-to-knowing.

The attempt *count* is deliberately unchanged. Fewer retries would turn a
five-second blip into a lost notification, which is the opposite of the
problem being solved.
"""

from datetime import datetime, timedelta, timezone

from app.services.webhook_delivery import _BACKOFF_SECONDS, _MAX_ATTEMPTS, _is_due


def _elapsed_at(attempt: int) -> int:
    """Seconds from the first attempt until attempt number `attempt`."""
    return sum(_BACKOFF_SECONDS[:attempt])


def test_the_whole_sequence_finishes_in_ten_minutes():
    assert _elapsed_at(_MAX_ATTEMPTS) == 600


def test_there_are_still_five_attempts():
    """Fewer would lose a notification to a momentary blip."""
    assert _MAX_ATTEMPTS == 5


def test_the_first_attempt_is_immediate():
    assert _BACKOFF_SECONDS[0] == 0


def test_the_gaps_only_ever_widen():
    """A backoff that narrows would hammer an endpoint that is already
    struggling — which is how a slow receiver becomes a dead one."""
    gaps = _BACKOFF_SECONDS[1:]
    assert gaps == sorted(gaps)
    assert len(set(gaps)) == len(gaps)


def test_a_merchant_learns_within_half_a_minute_that_something_is_wrong():
    """The point of the change. The second attempt is what turns one bad
    response into a visible `retrying` state on their Collections page."""
    assert _elapsed_at(2) <= 60


def test_the_old_schedule_would_have_taken_nearly_an_hour():
    """Pins the thing being fixed, so a revert is loud rather than quiet."""
    old = [0, 60, 300, 900, 1800]

    assert sum(old) == 3060  # 51 minutes
    assert sum(_BACKOFF_SECONDS) < sum(old) / 5


# --- the schedule is actually applied -------------------------------------


def _event(attempts: int, *, last_attempt_seconds_ago: float):
    return {
        "attempts": attempts,
        "last_attempted_at": (
            datetime.now(timezone.utc) - timedelta(seconds=last_attempt_seconds_ago)
        ).isoformat(),
    }


def test_a_never_attempted_event_is_due_at_once():
    assert _is_due({"attempts": 0, "last_attempted_at": None}, now=datetime.now(timezone.utc)) is True


def test_an_event_inside_its_backoff_is_not_retried_early():
    # One attempt made; the next is owed 30s later.
    assert _is_due(_event(1, last_attempt_seconds_ago=5), now=datetime.now(timezone.utc)) is False


def test_an_event_past_its_backoff_is_due():
    assert _is_due(_event(1, last_attempt_seconds_ago=45), now=datetime.now(timezone.utc)) is True


def test_the_last_gap_is_five_minutes_not_thirty():
    assert _is_due(_event(4, last_attempt_seconds_ago=200), now=datetime.now(timezone.utc)) is False
    assert _is_due(_event(4, last_attempt_seconds_ago=400), now=datetime.now(timezone.utc)) is True


def test_an_exhausted_event_is_never_due_again():
    """After the fifth failure nothing retries it — recovery is the resend
    endpoint, deliberately, so a permanently broken endpoint cannot be
    retried forever against live traffic."""
    assert _is_due(_event(_MAX_ATTEMPTS, last_attempt_seconds_ago=99999),
                   now=datetime.now(timezone.utc)) is False
