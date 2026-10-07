"""A dead connection must not look like a failed request.

A pooled HTTPS connection to Supabase can be closed by them, or by
something between us and them, while it sits idle in httpx's pool. The
next request writes to a socket nobody is holding open any more and
fails. In production this arrived as
`ReadError: [Errno 11] Resource temporarily unavailable` on ordinary
reads — /v1/merchant/overview, /v1/merchant/wallet/ledger,
/v1/admin/merchants — a few times a day once real traffic started. The
merchant saw a page that loaded fine on refresh.

So a read whose connection died is retried once. A write is not, and
that asymmetry is the point: a POST may have been applied before the
connection broke, and replaying one could credit a wallet twice.
"""

import httpx
import pytest

from app.database.session import _RetryStaleConnectionTransport


def _transport(failures: int, error: Exception) -> _RetryStaleConnectionTransport:
    """A transport whose underlying send fails `failures` times first."""
    transport = _RetryStaleConnectionTransport()
    attempts: list[httpx.Request] = []
    state = {"remaining": failures}

    def fake_super(request):
        attempts.append(request)
        if state["remaining"] > 0:
            state["remaining"] -= 1
            raise error
        return httpx.Response(200, json={"ok": True}, request=request)

    # Replace what the retry wrapper delegates to, leaving the retry
    # decision itself — the thing under test — untouched.
    original = httpx.HTTPTransport.handle_request
    httpx.HTTPTransport.handle_request = lambda self, request: fake_super(request)  # type: ignore[assignment]
    transport._restore = lambda: setattr(httpx.HTTPTransport, "handle_request", original)  # type: ignore[attr-defined]
    transport.attempts = attempts  # type: ignore[attr-defined]
    return transport


@pytest.fixture
def make_transport():
    created = []

    def _factory(failures: int, error: Exception):
        t = _transport(failures, error)
        created.append(t)
        return t

    yield _factory
    for t in created:
        t._restore()  # type: ignore[attr-defined]


_CONNECTION_ERRORS = [
    pytest.param(httpx.ReadError("[Errno 11] Resource temporarily unavailable"), id="ReadError-errno11"),
    pytest.param(httpx.ConnectError("connection refused"), id="ConnectError"),
    pytest.param(httpx.RemoteProtocolError("server disconnected"), id="RemoteProtocolError"),
]


@pytest.mark.parametrize("error", _CONNECTION_ERRORS)
def test_a_read_whose_connection_died_is_retried(make_transport, error):
    """The production symptom. One dead socket must not become a failed
    page for a merchant."""
    transport = make_transport(1, error)
    request = httpx.Request("GET", "https://project.supabase.co/rest/v1/collections")

    response = transport.handle_request(request)

    assert response.status_code == 200
    assert len(transport.attempts) == 2, "the read was not retried"


@pytest.mark.parametrize("method", ["POST", "PATCH", "PUT", "DELETE"])
def test_a_write_is_never_replayed(make_transport, method):
    """The safety argument for the whole change. A write may already have
    been applied when the connection broke — replaying one could credit a
    wallet twice or create a second payment."""
    transport = make_transport(1, httpx.ReadError("[Errno 11] Resource temporarily unavailable"))
    request = httpx.Request(method, "https://project.supabase.co/rest/v1/collections")

    with pytest.raises(httpx.ReadError):
        transport.handle_request(request)

    assert len(transport.attempts) == 1, f"{method} must not be replayed"


def test_a_second_failure_is_not_hidden(make_transport):
    """One retry, not a loop. A connection that fails twice is a real
    outage and should be reported as one rather than buried under more
    waiting."""
    transport = make_transport(2, httpx.ReadError("still down"))
    request = httpx.Request("GET", "https://project.supabase.co/rest/v1/collections")

    with pytest.raises(httpx.ReadError):
        transport.handle_request(request)

    assert len(transport.attempts) == 2


def test_a_healthy_read_is_sent_once(make_transport):
    """No retry when nothing went wrong — this must not double every
    query the platform makes."""
    transport = make_transport(0, httpx.ReadError("unused"))
    request = httpx.Request("GET", "https://project.supabase.co/rest/v1/collections")

    assert transport.handle_request(request).status_code == 200
    assert len(transport.attempts) == 1


def test_a_database_error_is_not_retried(make_transport):
    """PostgREST answering 4xx/5xx is a real answer, not a broken
    connection. Retrying it would double the load on a database already
    in trouble, and change nothing."""
    transport = make_transport(0, httpx.ReadError("unused"))
    attempts: list[httpx.Request] = []

    def failing_response(self, request):
        attempts.append(request)
        return httpx.Response(500, json={"message": "db error"}, request=request)

    original = httpx.HTTPTransport.handle_request
    httpx.HTTPTransport.handle_request = failing_response  # type: ignore[assignment]
    try:
        request = httpx.Request("GET", "https://project.supabase.co/rest/v1/collections")
        assert transport.handle_request(request).status_code == 500
        assert len(attempts) == 1, "a 500 response must not be retried"
    finally:
        httpx.HTTPTransport.handle_request = original  # type: ignore[assignment]
