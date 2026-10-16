"""Merchant collection notification email settings — /v1/merchant/notification-settings
and /v1/admin/merchants/{id}/notification-settings. See
app/services/merchant_notifications.py for the shared validation/storage
logic both routes call through, and
supabase/migrations/20260901010000_merchant_notification_settings.sql for
the table.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class MerchantNotificationSettingsUpdate(BaseModel):
    """PUT-shaped request body (routed through PATCH, this codebase's
    existing update-verb convention). Deliberately loose typing here —
    format/max-2/duplicate/at-least-1-if-enabled are all enforced in
    app/services/merchant_notifications.py::validate_notification_emails
    with the feature brief's exact error message strings, not via pydantic
    field constraints (whose generic "Invalid request" envelope would bury
    the specific message the Merchant Portal/Super Admin UI is meant to
    show)."""

    primary_notification_email: str | None = None
    secondary_notification_email: str | None = None
    collection_notifications_enabled: bool = True

    # SMS. Separate flags from the email ones above and from each other:
    # a merchant who stops wanting announcements must not thereby lose
    # their own payment alerts. Both are optional here so an existing
    # caller that only sends the email fields keeps working unchanged -
    # None means "leave as it is", not "turn off".
    collection_sms_enabled: bool | None = None
    announcement_sms_enabled: bool | None = None
    # The merchant's own number. Blank clears it and falls back to
    # merchants.contact_phone. Never a payer's number.
    sms_notification_phone: str | None = None


class MerchantNotificationSettingsResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    primary_notification_email: str | None = None
    secondary_notification_email: str | None = None
    collection_notifications_enabled: bool
    collection_sms_enabled: bool = False
    announcement_sms_enabled: bool = True
    sms_notification_phone: str | None = None
    created_at: datetime
    updated_at: datetime
    updated_by: uuid.UUID | None = None


class NotificationDeliveryLogResponse(BaseModel):
    """One email_deliveries row, narrowed to email_type =
    'merchant_collection_notification' — Super Admin's per-recipient
    delivery history (feature brief Part 7's "email delivery log history
    per recipient")."""

    id: uuid.UUID
    recipient_email: str
    status: str
    provider_message_id: str | None = None
    error_message: str | None = None
    related_resource_id: uuid.UUID | None = None
    created_at: datetime


class AdminMerchantNotificationSettingsResponse(MerchantNotificationSettingsResponse):
    """Super Admin's view of one merchant's notification settings, plus
    the delivery summary the feature brief's Notification Details screen
    asks for: merchant name/ID (for a page that isn't already scoped to
    one merchant), last notification sent date/time + status, and a
    failed-count so a Super Admin can spot a merchant whose notification
    email is silently bouncing without opening the full delivery log."""

    merchant_name: str
    merchant_code: str | None = None
    last_notification_sent_at: datetime | None = None
    last_notification_status: str | None = None
    failed_notification_count: int = 0
    recent_deliveries: list[NotificationDeliveryLogResponse] = []
