import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.phone import validate_and_normalize_phone
from app.schemas.enums import (
    AccountStatus,
    DocumentType,
    DocumentUploadStatus,
    ServiceNeeded,
)
from app.schemas.merchants import MerchantResponse

# Same convention as app/schemas/auth.py's _EMAIL_PATTERN — no pydantic
# EmailStr, which needs the email-validator package this codebase avoids.
_EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


class OnboardingMerchantAccountCreate(BaseModel):
    """No merchant_id, no contact_email — the caller's identity comes from
    their verified JWT (app.auth.get_current_user), never the request body.

    `nida_number` is a plain str here (not format-validated at the schema
    layer) so the service can raise the dedicated `nida_required` /
    `nida_invalid` error codes the frontend keys off — see
    app/core/nida.py and app/services/onboarding.py.

    legal_business_name/business_email/business_phone/notes are all
    optional here (not just at the Get Started form's UI layer) so the
    older two-step /onboarding form — which doesn't collect them — keeps
    working unchanged; app/services/onboarding.py falls back to the
    account owner's own email/phone when business_email/business_phone
    are blank."""

    business_name: str
    nature_of_business: str
    business_category: str
    # No longer collected on the Get Started form (business address and
    # region were dropped from signup). Still non-null columns in
    # onboarding_submissions, so they default to "" rather than None —
    # an empty string satisfies the NOT NULL constraint without needing a
    # migration, and the older two-step /onboarding form still sends real
    # values.
    physical_address: str = ""
    region_city: str = ""
    website_url: str | None = None
    contact_phone: str
    nida_number: str = ""
    tin_number: str | None = None
    expected_monthly_volume: str | None = None
    legal_business_name: str | None = None
    business_email: str | None = None
    business_phone: str | None = None
    notes: str | None = None
    # Was min_length=1 while the Get Started form asked which services a
    # merchant wanted; that section was removed, so an empty list is now
    # valid. The column is `not null default '{}'`, so this needs no
    # migration either.
    services_needed: list[ServiceNeeded] = Field(default_factory=list)
    accepted_terms: bool
    accepted_privacy: bool

    @field_validator("contact_phone")
    @classmethod
    def _check_phone(cls, value: str) -> str:
        return validate_and_normalize_phone(value)

    @field_validator("business_phone")
    @classmethod
    def _check_business_phone(cls, value: str | None) -> str | None:
        return validate_and_normalize_phone(value) if value else None

    @field_validator("business_email")
    @classmethod
    def _check_business_email(cls, value: str | None) -> str | None:
        if not value:
            return None
        if not re.match(_EMAIL_PATTERN, value):
            raise ValueError("Enter a valid business email address")
        return value


class OnboardingSignupCreate(OnboardingMerchantAccountCreate):
    """The single combined signup page — account credentials AND business
    details in one request (POST /v1/onboarding/signup, unauthenticated).

    The backend creates the Supabase Auth user itself (service_role,
    app/services/onboarding.py::signup_merchant) — the frontend never
    calls Supabase directly for this flow and never supplies a
    merchant_id or an account status."""

    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(pattern=_EMAIL_PATTERN, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class OnboardingMerchantAccountResponse(BaseModel):
    merchant: MerchantResponse
    account_status: AccountStatus
    next_path: str = "/dashboard/overview"


class OnboardingSignupResponse(BaseModel):
    """Response to POST /v1/onboarding/signup. Deliberately minimal — no
    session, no tokens: the merchant must verify their email (if required)
    and then wait for Super Admin approval before logging in."""

    merchant_id: uuid.UUID
    merchant_code: str | None = None
    account_status: AccountStatus = AccountStatus.PENDING_VERIFICATION
    email_confirmation_required: bool = True


class OnboardingStatusResponse(BaseModel):
    has_account: bool
    onboarding_completed: bool
    merchant_id: uuid.UUID | None = None
    account_status: AccountStatus | None = None
    next_path: str


class OnboardingDocumentResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    document_type: DocumentType
    original_filename: str
    mime_type: str
    size_bytes: int
    upload_status: DocumentUploadStatus
    uploaded_at: datetime
    signed_url: str | None = None


class OnboardingSubmissionResponse(BaseModel):
    """Super-admin list/detail view — joins the merchant's own profile
    fields onto its onboarding_submissions row."""

    id: uuid.UUID
    merchant_id: uuid.UUID
    merchant_code: str | None = None
    business_name: str
    # legal_name lives on merchants (not this submission's own table) —
    # the registered/legal business name if different from the
    # trading/display business_name above. Optional; most merchants leave
    # it blank.
    legal_name: str | None = None
    owner_email: str
    contact_phone: str | None = None
    nature_of_business: str
    business_category: str
    physical_address: str
    region_city: str
    website_url: str | None = None
    # Optional free-text notes/description from the signup form —
    # distinct from nature_of_business (required, a business-type
    # description) above.
    notes: str | None = None
    # Masked — last 4 digits only (e.g. "1234"). The full NIDA number is
    # never returned by the API, only this. None for pre-NIDA submissions.
    nida_last4: str | None = None
    tin_number: str | None = None
    expected_monthly_volume: str | None = None
    services_needed: list[ServiceNeeded]
    review_status: AccountStatus
    review_note: str | None = None
    document_status: DocumentUploadStatus
    submitted_at: datetime
    updated_at: datetime
    documents: list[OnboardingDocumentResponse] = Field(default_factory=list)
    # Set only in the response to an approve action, and only when the
    # merchant's welcome email couldn't be sent because contact_email is
    # missing — see app/services/onboarding.py::approve_onboarding_submission.
    # None on every ordinary GET; never persisted.
    welcome_email_warning: str | None = None


class OnboardingReviewAction(BaseModel):
    review_note: str | None = None
