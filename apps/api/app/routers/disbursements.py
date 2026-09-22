"""Disbursements: requesting a payout from a merchant's InfinityPay balance,
and reading back what's been recorded.

Flat resource routes — there's no merchant_id path segment, matching the
payment_links/invoices/collections pattern: the caller's merchant is
resolved from their API key, or checked against merchant_id in the request
body/a fetched row for a dashboard JWT caller — see
app.auth.get_authenticated_caller / authorize_merchant_action.

Super Admin approval/reject/request-info/refresh-status actions live in
app/routers/admin_withdrawals.py, not here — this router is purely the
merchant/API-key-facing create/list/get surface. Every disbursement created
here is always *created* PENDING_ADMIN_APPROVAL, and stays there for a
human unless withdrawal automation is enabled and the request passes the
eligibility check, in which case execute_disbursement auto-processes it
inline (see app/services/disbursements.py::execute_disbursement and
Settings.auto_withdrawals_enabled). Automation is off by default.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.auth import (
    authorize_merchant_action,
    get_authenticated_caller,
)
from app.core.errors import NotFoundError
from app.core.feature_flags import require_withdrawals_enabled
from app.core.pagination import PaginationParams, build_page_meta, pagination_params
from app.core.rate_limit import rate_limit
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedCaller
from app.schemas.common import APIResponse
from app.schemas.disbursements import (
    BankAccountDisbursementRequest,
    DisbursementResponse,
    PhoneDisbursementRequest,
)
from app.schemas.enums import DisbursementMethod, UserRole
from app.services.audit import write_audit_log
from app.services.crud import get_by_id, list_for_merchant
from app.services.disbursements import execute_disbursement
from app.services.idempotency import run_idempotent

router = APIRouter(prefix="/disbursements", tags=["disbursements"])

_DASHBOARD_ROLES = (UserRole.MERCHANT_ADMIN, UserRole.MERCHANT_STAFF)

_METHOD_PATHS: dict[DisbursementMethod, str] = {
    DisbursementMethod.SELCOM_PESA: "selcom-pesa",
    DisbursementMethod.MOBILE_MONEY: "mobile-money",
    DisbursementMethod.BANK_ACCOUNT: "bank-account",
}


async def _create_disbursement(
    method: DisbursementMethod,
    payload: PhoneDisbursementRequest | BankAccountDisbursementRequest,
    caller: AuthenticatedCaller,
    idempotency_key: str,
) -> APIResponse[DisbursementResponse]:
    require_withdrawals_enabled()
    authorize_merchant_action(caller, payload.merchant_id, *_DASHBOARD_ROLES)
    client = get_supabase_admin()

    async def _handler() -> tuple[int, dict]:
        disbursement = await execute_disbursement(
            client,
            merchant_id=payload.merchant_id,
            method=method,
            amount=payload.amount,
            currency=payload.currency,
            destination_name=payload.destination_name,
            destination_identifier=payload.destination_identifier,
            destination_code=payload.destination_code,
            bank_name=getattr(payload, "bank_name", None),
        )
        write_audit_log(
            client,
            actor_id=caller.actor_id,
            actor_type=caller.actor_type,
            merchant_id=payload.merchant_id,
            action="disbursement.requested",
            resource_type="disbursement",
            resource_id=uuid.UUID(disbursement["id"]),
            metadata={"method": method.value},
        )
        return status.HTTP_202_ACCEPTED, disbursement

    _status_code, body = await run_idempotent(
        client,
        merchant_id=payload.merchant_id,
        endpoint=f"POST /v1/disbursements/{_METHOD_PATHS[method]}",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )

    return APIResponse(data=DisbursementResponse(**body))


@router.post(
    "/selcom-pesa", response_model=APIResponse[DisbursementResponse], status_code=status.HTTP_202_ACCEPTED
)
async def create_selcom_pesa_disbursement(
    payload: PhoneDisbursementRequest,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="withdrawal_request", limit=10, window_seconds=60))],
):
    return await _create_disbursement(DisbursementMethod.SELCOM_PESA, payload, caller, idempotency_key)


@router.post(
    "/mobile-money", response_model=APIResponse[DisbursementResponse], status_code=status.HTTP_202_ACCEPTED
)
async def create_mobile_money_disbursement(
    payload: PhoneDisbursementRequest,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="withdrawal_request", limit=10, window_seconds=60))],
):
    return await _create_disbursement(DisbursementMethod.MOBILE_MONEY, payload, caller, idempotency_key)


@router.post(
    "/bank-account", response_model=APIResponse[DisbursementResponse], status_code=status.HTTP_202_ACCEPTED
)
async def create_bank_account_disbursement(
    payload: BankAccountDisbursementRequest,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="withdrawal_request", limit=10, window_seconds=60))],
):
    return await _create_disbursement(DisbursementMethod.BANK_ACCOUNT, payload, caller, idempotency_key)


@router.get("", response_model=APIResponse[list[DisbursementResponse]])
def list_disbursements(
    merchant_id: Annotated[uuid.UUID, Query(description="The merchant to list disbursements for")],
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    authorize_merchant_action(caller, merchant_id, *_DASHBOARD_ROLES)
    client = get_supabase_admin()
    rows, total = list_for_merchant(client, "disbursements", merchant_id=merchant_id, pagination=pagination)
    data = [DisbursementResponse(**row) for row in rows]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


@router.get("/{disbursement_id}", response_model=APIResponse[DisbursementResponse])
def get_disbursement(
    disbursement_id: uuid.UUID,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
):
    client = get_supabase_admin()
    row = get_by_id(client, "disbursements", disbursement_id)
    if not row:
        raise NotFoundError("Disbursement not found")

    authorize_merchant_action(caller, uuid.UUID(row["merchant_id"]), *_DASHBOARD_ROLES)
    return APIResponse(data=DisbursementResponse(**row))
