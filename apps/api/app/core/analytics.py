"""Product analytics — PostHog, off unless an API key is configured.

Two rules shape everything here, and they are not negotiable on a
platform that moves real money:

1. **An analytics failure must never affect a payment.** PostHog being
   down, slow, misconfigured or rate-limited has to be invisible to the
   merchant whose collection is being credited. So every function in
   this module swallows its own exceptions, and events are handed to the
   client's background queue rather than sent inline. Nothing here is
   ever awaited on a request path.

2. **No personal data leaves.** The only identity sent is `merchant_id`
   — a UUID this platform generated, which means nothing to PostHog and
   identifies no human. Phone numbers, emails, customer names, NIDA
   numbers and amounts are not sent. Properties are passed through the
   same scrubber the error reporter uses, so a mistake at a call site
   gets caught here rather than at PostHog.

What this is for: knowing that collections are succeeding, that webhook
deliveries are landing, that merchants are getting through onboarding.
Business health, not surveillance.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.monitoring import redact_text

logger = logging.getLogger("infinity.analytics")

_client: Any | None = None

# Properties are also allow-listed by name. The scrubber catches values
# that look sensitive; this catches the ones that do not — a customer
# name has no pattern to match, so the defence has to be structural.
_ALLOWED_PROPERTIES = frozenset(
    {
        "channel",
        "provider",
        "status",
        "failure_reason_code",
        "source",
        "created_via",
        "currency",
        "amount_band",
        "attempt",
        "http_status",
        "duration_ms",
        "environment",
        "event_type",
        "result",
    }
)


def init_analytics() -> bool:
    """Starts the PostHog client if configured. Returns whether it did.

    Never raises — see this module's docstring.
    """
    global _client

    from app.config import get_settings

    settings = get_settings()
    api_key = (settings.posthog_api_key or "").strip()
    if not api_key:
        return False

    try:
        from posthog import Posthog
    except ImportError:
        logger.warning("posthog_key_set_but_sdk_not_installed")
        return False

    try:
        _client = Posthog(
            project_api_key=api_key,
            host=settings.posthog_host,
            # Nothing is sent inline. The client's own thread drains the
            # queue, so a slow PostHog cannot add latency to a payment.
            sync_mode=False,
            # PostHog's SDK will otherwise raise out of capture() when a
            # send fails. On this platform that would mean an analytics
            # outage surfacing as a failed collection.
            on_error=_swallow_error,
            # No IP, and no geo lookup derived from one.
            disable_geoip=True,
        )
        logger.info("posthog_initialised host=%s", settings.posthog_host)
        return True
    except Exception:  # see module docstring.
        logger.exception("posthog_init_failed")
        _client = None
        return False


def _swallow_error(error: Any, items: Any = None) -> None:
    """PostHog's error hook. Logs and returns; never re-raises."""
    logger.warning("posthog_send_failed error=%s", redact_text(str(error)))


def shutdown_analytics() -> None:
    """Flushes the queue on a clean shutdown, so the last few events of a
    deploy are not lost. Bounded and best-effort: a hanging flush must
    not hold the process open."""
    global _client

    client = _client
    _client = None
    if client is None:
        return
    try:
        client.shutdown()
    except Exception:  # see module docstring.
        logger.debug("posthog_shutdown_failed", exc_info=True)


def _clean_properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    if not properties:
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in properties.items():
        if key not in _ALLOWED_PROPERTIES:
            continue
        cleaned[key] = redact_text(value) if isinstance(value, str) else value
    return cleaned


def track(
    event: str,
    *,
    merchant_id: str | None = None,
    properties: dict[str, Any] | None = None,
) -> None:
    """Records one product event. Does nothing if analytics is off.

    Safe to call from anywhere, including inside a payment path: it never
    raises, never blocks, and drops anything it cannot send. Properties
    outside `_ALLOWED_PROPERTIES` are discarded rather than sent.
    """
    client = _client
    if client is None:
        return
    try:
        client.capture(
            distinct_id=str(merchant_id) if merchant_id else "platform",
            event=event,
            properties=_clean_properties(properties),
        )
    except Exception:  # a dropped metric is the correct
        # outcome. The alternative is an analytics bug reaching a merchant
        # as a failed payment.
        logger.debug("posthog_capture_failed event=%s", event, exc_info=True)


def amount_band(amount: Any) -> str:
    """Buckets an amount instead of sending it.

    An exact figure plus a timestamp re-identifies a specific payment,
    and with it a specific payer. A band answers the question analytics
    actually asks — are small payments failing more than large ones —
    without carrying that back out.
    """
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return "unknown"
    for ceiling, label in (
        (1_000, "<1k"),
        (10_000, "1k-10k"),
        (100_000, "10k-100k"),
        (1_000_000, "100k-1m"),
    ):
        if value < ceiling:
            return label
    return ">=1m"
