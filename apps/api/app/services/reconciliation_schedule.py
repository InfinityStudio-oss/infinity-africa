"""How often to ask Selcom about one pending payment.

Deliberately separate from how often the sweep runs. Those were the same
dial until 2026-10-17: each sweep asked about every pending row, so
halving the interval doubled the questions asked about every payment,
including the ones that were never going to resolve.

Measured on 4,024 real collections from 10-17 October:

    flat 120s         15,482 provider calls    3.8 per collection
    flat  30s         57,529                  14.3   (the interval then)
    flat  10s        175,706                  43.7
    tiered 10->300s   50,214                  12.5

58% of collections resolve within two minutes. The p90 is 1,909 seconds,
which is an abandoned push waiting out collection_push_expiry_minutes.
A flat 10 second sweep spends most of its budget asking about those,
roughly 190 times each, and learns nothing until they expire.

So the schedule is front-loaded: frequent while an answer is plausible,
backing off as it stops being. That is what lets the sweep run every ten
seconds *and* cost less than it did at thirty.

**This file decides nothing financial.** It answers "when should we ask
again", never "what is the answer". A payment is resolved only by
Selcom's own response, through the same completion path a callback uses.
"""

from datetime import datetime, timedelta, timezone

# (age of the payment in seconds, how long to wait before asking again).
# The first row whose age limit the payment has not yet reached wins.
#
# The first tier matches the sweep interval, so a young payment really is
# checked about every ten seconds - that is the part of this change a
# merchant notices. The last tier runs out past
# collection_push_expiry_minutes (30), by which point the expiry sweep
# has taken the row and there is nothing left to ask about.
_TIERS: tuple[tuple[int, int], ...] = (
    (120, 10),
    (300, 30),
    (900, 120),
    (2400, 300),
)

# Past the last tier. Long enough that a row which somehow escapes expiry
# is not polled in a loop forever, short enough that it is not abandoned.
_FALLBACK_SECONDS = 900

# Added to every interval as a fraction, so a burst of payments created in
# the same second does not stay in lockstep and arrive at the provider
# together on every subsequent check.
_JITTER_FRACTION = 0.15


def _age_seconds(created_at: str | datetime, now: datetime) -> float:
    started = (
        created_at
        if isinstance(created_at, datetime)
        else datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    )
    return max(0.0, (now - started).total_seconds())


def interval_for_age(age_seconds: float) -> int:
    """Seconds to wait before asking about a payment of this age."""
    for limit, interval in _TIERS:
        if age_seconds < limit:
            return interval
    return _FALLBACK_SECONDS


def next_check_at(
    created_at: str | datetime,
    *,
    now: datetime | None = None,
    attempt: int = 0,
) -> str:
    """When this payment should next be asked about, as an ISO string.

    `attempt` is the number of consecutive transient failures - a timeout
    or a 5xx from the provider, not an answer of "still pending". Those
    back off on top of the age tier, because repeating a question the
    provider is currently unable to answer helps nobody and spends the
    same budget a healthy payment needs.

    Jitter is applied in both cases. Without it, payments created in the
    same second stay in lockstep forever and arrive at the provider in a
    clump on every single check.
    """
    now = now or datetime.now(timezone.utc)
    base = interval_for_age(_age_seconds(created_at, now))
    if attempt > 0:
        # 2, 4, 8 ... capped. Multiplies the tier rather than replacing
        # it, so a failing young payment still returns sooner than a
        # failing old one.
        base = min(base * (2 ** min(attempt, 4)), _FALLBACK_SECONDS)
    # Deterministic jitter from the clock's microseconds: no RNG to seed
    # in tests, and spread enough to break lockstep.
    #
    # The whole microsecond field, not `% 1000`. That earlier version
    # gave zero jitter for any microsecond value divisible by 1000 -
    # which is most of them when a timestamp comes back from a database
    # rounded to the millisecond, so the clump it exists to prevent
    # survived exactly where it was most likely. Caught by
    # test_payments_created_together_do_not_stay_in_lockstep.
    jitter = base * _JITTER_FRACTION * (now.microsecond / 1_000_000)
    return (now + timedelta(seconds=base + jitter)).isoformat()


# When to re-ask about a collection we have ALREADY expired, measured
# from `failed_at`. A separate ladder from the tiers above, because it
# answers a different question against a much tighter budget.
#
# The tiers above schedule a payment that is still live, over at most
# collection_push_expiry_minutes. These schedule one we have already
# given up on, over collection_push_expiry_grace_hours - 24 hours rather
# than 5 minutes, across every row expired in that window.
#
# Why a fixed ladder and not an interval: selcom_outbound_max_per_minute
# is 60 for the whole platform, and callers WAIT for a slot, so every
# recheck is taken directly out of what live payments need. At roughly
# 2,500 expiries a day a recurring interval is unaffordable - a 15 minute
# one would cost ~160 calls a minute on its own. A ladder asks each
# expired collection four times and then stops, which is ~4 calls per
# collection, around 7 a minute at that volume.
#
# Front-loaded because that is where the answers are. A late approval is
# someone who found their phone and typed their PIN a moment after we
# gave up, not someone who did it six hours later.
_RECHECK_AFTER_SECONDS: tuple[int, ...] = (300, 1200, 3600, 10800)


def next_expiry_recheck_at(
    failed_at: str | datetime,
    *,
    now: datetime | None = None,
    grace_hours: int,
) -> str:
    """When to ask about this expired collection again, as an ISO string.

    Returns a timestamp beyond the grace window once the ladder is
    exhausted, which is how a row stops being a candidate: the caller
    filters on `next_check_at <= now` AND `failed_at` inside the window,
    so a row scheduled past its own window is never selected again and
    simply ages out.

    That "stop" value is what makes the queue drain. Without it an
    unpaid candidate kept its place at the head forever - the sweep
    re-asked the same oldest rows every pass and never reached anything
    newer.
    """
    now = now or datetime.now(timezone.utc)
    failed = (
        failed_at
        if isinstance(failed_at, datetime)
        else datetime.fromisoformat(str(failed_at).replace("Z", "+00:00"))
    )
    age = max(0.0, (now - failed).total_seconds())

    for offset in _RECHECK_AFTER_SECONDS:
        if age < offset:
            # Same jitter rationale as next_check_at: a burst of pushes
            # that expired together must not come back together.
            jitter = (offset - age) * _JITTER_FRACTION * (now.microsecond / 1_000_000)
            return (now + timedelta(seconds=(offset - age) + jitter)).isoformat()

    # Ladder exhausted - park it past its own grace window.
    return (failed + timedelta(hours=max(1, grace_hours), minutes=1)).isoformat()


__all__ = ["interval_for_age", "next_check_at", "next_expiry_recheck_at"]
