"""Super Admin withdrawal review — approve/reject/request-info/refresh-status
plus a batch reconcile action. Own file, not admin.py (which stays a
read-only platform-wide dashboard) or disbursements.py (merchant/API-key-
facing create/list/get only) — matching the one-file-per-review-workflow
convention already used by admin_onboarding.py/admin_disputes.py/admin_risk.py.

Selcom is only ever called from approve_disbursement (via
_reserve_and_run_disbursement_provider) — every route here is
`require_super_admin`-gated, and nothing a merchant does can reach any of
these paths. See app/services/disbursements.py for the state machine.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth import require_super_admin
from app.config import get_settings
from app.core.rate_limit import rate_limit
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse
from app.schemas.disbursements import DisbursementResponse
from app.schemas.withdrawals import (
    WithdrawalRejectRequest,
    WithdrawalRequestInfoRequest,
)
from app.services.audit import write_audit_log
from app.services.crud import get_by_id
from app.services.disbursements import (
    approve_disbursement,
    reconcile_pending_disbursements,
    refresh_disbursement_status,
    reject_disbursement,
    request_more_info,
    retry_disbursement_payout,
)
from app.services.security_alerts import notify_security_event
from app.services.selcom_business.client import get_selcom_business_client
from app.services.selcom_business.parsing import parse_float_balance

logger = logging.getLogger("infinity.admin.withdrawals")

router = APIRouter(prefix="/admin/withdrawals", tags=["admin-withdrawals"])


def _alert_withdrawal(client, *, admin, disbursement: dict, title: str, event: str, extra=None) -> None:
    """Money moved, or was refused. Never deduplicated: each approval is a
    separate decision about real funds, so every one gets its own email."""
    merchant = get_by_id(client, "merchants", uuid.UUID(disbursement["merchant_id"]))
    notify_security_event(
        client,
        event=event,
        title=title,
        actor_email=admin.email,
        actor_id=admin.id,
        merchant_name=(merchant or {}).get("business_name"),
        amount=disbursement.get("amount"),
        currency=disbursement.get("currency") or "TZS",
        destination=disbursement.get("destination_identifier"),
        extra=extra,
    )


@router.post("/{disbursement_id}/approve", response_model=APIResponse[DisbursementResponse])
async def approve_withdrawal(
    disbursement_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="withdrawal_approval", limit=60, window_seconds=60))],
):
    client = get_supabase_admin()
    disbursement = await approve_disbursement(client, disbursement_id=disbursement_id, approver_id=admin.id)

    write_audit_log(
        client,
        actor_id=admin.id,
        merchant_id=uuid.UUID(disbursement["merchant_id"]),
        action="disbursement.approved",
        resource_type="disbursement",
        resource_id=disbursement_id,
    )

    _alert_withdrawal(
        client,
        admin=admin,
        disbursement=disbursement,
        title="Withdrawal approved",
        event="super_admin.withdrawal.approved",
        extra={"Status": disbursement.get("status")},
    )

    return APIResponse(data=DisbursementResponse(**disbursement))


@router.post("/{disbursement_id}/reject", response_model=APIResponse[DisbursementResponse])
def reject_withdrawal(
    disbursement_id: uuid.UUID,
    payload: WithdrawalRejectRequest,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="withdrawal_approval", limit=60, window_seconds=60))],
):
    client = get_supabase_admin()
    disbursement = reject_disbursement(
        client,
        disbursement_id=disbursement_id,
        approver_id=admin.id,
        rejection_reason=payload.rejection_reason,
    )

    write_audit_log(
        client,
        actor_id=admin.id,
        merchant_id=uuid.UUID(disbursement["merchant_id"]),
        action="disbursement.rejected",
        resource_type="disbursement",
        resource_id=disbursement_id,
        metadata={"rejection_reason": payload.rejection_reason},
    )

    _alert_withdrawal(
        client,
        admin=admin,
        disbursement=disbursement,
        title="Withdrawal rejected",
        event="super_admin.withdrawal.rejected",
        extra={"Reason": payload.rejection_reason},
    )

    return APIResponse(data=DisbursementResponse(**disbursement))


@router.post("/{disbursement_id}/request-info", response_model=APIResponse[DisbursementResponse])
def request_withdrawal_info(
    disbursement_id: uuid.UUID,
    payload: WithdrawalRequestInfoRequest,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    disbursement = request_more_info(
        client,
        disbursement_id=disbursement_id,
        admin_id=admin.id,
        message=payload.message,
        requested_documents=payload.requested_documents,
    )

    write_audit_log(
        client,
        actor_id=admin.id,
        merchant_id=uuid.UUID(disbursement["merchant_id"]),
        action="disbursement.info_requested",
        resource_type="disbursement",
        resource_id=disbursement_id,
        metadata={"message": payload.message, "requested_documents": payload.requested_documents},
    )

    return APIResponse(data=DisbursementResponse(**disbursement))


@router.post("/{disbursement_id}/refresh-status", response_model=APIResponse[DisbursementResponse])
async def refresh_withdrawal_status(
    disbursement_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    disbursement = await refresh_disbursement_status(client, disbursement_id=disbursement_id)

    write_audit_log(
        client,
        actor_id=admin.id,
        merchant_id=uuid.UUID(disbursement["merchant_id"]),
        action="disbursement.status_refreshed",
        resource_type="disbursement",
        resource_id=disbursement_id,
        metadata={"status": disbursement["status"]},
    )

    return APIResponse(data=DisbursementResponse(**disbursement))


@router.post("/{disbursement_id}/retry", response_model=APIResponse[DisbursementResponse])
async def retry_withdrawal_payout(
    disbursement_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Re-attempt a payout that failed for a reason since fixed — most
    often an empty Selcom disbursement float.

    The service refuses unless it can prove the first attempt did not pay
    out, so this cannot be used to pay a merchant twice. retry_payout is
    audited separately from the original approval, with the old status and
    reason preserved.
    """
    client = get_supabase_admin()
    disbursement = await retry_disbursement_payout(
        client, disbursement_id=disbursement_id, approver_id=admin.id
    )

    write_audit_log(
        client,
        actor_id=admin.id,
        merchant_id=uuid.UUID(disbursement["merchant_id"]),
        action="disbursement.retry_requested",
        resource_type="disbursement",
        resource_id=disbursement_id,
        metadata={"status": disbursement["status"]},
    )

    return APIResponse(data=DisbursementResponse(**disbursement))


@router.get("/float-balance", response_model=APIResponse[dict])
async def read_disbursement_float_balance(
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """The platform's own Selcom disbursement float.

    This is the number that decides whether an approval can actually pay
    out: an empty float rejects the call with HTTP 400 and the withdrawal
    fails, which is invisible until it happens. Showing it next to the
    approve button turns that into something an operator can see first.

    Never raises for the caller. A provider outage or an unrecognised
    response shape returns `available: null` and the UI says the balance
    is unavailable, rather than blocking the withdrawals page or — worse —
    showing a number we are not sure of.
    """
    settings = get_settings()
    account_number = settings.selcom_business_account_number
    if not account_number:
        return APIResponse(data={"available": None, "currency": "TZS", "reason": "not_configured"})

    try:
        response = await get_selcom_business_client().balance(account_number=account_number)
    except Exception:  # Provider down, misconfigured, or timing out.
        logger.warning("selcom_float_balance_unavailable", exc_info=True)
        return APIResponse(data={"available": None, "currency": "TZS", "reason": "provider_unavailable"})

    balance = parse_float_balance(response)
    if balance is None:
        # The call worked but the figure was not where we expected it.
        # Reported as unavailable rather than guessed at — see
        # parse_float_balance.
        logger.warning("selcom_float_balance_unparsed")
        return APIResponse(data={"available": None, "currency": "TZS", "reason": "unrecognised_response"})

    return APIResponse(data={"available": str(balance), "currency": "TZS", "reason": None})


@router.post("/reconcile-pending", response_model=APIResponse[dict])
async def reconcile_pending_withdrawals(
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    summary = await reconcile_pending_disbursements(client)

    write_audit_log(
        client,
        actor_id=admin.id,
        action="disbursement.reconcile_pending",
        resource_type="disbursement",
        metadata=summary,
    )

    return APIResponse(data=summary)
