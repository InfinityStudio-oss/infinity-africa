"""Super Admin announcements to merchants.

A campaign is a draft until somebody dispatches it, and a draft never
sends. That is the sharpest rule in this file and the schema enforces it
too: there is no transition back to 'draft', so a sent campaign cannot
reappear as something editable and be sent again.

**Recipients are resolved here, on the server, from merchant records.**
The client sends filters, never a list of numbers. Nothing in this module
can address a payer: every candidate comes from the merchants table, and
the only phone columns read are the merchant's own notification number and
contact_phone.

**Dispatch freezes everything.** When a campaign starts, the recipients
and the rendered text become sms_messages rows. Nothing re-resolves them
afterwards, so a merchant added, suspended or opted out five minutes later
does not change a campaign already in flight - and a second Send click
finds the campaign already out of 'draft' and does nothing.
"""

import logging
import uuid

from supabase import Client

from app.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationAPIError
from app.core.time import utc_now_iso
from app.services.sms_messages import resolve_recipient
from app.services.sms_text import message_cost

logger = logging.getLogger("infinity.sms")

# A merchant in one of these states should not be receiving marketing.
# Suspended and closed accounts cannot trade, and pending ones have not
# been approved yet.
_ELIGIBLE_STATUSES = ("active",)

EXCLUDED_NO_NUMBER = "no usable notification number"
EXCLUDED_OPTED_OUT = "announcements switched off"
EXCLUDED_DUPLICATE_NUMBER = "duplicate number, already included"
EXCLUDED_NOT_ACTIVE = "account is not active"


def _settings_by_merchant(client: Client) -> dict[str, dict]:
    rows = (
        client.table("merchant_notification_settings")
        .select("merchant_id,announcement_sms_enabled,sms_notification_phone")
        .execute()
        .data
        or []
    )
    return {r["merchant_id"]: r for r in rows}


def resolve_recipients(client: Client, *, merchant_ids: list[str] | None) -> dict:
    """Who would actually receive this, and who would not and why.

    `merchant_ids` None means every eligible merchant. A supplied list is
    still filtered by the same rules - an explicit selection does not
    override a merchant who has opted out, because the opt-out is the
    merchant's decision and the selection is ours.

    Deduplicates by phone number. Two merchant accounts sharing one number
    is not hypothetical here: five businesses did exactly that until
    recently, and sending one person the same announcement three times is
    both a cost and an annoyance.
    """
    query = client.table("merchants").select(
        "id,business_name,merchant_code,contact_phone,status"
    )
    merchants = query.execute().data or []
    if merchant_ids is not None:
        wanted = set(merchant_ids)
        merchants = [m for m in merchants if m["id"] in wanted]

    prefs = _settings_by_merchant(client)
    recipients: list[dict] = []
    excluded: list[dict] = []
    seen_numbers: dict[str, str] = {}

    for merchant in sorted(merchants, key=lambda m: (m.get("business_name") or "").lower()):
        row = {
            "merchant_id": merchant["id"],
            "business_name": merchant.get("business_name"),
            "merchant_code": merchant.get("merchant_code"),
        }
        if merchant.get("status") not in _ELIGIBLE_STATUSES:
            excluded.append({**row, "reason": EXCLUDED_NOT_ACTIVE})
            continue

        pref = prefs.get(merchant["id"], {})
        # Absent row means the merchant never opened notification
        # settings; the column defaults to true, so an announcement is
        # allowed. Transactional alerts default the other way - these are
        # separate decisions on purpose.
        if pref and not pref.get("announcement_sms_enabled", True):
            excluded.append({**row, "reason": EXCLUDED_OPTED_OUT})
            continue

        phone, skip_reason = resolve_recipient(client, uuid.UUID(merchant["id"]))
        if skip_reason or not phone:
            excluded.append({**row, "reason": EXCLUDED_NO_NUMBER})
            continue

        if phone in seen_numbers:
            excluded.append(
                {**row, "reason": f"{EXCLUDED_DUPLICATE_NUMBER} ({seen_numbers[phone]})"}
            )
            continue

        seen_numbers[phone] = merchant.get("merchant_code") or merchant["id"]
        recipients.append({**row, "phone": phone})

    return {"recipients": recipients, "excluded": excluded}


def preview_campaign(client: Client, *, body: str, merchant_ids: list[str] | None) -> dict:
    """What Compose shows before anybody can click Send: who gets it, who
    does not, how many parts it is and what we think that costs.

    The credit figure is our own estimate from the rendered text. It is
    labelled as an estimate everywhere it appears because the provider's
    dry run is the only thing that confirms a price.
    """
    resolved = resolve_recipients(client, merchant_ids=merchant_ids)
    cost = message_cost(body)
    count = len(resolved["recipients"])
    return {
        "recipient_count": count,
        "excluded_count": len(resolved["excluded"]),
        "excluded": resolved["excluded"],
        "recipients": resolved["recipients"],
        "encoding": cost["encoding"],
        "characters": cost["length"],
        "segments_per_message": cost["segments"],
        # 1 credit per part per recipient, per the provider's pricing.
        "estimated_credits": cost["segments"] * count,
        "estimate_only": True,
    }


def create_draft(client: Client, *, title: str, body: str, created_by: uuid.UUID, filters: dict) -> dict:
    _require_text(title, "Give the announcement a title.")
    _require_text(body, "Write the message before saving.")
    return (
        client.table("sms_campaigns")
        .insert(
            {
                "title": title.strip(),
                "body": body,
                "status": "draft",
                "filters": filters or {},
                "created_by": str(created_by),
            }
        )
        .execute()
        .data[0]
    )


def update_draft(client: Client, *, campaign_id: uuid.UUID, title: str, body: str, filters: dict) -> dict:
    """Editing is allowed only while the campaign is a draft.

    Enforced on the status we read rather than trusted from the client,
    because "save" and "send" arriving close together is exactly how a
    campaign gets edited mid-dispatch.
    """
    campaign = _get(client, campaign_id)
    if campaign["status"] != "draft":
        raise ConflictError("This announcement has already been sent and can no longer be edited.")
    _require_text(title, "Give the announcement a title.")
    _require_text(body, "Write the message before saving.")
    return (
        client.table("sms_campaigns")
        .update({"title": title.strip(), "body": body, "filters": filters or {}})
        .eq("id", str(campaign_id))
        .eq("status", "draft")
        .execute()
        .data[0]
    )


def duplicate_draft(client: Client, *, campaign_id: uuid.UUID, created_by: uuid.UUID) -> dict:
    """Copy any campaign, sent or not, into a new draft. This is how a
    sent campaign is reused without the original ever becoming editable
    again."""
    original = _get(client, campaign_id)
    return create_draft(
        client,
        title=f"Copy of {original['title']}",
        body=original["body"],
        created_by=created_by,
        filters=original.get("filters") or {},
    )


def delete_draft(client: Client, *, campaign_id: uuid.UUID) -> None:
    campaign = _get(client, campaign_id)
    if campaign["status"] != "draft":
        raise ConflictError("Only an unsent draft can be deleted.")
    client.table("sms_campaigns").delete().eq("id", str(campaign_id)).eq(
        "status", "draft"
    ).execute()


def dispatch_campaign(client: Client, *, campaign_id: uuid.UUID, dispatched_by: uuid.UUID) -> dict:
    """Turn a draft into queued messages. The only function here that
    can cause an SMS to be sent.

    The status transition happens first and is conditional on the campaign
    still being a draft. A second Send click - or a double-submitting
    button, or a retried request - finds it already 'sending' and is
    refused, so the recipients are frozen exactly once.
    """
    campaign = _get(client, campaign_id)
    if campaign["status"] != "draft":
        raise ConflictError("This announcement has already been sent.")

    settings = get_settings()
    if not settings.oasis_sms_sender_id:
        raise ValidationAPIError("No approved sender ID is configured, so nothing can be sent.")

    claimed = (
        client.table("sms_campaigns")
        .update({"status": "sending", "dispatched_by": str(dispatched_by), "dispatched_at": utc_now_iso()})
        .eq("id", str(campaign_id))
        .eq("status", "draft")
        .execute()
        .data
        or []
    )
    if not claimed:
        # Somebody else claimed it between the read and the update.
        raise ConflictError("This announcement is already being sent.")

    resolved = resolve_recipients(client, merchant_ids=(campaign.get("filters") or {}).get("merchant_ids"))
    cost = message_cost(campaign["body"])
    queued = 0

    for recipient in resolved["recipients"]:
        row = {
            "merchant_id": recipient["merchant_id"],
            "purpose": "announcement",
            "campaign_id": str(campaign_id),
            "recipient_phone": recipient["phone"],
            "sender_id": settings.oasis_sms_sender_id,
            "body": campaign["body"],
            "status": "queued",
            "next_attempt_at": utc_now_iso(),
            # Per message, not per collection: an announcement has no
            # collection to derive from. Still stable once written, which
            # is what a retry needs.
            "idempotency_key": f"ipay-a-{uuid.uuid4().hex}",
            "segments": cost["segments"],
            "encoding": cost["encoding"],
        }
        try:
            client.table("sms_messages").insert(row).execute()
            queued += 1
        except Exception:  # noqa: BLE001 — one bad recipient must not stop the campaign
            logger.warning("sms_campaign_recipient_skipped campaign_id=%s", campaign_id)

    return (
        client.table("sms_campaigns")
        .update(
            {
                "recipient_count": queued,
                "excluded_count": len(resolved["excluded"]),
                "estimated_segments": cost["segments"],
                "estimated_credits": cost["segments"] * queued,
                # Terminal for the campaign record. The individual
                # messages carry their own delivery state from here.
                "status": "sent",
            }
        )
        .eq("id", str(campaign_id))
        .execute()
        .data[0]
    )


def _get(client: Client, campaign_id: uuid.UUID) -> dict:
    rows = client.table("sms_campaigns").select("*").eq("id", str(campaign_id)).execute().data or []
    if not rows:
        raise NotFoundError("Announcement not found")
    return rows[0]


def _require_text(value: str, message: str) -> None:
    if not value or not value.strip():
        raise ValidationAPIError(message)
