"""Database session / Supabase client setup.

No ORM/models yet — no persistence has been built beyond the auth layer.
`get_supabase_admin()` below is the one piece implemented so far: a
service_role Supabase client used by app/auth to look up role membership
and API keys directly against the tables in supabase/migrations.
"""

import logging
from functools import lru_cache

import httpx
from supabase import Client, create_client
from supabase.lib.client_options import ClientOptions

from app.config import get_settings

logger = logging.getLogger("infinity.database")

# Errors that mean the connection died, not that the database said no.
#
# A pooled HTTPS connection to Supabase can be closed by them, or by
# something between us and them, while it sits idle in httpx's pool. The
# next request picks it up, writes to a socket nobody is holding open any
# more, and fails — in production this surfaced as
# `ReadError: [Errno 11] Resource temporarily unavailable` on ordinary
# reads like /v1/merchant/overview and /v1/merchant/wallet/ledger, a few
# times a day once real traffic arrived. The merchant saw a page that
# would load fine on refresh.
_CONNECTION_FAILURES = (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError, httpx.WriteError)

# Only these are replayed. The distinction is the whole safety argument:
# a GET can be repeated as many times as we like, while a POST or PATCH
# may well have been applied before the connection broke — replaying one
# could double-credit a wallet or create a second payment. A failed write
# stays failed and surfaces to the caller, exactly as it does today.
_REPLAYABLE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class _RetryStaleConnectionTransport(httpx.HTTPTransport):
    """Retries a read once when the connection itself failed.

    Deliberately at the transport rather than at the 124 `.execute()`
    call sites: this covers every query in the codebase, including ones
    not yet written, and it is the only layer that can tell a dead socket
    apart from a database error. PostgREST returning 4xx/5xx is a real
    answer and is never retried here — it never reaches this branch.
    """

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            return super().handle_request(request)
        except _CONNECTION_FAILURES as exc:
            if request.method not in _REPLAYABLE_METHODS:
                raise
            logger.info(
                "supabase_connection_retry method=%s error=%s",
                request.method,
                type(exc).__name__,
            )
            # The broken connection has already been discarded by the
            # pool, so this gets a fresh one. One retry only: a second
            # failure is a real outage, and should be reported as such
            # rather than hidden behind more waiting.
            return super().handle_request(request)


@lru_cache
def get_supabase_admin() -> Client:
    """Server-only Supabase client authenticated as service_role.

    This bypasses Row Level Security entirely, which is exactly why it may
    only ever be constructed here, in the backend. SUPABASE_SERVICE_ROLE_KEY
    must never be set in apps/web's environment or sent to a browser.
    """
    settings = get_settings()

    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not configured")

    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
        options=ClientOptions(
            httpx_client=httpx.Client(
                transport=_RetryStaleConnectionTransport(),
                # Supabase's own default for this client. Stated here
                # because passing httpx_client replaces their construction
                # of it, so an unstated timeout would silently become
                # httpx's 5s and start failing slow queries.
                timeout=httpx.Timeout(settings.supabase_client_timeout_seconds),
            )
        ),
    )
