import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_DAR_ES_SALAAM = ZoneInfo("Africa/Dar_es_Salaam")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dar_es_salaam_day_bounds_utc(
    start_date: date | None, end_date: date | None
) -> tuple[datetime | None, datetime | None]:
    """Converts a merchant-facing (start_date, end_date) calendar-day range,
    interpreted in Africa/Dar_es_Salaam (Tanzania has no DST, so this is
    always a fixed UTC+3 — zoneinfo handles it correctly regardless), into
    UTC datetime bounds for comparing against created_at timestamps stored
    in UTC. start is inclusive at 00:00 EAT; end is exclusive at 00:00 EAT
    of the day *after* end_date, so the whole end_date calendar day is
    included. Either side is None if the caller didn't filter on it."""
    start_utc = (
        datetime(start_date.year, start_date.month, start_date.day, tzinfo=_DAR_ES_SALAAM).astimezone(timezone.utc)
        if start_date
        else None
    )
    end_utc = (
        (datetime(end_date.year, end_date.month, end_date.day, tzinfo=_DAR_ES_SALAAM) + timedelta(days=1)).astimezone(
            timezone.utc
        )
        if end_date
        else None
    )
    return start_utc, end_utc


def dar_es_salaam_date(value: str | datetime) -> date:
    """The Tanzanian calendar date a UTC timestamp falls on.

    Timestamps are stored in UTC, but a merchant's day is the one they
    live in. Tanzania is UTC+3 with no DST, so a UTC calendar date rolls
    over at 03:00 local — which put every payment taken between midnight
    and 3am into the previous business day, and reset the "today" counters
    at 3am while hotspot merchants were still trading.
    """
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_DAR_ES_SALAAM).date()


def dar_es_salaam_day_start_utc(now: datetime) -> str:
    """Midnight of the current Tanzanian day, as a UTC ISO string.

    For narrowing a query to "today" in the database rather than fetching
    every row and filtering in Python. PostgREST caps an unbounded select
    at 1000 rows, so a table that grows past that silently stops
    containing today at all — which is exactly how Collections Today
    reached TZS 0.00 on a morning that had taken 41 payments.
    """
    local_midnight = now.astimezone(_DAR_ES_SALAAM).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return local_midnight.astimezone(timezone.utc).isoformat()


def dar_es_salaam_month_start_utc(now: datetime) -> str:
    """Midnight on the 1st of the current Tanzanian month, as UTC ISO.

    Month-to-date has to start where the merchant's month starts, for the
    same reason the day does: a UTC month boundary begins at 03:00 local
    on the 1st, so revenue earned in those three hours would be counted
    in the previous month.
    """
    local_first = now.astimezone(_DAR_ES_SALAAM).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    return local_first.astimezone(timezone.utc).isoformat()


def is_dar_es_salaam_today(value: str | datetime | None, now: datetime) -> bool:
    """Whether a stored UTC timestamp falls on the current Tanzanian day.

    `now` is passed in rather than read here so one request's counters all
    agree, even if it straddles midnight. A null timestamp (a withdrawal
    with no completed_at, say) is never "today".
    """
    if not value:
        return False
    try:
        return dar_es_salaam_date(value) == dar_es_salaam_date(now)
    except ValueError:
        return False


def to_dar_es_salaam(iso_value: str) -> datetime:
    """Parses a UTC ISO timestamp (as stored in created_at columns) and
    converts it to Africa/Dar_es_Salaam local time — for display only
    (e.g. the Wallet Ledger Excel export), never for filtering, which
    already happens in UTC via dar_es_salaam_day_bounds_utc."""
    return datetime.fromisoformat(iso_value.replace("Z", "+00:00")).astimezone(_DAR_ES_SALAAM)


_PLAIN_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class InvalidFilterDateError(ValueError):
    """A date/timestamp filter value that cannot be understood."""


def resolve_day_filter_bound(value: str, *, end_of_day: bool) -> str:
    """Normalises a date-or-timestamp filter value to one comparable
    timestamp, anchored in Africa/Dar_es_Salaam when it is a bare date.

    The Super Admin list endpoints are reached two ways, and both have
    to keep working:

      - a person picking a day in a date box, which sends "2026-11-22"
      - the dashboard's own counters, which already send a full
        "2026-11-22T00:00:00.000+03:00" they converted themselves

    A bare date used to be passed straight into the query, where
    Postgres read it as midnight UTC. Tanzania is UTC+3, so every
    payment taken between 00:00 and 03:00 local fell outside the day it
    belonged to - 127 real payments on one day, measured against
    production. A timestamp that already carries an offset is returned
    untouched, because the caller has already said which instant it
    means.

    `end_of_day` makes a bare date the LAST instant of that Tanzanian
    day rather than the first, so a range stays inclusive at both ends -
    "22 Nov to 22 Nov" is a whole day, not an empty instant. The bound
    is microsecond-precise (…23:59:59.999999), which leaves no gap at
    the precision Postgres stores, so callers can keep using an
    inclusive comparison throughout rather than switching operators
    depending on what shape the value arrived in.

    Raises InvalidFilterDateError for anything unparseable, so a typo
    becomes a clear 4xx rather than a database error or, worse, a
    filter that silently matches everything.
    """
    text = (value or "").strip()
    if not text:
        raise InvalidFilterDateError("must be a date (YYYY-MM-DD) or an ISO timestamp")

    if _PLAIN_DATE.match(text):
        try:
            day = date.fromisoformat(text)
        except ValueError as exc:
            raise InvalidFilterDateError(
                f"{text!r} is not a real date"
            ) from exc
        if end_of_day:
            moment = datetime(
                day.year, day.month, day.day, 23, 59, 59, 999999, tzinfo=_DAR_ES_SALAAM
            )
        else:
            moment = datetime(day.year, day.month, day.day, tzinfo=_DAR_ES_SALAAM)
        return moment.isoformat()

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidFilterDateError(
            "must be a date (YYYY-MM-DD) or an ISO timestamp"
        ) from exc
    # A timestamp with no offset is ambiguous, and guessing UTC is how
    # the three-hour hole appeared in the first place. Read it as local
    # time, which is what somebody writing a bare timestamp by hand in
    # Dar es Salaam means.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_DAR_ES_SALAAM)
    return parsed.isoformat()
