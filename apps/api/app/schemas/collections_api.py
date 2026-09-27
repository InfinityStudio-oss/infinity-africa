"""Request/response schemas for the external developer Collections API
(app/routers/collections_api.py, POST/GET /v1/collections...) — the
"create a collection, get a payment_url or a push/QR result, poll or
refresh its status" surface documented in
docs/developer-collections-api.md and apps/web/src/app/developers/collections/.

Deliberately separate from app/schemas/collections.py (the older
USSD/STK/Selcom-Pesa-push/Dynamic-QR schemas backing
app/routers/collections.py, still functional but backed by the
unconfirmed placeholder app/services/selcom/ client rather than the
real, proven Selcom Checkout integration) — different field names
(`phone`/`reference` here vs `customer_phone`/`merchant_reference`
there) mean these can't just extend those without an awkward alias
layer. New integrations should use this module's endpoints; the older
ones are kept only for backward compatibility with any existing caller.

`method`/`status` values on responses use the external vocabulary this
API commits to (wallet_push/selcom_pesa/qr, created/processing/
pending_clearance/successful/failed/cancelled/reversed) — translated
from this codebase's real internal collections.method/status values by
app/services/collections_api.py, never returned raw. See that module's
docstring for the exact translation table and why "pending_clearance"
maps from "pending_review" specifically.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.phone import validate_and_normalize_phone

ExternalCollectionMethod = Literal["wallet_push", "selcom_pesa", "qr"]
ExternalCollectionStatus = Literal[
    "created", "processing", "pending_clearance", "successful", "failed", "cancelled", "reversed"
]


class CollectionCreateRequest(BaseModel):
    """POST /v1/collections — the recommended "Infinity Payment Page"
    flow: creates a shareable payment page (internally a payment_links
    row — the same resource Payment Links and Merchant Portal's "Request
    Collection" already use) and returns its URL for you to redirect
    your customer to. No payment method is chosen here — the customer
    picks Mobile Money Push / Selcom Pesa / Scan QR on that page
    themselves."""

    merchant_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    currency: str = "TZS"
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_email: str | None = None
    reference: str | None = Field(default=None, max_length=100)
    description: str | None = None
    redirect_url: str | None = None
    cancel_url: str | None = None
    # Accepted for forward compatibility, not yet used — webhook delivery
    # is configured once per merchant account (PATCH
    # /v1/merchant/webhook-config or the Merchant Portal), not per
    # request. See docs/developer-collections-api.md.
    webhook_url: str | None = None

    @field_validator("customer_phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        return validate_and_normalize_phone(value) if value is not None else None


class CollectionCreateResponse(BaseModel):
    collection_id: uuid.UUID
    reference: str | None = None
    status: ExternalCollectionStatus
    payment_url: str


SimulatedCollectionStatus = Literal["successful", "failed", "pending_clearance", "reversed"]


class CollectionPushCreateRequest(BaseModel):
    """Shared shape for POST /v1/collections/wallet-push and
    POST /v1/collections/selcom-pesa — a phone number is required, a
    push has nowhere to go without one."""

    merchant_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    currency: str = "TZS"
    phone: str
    customer_name: str | None = None
    reference: str | None = Field(default=None, max_length=100)
    description: str | None = None
    # Sandbox-only — picks the outcome to simulate instead of a real
    # Selcom call. Rejected (not silently ignored) for a live key; see
    # app/services/sandbox_collections.py.
    simulate_status: SimulatedCollectionStatus | None = None

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str) -> str:
        return validate_and_normalize_phone(value)


class CollectionPushCreateResponse(BaseModel):
    collection_id: uuid.UUID
    reference: str | None = None
    status: ExternalCollectionStatus
    message: str


class CollectionQrCreateRequest(BaseModel):
    """POST /v1/collections/qr — phone is optional (unlike the push
    methods): a QR/token has nowhere to push to, the customer scans it
    themselves."""

    merchant_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    currency: str = "TZS"
    customer_name: str | None = None
    customer_phone: str | None = None
    reference: str | None = Field(default=None, max_length=100)
    description: str | None = None
    simulate_status: SimulatedCollectionStatus | None = None

    @field_validator("customer_phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        return validate_and_normalize_phone(value) if value is not None else None


class CollectionQrCreateResponse(BaseModel):
    """payment_token/qr_payload are exactly what Selcom's own
    create-order-minimal response returned — never generated by this
    codebase (see app/services/checkout_orders.py). expires_at is
    `null`: Selcom's real create-order-minimal response does not include
    a QR/token expiry field, so this is never fabricated — do not assume
    the QR is time-limited unless/until Selcom's API actually returns
    one."""

    collection_id: uuid.UUID
    reference: str | None = None
    status: ExternalCollectionStatus
    payment_token: str | None = None
    qr_payload: str | None = None
    expires_at: str | None = None


class CollectionStatusResponse(BaseModel):
    collection_id: uuid.UUID
    reference: str | None = None
    status: ExternalCollectionStatus
    amount: Decimal
    currency: str
    method: ExternalCollectionMethod | None = None
    provider_payment_status: str | None = None
    # Free text, historically sometimes the provider's own message. Kept
    # for existing integrations; new ones should branch on
    # failure_reason_code, which is a closed, documented set.
    failure_reason: str | None = None
    failure_reason_code: str | None = None
    failure_reason_message: str | None = None
    failed_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: str
    updated_at: str
