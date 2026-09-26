"""Super-admin onboarding review — /v1/admin/onboarding/*.

Not in the original self-service endpoint list, but required for the
Super Admin "Onboarding Requests" page (View/Approve/Reject/Request More
Info) to act on real data instead of the retired mock store.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends
from supabase import Client

from app.auth import require_super_admin
from app.core.errors import NotFoundError
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse
from app.schemas.onboarding import OnboardingReviewAction, OnboardingSubmissionResponse
from app.schemas.withdrawals import PricingRuleCreate
from app.services.crud import execute_maybe_single, get_by_id
from app.services.onboarding import (
    approve_onboarding_submission,
    get_onboarding_submission,
    list_onboarding_submissions,
    reject_onboarding_submission,
    request_more_info_onboarding_submission,
)
from app.services.security_alerts import notify_security_event

router = APIRouter(prefix="/admin/onboarding", tags=["admin-onboarding"])

# Optional and defaulted to None so existing bodyless approve calls (the
# Merchants dashboard's PATCH .../approve sends no body at all) keep working
# unchanged — only a Super Admin UI that wants to assign custom pricing
# during approval needs to send this.
_PricingBody = Annotated[PricingRuleCreate | None, Body()]


def _resolve_submission_id(client: Client, id: uuid.UUID) -> uuid.UUID:
    """The Merchants dashboard only knows a merchant_id, not a submission_id
    — but onboarding_submissions.merchant_id is UNIQUE (1:1), so `id` is
    accepted as either. Tries it as a submission id first (the primary key),
    falling back to treating it as a merchant_id."""
    if get_by_id(client, "onboarding_submissions", id):
        return id

    row = execute_maybe_single(
        client.table("onboarding_submissions").select("id").eq("merchant_id", str(id)).maybe_single()
    )
    if not row:
        raise NotFoundError("Onboarding submission not found")
    return uuid.UUID(row["id"])


@router.get("", response_model=APIResponse[list[OnboardingSubmissionResponse]])
def list_submissions(_admin: Annotated[AuthenticatedUser, Depends(require_super_admin)]):
    client = get_supabase_admin()
    rows = list_onboarding_submissions(client)
    return APIResponse(data=[OnboardingSubmissionResponse(**row) for row in rows])


@router.get("/{id}", response_model=APIResponse[OnboardingSubmissionResponse])
def get_submission(id: uuid.UUID, _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)]):
    """`id` may be either a submission_id or a merchant_id — same
    resolution as the PATCH .../approve|reject|request-more-info routes
    below, so the merchant detail page can look up KYC documents knowing
    only the merchant_id."""
    client = get_supabase_admin()
    submission_id = _resolve_submission_id(client, id)
    row = get_onboarding_submission(client, submission_id)
    return APIResponse(data=OnboardingSubmissionResponse(**row))


def _alert_onboarding(client, *, admin, row: dict, title: str, event: str, extra=None) -> None:
    """Admitting a business to the platform, or refusing one. The audit
    entry is written inside the onboarding service; this is the
    notification. Applied to both the POST and PATCH forms of each action —
    they are aliases of the same decision, and an alert that fired for only
    one of them would be worse than none, because it would look complete."""
    merchant_id = row.get("merchant_id")
    merchant = get_by_id(client, "merchants", uuid.UUID(merchant_id)) if merchant_id else None
    notify_security_event(
        client,
        event=event,
        title=title,
        actor_email=admin.email,
        actor_id=admin.id,
        merchant_name=(merchant or {}).get("business_name"),
        extra=extra,
    )


@router.post("/{submission_id}/approve", response_model=APIResponse[OnboardingSubmissionResponse])
def approve(
    submission_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pricing: _PricingBody = None,
):
    client = get_supabase_admin()
    row = approve_onboarding_submission(client, submission_id=submission_id, reviewer_id=admin.id, pricing=pricing)

    _alert_onboarding(
        client, admin=admin, row=row, title="Business approved", event="super_admin.merchant.approved"
    )

    return APIResponse(data=OnboardingSubmissionResponse(**row))


@router.post("/{submission_id}/reject", response_model=APIResponse[OnboardingSubmissionResponse])
def reject(
    submission_id: uuid.UUID,
    payload: OnboardingReviewAction,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    row = reject_onboarding_submission(
        client, submission_id=submission_id, reviewer_id=admin.id, note=payload.review_note
    )

    _alert_onboarding(
        client,
        admin=admin,
        row=row,
        title="Business rejected",
        event="super_admin.merchant.rejected",
        extra={"Reason": payload.review_note} if payload.review_note else None,
    )

    return APIResponse(data=OnboardingSubmissionResponse(**row))


@router.post("/{submission_id}/request-more-info", response_model=APIResponse[OnboardingSubmissionResponse])
def request_more_info(
    submission_id: uuid.UUID,
    payload: OnboardingReviewAction,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    row = request_more_info_onboarding_submission(
        client, submission_id=submission_id, reviewer_id=admin.id, note=payload.review_note
    )
    return APIResponse(data=OnboardingSubmissionResponse(**row))


# --- PATCH variants, id = submission_id OR merchant_id -----------------------
# Additional routes (same paths as the POST ones above, different method) for
# callers that only know a merchant_id — the Merchants dashboard, notably.


@router.patch("/{id}/approve", response_model=APIResponse[OnboardingSubmissionResponse])
def approve_by_id(
    id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pricing: _PricingBody = None,
):
    client = get_supabase_admin()
    submission_id = _resolve_submission_id(client, id)
    row = approve_onboarding_submission(client, submission_id=submission_id, reviewer_id=admin.id, pricing=pricing)

    _alert_onboarding(
        client, admin=admin, row=row, title="Business approved", event="super_admin.merchant.approved"
    )

    return APIResponse(data=OnboardingSubmissionResponse(**row))


@router.patch("/{id}/reject", response_model=APIResponse[OnboardingSubmissionResponse])
def reject_by_id(
    id: uuid.UUID,
    payload: OnboardingReviewAction,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    submission_id = _resolve_submission_id(client, id)
    row = reject_onboarding_submission(
        client, submission_id=submission_id, reviewer_id=admin.id, note=payload.review_note
    )

    _alert_onboarding(
        client,
        admin=admin,
        row=row,
        title="Business rejected",
        event="super_admin.merchant.rejected",
        extra={"Reason": payload.review_note} if payload.review_note else None,
    )

    return APIResponse(data=OnboardingSubmissionResponse(**row))


@router.patch("/{id}/request-more-info", response_model=APIResponse[OnboardingSubmissionResponse])
def request_more_info_by_id(
    id: uuid.UUID,
    payload: OnboardingReviewAction,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    submission_id = _resolve_submission_id(client, id)
    row = request_more_info_onboarding_submission(
        client, submission_id=submission_id, reviewer_id=admin.id, note=payload.review_note
    )
    return APIResponse(data=OnboardingSubmissionResponse(**row))
