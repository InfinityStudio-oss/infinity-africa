"""Response models for the platform-wide super-admin dashboard —
/v1/admin/* (app/routers/admin.py). Every model here adds a merchant_name
(or owner/actor name) join on top of an existing per-resource response
shape (see app/schemas/{merchants,payment_links,invoices,collections,
disbursements,transactions}.py) — these are read-only dashboard views, not
a replacement for those resource-oriented schemas.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


class AdminOverviewResponse(BaseModel):
    total_merchants: int
    collections_today: Decimal
    withdrawals_today: Decimal
    active_payment_links: int
    paid_invoices_today: int
    outstanding_invoice_value: Decimal
    failed_transactions: int
    platform_revenue: Decimal
    pending_onboarding_requests: int
    pending_withdrawals: int


class AdminCustomerResponse(BaseModel):
    """Derived, not read from a table — see
    app/services/admin_customers.py's own docstring for why."""

    id: str
    merchant_id: uuid.UUID
    merchant_name: str
    merchant_code: str | None = None
    full_name: str | None = None
    phone: str
    currency: str
    total_spent: Decimal
    transaction_count: int
    first_seen_at: datetime | None = None
    last_transaction_at: datetime | None = None


class AdminApiKeyResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    merchant_name: str
    merchant_code: str | None = None
    name: str
    environment: str
    key_prefix: str
    key_last4: str | None = None
    scopes: list[str]
    status: str
    ip_whitelist_enabled: bool = False
    last_used_at: datetime | None = None
    last_used_ip: str | None = None
    revoked_at: datetime | None = None
    created_at: datetime


class AdminMerchantResponse(BaseModel):
    merchant_id: uuid.UUID
    merchant_code: str | None = None
    business_name: str
    owner_name: str | None = None
    email: str
    contact_phone: str | None = None
    nature_of_business: str | None = None
    physical_address: str | None = None
    account_status: str
    kyc_status: str
    api_access_suspended: bool
    production_api_eligible: bool
    available_balance: Decimal
    created_at: datetime


class AdminMerchantUserResponse(BaseModel):
    user_id: uuid.UUID
    merchant_id: uuid.UUID
    merchant_name: str
    merchant_code: str | None = None
    full_name: str | None = None
    email: str | None = None
    role: str
    status: str
    created_at: datetime


class AdminPaymentLinkResponse(BaseModel):
    link_id: uuid.UUID
    merchant_id: uuid.UUID
    merchant_name: str
    merchant_code: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    amount: Decimal
    currency: str
    status: str
    expires_at: datetime | None = None
    created_at: datetime
    # 'payment_link' | 'request_collection' | 'api' | 'pay_by_link' — which
    # Merchant Portal surface (or external API) created this row. See
    # supabase/migrations/20260824020000_collection_source_tracking.sql's
    # column comment and app/services/collection_source.py, which derives
    # an eventual collection's own `source` from this same field.
    created_via: str


class AdminPayByLinkResponse(BaseModel):
    """Platform-wide row for GET /v1/admin/pay-by-link — a merchant's
    permanent public checkout page, distinct from AdminPaymentLinkResponse
    above (a one-off generated link, or a payment created *through* a Pay
    by Link page — see created_via="pay_by_link" there). This response is
    about the page itself: does it exist, is it active, when was it last
    used."""

    pay_by_link_id: uuid.UUID
    merchant_id: uuid.UUID
    merchant_name: str
    merchant_code: str | None = None
    slug: str
    display_name: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None


class AdminInvoiceResponse(BaseModel):
    invoice_id: uuid.UUID
    invoice_number: str
    merchant_id: uuid.UUID
    merchant_name: str
    merchant_code: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_email: str | None = None
    total_amount: Decimal
    status: str
    due_date: date
    created_at: datetime
    # Set only once the payment-request email actually goes out.
    sent_at: datetime | None = None
    # Most recent email_deliveries row for this invoice, if any — null
    # fields mean no send has ever been attempted, not "unknown".
    email_status: str | None = None
    email_provider_message_id: str | None = None
    email_failed_reason: str | None = None


class AdminCollectionResponse(BaseModel):
    collection_id: uuid.UUID
    merchant_id: uuid.UUID
    merchant_name: str
    merchant_code: str | None = None
    source: str | None = None
    method: str
    amount: Decimal
    currency: str
    fee_amount: Decimal | None = None
    net_amount: Decimal | None = None
    phone: str | None = None
    merchant_reference: str | None = None
    provider_reference: str | None = None
    api_key_id: uuid.UUID | None = None
    payment_link_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    status: str
    created_at: datetime
    # Selcom Checkout wallet-push fields — null for collections made via
    # the older selcom/ placeholder client.
    order_id: str | None = None
    provider_transid: str | None = None
    channel: str | None = None
    provider_payment_status: str | None = None
    failure_reason: str | None = None


class AdminWithdrawalResponse(BaseModel):
    withdrawal_id: uuid.UUID
    merchant_id: uuid.UUID
    merchant_name: str
    merchant_code: str | None = None
    method: str
    amount: Decimal
    currency: str
    destination: str
    destination_code: str | None = None
    # Raw account/phone number — the frontend masks this for display
    # (see apps/web/src/lib/format.ts::maskAccountIdentifier); never masked
    # here, since masking is a presentation concern, not a data-access one.
    destination_identifier: str
    status: str
    requires_approval: bool
    # True if this withdrawal skipped Super Admin approval via the
    # automated eligibility check — see
    # app/services/disbursements.py::_evaluate_auto_withdrawal_eligibility.
    # auto_decision_reason explains why, whichever way the check went
    # (still populated for a withdrawal that fell back to manual review).
    auto_approved: bool = False
    auto_decision_reason: str | None = None
    provider_reference: str | None = None
    # Fee snapshot, so the approval queue can show total charges/reserved/
    # recipient-receives without a second lookup — see
    # app/schemas/withdrawals.py::FeeBreakdown for the full breakdown shape.
    total_charges: Decimal = Decimal(0)
    total_reserved_amount: Decimal | None = None
    recipient_net_amount: Decimal | None = None
    # The merchant's *current* wallet balance (not a snapshot from request
    # time) — lets a Super Admin see at a glance whether this request can
    # actually be covered before approving. See
    # app/services/admin_directory.py::batch_wallet_balances. A merchant
    # with no ledger_accounts row yet (never received a payment) shows 0,
    # not null.
    available_balance: Decimal = Decimal(0)
    pricing_rule_id: uuid.UUID | None = None
    rejection_reason: str | None = None
    admin_status_reason: str | None = None
    created_at: datetime
    # Delivery status of the two emails this withdrawal can trigger — see
    # app/services/email.py::send_withdrawal_request_notification_email /
    # send_withdrawal_success_email. None means that email hasn't been
    # attempted yet (e.g. success_email_status is always None until the
    # withdrawal actually reaches SUCCESS).
    request_email_status: str | None = None
    success_email_status: str | None = None


class AdminTransactionResponse(BaseModel):
    transaction_id: uuid.UUID
    merchant_id: uuid.UUID
    merchant_name: str
    merchant_code: str | None = None
    reference: str
    provider_reference: str | None = None
    type: str
    method: str
    gross_amount: Decimal
    fee_amount: Decimal
    net_amount: Decimal
    currency: str
    status: str
    balance_before: Decimal | None = None
    balance_after: Decimal | None = None
    direction: str | None = None
    created_at: datetime


class AdminWebhookEventResponse(BaseModel):
    """Inbound provider callback log (public.selcom_webhook_events) — not
    the outbound merchant webhook deliveries table (webhook_events), which
    already has its own merchant-scoped list at
    GET /v1/merchants/{merchant_id}/webhooks."""

    webhook_event_id: uuid.UUID
    provider: str
    event_type: str
    reference: str
    processed_at: datetime | None = None
    created_at: datetime
    status: str
    processing_error: str | None = None


class AdminAuditLogResponse(BaseModel):
    audit_id: uuid.UUID
    actor: str | None = None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None = None
    metadata: dict[str, Any]
    ip_address: str | None = None
    created_at: datetime


class AdminInquiryResponse(BaseModel):
    """A "contact us" submission (POST /v1/public/inquiries) — read-only,
    no super-admin action exists on these beyond viewing/replying by
    email directly; see app/routers/public_inquiries.py."""

    id: uuid.UUID
    full_name: str
    business_name: str | None = None
    email: str
    phone: str | None = None
    message: str
    source: str
    created_at: datetime
