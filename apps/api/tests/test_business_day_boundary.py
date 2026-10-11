"""The business day is the merchant's, not UTC's.

Tanzania is UTC+3 with no DST, so a UTC calendar date rolls over at 03:00
in Dar es Salaam. Every "today" counter compared UTC dates, which meant:

  - a payment taken at 01:00 EAT was reported as *yesterday's*
  - the counters reset to zero at 3am, while hotspot merchants were still
    trading, so the Super Admin dashboard read "Collections Today:
    TZS 0.00" during a live trading morning

Measured on production for 11 Oct 2026: 21 successful collections by the
merchant's own calendar, 7 by UTC's. Fourteen real payments filed under
the wrong day.

The reports and wallet-ledger export endpoints already used
Africa/Dar_es_Salaam (dar_es_salaam_day_bounds_utc), so the dashboards
also disagreed with the reports a merchant could run against them.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.time import dar_es_salaam_date, is_dar_es_salaam_today

EAT = timezone(timedelta(hours=3))

# 08:20 EAT on 11 Oct 2026 — the morning the dashboard showed TZS 0.00.
NOW = datetime(2026, 10, 11, 5, 20, tzinfo=timezone.utc)


def at_eat(day: int, hour: int, minute: int = 0) -> str:
    """A timestamp written the way a merchant would read it, returned as
    the UTC string the database actually stores."""
    return (
        datetime(2026, 10, day, hour, minute, tzinfo=EAT)
        .astimezone(timezone.utc)
        .isoformat()
    )


@pytest.mark.parametrize(
    "label,stamp,expected",
    [
        # The window the UTC comparison lost: after the merchant's
        # midnight, before UTC's.
        ("00:05 EAT today", at_eat(11, 0, 5), True),
        ("02:12 EAT today", at_eat(11, 2, 12), True),
        ("02:59 EAT today", at_eat(11, 2, 59), True),
        # Either side of the old 03:00 reset.
        ("03:00 EAT today", at_eat(11, 3, 0), True),
        ("08:07 EAT today", at_eat(11, 8, 7), True),
        # Yesterday stays yesterday, including the late-evening hours that
        # UTC would still call today.
        ("23:59 EAT yesterday", at_eat(10, 23, 59), False),
        ("21:30 EAT yesterday", at_eat(10, 21, 30), False),
        ("08:00 EAT yesterday", at_eat(10, 8, 0), False),
        # And tomorrow is not today.
        ("00:01 EAT tomorrow", at_eat(12, 0, 1), False),
    ],
)
def test_the_day_turns_at_the_merchants_midnight(label, stamp, expected):
    assert is_dar_es_salaam_today(stamp, NOW) is expected, label


def test_the_early_hours_are_no_longer_filed_as_yesterday():
    """The specific regression: 00:00-03:00 EAT used to read as the
    previous UTC day."""
    early = at_eat(11, 1, 0)

    assert datetime.fromisoformat(early).date().isoformat() == "2026-10-10"  # UTC says yesterday
    assert dar_es_salaam_date(early).isoformat() == "2026-10-11"  # the merchant says today
    assert is_dar_es_salaam_today(early, NOW) is True


def test_a_missing_timestamp_is_never_today():
    """A withdrawal with no completed_at must not be counted."""
    assert is_dar_es_salaam_today(None, NOW) is False
    assert is_dar_es_salaam_today("", NOW) is False


def test_an_unparseable_timestamp_does_not_break_the_dashboard():
    assert is_dar_es_salaam_today("not a timestamp", NOW) is False


def test_a_naive_timestamp_is_read_as_utc():
    """Stored timestamps are UTC; one that arrives without an offset must
    not be read as though it were already local, which would shift it
    three hours and move payments across the boundary."""
    assert dar_es_salaam_date("2026-10-10T22:00:00").isoformat() == "2026-10-11"


def test_both_overviews_use_it():
    """Pinned so neither dashboard drifts back to a UTC comparison while
    reports keep using the merchant's midnight."""
    from app.services import admin_overview, merchant_overview

    assert admin_overview._is_today(at_eat(11, 1, 0), NOW) is True
    assert merchant_overview._is_today(at_eat(11, 1, 0), NOW) is True
    assert admin_overview._is_today(at_eat(10, 23, 0), NOW) is False
    assert merchant_overview._is_today(at_eat(10, 23, 0), NOW) is False
