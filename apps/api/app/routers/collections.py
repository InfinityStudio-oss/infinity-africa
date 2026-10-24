"""Collections: initiating a mock push/QR collection from a customer, and
reading back what's been recorded.

Initiation is flat (/v1/collections/{method}, no merchant_id path segment —
merchant_id lives in the request body instead, same reasoning and the same
app.auth.get_authenticated_caller/authorize_merchant_action pattern as
app.routers.payment_links). Reading stays merchant-scoped
(/v1/merchants/{merchant_id}/collections), unaffected by this.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status

from app.auth import (
    authorize_merchant_action,
    get_authenticated_caller,
    require_api_key_scope,
    require_role,
)
from app.core.errors import NotFoundError
from app.core.feature_flags import require_collections_enabled
from app.core.pagination import PaginationParams, build_page_meta, pagination_params
from app.core.rate_limit import rate_limit
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedCaller, AuthenticatedUser
from app.schemas.collections import (
    CollectionResponse,
    DynamicQrCollectionRequest,
    DynamicQrCollectionResponse,
    PushCollectionRequest,
)
from app.schemas.common import APIResponse
from app.schemas.enums import CollectionMethod, UserRole
from app.services.audit import write_audit_log
from app.services.collections import initiate_collection, initiate_dynamic_qr_collection
from app.services.crud import get_for_merchant, list_for_merchant
from app.services.idempotency import run_idempotent
from app.services.payment_links import validate_payment_link_for_collection
from app.services.webhook_status import (
    apply_webhook_status,
    batch_collection_webhook_status,
)

router = APIRouter(prefix="/merchants/{merchant_id}/collections", tags=["collections"])
initiate_router = APIRouter(prefix="/collections", tags=["collections"])

_DASHBOARD_ROLES = (UserRole.MERCHANT_ADMIN, UserRole.MERCHANT_STAFF)

_METHOD_PATHS: dict[CollectionMethod, str] = {
    CollectionMethod.USSD_PUSH: "ussd-push",
    CollectionMethod.STK_PUSH: "stk-push",
    CollectionMethod.SELCOM_PESA_PUSH: "selcom-pesa-push",
    CollectionMethod.DYNAMIC_QR: "dynamic-qr",
}

# This legacy/placeholder-backed router is still API-key-callable, so a
# collection created here with no payment_link_id/invoice_id still needs
# a correct CollectionSource — create_processing_collection()'s own
# fallback would otherwise default it to DASHBOARD_REQUEST even for an
# API-key caller. Only used when the caller is actually an API key; a
# dashboard caller in that same situation genuinely is DASHBOARD_REQUEST
# (create_processing_collection's default), so this map is intentionally
# not consulted for actor_type == "user".
_API_KEY_METHOD_SOURCE: dict[CollectionMethod, str] = {
    CollectionMethod.USSD_PUSH: "API_WALLET_PUSH",
    CollectionMethod.STK_PUSH: "API_WALLET_PUSH",
    CollectionMethod.SELCOM_PESA_PUSH: "API_SELCOM_PESA",
    CollectionMethod.DYNAMIC_QR: "API_TANQR",
}


async def _create_push_collection(
    method: CollectionMethod,
    payload: PushCollectionRequest,
    caller: AuthenticatedCaller,
    idempotency_key: str,
) -> APIResponse[CollectionResponse]:
    require_collections_enabled()
    authorize_merchant_action(caller, payload.merchant_id, *_DASHBOARD_ROLES)
    require_api_key_scope(caller, "collections:write")
    client = get_supabase_admin()

    await validate_payment_link_for_collection(
        client, merchant_id=payload.merchant_id, payment_link_id=payload.payment_link_id, method=method
    )

    source = None
    if caller.actor_type == "api_key" and not (payload.payment_link_id or payload.invoice_id):
        source = _API_KEY_METHOD_SOURCE[method]

    async def _handler() -> tuple[int, dict]:
        collection = await initiate_collection(
            client,
            merchant_id=payload.merchant_id,
            method=method,
            amount=payload.amount,
            currency=payload.currency,
            customer_id=payload.customer_id,
            customer_phone=payload.customer_phone,
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            payment_link_id=payload.payment_link_id,
            invoice_id=payload.invoice_id,
            merchant_reference=payload.merchant_reference,
            description=payload.description,
            callback_url=payload.callback_url,
            source=source,
            api_key_id=caller.actor_id if caller.actor_type == "api_key" else None,
        )
        write_audit_log(
            client,
            actor_id=caller.actor_id,
            actor_type=caller.actor_type,
            merchant_id=payload.merchant_id,
            action="collection.initiated",
            resource_type="collection",
            resource_id=uuid.UUID(collection["id"]),
            metadata={"method": method.value},
        )
        return status.HTTP_202_ACCEPTED, collection

    _status_code, body = await run_idempotent(
        client,
        merchant_id=payload.merchant_id,
        endpoint=f"POST /v1/collections/{_METHOD_PATHS[method]}",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )

    return APIResponse(data=CollectionResponse(**body))


@initiate_router.post(
    "/ussd-push", response_model=APIResponse[CollectionResponse], status_code=status.HTTP_202_ACCEPTED
)
async def create_ussd_push_collection(
    payload: PushCollectionRequest,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="collection_create", limit=20, window_seconds=60))],
):
    return await _create_push_collection(CollectionMethod.USSD_PUSH, payload, caller, idempotency_key)


@initiate_router.post(
    "/stk-push", response_model=APIResponse[CollectionResponse], status_code=status.HTTP_202_ACCEPTED
)
async def create_stk_push_collection(
    payload: PushCollectionRequest,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="collection_create", limit=20, window_seconds=60))],
):
    return await _create_push_collection(CollectionMethod.STK_PUSH, payload, caller, idempotency_key)


@initiate_router.post(
    "/selcom-pesa-push", response_model=APIResponse[CollectionResponse], status_code=status.HTTP_202_ACCEPTED
)
async def create_selcom_pesa_push_collection(
    payload: PushCollectionRequest,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="collection_create", limit=20, window_seconds=60))],
):
    return await _create_push_collection(CollectionMethod.SELCOM_PESA_PUSH, payload, caller, idempotency_key)


@initiate_router.post(
    "/dynamic-qr", response_model=APIResponse[DynamicQrCollectionResponse], status_code=status.HTTP_202_ACCEPTED
)
async def create_dynamic_qr_collection(
    payload: DynamicQrCollectionRequest,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="collection_create", limit=20, window_seconds=60))],
):
    require_collections_enabled()
    authorize_merchant_action(caller, payload.merchant_id, *_DASHBOARD_ROLES)
    require_api_key_scope(caller, "collections:write")
    client = get_supabase_admin()

    await validate_payment_link_for_collection(
        client,
        merchant_id=payload.merchant_id,
        payment_link_id=payload.payment_link_id,
        method=CollectionMethod.DYNAMIC_QR,
    )

    source = None
    if caller.actor_type == "api_key" and not (payload.payment_link_id or payload.invoice_id):
        source = "API_TANQR"

    async def _handler() -> tuple[int, dict]:
        collection, qr_result = await initiate_dynamic_qr_collection(
            client,
            merchant_id=payload.merchant_id,
            amount=payload.amount,
            currency=payload.currency,
            customer_id=payload.customer_id,
            customer_phone=payload.customer_phone,
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            payment_link_id=payload.payment_link_id,
            invoice_id=payload.invoice_id,
            merchant_reference=payload.merchant_reference,
            description=payload.description,
            callback_url=payload.callback_url,
            source=source,
            api_key_id=caller.actor_id if caller.actor_type == "api_key" else None,
        )
        write_audit_log(
            client,
            actor_id=caller.actor_id,
            actor_type=caller.actor_type,
            merchant_id=payload.merchant_id,
            action="collection.initiated",
            resource_type="collection",
            resource_id=uuid.UUID(collection["id"]),
            metadata={"method": "DYNAMIC_QR"},
        )
        body = {
            **collection,
            "qr_payload": qr_result.qr_payload,
            "qr_expires_at": qr_result.qr_expires_at.isoformat(),
            "expires_at": qr_result.qr_expires_at.isoformat(),
        }
        return status.HTTP_202_ACCEPTED, body

    _status_code, body = await run_idempotent(
        client,
        merchant_id=payload.merchant_id,
        endpoint="POST /v1/collections/dynamic-qr",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )

    return APIResponse(data=DynamicQrCollectionResponse(**body))


# --- Reading back what's been recorded (unchanged, merchant-scoped) -------


@router.get("", response_model=APIResponse[list[CollectionResponse]])
def list_collections(
    merchant_id: uuid.UUID,
    _actor: Annotated[AuthenticatedUser, Depends(require_role(*_DASHBOARD_ROLES))],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    client = get_supabase_admin()
    rows, total = list_for_merchant(client, "collections", merchant_id=merchant_id, pagination=pagination)
    # One batched query for the whole page, not one per row — a merchant
    # needs to know when a payment succeeded but their endpoint never
    # received it, which was previously visible only to us.
    statuses = batch_collection_webhook_status(
        client, merchant_id=merchant_id, collection_ids=[str(row["id"]) for row in rows]
    )
    data = [CollectionResponse(**row) for row in apply_webhook_status(rows, statuses)]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


@router.get("/{collection_id}", response_model=APIResponse[CollectionResponse])
def get_collection(
    merchant_id: uuid.UUID,
    collection_id: uuid.UUID,
    _actor: Annotated[AuthenticatedUser, Depends(require_role(*_DASHBOARD_ROLES))],
):
    client = get_supabase_admin()
    row = get_for_merchant(client, "collections", merchant_id=merchant_id, row_id=collection_id)
    if not row:
        raise NotFoundError("Collection not found")
    statuses = batch_collection_webhook_status(
        client, merchant_id=merchant_id, collection_ids=[str(row["id"])]
    )
    return APIResponse(data=CollectionResponse(**apply_webhook_status([row], statuses)[0]))
