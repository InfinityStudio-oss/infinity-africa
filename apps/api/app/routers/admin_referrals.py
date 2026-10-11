"""Super Admin review of merchant referrals and their commissions.

Every route here is super-admin only and every state change is audit
logged inside the service it calls. Nothing in this router moves money:
approving a commission marks it payable, and marking one paid records a
payout that was made through the normal disbursement process. There is no
automated referral payout, deliberately — a human confirming a referral
was genuine is the control the whole design rests on.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth import require_super_admin
from app.core.pagination import PaginationParams, build_page_meta, pagination_params
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse
from app.schemas.referrals import (
    AdminReferralCommissionResponse,
    AdminReferralResponse,
    CommissionPaidRequest,
    CommissionRejectRequest,
    FraudHoldRequest,
    ReferralCodeStatusRequest,
)
from app.services.admin_referrals import (
    list_admin_referrals,
    referral_programme_summary,
)
from app.services.referral_commissions import (
    approve_commission,
    calculate_referral_commission,
    mark_commission_paid,
    recalculate_open_referrals,
    reject_commission,
)
from app.services.referrals import set_fraud_hold, set_referral_code_status

router = APIRouter(prefix="/admin/referrals", tags=["admin-referrals"])


@router.get("", response_model=APIResponse[list[AdminReferralResponse]])
def list_referrals_route(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    status: Annotated[str | None, Query()] = None,
    referrer_merchant_id: Annotated[uuid.UUID | None, Query()] = None,
):
    client = get_supabase_admin()
    rows, total = list_admin_referrals(
        client, status=status, referrer_merchant_id=referrer_merchant_id, pagination=pagination
    )
    return APIResponse(
        data=[AdminReferralResponse(**row) for row in rows], meta=build_page_meta(pagination, total)
    )


@router.get("/summary")
def referral_summary_route(_admin: Annotated[AuthenticatedUser, Depends(require_super_admin)]):
    """Counts across every referral, not the page the browser received."""
    return APIResponse(data=referral_programme_summary(get_supabase_admin()))


@router.post("/recalculate")
def recalculate_route(_admin: Annotated[AuthenticatedUser, Depends(require_super_admin)]):
    """Revalues every open referral now, instead of waiting for the sweep.

    Idempotent: it updates the one commission row each referral has, so
    running it twice cannot create a second payable record.
    """
    return APIResponse(data=recalculate_open_referrals(get_supabase_admin()))


@router.post("/{referral_id}/recalculate", response_model=APIResponse[AdminReferralCommissionResponse | None])
def recalculate_one_route(
    referral_id: uuid.UUID,
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    from app.core.errors import NotFoundError
    from app.services.crud import get_by_id

    client = get_supabase_admin()
    referral = get_by_id(client, "merchant_referrals", referral_id)
    if not referral:
        raise NotFoundError("Referral not found")
    commission = calculate_referral_commission(client, referral=referral)
    return APIResponse(
        data=AdminReferralCommissionResponse(**commission) if commission else None
    )


@router.post("/{referral_id}/fraud-hold", response_model=APIResponse[AdminReferralResponse])
def place_fraud_hold_route(
    referral_id: uuid.UUID,
    payload: FraudHoldRequest,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Freezes a referral. It stops accruing and cannot be approved."""
    client = get_supabase_admin()
    set_fraud_hold(client, referral_id=referral_id, on=True, reason=payload.reason, actor_id=admin.id)
    rows, _ = list_admin_referrals(client, referral_id=referral_id)
    return APIResponse(data=AdminReferralResponse(**rows[0]))


@router.delete("/{referral_id}/fraud-hold", response_model=APIResponse[AdminReferralResponse])
def clear_fraud_hold_route(
    referral_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    set_fraud_hold(client, referral_id=referral_id, on=False, reason=None, actor_id=admin.id)
    rows, _ = list_admin_referrals(client, referral_id=referral_id)
    return APIResponse(data=AdminReferralResponse(**rows[0]))


@router.post(
    "/commissions/{commission_id}/approve",
    response_model=APIResponse[AdminReferralCommissionResponse],
)
def approve_commission_route(
    commission_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Marks a commission payable. Moves no money."""
    commission = approve_commission(get_supabase_admin(), commission_id=commission_id, admin_id=admin.id)
    return APIResponse(data=AdminReferralCommissionResponse(**commission))


@router.post(
    "/commissions/{commission_id}/reject",
    response_model=APIResponse[AdminReferralCommissionResponse],
)
def reject_commission_route(
    commission_id: uuid.UUID,
    payload: CommissionRejectRequest,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    commission = reject_commission(
        get_supabase_admin(), commission_id=commission_id, admin_id=admin.id, reason=payload.reason
    )
    return APIResponse(data=AdminReferralCommissionResponse(**commission))


@router.post(
    "/commissions/{commission_id}/paid",
    response_model=APIResponse[AdminReferralCommissionResponse],
)
def mark_paid_route(
    commission_id: uuid.UUID,
    payload: CommissionPaidRequest,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Records that an approved commission was paid elsewhere. This
    endpoint does not pay it."""
    commission = mark_commission_paid(
        get_supabase_admin(), commission_id=commission_id, admin_id=admin.id, note=payload.note
    )
    return APIResponse(data=AdminReferralCommissionResponse(**commission))


@router.patch("/merchants/{merchant_id}/code")
def set_code_status_route(
    merchant_id: uuid.UUID,
    payload: ReferralCodeStatusRequest,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Enables or disables one merchant's referral code.

    Disabling stops the code working at signup; referrals already captured
    under it keep their own status and are judged on their own merits.
    """
    merchant = set_referral_code_status(
        get_supabase_admin(),
        merchant_id=merchant_id,
        status=payload.status,
        actor_id=admin.id,
        reason=payload.reason,
    )
    return APIResponse(
        data={
            "merchant_id": str(merchant_id),
            "referral_code": merchant.get("referral_code"),
            "referral_code_status": merchant.get("referral_code_status"),
        }
    )
