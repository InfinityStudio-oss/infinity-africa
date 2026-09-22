import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.core.phone import validate_and_normalize_phone
from app.schemas.enums import DestinationCode


class DisbursementInitiateBase(BaseModel):
    """Shared fields across all three /v1/disbursements/{method} endpoints.
    `method` itself isn't a field here — it's implied by which endpoint is
    called, so there's no way to send a method that doesn't match the URL."""

    merchant_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    currency: str = "TZS"
    destination_name: str
    destination_code: DestinationCode


class PhoneDisbursementRequest(DisbursementInitiateBase):
    """SELCOM_PESA / MOBILE_MONEY — paid out to a phone number."""

    destination_identifier: str

    @field_validator("destination_identifier")
    @classmethod
    def _check_phone(cls, value: str) -> str:
        return validate_and_normalize_phone(value)


class BankAccountDisbursementRequest(DisbursementInitiateBase):
    """BANK_ACCOUNT — destination_identifier is the bank account number."""

    destination_identifier: str
    bank_name: str


class DisbursementResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    settlement_account_id: uuid.UUID | None = None
    method: str
    amount: Decimal
    currency: str
    destination_name: str
    destination_identifier: str
    destination_code: str | None = None
    bank_name: str | None = None
    status: str
    requires_approval: bool
    # True if this withdrawal skipped Super Admin approval via the
    # automated eligibility check (Settings.auto_withdrawals_enabled) —
    # approved_by/approved_at stay null in that case, since no human
    # approved it. auto_decision_reason explains why the eligibility
    # check did or did not auto-process this one, whichever way it went.
    auto_approved: bool = False
    auto_decision_reason: str | None = None
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    rejected_by: uuid.UUID | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    admin_status_reason: str | None = None
    provider_reference: str | None = None
    selcom_trans_id: str | None = None
    selcom_receipt: str | None = None
    selcom_status: str | None = None
    # Full raw Selcom Business API response body from the last
    # transaction/process or transaction/query call — see
    # app.services.selcom_business.parsing. The column itself is nullable
    # (supabase/migrations/20260820090002_disbursements_selcom_raw_response.sql)
    # and Postgres/PostgREST returns an explicit `null`, not an absent key,
    # for every row until a real (non-mock) provider call resolves this
    # withdrawal — must allow None, not just default to {} for a missing
    # key (a real production 500 on every GET/POST .../withdrawals until
    # fixed, see docs/withdrawal-pricing-and-approval.md).
    selcom_raw_response: dict | None = None
    # Fee snapshot — calculated once at request time and frozen here; a
    # later merchant_pricing_rules edit never changes an already-submitted
    # withdrawal. See app/services/withdrawals/fee_calculator.py.
    processor_charge: Decimal = Decimal(0)
    infinity_fee: Decimal = Decimal(0)
    percentage_fee_component: Decimal = Decimal(0)
    flat_fee_component: Decimal = Decimal(0)
    total_charges: Decimal = Decimal(0)
    total_reserved_amount: Decimal | None = None
    recipient_net_amount: Decimal | None = None
    pricing_rule_id: uuid.UUID | None = None
    pricing_snapshot_json: dict = Field(default_factory=dict)
    # Response-only enrichment stamped on by services/disbursements.py once
    # a transaction exists — null while a withdrawal still sits pending
    # approval, since nothing's been reserved yet.
    transaction_reference: str | None = None
    fee_amount: Decimal | None = None
    net_amount: Decimal | None = None
    initiated_at: datetime
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
