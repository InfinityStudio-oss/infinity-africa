import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


class TransactionResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    reference: str
    provider_reference: str | None = None
    type: str
    method: str
    collection_id: uuid.UUID | None = None
    disbursement_id: uuid.UUID | None = None
    gross_amount: Decimal
    fee_amount: Decimal
    net_amount: Decimal
    currency: str
    status: str
    # Merchant-wallet balance snapshot around this transaction's most recent
    # ledger posting, and that posting's direction — null for transactions
    # created before this column existed, or with no wallet-affecting leg.
    # Never computed/guessed here: null means "not available", shown as
    # such, not backfilled with a derived number.
    balance_before: Decimal | None = None
    balance_after: Decimal | None = None
    direction: str | None = None
    # The customer who paid, resolved through collection_id rather than
    # stored here — see app/services/customer_lookup.py. Null for withdrawals
    # (no paying customer) and QR scans (no phone captured), never guessed.
    customer_phone: str | None = None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


# --- payment tracking ---------------------------------------------------------
#
# GET /v1/merchant/transactions/{id}/tracking and its Super Admin twin.
# Built by app/services/payment_tracking.py from recorded evidence only.


class PaymentTrackingIdentifiers(BaseModel):
    # InfinityPay's own stable id for the payment (collections.id) - the
    # `collection_id` already returned by the Collections API create and
    # status responses and every collection.* webhook. The ONE value to
    # share with a billing system. Null for a withdrawal or fee.
    payment_id: str | None = None
    # The integrator's own order/subscriber reference, exactly as they
    # sent it (collections.merchant_reference). Theirs, not ours.
    merchant_reference: str | None = None
    # InfinityPay's ledger handle for this row (transactions.reference).
    transaction_reference: str | None = None
    # The mobile-money provider's receipt/transaction id.
    provider_reference: str | None = None


class PaymentTrackingStep(BaseModel):
    code: str
    label: str
    # done | failed | waiting | unknown
    state: str
    # Only ever a recorded timestamp; null when none is recorded.
    at: str | None = None
    detail: str | None = None


class WebhookDeliveryRecord(BaseModel):
    event_name: str | None = None
    # queued | retrying | delivered | exhausted
    state: str
    label: str
    attempts: int
    max_attempts: int
    queued_at: str | None = None
    last_attempt_at: str | None = None
    delivered_at: str | None = None
    # The merchant's own server's HTTP answer to the last attempt.
    response_status: int | None = None
    next_retry_at: str | None = None


class PaymentTrackingWebhooks(BaseModel):
    applicable: bool
    configured: bool
    available: bool
    deliveries: list[WebhookDeliveryRecord]


class ServiceActivation(BaseModel):
    # Always "not_confirmed" today: no billing integration sends an
    # authenticated activation acknowledgement. See docs/payment-tracking.md.
    status: str
    label: str
    detail: str


class PaymentTrackingResponse(BaseModel):
    transaction_id: str
    identifiers: PaymentTrackingIdentifiers
    payment: list[PaymentTrackingStep]
    webhooks: PaymentTrackingWebhooks
    service_activation: ServiceActivation
