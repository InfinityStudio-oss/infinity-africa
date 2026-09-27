"""Withdrawal fee quoting + Super Admin pricing-rule management + the
approval-action request bodies (reject/request-info). Sibling of
app/schemas/disbursements.py — kept separate since these are all new,
pricing-engine-specific shapes rather than extensions of the existing
disbursement request/response models.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.phone import validate_and_normalize_phone
from app.schemas.enums import DestinationCode, DisbursementMethod

# --- Fee quote ---------------------------------------------------------------


class WithdrawalQuoteRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    method: DisbursementMethod
    destination_code: DestinationCode
    destination_identifier: str
    recipient_name: str | None = None

    @model_validator(mode="after")
    def _normalize_phone_destination(self) -> "WithdrawalQuoteRequest":
        # Bank account numbers are never phone-shaped — only normalize for
        # wallet/mobile channels, exactly mirroring WithdrawalCreate's own
        # bank-vs-phone branch (app/schemas/merchant_portal.py).
        if self.method != DisbursementMethod.BANK_ACCOUNT:
            self.destination_identifier = validate_and_normalize_phone(self.destination_identifier)
        return self


class FeeBreakdown(BaseModel):
    withdrawal_amount: Decimal
    processor_charge: Decimal
    infinity_fee: Decimal
    percentage_fee: Decimal
    flat_fee: Decimal
    total_charges: Decimal
    total_reserved_amount: Decimal
    recipient_net_amount: Decimal
    channel: str
    destination_code: str
    pricing_rule_id: uuid.UUID | None = None
    pricing_rule_label: str | None = None
    processor_fee_pass_through: bool = False
    # True when the applied rule is a platform fallback (merchant_pricing_rules
    # row with merchant_id IS NULL) rather than one scoped to this merchant —
    # see app.services.withdrawals.fee_calculator.find_pricing_rule's
    # precedence tiers. False both when a merchant-specific rule applied and
    # when no rule matched at all (pricing_rule_id is None).
    is_platform_fallback: bool = False


# --- Super Admin pricing-rule management ------------------------------------


class PricingRuleCreate(BaseModel):
    channel: DisbursementMethod | None = None
    destination_code: DestinationCode | None = None
    percentage_fee: Decimal = Field(default=Decimal(0), ge=0, le=100)
    flat_fee: Decimal = Field(default=Decimal(0), ge=0)
    minimum_fee: Decimal | None = Field(default=None, ge=0)
    maximum_fee: Decimal | None = Field(default=None, ge=0)
    processor_fee_flat: Decimal = Field(default=Decimal(0), ge=0)
    processor_fee_pass_through: bool = False
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    is_active: bool = True
    label: str | None = None

    @model_validator(mode="after")
    def _check_fee_range(self) -> "PricingRuleCreate":
        if self.minimum_fee is not None and self.maximum_fee is not None and self.maximum_fee < self.minimum_fee:
            raise ValueError("maximum_fee must be greater than or equal to minimum_fee")
        if self.effective_to is not None and self.effective_from is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        return self


class PricingRuleUpdate(BaseModel):
    """Every field optional — only what's set is applied (model_dump(exclude_unset=True))."""

    channel: DisbursementMethod | None = None
    destination_code: DestinationCode | None = None
    percentage_fee: Decimal | None = Field(default=None, ge=0, le=100)
    flat_fee: Decimal | None = Field(default=None, ge=0)
    minimum_fee: Decimal | None = Field(default=None, ge=0)
    maximum_fee: Decimal | None = Field(default=None, ge=0)
    processor_fee_flat: Decimal | None = Field(default=None, ge=0)
    processor_fee_pass_through: bool | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    is_active: bool | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _check_fee_range(self) -> "PricingRuleUpdate":
        if self.minimum_fee is not None and self.maximum_fee is not None and self.maximum_fee < self.minimum_fee:
            raise ValueError("maximum_fee must be greater than or equal to minimum_fee")
        if self.effective_to is not None and self.effective_from is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        return self


class PricingRuleResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID | None = None
    channel: str | None = None
    destination_code: str | None = None
    percentage_fee: Decimal
    flat_fee: Decimal
    minimum_fee: Decimal | None = None
    maximum_fee: Decimal | None = None
    processor_fee_flat: Decimal
    processor_fee_pass_through: bool
    effective_from: datetime
    effective_to: datetime | None = None
    is_active: bool
    label: str | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


# --- Super Admin withdrawal review actions ----------------------------------


class WithdrawalRejectRequest(BaseModel):
    rejection_reason: str = Field(min_length=1)


class WithdrawalRequestInfoRequest(BaseModel):
    message: str = Field(min_length=1)
    requested_documents: list[str] = Field(default_factory=list)

    @field_validator("requested_documents")
    @classmethod
    def _no_blank_entries(cls, value: list[str]) -> list[str]:
        return [item for item in value if item.strip()]


class RecipientLookupRequest(BaseModel):
    """Asks who owns a withdrawal destination, for the review step."""

    method: DisbursementMethod
    destination_code: DestinationCode
    destination_identifier: str

    @model_validator(mode="after")
    def _normalize_phone_destination(self) -> "RecipientLookupRequest":
        if self.method != DisbursementMethod.BANK_ACCOUNT:
            self.destination_identifier = validate_and_normalize_phone(self.destination_identifier)
        return self


class RecipientLookupResponse(BaseModel):
    # None whenever the name could not be established — an unsupported
    # channel, an account that does not exist, or a provider that did not
    # answer. The merchant is shown "Name not available" for all of them,
    # and a name is never invented to fill the gap.
    recipient_name: str | None = None
