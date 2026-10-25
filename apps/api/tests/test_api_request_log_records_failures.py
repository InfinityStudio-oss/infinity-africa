"""The requests most worth a record were the only ones never recorded.

`api_request_logs` is what the API Logs views show a merchant and what
anyone would check to ask "is this partner getting errors from us". Until
2026-10-25 it contained **no 5xx rows at all** - not few, zero, ever -
because the middleware wrote its row after `await call_next(request)`, so
an unhandled exception skipped the write on its way up.

That hid a real failure. INFINITYPAY-API-14 returned 500 from
`POST /v1/collections/wallet-push` *after* the customer had been charged,
and the logs showed a clean day. "No errors in the logs" meant nothing,
and nothing said so.

What must hold now: a request that blows up still leaves a row, the
exception still reaches the client unchanged, and a logging failure never
replaces the real error with one of its own.
"""

import uuid
from dataclasses import dataclass

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import app.middleware.api_request_log as module
from app.middleware.api_request_log import ApiRequestLogMiddleware


@dataclass
class _Context:
    id: uuid.UUID
    merchant_id: uuid.UUID
    environment: str = "live"


def _build(fake_client, monkeypatch, *, context=None, blow_up=False):
    monkeypatch.setattr(module, "get_supabase_admin", lambda: fake_client)

    app = FastAPI()
    app.add_middleware(ApiRequestLogMiddleware)

    @app.get("/thing")
    def thing(request: Request):
        if context is not None:
            request.state.api_key_context = context
        request.state.client_ip = "41.0.0.9"
        if blow_up:
            raise RuntimeError("kaboom")
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def _rows(fake_client):
    return fake_client.table("api_request_logs")._table.rows


@pytest.fixture
def context():
    return _Context(id=uuid.uuid4(), merchant_id=uuid.uuid4())


# --- the gap that existed ----------------------------------------------


def test_a_request_that_raises_is_still_recorded(fake_client, monkeypatch, context):
    """The whole point. Before this there were no 5xx rows at all."""
    client = _build(fake_client, monkeypatch, context=context, blow_up=True)

    client.get("/thing")

    assert len(_rows(fake_client)) == 1


def test_it_is_recorded_as_a_500(fake_client, monkeypatch, context):
    """There is no response to read a status off — anything still raising
    here is an unhandled server error."""
    client = _build(fake_client, monkeypatch, context=context, blow_up=True)

    client.get("/thing")

    assert _rows(fake_client)[0]["status_code"] == 500


def test_the_failed_request_is_attributed_to_the_right_merchant(fake_client, monkeypatch, context):
    """A row nobody can attribute is nearly as useless as no row."""
    client = _build(fake_client, monkeypatch, context=context, blow_up=True)

    client.get("/thing")

    row = _rows(fake_client)[0]
    assert row["merchant_id"] == str(context.merchant_id)
    assert row["api_key_id"] == str(context.id)
    assert row["path"] == "/thing"


# --- what must not change ----------------------------------------------


def test_the_error_still_reaches_the_client(fake_client, monkeypatch, context):
    """Logging it must not swallow it. A quietly-200'd crash would be far
    worse than the missing row this fixes."""
    client = _build(fake_client, monkeypatch, context=context, blow_up=True)

    assert client.get("/thing").status_code == 500


def test_a_successful_request_is_recorded_exactly_as_before(fake_client, monkeypatch, context):
    client = _build(fake_client, monkeypatch, context=context)

    assert client.get("/thing").status_code == 200
    row = _rows(fake_client)[0]
    assert row["status_code"] == 200
    assert row["ip_address"] == "41.0.0.9"


def test_a_request_with_no_api_key_is_still_not_logged(fake_client, monkeypatch):
    """Unchanged rule: an unauthenticated request has no merchant to
    attribute a row to. This must not start logging the world."""
    client = _build(fake_client, monkeypatch, context=None, blow_up=True)

    client.get("/thing")

    assert _rows(fake_client) == []


def test_a_logging_failure_never_replaces_the_real_error(fake_client, monkeypatch, context):
    """The guarantee that matters most. If the insert throws while an
    exception is already travelling up, the caller must still see the
    original failure - not a database error from the logger."""
    client = _build(fake_client, monkeypatch, context=context, blow_up=True)

    class _Exploding:
        def table(self, _name):
            raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(module, "get_supabase_admin", lambda: _Exploding())

    response = client.get("/thing")

    assert response.status_code == 500


def test_a_logging_failure_does_not_break_a_working_request(fake_client, monkeypatch, context):
    client = _build(fake_client, monkeypatch, context=context)

    class _Exploding:
        def table(self, _name):
            raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(module, "get_supabase_admin", lambda: _Exploding())

    assert client.get("/thing").status_code == 200
