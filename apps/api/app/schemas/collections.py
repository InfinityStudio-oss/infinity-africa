import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.core.phone import validate_and_normalize_phone


class CollectionInitiateBase(BaseModel):
    """Shared fields across all four /v1/collections/{method} endpoints.
    `method` itself isn't a field here — it's implied by which endpoint is
    called, so there's no way to send a method that doesn't match the URL."""

    merchant_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    currency: str = "TZS"
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    merchant_reference: str | None = Field(default=None, max_length=100)
    payment_link_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    description: str | None = None
    callback_url: str | None = None


class PushCollectionRequest(CollectionInitiateBase):
    """USSD_PUSH / STK_PUSH / SELCOM_PESA_PUSH — pushed to a phone, so a
    phone number is required."""

    customer_phone: str

    @field_validator("customer_phone")
    @classmethod
    def _check_phone(cls, value: str) -> str:
        return validate_and_normalize_phone(value)


class DynamicQrCollectionRequest(CollectionInitiateBase):
    """DYNAMIC_QR — scan-based; no phone number needed."""

    customer_phone: str | None = None

    @field_validator("customer_phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        return validate_and_normalize_phone(value) if value is not None else None


class CollectionResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    payment_link_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    merchant_reference: str | None = None
    method: str
    amount: Decimal
    currency: str
    customer_phone: str | None = None
    status: str
    provider: str | None = None
    provider_reference: str | None = None
    failure_reason: str | None = None
    # Selcom Checkout wallet-push fields (app/services/wallet_push.py,
    # app/services/checkout_reconciliation.py) — null for collections made
    # via the older selcom/ placeholder client, which never sets them.
    checkout_order_id: uuid.UUID | None = None
    provider_transid: str | None = None
    provider_resultcode: str | None = None
    provider_result: str | None = None
    provider_payment_status: str | None = None
    channel: str | None = None
    # Convenience fields threaded in by the router from data already
    # available at initiation time (the linked transaction row, a static
    # per-method message) — not columns of the collections table itself.
    transaction_reference: str | None = None
    message: str | None = None
    # Whether the merchant's own endpoint received the notification for
    # this payment — see app/services/webhook_status.py. A payment can be
    # entirely successful here while their system never heard about it,
    # which used to be visible only to us. None means there is nothing to
    # say: no webhook configured, or no event raised yet.
    webhook_delivery_status: str | None = None
    webhook_response_code: int | None = None
    webhook_attempts: int | None = None
    expires_at: datetime | None = None
    initiated_at: datetime
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DynamicQrCollectionResponse(CollectionResponse):
    qr_payload: str
    qr_expires_at: datetime
    # Always null today — no real QR image rendering exists in this
    # codebase yet (the frontend's QrPlaceholder is an explicit dev
    # placeholder, not derived from qr_payload). Populate once a real
    # Selcom response is observed to actually return one.
    qr_image_url: str | None = None


class HostedCheckoutCollectionResponse(CollectionResponse):
    """Merchant Portal "Request Collection" — the merchant no longer
    picks a channel; Selcom's own hosted checkout page shows whichever
    methods are enabled on the account. See
    app/services/hosted_checkout.py."""

    payment_gateway_url: str | None = None
