"""Request/response schemas for the self-service /v1/merchant/* API surface
(app/routers/merchant_portal.py).

Every *Create schema here is a sibling of an existing one in
app/schemas/{payment_links,invoices,collections,disbursements}.py with
merchant_id removed — /v1/merchant/* never takes merchant_id from the
client at all, it's resolved from the caller's JWT (see
app.auth.get_own_merchant). Response shapes are reused as-is from those
modules wherever nothing about them is merchant_id-specific.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.phone import validate_and_normalize_phone
from app.schemas.enums import (
    LEGACY_ALLOWED_PAYMENT_METHODS_DEFAULT,
    CollectionMethod,
    DestinationCode,
    DisbursementMethod,
    UserRole,
)
from app.schemas.invoices import InvoiceItemCreate
from app.schemas.merchants import MerchantResponse

# --- Overview ---------------------------------------------------------------


class MerchantOverviewResponse(BaseModel):
    merchant: MerchantResponse
    total_collections: Decimal
    available_balance: Decimal
    pending_transactions: int
    successful_withdrawals: int
    active_payment_links: int
    unpaid_invoices: int
    total_fees_charged: Decimal


# --- Wallet -------------------------------------------------------------------


class WalletLedgerEntryResponse(BaseModel):
    id: uuid.UUID
    transaction_id: uuid.UUID | None = None
    date: datetime
    description: str | None = None
    direction: Literal["credit", "debit"]
    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal
    # Joined from the entry's transactions row (see
    # app/services/ledger.py::_wallet_ledger_entries) — null when the entry
    # has no linked transaction, never guessed.
    type: str | None = None
    reference: str | None = None
    provider_reference: str | None = None
    method: str | None = None
    fee_amount: Decimal | None = None
    net_amount: Decimal | None = None
    status: str | None = None


# --- Payment links ------------------------------------------------------------


class MerchantPaymentLinkCreate(BaseModel):
    customer_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0)
    currency: str = "TZS"
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_email: str | None = None
    description: str | None = None
    # No longer collected from the merchant — see PaymentLinkCreate's
    # sibling field docstring in app/schemas/payment_links.py.
    allowed_payment_methods: list[CollectionMethod] = Field(
        default_factory=lambda: list(LEGACY_ALLOWED_PAYMENT_METHODS_DEFAULT)
    )
    expires_at: datetime | None = None
    merchant_reference: str | None = Field(default=None, max_length=100)
    success_redirect_url: str | None = None
    failure_redirect_url: str | None = None
    # "payment_link" (default) for the Payment Links page; "request_collection"
    # for the Request Collection page — same underlying resource and
    # endpoint, this is purely a label for Super Admin's source filter
    # (collections.source, resolved via
    # app/services/collection_source.py) — never trusted for anything
    # security-relevant, only which merchant-portal form the merchant used.
    origin: Literal["payment_link", "request_collection"] = "payment_link"


class MerchantPaymentLinkUpdate(BaseModel):
    """Mirrors PaymentLinkUpdate (schemas/payment_links.py) minus merchant_id
    — same "only an ACTIVE link may be edited" rule, enforced in the router."""

    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_email: str | None = None
    description: str | None = None
    allowed_payment_methods: list[CollectionMethod] | None = None
    expires_at: datetime | None = None
    merchant_reference: str | None = Field(default=None, max_length=100)
    success_redirect_url: str | None = None
    failure_redirect_url: str | None = None


# --- Invoices -----------------------------------------------------------------


class MerchantInvoiceCreate(BaseModel):
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    due_date: date
    currency: str = "TZS"
    tax_amount: Decimal = Field(default=Decimal(0), ge=0)
    discount_amount: Decimal = Field(default=Decimal(0), ge=0)
    notes: str | None = None
    items: list[InvoiceItemCreate] = Field(min_length=1)


# --- Collections ----------------------------------------------------------


class MerchantPushCollectionRequest(BaseModel):
    """USSD_PUSH / STK_PUSH / SELCOM_PESA_PUSH — a phone number is required."""

    amount: Decimal = Field(gt=0)
    currency: str = "TZS"
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str
    merchant_reference: str | None = Field(default=None, max_length=100)
    payment_link_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    description: str | None = None
    callback_url: str | None = None

    @field_validator("customer_phone")
    @classmethod
    def _check_phone(cls, value: str) -> str:
        return validate_and_normalize_phone(value)


class CreateOrderMinimalRequest(BaseModel):
    """POST /v1/merchant/collections/create-order-minimal — Selcom
    Checkout's Create Order - Minimal
    (https://developers.selcommobile.com/#create-order-minimal), Step 1
    for STK/USSD/wallet push, payment-link checkout, and dynamic QR/token
    display. Never itself pulls money.

    order_id is deliberately not a client-supplied field — the service
    generates it server-side (generate_reference("ORD")) so uniqueness is
    guaranteed rather than trusted from the caller; merchant_reference
    below is where the merchant's own tracking value goes instead, same
    role as collections.merchant_reference."""

    payment_link_id: uuid.UUID | None = None
    merchant_reference: str | None = Field(default=None, max_length=100)

    buyer_email: str
    buyer_name: str
    buyer_phone: str
    amount: Decimal = Field(gt=0)
    currency: str = "TZS"
    buyer_remarks: str | None = None
    merchant_remarks: str | None = None
    no_of_items: int = Field(gt=0)

    @field_validator("buyer_phone")
    @classmethod
    def _check_phone(cls, value: str) -> str:
        return validate_and_normalize_phone(value)


class MerchantDynamicQrCollectionRequest(BaseModel):
    """DYNAMIC_QR — scan-based; no phone number needed."""

    amount: Decimal = Field(gt=0)
    currency: str = "TZS"
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    merchant_reference: str | None = Field(default=None, max_length=100)
    payment_link_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    description: str | None = None
    callback_url: str | None = None

    @field_validator("customer_phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        return validate_and_normalize_phone(value) if value is not None else None


class MerchantHostedCheckoutCollectionRequest(BaseModel):
    """"Request Collection" — no channel to pick; Selcom's own hosted
    checkout page shows whichever methods are enabled on the account
    (card confirmed not enabled — no exclusion logic needed here)."""

    amount: Decimal = Field(gt=0)
    currency: str = "TZS"
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    merchant_reference: str | None = Field(default=None, max_length=100)
    invoice_id: uuid.UUID | None = None
    description: str | None = None

    @field_validator("customer_phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        return validate_and_normalize_phone(value) if value is not None else None


# --- Withdrawals (disbursements, user-facing name) -------------------------


class WithdrawalCreate(BaseModel):
    method: DisbursementMethod
    amount: Decimal = Field(gt=0)
    currency: str = "TZS"
    # Which provider the fee/pricing rule lookup and Selcom payout resolve
    # against (see app/services/withdrawals/fee_calculator.py) — required
    # so the fee actually charged always matches what the merchant saw on
    # the /quote call.
    destination_code: DestinationCode
    # A generic recipient display name — optional since the literal spec
    # only names bank_account_name (bank transfers); kept here too so a
    # phone-based withdrawal doesn't lose the name a merchant already typed
    # (the Merchant Portal withdrawal form collects one for every method).
    destination_name: str | None = None
    destination_phone: str | None = None
    # Optional, MOBILE_MONEY-only in practice — Selcom's real requirement
    # here is unverified (see app/services/selcom/withdrawals.py), so this
    # stays unvalidated rather than guessing a required/allowed-values list.
    network: str | None = None
    bank_name: str | None = None
    bank_account_number: str | None = None
    bank_account_name: str | None = None
    description: str | None = None

    @model_validator(mode="after")
    def _validate_destination(self) -> "WithdrawalCreate":
        if self.method == DisbursementMethod.BANK_ACCOUNT:
            if not self.bank_name or not self.bank_account_number:
                raise ValueError("bank_name and bank_account_number are required for BANK_ACCOUNT withdrawals")
        else:
            if not self.destination_phone:
                raise ValueError("destination_phone is required for this withdrawal method")
            self.destination_phone = validate_and_normalize_phone(self.destination_phone)
        return self

    @property
    def destination_identifier(self) -> str:
        return self.bank_account_number if self.method == DisbursementMethod.BANK_ACCOUNT else (self.destination_phone or "")

    @property
    def resolved_destination_name(self) -> str:
        """execute_disbursement() requires a destination_name for every
        method, but the withdrawal request only carries a name for
        BANK_ACCOUNT (bank_account_name) — for phone-based methods the
        phone number itself is the only identifying detail given, so it
        doubles as the display name."""
        if self.method == DisbursementMethod.BANK_ACCOUNT:
            return self.bank_account_name or self.bank_account_number or "Bank withdrawal"
        return self.destination_name or self.destination_phone or "Withdrawal"


# --- Team / Users ------------------------------------------------------------

_EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


class MerchantUserCreate(BaseModel):
    """Inviting a new teammate onto the caller's own merchant. A brand new
    Supabase Auth user is created (invited) for this email — see
    create_my_merchant_user — so full_name is required up front and stored
    on that user's user_metadata.full_name, the same place every other
    person's display name in this codebase is read from (see
    app.services.admin_directory)."""

    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(pattern=_EMAIL_PATTERN)
    role: UserRole

    @field_validator("full_name")
    @classmethod
    def _strip_full_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("full_name cannot be blank")
        return stripped

    @field_validator("role")
    @classmethod
    def _check_merchant_role(cls, value: UserRole) -> UserRole:
        if value == UserRole.SUPER_ADMIN:
            raise ValueError("role must be one of MERCHANT_ADMIN, MERCHANT_STAFF, DEVELOPER")
        return value


class MerchantUserUpdate(BaseModel):
    """Only role/status are editable here — full_name/email live on Supabase
    Auth's own user record, not merchant_users, and changing another
    person's isn't something this endpoint does."""

    role: UserRole | None = None
    status: str | None = Field(default=None, pattern="^(invited|active|suspended)$")

    @field_validator("role")
    @classmethod
    def _check_merchant_role(cls, value: UserRole | None) -> UserRole | None:
        if value == UserRole.SUPER_ADMIN:
            raise ValueError("role must be one of MERCHANT_ADMIN, MERCHANT_STAFF, DEVELOPER")
        return value


class MerchantUserResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    merchant_id: uuid.UUID
    full_name: str | None = None
    email: str | None = None
    role: UserRole
    status: str
    created_at: datetime
    updated_at: datetime


class WithdrawalOtpChallengeResponse(BaseModel):
    """What POST /withdrawals returns now: the withdrawal has NOT been
    created, only a verification challenge. Carries nothing sensitive — no
    code, no hash, and the email only in masked form, so the response is
    safe to render and safe to log."""

    otp_required: bool = True
    challenge_id: uuid.UUID
    masked_email: str
    expires_at: datetime
    resend_cooldown_seconds: int
    max_attempts: int


class WithdrawalOtpVerify(BaseModel):
    # Exactly six digits, enforced here so a malformed code never reaches
    # the comparison or burns an attempt on something that could not have
    # been valid.
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
