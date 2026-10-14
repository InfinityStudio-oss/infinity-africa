"""GET /health/db-latency, and the slow-query warning behind it.

Both exist to make one number visible: the API runs in Amsterdam and
Supabase in Frankfurt, so every query pays 5-8ms of travel before
Postgres does anything. Measuring that from a browser is useless, since
a merchant in Dar es Salaam is ~90ms from anything in Europe and the
signal disappears. These measure it from the side that makes the trip.

What the tests hold is mostly about what must NOT come back or be
logged. A probe endpoint is the kind of thing that quietly grows a
"helpful" field naming the host or the failing query, and an
unauthenticated endpoint is exactly where that cannot be allowed.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database.session import _log_if_slow
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SLOW_QUERY_WARNING_MS", "400")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- the endpoint ----------------------------------------------------------


def test_it_reports_the_database_answered_and_how_long_it_took(fake_client):
    response = client.get("/health/db-latency")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["database"] == "ok"
    assert isinstance(body["latency_ms"], int)
    assert body["latency_ms"] >= 0
    assert body["timestamp"]


def test_the_body_describes_the_database_only_as_up_or_down(fake_client):
    """No host, no region, no connection string, no driver, no table or
    row counts. This is reachable without a credential, so every field
    here is a field anyone can read."""
    body = client.get("/health/db-latency").json()

    assert set(body) == {"ok", "database", "latency_ms", "timestamp"}
    blob = str(body).lower()
    for leak in ("supabase", "postgres", "password", "key", "http", "@", "amsterdam", "frankfurt"):
        assert leak not in blob, f"{leak!r} must not appear in an unauthenticated response"


def test_a_database_outage_answers_rather_than_raising(fake_client, monkeypatch):
    """"The database is down" is the thing this endpoint exists to
    report. A 500 here would tell an uptime monitor that the monitor is
    broken, which is the opposite of useful."""
    import app.routers.health as health_module

    class _Dead:
        def table(self, _name):
            raise RuntimeError("connection refused to db.abcdefgh.supabase.co:5432")

    monkeypatch.setattr(health_module, "get_supabase_admin", lambda: _Dead())

    response = client.get("/health/db-latency")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["database"] == "unreachable"
    # The exception text carried a hostname. It must not have come with it.
    assert "supabase.co" not in str(body)


def test_it_stays_unauthenticated_so_a_monitor_can_call_it(fake_client):
    """Deliberate, and paired with a rate limit. It is also pinned in
    tests/test_tenant_isolation_route_guards.py's PUBLIC_ROUTES, which is
    what forces a reason to be written down for any route with no tenant
    guard."""
    assert client.get("/health/db-latency").status_code == 200


# --- the slow-query warning -------------------------------------------------


def _request(url: str):
    import httpx

    return httpx.Request("GET", url)


@pytest.fixture
def db_logs(caplog):
    """caplog cannot see these warnings on its own.

    Every logger in this app is named "infinity.X" and the shared
    "infinity" parent sets propagate=False (app/main.py::
    _configure_logging) so messages never reach the root logger, which is
    where caplog attaches its handler. A test that just uses caplog here
    reads an empty string - and the two assertions below that check
    nothing was logged would pass without the code being run at all.
    Attaching caplog's handler to the logger directly is what makes them
    mean something."""
    logger = logging.getLogger("infinity.database")
    caplog.set_level(logging.WARNING, logger="infinity.database")
    logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


def test_a_slow_query_is_logged_with_its_table(db_logs):
    with db_logs.at_level(logging.WARNING, logger="infinity.database"):
        _log_if_slow(_request("https://x.supabase.co/rest/v1/transactions?select=*"), 900)

    assert "slow_supabase_query" in db_logs.text
    assert "transactions" in db_logs.text


def test_a_normal_query_is_not_logged(db_logs):
    """A threshold that fires on ordinary traffic is one people learn to
    filter out, which costs the warning its only purpose."""
    with db_logs.at_level(logging.WARNING, logger="infinity.database"):
        _log_if_slow(_request("https://x.supabase.co/rest/v1/transactions?select=*"), 12)

    assert db_logs.text == ""


def test_the_filters_are_never_logged(db_logs):
    """A PostgREST URL carries its filters, and on this platform those
    filters are a customer's phone number, a merchant id and a payment
    reference. The table name identifies the slow query; the values would
    make a log file a privacy leak."""
    url = (
        "https://x.supabase.co/rest/v1/collections"
        "?customer_phone=eq.255712345678&merchant_id=eq.c9e9bc9a-e0d9-4712-ba0e-d575fb7d2fbd"
    )
    with db_logs.at_level(logging.WARNING, logger="infinity.database"):
        _log_if_slow(_request(url), 5000)

    assert "collections" in db_logs.text
    assert "255712345678" not in db_logs.text
    assert "c9e9bc9a" not in db_logs.text
    assert "?" not in db_logs.text


def test_the_warning_can_be_switched_off(db_logs, monkeypatch):
    monkeypatch.setenv("SLOW_QUERY_WARNING_MS", "0")
    get_settings.cache_clear()

    with db_logs.at_level(logging.WARNING, logger="infinity.database"):
        _log_if_slow(_request("https://x.supabase.co/rest/v1/transactions"), 99_000)

    assert db_logs.text == ""
