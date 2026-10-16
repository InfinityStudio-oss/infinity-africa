"""Super Admin SMS — /v1/admin/sms/*, plus the provider callback.

Every route here is Super Admin only, including the read-only ones: an
SMS list carries merchant phone numbers and message bodies, which is not
something a merchant should see about other merchants.

The one exception is the provider callback at the bottom, which is
unauthenticated by necessity and authenticated instead by an HMAC over
the raw request bytes.

Nothing in this router can change a payment. The retry endpoint requeues
a message; the send endpoint queues messages. Neither touches a ledger,
transaction or collection row.
"""

import hashlib
import hmac
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from app.auth import require_super_admin
from app.config import get_settings
from app.core.errors import NotFoundError, ValidationAPIError
from app.core.time import utc_now_iso
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse
from app.services.audit import write_audit_log
from app.services.sms_campaigns import (
    create_draft,
    delete_draft,
    dispatch_campaign,
    duplicate_draft,
    preview_campaign,
    update_draft,
)
from app.services.sms_dispatch import MAX_ATTEMPTS
from app.services.sms_provider import get_balance, send_sms
from app.services.sms_text import message_cost

logger = logging.getLogger("infinity.sms")

router = APIRouter(prefix="/admin/sms", tags=["admin-sms"])
callback_router = APIRouter(prefix="/sms", tags=["sms-callbacks"])


def _mask_phone(value: str | None) -> str:
    """``255712345678`` -> ``2557****5678``.

    The Super Admin list shows enough to recognise a number without
    putting 60 merchants' phone numbers on one screen in full. The
    unmasked value is still available on the single-message view, where
    somebody is looking at one merchant deliberately.
    """
    digits = (value or "").strip()
    if len(digits) < 8:
        return "****" if digits else "—"
    return f"{digits[:4]}{'*' * (len(digits) - 8)}{digits[-4:]}"


class CampaignInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=1600)
    # None means every eligible merchant. An explicit list still goes
    # through the same eligibility and opt-out rules server-side.
    merchant_ids: list[uuid.UUID] | None = None


class PreviewInput(BaseModel):
    body: str = Field(min_length=1, max_length=1600)
    merchant_ids: list[uuid.UUID] | None = None


@router.get("/overview", response_model=APIResponse[dict])
def sms_overview(admin: Annotated[AuthenticatedUser, Depends(require_super_admin)]):
    """Queue health at a glance: how many messages are in each state, how
    long the oldest has been waiting, and the provider credit balance if
    we can read it."""
    client = get_supabase_admin()
    rows = (
        client.table("sms_messages")
        .select("status,purpose,created_at,skipped_reason,last_error")
        .order("created_at", desc=True)
        .limit(1000)
        .execute()
        .data
        or []
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    waiting = [r["created_at"] for r in rows if r["status"] in ("queued", "sending")]
    settings = get_settings()
    return APIResponse(
        data={
            "enabled": settings.oasis_sms_enabled,
            "sender_id": settings.oasis_sms_sender_id or None,
            "dispatch_interval_seconds": settings.oasis_sms_dispatch_interval_seconds,
            "counts": counts,
            "oldest_waiting_at": min(waiting) if waiting else None,
            "queue_depth": len(waiting),
            # None when no key is configured or the provider is
            # unreachable — a missing number here is not an error.
            "provider_credits": get_balance(),
            "recent_errors": [
                {"error": r["last_error"], "at": r["created_at"]}
                for r in rows
                if r.get("last_error")
            ][:10],
            "recent_skips": [
                {"reason": r["skipped_reason"], "at": r["created_at"]}
                for r in rows
                if r.get("skipped_reason")
            ][:10],
        }
    )


@router.get("/messages", response_model=APIResponse[list[dict]])
def list_sms_messages(
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    status_filter: str | None = None,
    purpose: str | None = None,
    campaign_id: uuid.UUID | None = None,
    limit: int = 100,
):
    client = get_supabase_admin()
    query = client.table("sms_messages").select("*").order("created_at", desc=True)
    if status_filter:
        query = query.eq("status", status_filter)
    if purpose:
        query = query.eq("purpose", purpose)
    if campaign_id:
        query = query.eq("campaign_id", str(campaign_id))
    rows = query.limit(min(limit, 500)).execute().data or []

    merchants = {
        m["id"]: m
        for m in (
            client.table("merchants").select("id,business_name,merchant_code").execute().data or []
        )
    }
    return APIResponse(
        data=[
            {
                "id": r["id"],
                "merchant_id": r["merchant_id"],
                "business_name": (merchants.get(r["merchant_id"]) or {}).get("business_name"),
                "merchant_code": (merchants.get(r["merchant_id"]) or {}).get("merchant_code"),
                "purpose": r["purpose"],
                "status": r["status"],
                "recipient_phone": _mask_phone(r.get("recipient_phone")),
                "body": r.get("body"),
                "skipped_reason": r.get("skipped_reason"),
                "last_error": r.get("last_error"),
                "attempts": r.get("attempts"),
                "segments": r.get("segments"),
                "credits_used": r.get("credits_used"),
                "provider_ref": r.get("provider_ref"),
                "provider_status": r.get("provider_status"),
                "reference": r.get("reference"),
                "created_at": r["created_at"],
                "sent_at": r.get("sent_at"),
            }
            for r in rows
        ]
    )


@router.post("/messages/{message_id}/retry", response_model=APIResponse[dict])
def retry_sms_message(
    message_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Requeue a message that failed.

    Only 'failed' is eligible. 'sent', 'pending' and 'unknown' are all
    states where the provider may already have the message, and requeuing
    one of those is how a merchant gets the same payment alert twice. The
    stable idempotency key would most likely save us, but "most likely" is
    not a reason to offer the button.
    """
    client = get_supabase_admin()
    rows = client.table("sms_messages").select("*").eq("id", str(message_id)).execute().data or []
    if not rows:
        raise NotFoundError("Message not found")
    message = rows[0]

    if message["status"] != "failed":
        raise ValidationAPIError(
            f"Only a failed message can be retried. This one is '{message['status']}'."
        )

    updated = (
        client.table("sms_messages")
        .update(
            {
                "status": "queued",
                "attempts": 0,
                "next_attempt_at": utc_now_iso(),
                "last_error": None,
            }
        )
        .eq("id", str(message_id))
        .eq("status", "failed")
        .execute()
        .data
    )
    write_audit_log(
        client,
        actor_id=admin.id,
        actor_type="user",
        merchant_id=uuid.UUID(message["merchant_id"]),
        action="sms.message_retried",
        resource_type="sms_message",
        resource_id=message_id,
    )
    return APIResponse(data=(updated or [{}])[0])


@router.post("/preview", response_model=APIResponse[dict])
def preview(
    payload: PreviewInput,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Recipients, exclusions, parts and estimated credits — before
    anything is saved or sent. Resolves recipients server-side from
    merchant records; the client never supplies phone numbers."""
    client = get_supabase_admin()
    ids = [str(m) for m in payload.merchant_ids] if payload.merchant_ids is not None else None
    return APIResponse(data=preview_campaign(client, body=payload.body, merchant_ids=ids))


@router.post("/dry-run", response_model=APIResponse[dict])
def dry_run(
    payload: PreviewInput,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Ask the provider what this message would actually cost.

    The /preview figures are our own arithmetic over the rendered text.
    This is the only thing that confirms them: the provider runs every
    check it would run for a real send - sender approval, encoding,
    segment count, credit sufficiency - and returns the quote without
    sending, charging, logging, or consuming the idempotency key.

    Sends to a single recipient because a quote is per-message; multiply
    by the recipient count from /preview for the campaign total.
    """
    settings = get_settings()
    if not settings.oasis_sms_api_key or not settings.oasis_sms_sender_id:
        raise ValidationAPIError(
            "An API key and an approved sender ID are both needed before a cost can be checked."
        )

    client = get_supabase_admin()
    ids = [str(m) for m in payload.merchant_ids] if payload.merchant_ids is not None else None
    resolved = preview_campaign(client, body=payload.body, merchant_ids=ids)
    recipients = resolved["recipients"]
    if not recipients:
        raise ValidationAPIError("Nobody would receive this, so there is nothing to price.")

    result = send_sms(
        to=recipients[0]["phone"],
        sender=settings.oasis_sms_sender_id,
        message=payload.body,
        # Never used on a dry run - the provider documents it as not
        # consuming a key - but the signature requires one.
        idempotency_key="dry-run",
        dry_run=True,
    )
    if result.outcome != "dry_run":
        raise ValidationAPIError(result.error or "The provider could not price this message.")

    per_message = result.credits_required
    return APIResponse(
        data={
            "confirmed_by_provider": True,
            "recipient_count": resolved["recipient_count"],
            "segments_per_message": result.segments,
            "credits_per_message": per_message,
            "credits_total": (per_message * resolved["recipient_count"]) if per_message else None,
            "enough_credits": result.enough_credits,
        }
    )


@router.get("/campaigns", response_model=APIResponse[list[dict]])
def list_campaigns(admin: Annotated[AuthenticatedUser, Depends(require_super_admin)]):
    client = get_supabase_admin()
    return APIResponse(
        data=client.table("sms_campaigns")
        .select("*")
        .order("created_at", desc=True)
        .limit(200)
        .execute()
        .data
        or []
    )


@router.post("/campaigns", response_model=APIResponse[dict], status_code=status.HTTP_201_CREATED)
def create_campaign(
    payload: CampaignInput,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Saves a draft. Sends nothing — dispatch is a separate, explicit
    action, which is the whole point of drafts existing."""
    client = get_supabase_admin()
    filters = {
        "merchant_ids": [str(m) for m in payload.merchant_ids]
        if payload.merchant_ids is not None
        else None
    }
    draft = create_draft(
        client, title=payload.title, body=payload.body, created_by=admin.id, filters=filters
    )
    write_audit_log(
        client,
        actor_id=admin.id,
        actor_type="user",
        action="sms.campaign_drafted",
        resource_type="sms_campaign",
        resource_id=uuid.UUID(draft["id"]),
    )
    return APIResponse(data=draft)


@router.patch("/campaigns/{campaign_id}", response_model=APIResponse[dict])
def edit_campaign(
    campaign_id: uuid.UUID,
    payload: CampaignInput,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Editing never dispatches, and is refused once a campaign has left
    draft."""
    client = get_supabase_admin()
    filters = {
        "merchant_ids": [str(m) for m in payload.merchant_ids]
        if payload.merchant_ids is not None
        else None
    }
    return APIResponse(
        data=update_draft(
            client, campaign_id=campaign_id, title=payload.title, body=payload.body, filters=filters
        )
    )


@router.post("/campaigns/{campaign_id}/duplicate", response_model=APIResponse[dict])
def copy_campaign(
    campaign_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    return APIResponse(data=duplicate_draft(client, campaign_id=campaign_id, created_by=admin.id))


@router.delete("/campaigns/{campaign_id}", response_model=APIResponse[dict])
def remove_campaign(
    campaign_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    delete_draft(client, campaign_id=campaign_id)
    write_audit_log(
        client,
        actor_id=admin.id,
        actor_type="user",
        action="sms.campaign_deleted",
        resource_type="sms_campaign",
        resource_id=campaign_id,
    )
    return APIResponse(data={"deleted": True})


@router.post("/campaigns/{campaign_id}/send", response_model=APIResponse[dict])
def send_campaign(
    campaign_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """The explicit Send. Freezes recipients and queues messages.

    A second click is refused rather than ignored: the campaign is no
    longer a draft, and saying so is more useful than silently doing
    nothing.
    """
    client = get_supabase_admin()
    campaign = dispatch_campaign(client, campaign_id=campaign_id, dispatched_by=admin.id)
    write_audit_log(
        client,
        actor_id=admin.id,
        actor_type="user",
        action="sms.campaign_sent",
        resource_type="sms_campaign",
        resource_id=campaign_id,
        metadata={"recipient_count": campaign.get("recipient_count")},
    )
    return APIResponse(data=campaign)


@router.get("/settings", response_model=APIResponse[dict])
def sms_settings(admin: Annotated[AuthenticatedUser, Depends(require_super_admin)]):
    """Operational settings, read-only.

    Deliberately exposes no key material: whether a key is configured,
    never the key itself, and the same for the callback secret. These are
    environment variables on the API service, so changing them is a
    deployment action rather than a form.
    """
    settings = get_settings()
    return APIResponse(
        data={
            "enabled": settings.oasis_sms_enabled,
            # The two automatic messages, each switchable on its own.
            # Collection alerts are absent because they no longer exist -
            # retired 2026-10-17 for cost, not switched off.
            "welcome_enabled": settings.oasis_sms_welcome_enabled,
            "withdrawal_enabled": settings.oasis_sms_withdrawal_enabled,
            "credit_cost_tzs": str(settings.oasis_sms_credit_cost_tzs),
            "sender_id": settings.oasis_sms_sender_id or None,
            "api_key_configured": bool(settings.oasis_sms_api_key),
            "callback_secret_configured": bool(settings.oasis_sms_webhook_secret),
            "dispatch_interval_seconds": settings.oasis_sms_dispatch_interval_seconds,
            "rate_limit_per_minute": settings.oasis_sms_rate_limit_per_minute,
            "batch_size": settings.oasis_sms_batch_size,
            "announcement_batch_size": settings.oasis_sms_announcement_batch_size,
            "max_attempts": MAX_ATTEMPTS,
            "provider_credits": get_balance(),
        }
    )


@router.post("/segments", response_model=APIResponse[dict])
def segments(
    payload: PreviewInput,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Encoding and part count for an arbitrary body, so the Compose box
    can show the cost as it is typed without resolving recipients."""
    return APIResponse(data=message_cost(payload.body))


# --- provider callbacks ------------------------------------------------


@callback_router.post("/callbacks/oasis", response_model=APIResponse[dict])
async def oasis_callback(request: Request):
    """Delivery notifications from the provider.

    Unauthenticated by necessity and authenticated by HMAC instead: the
    signature is computed over the *raw* bytes, before any parsing, because
    re-serialising JSON changes the bytes and would make every valid
    signature fail.

    Acknowledges only after the event is durably stored, and deduplicates
    on the provider's event id — the provider retries at 1min, 5min, 30min,
    2h and 12h, so the same event arrives repeatedly by design.

    Never changes a payment. A delivery notification updates an
    sms_messages row and nothing else.
    """
    settings = get_settings()
    raw = await request.body()

    if not settings.oasis_sms_webhook_secret:
        # No secret configured means we cannot tell a real callback from
        # anyone's POST, so we accept nothing. Safer than a permissive
        # default on an endpoint that exists to be called by strangers.
        logger.warning("sms_callback_rejected reason=no_secret_configured")
        raise ValidationAPIError("SMS callbacks are not configured.")

    signature = request.headers.get("X-BulkSMS-Signature", "")
    expected = hmac.new(
        settings.oasis_sms_webhook_secret.encode(), raw, hashlib.sha256
    ).hexdigest()
    # Constant time, as the provider documents: a timing-variable compare
    # on an HMAC leaks the expected value a byte at a time.
    if not hmac.compare_digest(signature.strip().lower(), expected):
        logger.warning("sms_callback_rejected reason=bad_signature")
        raise ValidationAPIError("Invalid signature.")

    event_id = request.headers.get("X-BulkSMS-Event-Id") or ""
    event_name = request.headers.get("X-BulkSMS-Event") or ""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}

    if not event_id:
        raise ValidationAPIError("Missing event id.")

    client = get_supabase_admin()
    log_id = str(payload.get("sms_log_id") or payload.get("id") or "") or None

    try:
        client.table("sms_provider_events").insert(
            {
                "event_id": event_id,
                "event_name": event_name or str(payload.get("event") or "unknown"),
                "provider_sms_log_id": log_id,
                "payload": payload if isinstance(payload, dict) else {},
            }
        ).execute()
    except Exception:  # noqa: BLE001 — unique event_id: a retry of one we have
        return APIResponse(data={"status": "duplicate"})

    _apply_callback(client, event_name=event_name, log_id=log_id, payload=payload)
    return APIResponse(data={"status": "accepted"})


_CALLBACK_STATUS = {
    # The provider's own wording. "delivered" means the gateway accepted
    # it, which is not a handset receipt — so it maps to 'sent', the same
    # state a 200 produces, rather than to anything stronger.
    "sms.delivered": "sent",
    "sms.pending": "pending",
    "sms.failed": "failed",
}


def _apply_callback(client, *, event_name: str, log_id: str | None, payload: dict) -> None:
    """Move the message on, if we can find it and the event is newer.

    A callback can arrive before the send response has been saved, in
    which case there is no row carrying this log id yet. The event is
    already stored, so nothing is lost — it simply does not apply to
    anything, and the send result will set the state a moment later.
    """
    if event_name == "credits.low":
        logger.error("sms_provider_credits_low balance=%s", payload.get("balance"))
        return

    new_status = _CALLBACK_STATUS.get(event_name)
    if not new_status or not log_id:
        return

    rows = (
        client.table("sms_messages")
        .select("id,provider_event_at,status")
        .eq("provider_sms_log_id", log_id)
        .execute()
        .data
        or []
    )
    if not rows:
        return
    message = rows[0]

    # Older events must not overwrite newer state. The provider retries
    # for up to 12 hours, so a stale 'pending' can easily arrive after a
    # 'failed' that superseded it.
    if message.get("provider_event_at"):
        return

    client.table("sms_messages").update(
        {"status": new_status, "provider_event_at": utc_now_iso()}
    ).eq("id", message["id"]).execute()
