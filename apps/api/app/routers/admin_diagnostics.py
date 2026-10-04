"""Super Admin monitoring diagnostics — prove Sentry and PostHog are
actually wired up, without waiting for a real failure.

Why this exists: Sentry shows nothing until something breaks, which
makes "is monitoring live?" unanswerable right after a deploy. The
alternative — triggering a real error on a real endpoint — means
deliberately failing a request on a platform that moves money. These two
routes send one synthetic event each instead.

Everything here is deliberately inert and boring:

- `require_super_admin` on both. A merchant, an API key, or an
  unauthenticated caller cannot reach either.
- Nothing from the request is read, logged or sent. No headers, no
  cookies, no body, no IP, no merchant data — the events carry a fixed
  string plus the environment name, and nothing else.
- Neither route can fail the request. Monitoring being broken is
  precisely what you are testing for, so a provider outage reports
  `ok: false` with a safe reason rather than a 500.
- Rate-limited, and harmless if called repeatedly: the worst outcome is
  a few extra events in a dashboard you are already looking at.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth import require_super_admin
from app.config import get_settings
from app.core.analytics import track
from app.core.monitoring import capture_message
from app.core.rate_limit import rate_limit
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse

logger = logging.getLogger("infinity.admin.diagnostics")

router = APIRouter(prefix="/admin/diagnostics", tags=["admin-diagnostics"])

_RATE_LIMIT = rate_limit(scope="admin_diagnostics", limit=10, window_seconds=60)


@router.post("/sentry-test", response_model=APIResponse[dict])
async def send_sentry_test_event(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    _rate_limit: Annotated[None, Depends(_RATE_LIMIT)],
):
    """Send one synthetic Sentry event, so the API project can be
    confirmed live before a real error arrives.

    Reports whether monitoring is configured at all, which is the
    question being asked — a `false` here means SENTRY_DSN is unset on
    this deploy, not that something broke.
    """
    settings = get_settings()
    if not (settings.sentry_dsn or "").strip():
        return APIResponse(
            data={"ok": False, "message": "Sentry is not configured on this deployment"}
        )

    try:
        capture_message(
            "InfinityPay monitoring diagnostic — this event is synthetic and can be ignored",
            level="info",
            tags={"diagnostic": "true"},
        )
    except Exception:  # capture_message already swallows; belt and braces.
        logger.warning("sentry_diagnostic_failed", exc_info=True)
        return APIResponse(data={"ok": False, "message": "Sentry test event could not be sent"})

    return APIResponse(data={"ok": True, "message": "Sentry test event sent"})


@router.post("/posthog-test", response_model=APIResponse[dict])
async def send_posthog_test_event(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    _rate_limit: Annotated[None, Depends(_RATE_LIMIT)],
):
    """Send one synthetic PostHog event.

    Attributed to the fixed distinct_id "platform" rather than to the
    admin running it: a diagnostic should not create a person profile,
    and no human needs identifying for this to answer its question.
    """
    settings = get_settings()
    if not (settings.posthog_api_key or "").strip():
        return APIResponse(
            data={"ok": False, "message": "PostHog is not configured on this deployment"}
        )

    try:
        # No merchant_id: this is a platform event, not a merchant's.
        # `environment` is on the property allow-list; nothing else is sent.
        track("monitoring_diagnostic", properties={"environment": settings.environment})
    except Exception:  # track() already swallows; belt and braces.
        logger.warning("posthog_diagnostic_failed", exc_info=True)
        return APIResponse(data={"ok": False, "message": "PostHog test event could not be sent"})

    return APIResponse(
        data={
            "ok": True,
            # Said explicitly because the queue is asynchronous by design —
            # an empty dashboard a second later is expected, not a failure.
            "message": "PostHog test event sent (queued; allow up to a minute to appear)",
        }
    )
