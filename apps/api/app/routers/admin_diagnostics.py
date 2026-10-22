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
from urllib.parse import urlparse

from fastapi import APIRouter, Depends

from app.auth import require_super_admin
from app.config import get_settings
from app.core.analytics import track
from app.core.monitoring import capture_message
from app.core.rate_limit import rate_limit
from app.database.session import get_supabase_admin
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


@router.get("/webhook-signing", response_model=APIResponse[dict])
def webhook_signing_posture(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    _rate_limit: Annotated[None, Depends(_RATE_LIMIT)],
):
    """Which merchants have a webhook endpoint that is delivered unsigned.

    A merchant can save a webhook URL without a signing secret. When there
    is no secret, app/services/webhook_delivery.py omits
    X-Infinity-Signature entirely, so the receiver cannot distinguish our
    event from any other POST to the same URL. For a receiver that
    activates service on a payment event, that is the whole security of
    the integration, and it was invisible from the admin side - there was
    no screen or endpoint anywhere that showed it.

    New endpoints are now refused unless a secret is configured
    (app/routers/merchant_webhooks.py). Merchants already live without one
    keep working, so this is the list of who still needs contacting, and
    it is the reason this endpoint exists: the migration needs a worklist,
    not a warning.

    Returns identities, never secrets. The signing secret is not selected
    from the database at all here, encrypted or otherwise. Only the
    endpoint's **host** is returned, not the full URL - a webhook path can
    itself contain a token, and nothing here needs the path to be useful.
    """
    client = get_supabase_admin()

    # Two narrow queries rather than one wide one, so the ciphertext column
    # is never read into this process.
    with_url = (
        client.table("merchants").select("id, business_name, webhook_url").execute().data or []
    )
    unsigned_ids = {
        str(row.get("id"))
        for row in (
            client.table("merchants")
            .select("id")
            .is_("webhook_secret_encrypted", "null")
            .execute()
            .data
            or []
        )
    }

    configured = [row for row in with_url if (row.get("webhook_url") or "").strip()]
    unsigned = [row for row in configured if str(row.get("id")) in unsigned_ids]

    return APIResponse(
        data={
            "endpoints_configured": len(configured),
            "signed": len(configured) - len(unsigned),
            "unsigned": len(unsigned),
            "unsigned_merchants": [
                {
                    "merchant_id": str(row.get("id")),
                    "business_name": row.get("business_name"),
                    "webhook_host": urlparse(row.get("webhook_url") or "").hostname,
                }
                for row in unsigned
            ],
        }
    )


# Operational switches worth being able to read back from production.
# Booleans and numbers only - never a secret, and never anything whose
# value would help someone attack the platform.
_REPORTED_SETTINGS = (
    "environment",
    "selcom_checkout_accept_unsigned_callbacks",
    "selcom_checkout_reconcile_interval_seconds",
    "selcom_disbursement_reconcile_interval_seconds",
    "selcom_outbound_max_per_minute",
    "selcom_outbound_max_concurrent",
    "selcom_reconcile_batch_size",
    "collection_push_expiry_minutes",
    "webhook_delivery_interval_seconds",
    "require_super_admin_mfa",
    "cache_enabled",
    "oasis_sms_enabled",
)


@router.get("/settings", response_model=APIResponse[dict])
def report_effective_settings(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    _rate_limit: Annotated[None, Depends(_RATE_LIMIT)],
):
    """What the running process actually believes, not what the dashboard
    says it was given.

    A variable that is absent, misspelled, or unreadable all produce the
    same outcome - the field's default - and two of those three are
    silent. On 2026-10-22 that cost several rounds of guessing: Selcom
    callbacks kept being rejected after
    SELCOM_CHECKOUT_ACCEPT_UNSIGNED_CALLBACKS was reportedly set, and
    there was no way to tell from outside whether the process had ever
    seen it.

    `source` is what makes this answer the question. `env` means an
    environment variable supplied this value; `default` means nothing
    did, and the field fell back - which is exactly what a missing or
    misspelled variable looks like.

    Booleans and numbers only. No secret is reported here, in any form,
    and nothing is included whose value would help someone attack the
    platform.
    """
    settings = get_settings()
    supplied = settings.model_fields_set

    return APIResponse(
        data={
            "settings": {
                name: {
                    "value": getattr(settings, name, None),
                    "source": "env" if name in supplied else "default",
                }
                for name in _REPORTED_SETTINGS
                if hasattr(settings, name)
            }
        }
    )
