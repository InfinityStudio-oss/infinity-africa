"""Error monitoring — Sentry, off unless a DSN is configured.

Deliberately inert by default. No SENTRY_DSN means init_sentry() does
nothing at all: no network, no behaviour change. That is what makes it
safe to merge onto a platform already serving real payments — switching
it on becomes a deploy-time decision rather than a code one.

The scrubber below is the part that matters. An error report is a
payload leaving our infrastructure for a third party, and the obvious
things to send with an exception — the request that caused it, its
headers, its body — are exactly the things carrying a merchant's API
key, a customer's phone number, and a provider's credentials. So the
default is to send almost nothing and allow back only what is provably
safe.

Three layers, because any one alone has a hole:

1. Whole sections are dropped: request body, query string, cookies, and
   the server's environment. These cannot be made safe by redaction — a
   payment body is sensitive in its entirety.
2. Headers are allow-listed, not deny-listed. A deny-list protects the
   headers someone thought of; an allow-list protects against the one
   they did not.
3. Whatever survives is walked recursively and pattern-redacted, because
   a secret can arrive inside an exception message, a breadcrumb or a
   tag — places no structural rule reaches.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("infinity.monitoring")

REDACTED = "[redacted]"

# Headers worth keeping: they say what kind of request it was, never who
# made it or what they sent. Anything absent from this list is dropped.
_SAFE_HEADERS = frozenset(
    {
        "content-type",
        "content-length",
        "accept",
        "accept-encoding",
        "user-agent",
        "referer",
        "origin",
        "x-request-id",
    }
)

# Patterns that must never leave the building, wherever they appear.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Merchant API keys and their public counterparts, in any context.
    re.compile(r"\b[sp]k_(?:live|test)_[A-Za-z0-9_\-]{8,}", re.IGNORECASE),
    # Resend keys.
    re.compile(r"\bre_[A-Za-z0-9_\-]{8,}"),
    # Anything shaped like a JWT: Supabase access/refresh tokens, our own.
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]*"),
    # Bearer tokens that reached a message body rather than a header.
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    # Email addresses — a customer's, a merchant's, anyone's.
    re.compile(r"\b[^\s@]+@[^\s@]+\.[A-Za-z]{2,}\b"),
    # Tanzanian mobile numbers in every shape the platform accepts.
    re.compile(r"(?:\+?255|\b0)\d{9}\b"),
    # NIDA: 20 digits, with or without separators.
    re.compile(r"\b\d{8}[\s\-]?\d{5}[\s\-]?\d{5}[\s\-]?\d{2}\b"),
)

# Key names whose VALUE is always dropped, whatever it looks like —
# catching a secret that happens to match no pattern: a short token, a
# password, a PIN.
_SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "pin",
    "nida",
    "phone",
    "msisdn",
    "email",
    "signature",
    "credential",
    "private_key",
    "service_role",
)


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def redact_text(value: str) -> str:
    """Pattern-redacts one string. Exposed so the tests can assert
    against the patterns directly, rather than only through a whole
    Sentry event."""
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(REDACTED, value)
    return value


def _scrub(value: Any, *, depth: int = 0) -> Any:
    """Walks a value, redacting as it goes.

    Depth-limited: an exception message can contain anything a caller
    sent, so an unbounded recursive scrubber is a denial of service
    waiting for a deeply nested payload.
    """
    if depth > 12:
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            key: (REDACTED if _is_sensitive_key(key) else _scrub(item, depth=depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item, depth=depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub(item, depth=depth + 1) for item in value)
    return value


def scrub_event(event: dict, _hint: dict | None = None) -> dict | None:
    """Sentry `before_send`. Returns the event with everything sensitive
    removed, or None to drop it entirely.

    A pure function on purpose: the tests call it directly with realistic
    event shapes, so the guarantees hold without a DSN, a network call,
    or the SDK being installed at all.
    """
    try:
        request = event.get("request")
        if isinstance(request, dict):
            # Dropped whole. There is no useful redaction of a payment
            # payload — the amount, the phone and the reference ARE the
            # payload.
            request.pop("data", None)
            request.pop("query_string", None)
            request.pop("cookies", None)

            headers = request.get("headers")
            if isinstance(headers, dict):
                request["headers"] = {
                    name: headers[name]
                    for name in headers
                    if str(name).lower() in _SAFE_HEADERS
                }

        # Server env carries every secret the process started with.
        contexts = event.get("contexts")
        if isinstance(contexts, dict):
            contexts.pop("env", None)
        event.pop("environment_variables", None)

        return _scrub(event)
    except Exception:  # a scrubber that raises would either
        # lose the error being reported or, worse, let an unscrubbed event
        # through. Dropping it is the safe failure.
        logger.exception("sentry_scrub_failed")
        return None


def init_sentry() -> bool:
    """Starts Sentry if configured. Returns whether it did.

    Never raises: monitoring failing to start must not stop the API
    serving payments.
    """
    from app.config import get_settings

    settings = get_settings()
    dsn = (settings.sentry_dsn or "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk
    except ImportError:
        logger.warning("sentry_dsn_set_but_sdk_not_installed")
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=settings.sentry_environment or settings.environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            before_send=scrub_event,
            # Local variables in a stack frame are the richest accidental
            # leak there is: a frame mid-payment holds the phone, the
            # amount, often the provider credentials.
            include_local_variables=False,
            # Bodies never reach Sentry at all, rather than being scrubbed
            # after arrival.
            max_request_body_size="never",
            send_default_pii=False,
        )
        logger.info(
            "sentry_initialised environment=%s",
            settings.sentry_environment or settings.environment,
        )
        return True
    except Exception:  # see docstring.
        logger.exception("sentry_init_failed")
        return False


def capture_exception(exc: BaseException) -> None:
    """Reports one exception, if monitoring is on. Otherwise does nothing.

    Best effort by design, and silent on failure: this is called from the
    handler that is already dealing with a failed request, so a raise
    here would replace a merchant's 500 with a crash in the error path.

    Safe to call unconditionally — the SDK itself no-ops when no client
    is active, so there is no init flag to check and no import-order
    trap.
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        sentry_sdk.capture_exception(exc)
    except Exception:  # see docstring.
        logger.debug("sentry_capture_failed", exc_info=True)


def capture_message(
    message: str, *, level: str = "warning", tags: dict[str, str] | None = None
) -> None:
    """Reports a condition that is not an exception but still warrants
    someone's attention — a webhook a merchant will now never receive, a
    worker that gave up.

    Same contract as capture_exception: no-op when monitoring is off,
    never raises. The message is redacted here as well as in before_send,
    because a caller may interpolate a merchant-supplied URL into it.
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        with sentry_sdk.new_scope() as scope:
            for key, value in (tags or {}).items():
                scope.set_tag(key, redact_text(str(value)))
            sentry_sdk.capture_message(redact_text(message), level=level)
    except Exception:  # see capture_exception.
        logger.debug("sentry_message_failed", exc_info=True)
