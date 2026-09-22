"""Self-service merchant onboarding — /v1/onboarding/*.

No merchant_id anywhere in these routes: /merchant-account creates one from
the caller's own verified JWT identity (app.auth.get_current_user);
/documents and /status resolve it the same way the merchant-portal routes
do (app.auth.get_own_merchant / get_current_user + a null-safe lookup).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.auth import get_current_user, get_own_merchant
from app.core.errors import ValidationAPIError
from app.core.rate_limit import rate_limit
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedUser, MerchantMembership
from app.schemas.common import APIResponse
from app.schemas.enums import AccountStatus, DocumentType, ServiceNeeded
from app.schemas.merchants import MerchantResponse
from app.schemas.onboarding import (
    OnboardingDocumentResponse,
    OnboardingMerchantAccountCreate,
    OnboardingMerchantAccountResponse,
    OnboardingSignupCreate,
    OnboardingSignupResponse,
    OnboardingStatusResponse,
)
from app.services.onboarding import (
    create_merchant_onboarding,
    get_onboarding_status,
    register_onboarding_document,
    signup_merchant,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post(
    "/signup",
    response_model=APIResponse[OnboardingSignupResponse],
    status_code=status.HTTP_201_CREATED,
)
async def merchant_signup(
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="merchant_signup", limit=5, window_seconds=300))
    ],
    full_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    business_name: Annotated[str, Form()],
    nature_of_business: Annotated[str, Form()],
    business_category: Annotated[str, Form()],
    physical_address: Annotated[str, Form()],
    region_city: Annotated[str, Form()],
    contact_phone: Annotated[str, Form()],
    nida_number: Annotated[str, Form()],
    services_needed: Annotated[list[ServiceNeeded], Form()],
    accepted_terms: Annotated[bool, Form()],
    accepted_privacy: Annotated[bool, Form()],
    website_url: Annotated[str | None, Form()] = None,
    tin_number: Annotated[str | None, Form()] = None,
    legal_business_name: Annotated[str | None, Form()] = None,
    business_email: Annotated[str | None, Form()] = None,
    business_phone: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    tin_certificate: Annotated[UploadFile | None, File()] = None,
):
    """Combined signup: account credentials + business details (+ an
    optional TIN certificate file) in one `multipart/form-data` call.
    Unauthenticated — the backend creates the Supabase Auth user itself
    (service_role) so the frontend never touches Supabase Auth for this
    flow. The merchant is created PENDING_VERIFICATION; it is NOT
    auto-approved and no welcome/approval email is sent here (that only
    happens on Super Admin approval). NIDA is mandatory — a missing value
    returns `nida_required`, a malformed one `nida_invalid`."""
    try:
        payload = OnboardingSignupCreate(
            full_name=full_name,
            email=email,
            password=password,
            business_name=business_name,
            nature_of_business=nature_of_business,
            business_category=business_category,
            physical_address=physical_address,
            region_city=region_city,
            contact_phone=contact_phone,
            nida_number=nida_number,
            website_url=website_url or None,
            tin_number=tin_number or None,
            legal_business_name=legal_business_name or None,
            business_email=business_email or None,
            business_phone=business_phone or None,
            notes=notes or None,
            services_needed=services_needed,
            accepted_terms=accepted_terms,
            accepted_privacy=accepted_privacy,
        )
    except ValidationError as exc:
        raise ValidationAPIError("Invalid request", details=jsonable_encoder(exc.errors())) from exc

    client = get_supabase_admin()
    result = await signup_merchant(client, payload=payload, tin_certificate=tin_certificate)
    merchant = result["merchant"]
    return APIResponse(
        data=OnboardingSignupResponse(
            merchant_id=merchant["id"],
            merchant_code=merchant.get("merchant_code"),
            account_status=AccountStatus.PENDING_VERIFICATION,
            email_confirmation_required=result["email_confirmation_required"],
        )
    )


@router.post(
    "/merchant-account",
    response_model=APIResponse[OnboardingMerchantAccountResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_merchant_account(
    payload: OnboardingMerchantAccountCreate,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="merchant_onboarding_submit", limit=5, window_seconds=60))],
):
    client = get_supabase_admin()
    merchant = create_merchant_onboarding(client, user=user, payload=payload)
    return APIResponse(
        data=OnboardingMerchantAccountResponse(
            merchant=MerchantResponse(**merchant), account_status=AccountStatus.PENDING_VERIFICATION
        )
    )


@router.post("/documents", response_model=APIResponse[OnboardingDocumentResponse])
async def upload_document(
    membership: Annotated[MerchantMembership, Depends(get_own_merchant)],
    document_type: Annotated[DocumentType, Form()],
    file: Annotated[UploadFile, File()],
):
    client = get_supabase_admin()
    document = await register_onboarding_document(
        client,
        merchant_id=membership.merchant_id,
        document_type=document_type,
        file=file,
        uploaded_by=membership.user_id,
    )
    return APIResponse(data=OnboardingDocumentResponse(**document))


@router.get("/status", response_model=APIResponse[OnboardingStatusResponse])
def read_onboarding_status(user: Annotated[AuthenticatedUser, Depends(get_current_user)]):
    client = get_supabase_admin()
    result = get_onboarding_status(client, user=user)
    return APIResponse(data=OnboardingStatusResponse(**result))
