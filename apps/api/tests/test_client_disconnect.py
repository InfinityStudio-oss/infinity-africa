"""A caller hanging up is not a server error.

Selcom posts a Checkout callback, its own timeout fires before the body
finishes arriving, and `await request.body()` raises ClientDisconnect.
Because Starlette's BaseHTTPMiddleware runs the app inside an anyio task
group, that escaped as `ExceptionGroup: unhandled errors in a TaskGroup`
and woke us up at 3am for a dropped TCP connection.

Nothing was lost that we could have acted on: there is no body to parse.
Checkout crediting never depended on the callback anyway — the
reconciliation sweep and the manual refresh endpoints both ask Selcom
directly (see app/routers/webhooks.py's docstring).

These tests pin two things: a disconnect is answered rather than raised,
and it is never reported as an exception.
"""

# Explicit, so the 3.11+ builtin is not an undefined name to a linter
# with no target-version configured. Imported, not shadowed: these are
# the real builtins.
from builtins import ExceptionGroup
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect, Request

from app.core.errors import _is_client_disconnect, register_exception_handlers


class PassThroughMiddleware(BaseHTTPMiddleware):
    """Stands in for SecurityHeadersMiddleware / ApiRequestLogMiddleware.

    The specific middleware does not matter — what matters is that it is
    a BaseHTTPMiddleware, because that is what wraps the route in the
    task group that turns the disconnect into an ExceptionGroup.
    """

    async def dispatch(self, request: Request, call_next):
        return await call_next(request)


def build_app(boom: Exception) -> FastAPI:
    app = FastAPI()
    app.add_middleware(PassThroughMiddleware)
    register_exception_handlers(app)

    @app.post("/v1/webhooks/selcom/checkout")
    async def _endpoint(request: Request):
        # Where it really happens: the first read of the request body.
        raise boom

    return app


def test_a_disconnect_is_answered_not_raised():
    client = TestClient(build_app(ClientDisconnect()))

    response = client.post("/v1/webhooks/selcom/checkout", json={})

    # 499 "client closed request" — nobody reads it, it just keeps a
    # dropped connection out of the 5xx rate.
    assert response.status_code == 499


def test_a_disconnect_is_never_reported_as_an_exception():
    client = TestClient(build_app(ClientDisconnect()))

    with patch("app.core.errors.capture_exception") as capture:
        client.post("/v1/webhooks/selcom/checkout", json={})

    capture.assert_not_called()


def test_a_real_failure_is_still_reported():
    """The guard must not become a blanket excuse: anything that is not a
    disconnect still 500s and still reaches monitoring."""
    client = TestClient(build_app(RuntimeError("the database is on fire")), raise_server_exceptions=False)

    with patch("app.core.errors.capture_exception") as capture:
        response = client.post("/v1/webhooks/selcom/checkout", json={})

    assert response.status_code == 500
    capture.assert_called_once()


@pytest.mark.parametrize(
    "exc,expected",
    [
        (ClientDisconnect(), True),
        (ExceptionGroup("task group", [ClientDisconnect()]), True),
        # Nested, because anyio can wrap a group in a group.
        (ExceptionGroup("outer", [ExceptionGroup("inner", [ClientDisconnect()])]), True),
        # A group that merely contains something else is a real failure.
        (ExceptionGroup("task group", [RuntimeError("boom")]), False),
        (RuntimeError("boom"), False),
    ],
)
def test_recognises_a_disconnect_however_it_is_wrapped(exc, expected):
    assert _is_client_disconnect(exc) is expected
