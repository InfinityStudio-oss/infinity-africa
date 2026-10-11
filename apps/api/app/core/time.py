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
