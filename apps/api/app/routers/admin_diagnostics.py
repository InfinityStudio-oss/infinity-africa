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
import uuid
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import require_super_admin
from app.config import get_settings
from app.core.analytics import track
from app.core.monitoring import capture_message
from app.core.phone import normalize_tz_phone
from app.core.rate_limit import rate_limit
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse
from app.services.audit import write_audit_log
from app.services.security_alerts import mask_phone
from app.services.sms_provider import SmsNotConfigured, send_sms
from app.services.sms_text import message_cost, render_new_merchant_admin

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
    # Super Admin alerts. Reported because "configured" and "working" look
    # identical from the outside until a merchant happens to register or a
    # withdrawal happens to wait - and on a quiet night that is hours
    # away. A flag that was set but misspelled, or set on the wrong
    # service, reads here as `default` rather than `env`, which is the
    # whole point of this endpoint.
    #
    # The recipient itself is deliberately NOT listed: this reports
    # booleans and numbers only, never a value, and an operator's phone
    # number is not something to render in a diagnostics page. Whether one
    # is configured shows up instead as a skipped row with a reason in the
    # Super Admin SMS screen.
    "super_admin_sms_enabled",
    "super_admin_sms_new_merchant_enabled",
    "super_admin_sms_withdrawal_request_enabled",
    "super_admin_sms_withdrawal_auto_enabled",
    # Withdrawal automation. Added 2026-10-31, when enabling it meant
    # setting two Railway variables and then finding out whether they had
    # taken by looking at a portal page - this endpoint exists precisely
    # so that question has a direct answer. `source` is the whole point:
    # "env" means a variable supplied the value, "default" means nothing
    # did, which is what a missing or misspelled variable looks like.
    #
    # Booleans and numbers only, same as every other row here. The
    # database policy that sits under these is not reported: it changes
    # without a deploy, so a value read at request time belongs on the
    # Withdrawal Monitoring page where it is read fresh, not in a
    # diagnostics endpoint about this process's configuration.
    "require_admin_approval_for_all_withdrawals",
    "auto_withdrawals_enabled",
    "auto_withdrawal_max_amount_tzs",
    "auto_withdrawal_daily_limit_tzs",
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


# --- Super Admin SMS test ----------------------------------------------


class _SmsTestRequest(BaseModel):
    """How far to go. Each step proves strictly more than the one before,
    and only the last one costs money or reaches a handset."""

    mode: Literal["preview", "dry_run", "send"] = "preview"


@router.post("/test-sms", response_model=APIResponse[dict])
def test_super_admin_sms(
    payload: _SmsTestRequest,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="admin_sms_test", limit=3, window_seconds=300))
    ],
):
    """Prove the Super Admin SMS path without waiting for a merchant.

    "Configured" and "configured wrongly" are indistinguishable until a
    registration or a withdrawal happens to occur, which on a quiet night
    is hours away. This answers the question on demand, in three steps:

    **preview** (default) - renders the exact message, resolves and masks
    the recipient, reports the flags and where each came from. Touches no
    provider and costs nothing. Enough to catch an unset variable, a
    misspelled one, a number that will not normalise, or a template that
    has grown to two segments.

    **dry_run** - asks Oasis to validate the message without sending it.
    Proves the API key, the sender ID and the number format are accepted,
    and returns the provider's own segment count and whether there are
    enough credits. Still sends nothing and charges nothing.

    **send** - one real message to the configured operator number. The
    only step that reaches a handset, and the only one that costs.

    Super Admin only, inheriting whatever MFA require_super_admin
    enforces, rate limited to three calls in five minutes, and audited.
    Never a merchant-supplied recipient: the number comes from
    configuration and nothing in the request can change it.
    """
    settings = get_settings()
    supplied = settings.model_fields_set
    numbers = settings.super_admin_sms_numbers

    report: dict = {
        "mode": payload.mode,
        "flags": {
            name: {
                "value": getattr(settings, name, None),
                "source": "env" if name in supplied else "default",
            }
            for name in (
                "super_admin_sms_enabled",
                "super_admin_sms_new_merchant_enabled",
                "super_admin_sms_withdrawal_request_enabled",
                "oasis_sms_enabled",
            )
        },
        "recipients_configured": len(numbers),
        # Masked, always. A diagnostics response is read in a browser and
        # often pasted into a chat; the full operator number has no reason
        # to travel that way.
        "recipients": [mask_phone(n) for n in numbers],
        "sender_id": settings.oasis_sms_sender_id or None,
    }

    # The real template, with a name that cannot be mistaken for a real
    # registration. An operator who receives this at 2am must know in the
    # first three words that nothing has happened and nobody is waiting.
    sample = render_new_merchant_admin(business_name="SMS TEST - ignore")
    cost = message_cost(sample)
    report["sample_message"] = sample
    report["segments"] = cost["segments"]
    report["encoding"] = cost["encoding"]

    if not numbers:
        report["result"] = "no recipient configured - set SUPER_ADMIN_SMS_RECIPIENTS"
        return APIResponse(data=report)

    try:
        normalised = normalize_tz_phone(numbers[0])
    except Exception:  # noqa: BLE001
        report["result"] = "the configured recipient is not a valid Tanzanian number"
        return APIResponse(data=report)

    if payload.mode == "preview":
        report["result"] = "preview only - nothing was sent to the provider"
        return APIResponse(data=report)

    write_audit_log(
        get_supabase_admin(),
        actor_id=admin.id,
        actor_type="user",
        action=f"admin.sms_test.{payload.mode}",
        resource_type="sms",
        # The number is masked here too: an audit row proves who tested
        # and when, and does not need to carry the recipient in clear.
        metadata={"recipient": mask_phone(numbers[0]), "mode": payload.mode},
    )

    try:
        result = send_sms(
            to=normalised,
            sender=settings.oasis_sms_sender_id,
            message=sample,
            idempotency_key=f"ipay-admin-test-{uuid.uuid4().hex}",
            dry_run=payload.mode == "dry_run",
        )
    except SmsNotConfigured as exc:
        report["result"] = f"provider not configured: {exc}"
        return APIResponse(data=report)

    report["provider"] = {
        "outcome": result.outcome,
        "status_code": result.status_code,
        "segments": result.segments,
        "credits_required": result.credits_required,
        "enough_credits": result.enough_credits,
        # Provider error text can echo the request; it is reported because
        # an operator needs it, and it never contains our credentials.
        "error": result.error,
    }
    report["result"] = (
        "dry run accepted by the provider - nothing was sent"
        if payload.mode == "dry_run"
        else f"message handed to the provider ({result.outcome})"
    )
    return APIResponse(data=report)
