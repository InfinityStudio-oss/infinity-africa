"""Logs one row per API-key-authenticated HTTP request to
api_request_logs — the "API Logs" merchant/Super Admin views ask for.
Only requests that actually resolved a valid API key are logged here
(request.state.api_key_context, set by
app.auth.dependencies.verify_api_key on success): an invalid/unknown key
has no merchant to attribute a log row to, and isn't logged by this
middleware — see that dependency's own docstring for the one exception
(an IP-allowlist rejection, which *does* know the merchant by the time
it's rejected, and logs itself explicitly instead of relying on this
middleware).

Best-effort throughout: a logging failure must never break the real
request/response it's describing.
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.database.session import get_supabase_admin


class ApiRequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            # The requests most worth having a record of were the only
            # ones this never recorded. Until 2026-10-25 the call above
            # sat outside any try, so an unhandled exception skipped the
            # write entirely and `api_request_logs` held **no 5xx rows at
            # all** - zero, ever. A partner's request could 500 and the
            # only trace was Sentry.
            #
            # That hid a real failure: INFINITYPAY-API-14 returned 500
            # from wallet-push *after* the customer had paid, and the
            # logs showed a clean day. "No errors in the logs" meant
            # nothing, and nobody knew it meant nothing.
            #
            # 500 rather than response.status_code because there is no
            # response: an HTTPException is already turned into one by
            # the exception middleware below this, so anything still
            # raising here is an unhandled server error.
            self._record(request, status_code=500, start=start)
            raise

        self._record(request, status_code=response.status_code, start=start)
        return response

    def _record(self, request: Request, *, status_code: int, start: float) -> None:
        """Best-effort, and never raises - a logging failure must not
        break the request it describes, nor replace the exception that is
        on its way up with one of its own."""
        context = getattr(request.state, "api_key_context", None)
        if context is None:
            return
        duration_ms = int((time.monotonic() - start) * 1000)
        ip = getattr(request.state, "client_ip", None)
        try:
            get_supabase_admin().table("api_request_logs").insert(
                {
                    "merchant_id": str(context.merchant_id),
                    "api_key_id": str(context.id),
                    "environment": context.environment,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "ip_address": ip,
                    "duration_ms": duration_ms,
                }
            ).execute()
        except Exception:  # noqa: BLE001, S110
            pass
