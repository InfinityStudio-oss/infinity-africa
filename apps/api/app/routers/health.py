import logging
import time
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.core.rate_limit import rate_limit
from app.database.session import get_supabase_admin
from app.schemas.health import DbLatencyResponse, HealthResponse

logger = logging.getLogger("infinity.health")

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(status="ok", environment=settings.environment)


@router.get("/health/db-latency", response_model=DbLatencyResponse)
def db_latency(
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="health_db_latency", limit=30, window_seconds=60))
    ],
) -> DbLatencyResponse:
    """How long one trivial round trip to the database takes, from here.

    The number this exists to make visible: the API runs in Amsterdam and
    Supabase in Frankfurt, so every query pays 5-8ms of travel before
    Postgres does any work. An endpoint that makes ten queries spends
    most of a tenth of a second on geography alone, and until now there
    was no way to see that without guessing. Measuring it from a browser
    is useless — a merchant in Dar es Salaam is ~90ms from anything in
    Europe, which swamps the signal entirely. This measures the hop that
    actually matters, from the side that makes it.

    The query is the cheapest one that proves the database answered: a
    single indexed id, one row, no joins, no counts. It is a read and it
    touches nothing.

    **Unauthenticated on purpose, and rate limited because of it.** An
    uptime monitor has to be able to call this without holding a
    credential, and the response says nothing an attacker does not
    already know from the fact that the site works. The rate limit is
    what stops it being used to push load onto the database.

    Never fails the request. "The database is down" is precisely what
    this is for, so an outage answers `ok: false` rather than raising —
    a 500 here would tell a monitor that the *monitor* is broken.

    One caveat worth knowing rather than engineering around: a refused
    connection returns quickly, but a Supabase that accepts the socket
    and then hangs will hold this request for
    `SUPABASE_CLIENT_TIMEOUT_SECONDS` (120), because the timeout belongs
    to the shared client and is not worth a second client just for a
    probe. Any uptime monitor's own timeout fires long before that, so
    the outage is still reported — just by the monitor rather than by
    this response. The rate limit is what stops a hanging database
    turning repeated probes into held threads.
    """
    started = time.perf_counter()
    try:
        get_supabase_admin().table("merchants").select("id").limit(1).execute()
    except Exception:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        # The exception text can carry the Supabase host and the failing
        # query, so it goes to the server log and never into the body.
        logger.exception("db_latency_probe_failed duration_ms=%d", elapsed_ms)
        return DbLatencyResponse(
            ok=False,
            database="unreachable",
            latency_ms=elapsed_ms,
            timestamp=datetime.now(timezone.utc),
        )

    return DbLatencyResponse(
        ok=True,
        database="ok",
        latency_ms=int((time.perf_counter() - started) * 1000),
        timestamp=datetime.now(timezone.utc),
    )
