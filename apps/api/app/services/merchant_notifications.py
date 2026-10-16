"""Merchant collection notification email settings — the merchant-
configured "who should be emailed when a collection is confirmed" list
(up to 2 addresses), distinct from the customer-facing payment receipt
(app/services/email.py::send_payment_receipt_email).

Shared by both write paths — the merchant's own PUT
/v1/merchant/notification-settings (app/routers/merchant_portal.py) and
Super Admin's PUT /v1/admin/merchants/{id}/notification-settings
(app/routers/admin.py) — so the exact same rules (format, max 2, no
duplicates, at least 1 required while enabled) apply no matter who's
editing. See supabase/migrations/20260901010000_merchant_notification_settings.sql.
"""

import re
import uuid
from typing import Any

from supabase import Client

from app.core.errors import ValidationAPIError
from app.core.phone import InvalidPhoneNumberError, normalize_tz_phone
from app.core.time import utc_now_iso
from app.services.crud import execute_maybe_single, insert_row, update_row

# Same convention as app/schemas/auth.py's _EMAIL_PATTERN / app/schemas/
# merchant_portal.py's / app/schemas/pay_by_link.py's — deliberately not
# pydantic's EmailStr, which needs the email-validator package this
# codebase doesn't otherwise depend on.
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _is_valid_email(value: str) -> bool:
    return bool(_EMAIL_PATTERN.match(value))


def validate_notification_emails(raw_emails: list[str | None], *, enabled: bool) -> list[str]:
    """Trims/filters `raw_emails` (typically [primary, secondary] from the
    request body) down to the real, ordered list of configured addresses,
    enforcing every rule from the feature brief with its exact error
    message. Reused as-is for both the 2-field Merchant Portal/Super Admin
    request shape and the underlying business rule "no more than 2
    collection notification recipients" — the >2 branch is unreachable
    through the current 2-field API surface (there's physically nowhere to
    put a 3rd email), but stays here as the one place that rule is
    enforced so a future call site (e.g. a bulk-import) can't accidentally
    skip it. See tests/test_merchant_notification_settings.py."""
    emails = [e.strip() for e in raw_emails if e and e.strip()]

    # No address, with notifications on, is a legitimate state meaning
    # "send them to my account email" - which is exactly what
    # notification_recipient() below does, and what the settings page
    # tells the merchant in so many words ("No address set, so
    # confirmations go to your account email, <address>").
    #
    # Refusing to save it contradicted both. A merchant who had never set
    # an address could not change anything else on that card - including,
    # once SMS arrived, turning on their payment alerts - without first
    # inventing an email address they did not want. `enabled` is still
    # taken and still meaningful; it just no longer forces a second,
    # unrelated field to be filled in.

    if len(emails) > 2:
        raise ValidationAPIError("You can add up to 2 notification emails only.")

    for email in emails:
        if not _is_valid_email(email):
            raise ValidationAPIError("Enter a valid notification email.")

    if len({e.lower() for e in emails}) != len(emails):
        raise ValidationAPIError("Duplicate notification emails are not allowed.")

    return emails


def get_notification_settings(client: Client, merchant_id: uuid.UUID) -> dict | None:
    return execute_maybe_single(
        client.table("merchant_notification_settings").select("*").eq("merchant_id", str(merchant_id)).maybe_single()
    )


def get_or_create_notification_settings(client: Client, merchant_id: uuid.UUID) -> dict:
    """A merchant who has never opened Notification Settings has no row
    yet — GET still needs to return something (collection_notifications_enabled
    defaults true, both emails null) rather than 404, since "not configured
    yet" is a normal first-visit state, not an error. Lazily creates the
    default row on first read so the response always has a real `id` to
    key off of."""
    existing = get_notification_settings(client, merchant_id)
    if existing:
        return existing
    return insert_row(
        client,
        "merchant_notification_settings",
        {"merchant_id": str(merchant_id), "collection_notifications_enabled": True},
    )


def upsert_notification_settings(
    client: Client,
    merchant_id: uuid.UUID,
    *,
    primary_notification_email: str | None,
    secondary_notification_email: str | None,
    collection_notifications_enabled: bool,
    updated_by: uuid.UUID | None,
    collection_sms_enabled: bool | None = None,
    announcement_sms_enabled: bool | None = None,
    sms_notification_phone: str | None = None,
) -> dict:
    data: dict[str, Any] = {
        "primary_notification_email": primary_notification_email,
        "secondary_notification_email": secondary_notification_email,
        "collection_notifications_enabled": collection_notifications_enabled,
        "updated_by": str(updated_by) if updated_by else None,
    }
    # None means "not supplied", so a caller that knows nothing about SMS
    # cannot silently switch a merchant's alerts off by omission.
    if collection_sms_enabled is not None:
        data["collection_sms_enabled"] = collection_sms_enabled
    if announcement_sms_enabled is not None:
        data["announcement_sms_enabled"] = announcement_sms_enabled
    if sms_notification_phone is not None:
        # Validated and normalised to E.164 here rather than at the edge,
        # so every route that can set it goes through the same check and
        # the worker can trust what it reads. Blank clears it.
        cleaned = sms_notification_phone.strip()
        # normalize_tz_phone, not validate_and_normalize_phone: that
        # wrapper exists to raise a bare ValueError for Pydantic field
        # validators, and a bare ValueError escaping a service is a 500.
        # A merchant typing their number slightly wrong deserves a
        # message telling them so.
        try:
            data["sms_notification_phone"] = normalize_tz_phone(cleaned) if cleaned else None
        except InvalidPhoneNumberError as exc:
            raise ValidationAPIError(
                "Enter a valid Tanzanian phone number for SMS alerts "
                "(e.g. 0712 345 678)."
            ) from exc
        data["sms_phone_updated_by"] = str(updated_by) if updated_by else None
        data["sms_phone_updated_at"] = utc_now_iso()
    existing = get_notification_settings(client, merchant_id)
    if existing:
        return update_row(client, "merchant_notification_settings", uuid.UUID(existing["id"]), data) or existing
    return insert_row(client, "merchant_notification_settings", {"merchant_id": str(merchant_id), **data})


def notification_delivery_summary(client: Client, merchant_id: uuid.UUID) -> dict:
    """last_notification_sent_at/last_notification_status/failed_notification_count
    + the recent per-recipient delivery rows — Super Admin's Notification
    Details view (feature brief Part 7). Scoped to email_type =
    'merchant_collection_notification' only — a merchant's other email
    types (receipts, invites, ...) are irrelevant here."""
    rows = (
        client.table("email_deliveries")
        .select("*")
        .eq("merchant_id", str(merchant_id))
        .eq("email_type", "merchant_collection_notification")
        .order("created_at", desc=True)
        .execute()
    ).data or []

    latest = rows[0] if rows else None
    failed_count = sum(1 for row in rows if row["status"] == "failed")

    return {
        "last_notification_sent_at": latest["created_at"] if latest else None,
        "last_notification_status": latest["status"] if latest else None,
        "failed_notification_count": failed_count,
        "recent_deliveries": rows[:20],
    }


def notification_recipient(client: Client, merchant: dict) -> str | None:
    """The one address a merchant wants operational email sent to.

    Used by collection confirmations and withdrawal-success emails alike,
    so "where do my transaction emails go" has a single answer the
    merchant can see and change in one place. Withdrawal success used to
    ignore this entirely and go to contact_email, which meant a business
    could set a finance address, receive collection emails there, and
    still have payout confirmations arrive somewhere else.

    Falls back to the account's own contact_email: that is the address
    they registered, it is shown on the settings page as the effective
    recipient, and sending nowhere would be worse than sending there.

    Deliberately singular. A second address used to be configurable and
    was removed — one recipient the merchant can see beats two they have
    to remember, and a forwarding rule does the rest.
    """
    merchant_id = merchant.get("id")
    if merchant_id:
        settings_row = get_notification_settings(client, uuid.UUID(merchant_id)) or {}
        primary = (settings_row.get("primary_notification_email") or "").strip()
        if primary:
            return primary
    return (merchant.get("contact_email") or "").strip() or None
