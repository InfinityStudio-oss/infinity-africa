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


__all__ = ["interval_for_age", "next_check_at"]
