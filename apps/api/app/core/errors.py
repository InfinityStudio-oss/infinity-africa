"""Application error types + the exception handlers that turn them (and
anything else unhandled) into the standard {"success": false, "error": {...}}
envelope, registered onto the FastAPI app in app.main.
"""

import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.common import ErrorDetail, ErrorResponse

logger = logging.getLogger("infinity.api")


class APIError(Exception):
    """Base class for application errors. Raise a subclass (or this
    directly) anywhere in a router/service to get a well-formed error
    response instead of a bare 500."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(self, message: str, *, details: list | dict | None = None):
        self.message = message
        self.details = details
        super().__init__(message)


class NotFoundError(APIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(APIError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class ValidationAPIError(APIError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "validation_error"


class NidaRequiredError(APIError):
    """Merchant signup / onboarding submitted without a NIDA number. 400
    with a dedicated `nida_required` code so the frontend can attach the
    error to the NIDA field specifically ("NIDA number is required.")."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "nida_required"


class NidaInvalidError(APIError):
    """NIDA number present but not a valid Tanzanian NIDA shape (20
    digits). 422 with a dedicated `nida_invalid` code."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "nida_invalid"


class IdempotencyKeyReusedError(ConflictError):
    code = "idempotency_key_reused"


class InsufficientBalanceError(ConflictError):
    code = "insufficient_balance"


class WithdrawalRestrictedError(ConflictError):
    code = "withdrawal_restricted"


class MfaRequiredError(APIError):
    """A verified Super Admin whose session has not presented a second
    factor, while REQUIRE_SUPER_ADMIN_MFA is on.

    403 rather than 401: the caller IS authenticated and IS a platform
    admin, so re-logging-in is not the remedy — they need to complete a
    TOTP challenge on the session they already have. The distinct
    `mfa_required` code is what lets the portal route them to the
    challenge page instead of showing a generic "not authorized"."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "mfa_required"


class FeatureDisabledError(APIError):
    """A Super Admin has flipped one of the ENABLE_COLLECTIONS/
    ENABLE_WITHDRAWALS/ENABLE_MERCHANT_API_KEYS kill switches off in
    Railway (see app/core/feature_flags.py and Settings — 'Production
    safety switches') — new requests are paused; existing records stay
    fully viewable. 503, not 403/409: this isn't about the caller's
    permissions or a data conflict, the whole feature is temporarily
    paused platform-wide."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "feature_disabled"


class ProductionAccessRestrictedError(APIError):
    """A merchant tried to create/rotate a `live` API key before Super
    Admin enabled production API access for them (on top of already being
    KYC-approved) — see app/services/api_access.py. 403, not 409: this
    isn't a conflict with existing data, it's a permission the merchant
    doesn't have yet."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "production_access_restricted"


class MerchantNotApprovedError(APIError):
    """A merchant whose onboarding a Super Admin has not yet approved
    (merchants.status != 'active') tried to do something that moves or
    enables money — start a collection, issue a payment link or invoice,
    or mint an API key. 403, not 409: it's a permission they don't have
    yet, not a conflict with existing data. Withdrawals have their own
    WithdrawalRestrictedError for the same underlying rule (see
    app/services/disbursements.py::_check_merchant_is_verified)."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "merchant_not_approved"


class EmailDeliveryError(APIError):
    """Resend rejected the send, or the request to it failed outright
    (timeout/connection error), or RESEND_API_KEY isn't configured — see
    app/services/email.py. 502, not 500: this is an upstream provider
    failure (or missing config for one), not a bug in this app's own
    logic. The message is always safe to show a merchant/log — never
    includes the API key or raw provider payload."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "email_delivery_failed"


class MerchantCodeGenerationError(APIError):
    """Every candidate 8-digit Merchant ID (27 + 6 random digits) collided
    with an existing merchant across the retry budget — see
    app/services/merchant_code.py. 500, not 409: this isn't the caller's
    fault, it means the retry limit needs raising or the ID space is
    genuinely close to exhausted (extremely unlikely at 10^6 codes)."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "merchant_code_generation_failed"


class SelcomAPIError(APIError):
    """Selcom returned a non-2xx response, an unparseable body, or the
    request failed outright (timeout/connection error). 502, not 409/500 —
    this is an upstream provider failure, not a conflict in our own data or
    a bug in our own code. See app/services/selcom/client.py.

    `provider_status_code` (when known — a live HTTP error, not a
    connection failure) is Selcom's own response status, e.g. 403 for an
    IP-whitelist rejection — deliberately a different attribute from
    `status_code`, which is always 502 (this app's own response code to
    *its* caller, unrelated to what Selcom returned).

    `is_ip_whitelist_error` is the specific "Railway's outbound IP isn't
    whitelisted with Selcom yet" signal (HTTP 403 and/or Selcom's own error
    code 611 in the response body, per
    app/services/selcom_business/live_client.py) — deliberately its own flag
    rather than callers comparing `provider_status_code == 403` themselves,
    since a bare 403 alone is ambiguous (could also mean a bad API key).

    `provider_response_body` (Selcom Business only, currently — see
    app/services/selcom_business/live_client.py) is Selcom's raw error body
    when it parsed as JSON, `None` otherwise. Not logged or included in
    this app's own response to its caller (see api_error_handler below) —
    it exists so a direct caller like
    apps/api/scripts/test_selcom_disbursement_sandbox.py can print exactly
    why Selcom rejected a request (e.g. "invalid signature" vs. "invalid
    api key") instead of just a bare status code."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "selcom_api_error"

    def __init__(
        self,
        message: str,
        *,
        details: list | dict | None = None,
        provider_status_code: int | None = None,
        is_ip_whitelist_error: bool = False,
        provider_response_body: dict | None = None,
    ):
        super().__init__(message, details=details)
        self.provider_status_code = provider_status_code
        self.is_ip_whitelist_error = is_ip_whitelist_error
        self.provider_response_body = provider_response_body


def _error_content(code: str, message: str, details=None) -> dict:
    return ErrorResponse(error=ErrorDetail(code=code, message=message, details=details)).model_dump(
        mode="json"
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        # Retry-After on a 429 so a client backs off for the right
        # length of time rather than guessing -- and so a well-behaved
        # integrator stops hammering, which is the point of the limit.
        headers = None
        retry_after = getattr(exc, "retry_after", None)
        if retry_after:
            headers = {"Retry-After": str(int(retry_after))}
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_content(exc.code, exc.message, exc.details),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # exc.errors() can embed a raw exception object in `ctx` (e.g. a
        # field_validator that raises ValueError) — jsonable_encoder is what
        # actually makes that safe to serialize, not just str()-ing it.
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_content("validation_error", "Invalid request", jsonable_encoder(exc.errors())),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
        }.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_content(code, str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_content("internal_error", "An unexpected error occurred"),
        )
