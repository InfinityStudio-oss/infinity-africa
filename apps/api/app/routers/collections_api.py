"""The external developer Collections API — POST/GET /v1/collections...
See app/schemas/collections_api.py's module docstring for how this
relates to the older app/routers/collections.py endpoints, and
app/services/collections_api.py for the status/method vocabulary this
API commits to externally vs. this codebase's real internal one.

Every creation endpoint here is backed by the real, proven Selcom
Checkout integration (app/services/wallet_push.py,
app/services/selcom_checkout/client.py, etc.) — never the older,
unconfirmed app/services/selcom/ placeholder app/routers/collections.py
still uses for its own /ussd-push, /stk-push, /selcom-pesa-push,
/dynamic-qr endpoints.

Auth follows the exact same pattern as app/routers/collections.py and
app/routers/payment_links.py: get_authenticated_caller (API key or
dashboard JWT) + authorize_merchant_action (the request's own
merchant_id must match the caller) + require_api_key_scope. Every
creation endpoint requires an Idempotency-Key header, same convention
as every other money-moving endpoint in this codebase.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status

from app.auth import (
    authorize_merchant_action,
    get_authenticated_caller,
    require_api_key_scope,
)
from app.core.errors import ConflictError, NotFoundError, ValidationAPIError
from app.core.feature_flags import require_collections_enabled
from app.core.rate_limit import rate_limit
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedCaller
from app.schemas.collections_api import (
    CollectionCreateRequest,
    CollectionCreateResponse,
    CollectionPushCreateRequest,
    CollectionPushCreateResponse,
    CollectionQrCreateRequest,
    CollectionQrCreateResponse,
    CollectionStatusResponse,
)
from app.schemas.common import APIResponse
from app.schemas.enums import UserRole
from app.services.audit import write_audit_log
from app.services.checkout_reconciliation import refresh_checkout_collection_status
from app.services.collections_api import (
    find_collection_by_external_id,
    to_external_method,
    to_external_status,
)
from app.services.crud import insert_row
from app.services.dynamic_qr import execute_qr_collection
from app.services.idempotency import run_idempotent
from app.services.payment_links import build_public_url, generate_public_slug
from app.services.sandbox_collections import execute_sandbox_collection
from app.services.selcompesa_push import execute_selcompesa_push_collection
from app.services.wallet_push import execute_wallet_push_collection

router = APIRouter(prefix="/collections", tags=["collections-api"])

_DASHBOARD_ROLES = (UserRole.MERCHANT_ADMIN, UserRole.MERCHANT_STAFF)


def _is_sandbox_key(caller: AuthenticatedCaller) -> bool:
    return caller.actor_type == "api_key" and caller.environment == "sandbox"


def _reject_simulate_status_outside_sandbox(caller: AuthenticatedCaller, simulate_status: str | None) -> None:
    if simulate_status is not None and not _is_sandbox_key(caller):
        raise ValidationAPIError("simulate_status is only accepted from a sandbox API key")


def _resolve_merchant_id(caller: AuthenticatedCaller, requested: uuid.UUID | None) -> uuid.UUID:
    """The merchant this request is for.

    An API key already belongs to exactly one merchant, so `merchant_id`
    in the body is redundant for the server-to-server callers these
    endpoints exist for — and requiring it meant an integrator had to go
    find their own UUID first, which the portal does not display. When
    omitted it comes from the key.

    Sending it is still supported and still checked: authorize_merchant_action
    below rejects a value that is not the key's own merchant, so this
    cannot be used to act for someone else. A dashboard-session caller
    must still send it, because a user can belong to several merchants and
    there is nothing to infer from.
    """
    if requested is not None:
        return requested
    if caller.merchant_id is not None:
        return caller.merchant_id
    raise ValidationAPIError(
        "merchant_id is required when authenticating with a dashboard session. "
        "API keys do not need it — the key identifies the merchant."
    )


def _push_message(collection: dict, *, pending_message: str) -> str:
    """A real (non-sandbox) push always acks "processing" here — never
    synchronously "successful"/"reversed"/"pending_review" — so those
    three branches only ever apply to a sandbox collection's simulated
    final status."""
    status_value = collection["status"]
    if status_value == "failed":
        # The normalized sentence first — `failure_reason` is free text and
        # sometimes carries the provider's own wording.
        return (
            collection.get("failure_reason_message")
            or collection.get("failure_reason")
            or "This payment attempt failed."
        )
    if status_value == "successful":
        return "Payment completed (sandbox simulation)."
    if status_value == "reversed":
        return "Payment reversed (sandbox simulation)."
    if status_value == "pending_review":
        return "Payment pending clearance (sandbox simulation)."
    return pending_message


def _status_response(row: dict) -> CollectionStatusResponse:
    return CollectionStatusResponse(
        collection_id=uuid.UUID(row["id"]),
        reference=row.get("merchant_reference"),
        status=to_external_status(row["status"]),
        amount=row["amount"],
        currency=row["currency"],
        method=to_external_method(row.get("method")),
        provider_payment_status=row.get("provider_payment_status"),
        failure_reason=row.get("failure_reason"),
        failure_reason_code=row.get("failure_reason_code"),
        failure_reason_message=row.get("failure_reason_message"),
        failed_at=row.get("failed_at"),
        cancelled_at=row.get("cancelled_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post("", response_model=APIResponse[CollectionCreateResponse], status_code=status.HTTP_202_ACCEPTED)
async def create_collection(
    payload: CollectionCreateRequest,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="collection_create", limit=20, window_seconds=60))],
):
    """The recommended flow for ecommerce/mobile apps: creates an
    Infinity Payment Page (internally the same payment_links resource
    Payment Links and Merchant Portal's "Request Collection" already
    use) and returns its URL. Redirect your customer to `payment_url` —
    they choose Mobile Money Push / Selcom Pesa / Scan QR themselves;
    you never pick a channel here."""
    require_collections_enabled()
    merchant_id = _resolve_merchant_id(caller, payload.merchant_id)
    authorize_merchant_action(caller, merchant_id, *_DASHBOARD_ROLES)
    require_api_key_scope(caller, "collections:write")
    client = get_supabase_admin()

    async def _handler() -> tuple[int, dict]:
        row = insert_row(
            client,
            "payment_links",
            {
                "merchant_id": str(merchant_id),
                "amount": str(payload.amount),
                "currency": payload.currency,
                "customer_name": payload.customer_name,
                "customer_phone": payload.customer_phone,
                "customer_email": payload.customer_email,
                "description": payload.description,
                "merchant_reference": payload.reference,
                "allowed_payment_methods": [],
                "success_redirect_url": payload.redirect_url,
                "failure_redirect_url": payload.cancel_url,
                "public_slug": generate_public_slug(),
                "status": "ACTIVE",
                "created_via": "api",
                "api_key_id": str(caller.actor_id) if caller.actor_type == "api_key" else None,
            },
        )
        write_audit_log(
            client,
            actor_id=caller.actor_id,
            actor_type=caller.actor_type,
            merchant_id=merchant_id,
            action="collection.created",
            resource_type="payment_link",
            resource_id=uuid.UUID(row["id"]),
        )
        body = {
            "collection_id": row["id"],
            "reference": row.get("merchant_reference"),
            "status": "created",
            "payment_url": build_public_url(row["public_slug"]),
        }
        return status.HTTP_202_ACCEPTED, body

    _status_code, body = await run_idempotent(
        client,
        merchant_id=merchant_id,
        endpoint="POST /v1/collections",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )
    return APIResponse(data=CollectionCreateResponse(**body))


@router.post(
    "/wallet-push", response_model=APIResponse[CollectionPushCreateResponse], status_code=status.HTTP_202_ACCEPTED
)
async def create_wallet_push_collection(
    payload: CollectionPushCreateRequest,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="collection_create", limit=20, window_seconds=60))],
):
    """Sends a real Mobile Money Push prompt immediately — best for a
    checkout where you already have the customer's phone number. A
    `202`/`"processing"` response means the prompt was sent, **not**
    that payment succeeded — never mark an order paid from this
    response; poll GET /v1/collections/{collection_id} or wait for the
    `collection.successful` webhook."""
    require_collections_enabled()
    merchant_id = _resolve_merchant_id(caller, payload.merchant_id)
    authorize_merchant_action(caller, merchant_id, *_DASHBOARD_ROLES)
    require_api_key_scope(caller, "collections:write")
    _reject_simulate_status_outside_sandbox(caller, payload.simulate_status)
    client = get_supabase_admin()

    async def _handler() -> tuple[int, dict]:
        if _is_sandbox_key(caller):
            collection = execute_sandbox_collection(
                client,
                merchant_id=merchant_id,
                external_method="wallet_push",
                amount=payload.amount,
                currency=payload.currency,
                customer_phone=payload.phone,
                customer_name=payload.customer_name,
                merchant_reference=payload.reference,
                description=payload.description,
                source="API_WALLET_PUSH",
                api_key_id=caller.actor_id,
                simulate_status=payload.simulate_status,
            )
        else:
            collection = await execute_wallet_push_collection(
                client,
                merchant_id=merchant_id,
                amount=payload.amount,
                currency=payload.currency,
                customer_phone=payload.phone,
                customer_name=payload.customer_name,
                merchant_reference=payload.reference,
                description=payload.description,
                source="API_WALLET_PUSH",
                api_key_id=caller.actor_id if caller.actor_type == "api_key" else None,
            )
        message = _push_message(collection, pending_message="Payment prompt sent. Please approve on your phone.")
        body = {
            "collection_id": collection["id"],
            "reference": collection.get("merchant_reference"),
            "status": to_external_status(collection["status"]),
            "message": message,
        }
        return status.HTTP_202_ACCEPTED, body

    _status_code, body = await run_idempotent(
        client,
        merchant_id=merchant_id,
        endpoint="POST /v1/collections/wallet-push",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )
    return APIResponse(data=CollectionPushCreateResponse(**body))


@router.post(
    "/selcom-pesa", response_model=APIResponse[CollectionPushCreateResponse], status_code=status.HTTP_202_ACCEPTED
)
async def create_selcom_pesa_collection(
    payload: CollectionPushCreateRequest,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="collection_create", limit=20, window_seconds=60))],
):
    """Sends a real Selcom Pesa prompt immediately. Same rule as
    wallet-push: `"processing"` means the prompt was sent, not that
    payment succeeded."""
    require_collections_enabled()
    merchant_id = _resolve_merchant_id(caller, payload.merchant_id)
    authorize_merchant_action(caller, merchant_id, *_DASHBOARD_ROLES)
    require_api_key_scope(caller, "collections:write")
    _reject_simulate_status_outside_sandbox(caller, payload.simulate_status)
    client = get_supabase_admin()

    async def _handler() -> tuple[int, dict]:
        if _is_sandbox_key(caller):
            collection = execute_sandbox_collection(
                client,
                merchant_id=merchant_id,
                external_method="selcom_pesa",
                amount=payload.amount,
                currency=payload.currency,
                customer_phone=payload.phone,
                customer_name=payload.customer_name,
                merchant_reference=payload.reference,
                description=payload.description,
                source="API_SELCOM_PESA",
                api_key_id=caller.actor_id,
                simulate_status=payload.simulate_status,
            )
        else:
            collection = await execute_selcompesa_push_collection(
                client,
                merchant_id=merchant_id,
                amount=payload.amount,
                currency=payload.currency,
                customer_phone=payload.phone,
                customer_name=payload.customer_name,
                merchant_reference=payload.reference,
                description=payload.description,
                source="API_SELCOM_PESA",
                api_key_id=caller.actor_id if caller.actor_type == "api_key" else None,
            )
        message = _push_message(
            collection, pending_message="Selcom Pesa prompt sent. Please approve in your Selcom Pesa app."
        )
        body = {
            "collection_id": collection["id"],
            "reference": collection.get("merchant_reference"),
            "status": to_external_status(collection["status"]),
            "message": message,
        }
        return status.HTTP_202_ACCEPTED, body

    _status_code, body = await run_idempotent(
        client,
        merchant_id=merchant_id,
        endpoint="POST /v1/collections/selcom-pesa",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )
    return APIResponse(data=CollectionPushCreateResponse(**body))


@router.post("/qr", response_model=APIResponse[CollectionQrCreateResponse], status_code=status.HTTP_202_ACCEPTED)
async def create_qr_collection(
    payload: CollectionQrCreateRequest,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="collection_create", limit=20, window_seconds=60))],
):
    """POS/counter/delivery scan-to-pay. `qr_payload`/`payment_token` are
    exactly what Selcom's own create-order-minimal response returned —
    this endpoint never generates a QR itself. Order creation succeeding
    means a QR/token now exists, **not** that anyone has paid — never
    mark an order paid from this response."""
    require_collections_enabled()
    merchant_id = _resolve_merchant_id(caller, payload.merchant_id)
    authorize_merchant_action(caller, merchant_id, *_DASHBOARD_ROLES)
    require_api_key_scope(caller, "collections:write")
    _reject_simulate_status_outside_sandbox(caller, payload.simulate_status)
    client = get_supabase_admin()

    async def _handler() -> tuple[int, dict]:
        if _is_sandbox_key(caller):
            collection = execute_sandbox_collection(
                client,
                merchant_id=merchant_id,
                external_method="qr",
                amount=payload.amount,
                currency=payload.currency,
                customer_phone=payload.customer_phone,
                customer_name=payload.customer_name,
                merchant_reference=payload.reference,
                description=payload.description,
                source="API_TANQR",
                api_key_id=caller.actor_id,
                simulate_status=payload.simulate_status,
            )
        else:
            collection = await execute_qr_collection(
                client,
                merchant_id=merchant_id,
                amount=payload.amount,
                currency=payload.currency,
                customer_phone=payload.customer_phone,
                customer_name=payload.customer_name,
                merchant_reference=payload.reference,
                description=payload.description,
                source="API_TANQR",
                api_key_id=caller.actor_id if caller.actor_type == "api_key" else None,
            )
        body = {
            "collection_id": collection["id"],
            "reference": collection.get("merchant_reference"),
            "status": to_external_status(collection["status"]),
            "payment_token": collection.get("payment_token"),
            "qr_payload": collection.get("qr"),
            "expires_at": None,
        }
        return status.HTTP_202_ACCEPTED, body

    _status_code, body = await run_idempotent(
        client,
        merchant_id=merchant_id,
        endpoint="POST /v1/collections/qr",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )
    return APIResponse(data=CollectionQrCreateResponse(**body))


@router.get("/{collection_id}", response_model=APIResponse[CollectionStatusResponse])
def get_collection_status(
    collection_id: uuid.UUID,
    merchant_id: uuid.UUID,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
):
    """`collection_id` may be the id returned by any of the four create
    endpoints above — including a payment_links id from POST
    /v1/collections, resolved to its real linked collection once the
    customer has picked a method (see
    app/services/collections_api.py::find_collection_by_external_id)."""
    authorize_merchant_action(caller, merchant_id, *_DASHBOARD_ROLES)
    require_api_key_scope(caller, "collections:read")
    client = get_supabase_admin()

    row = find_collection_by_external_id(client, merchant_id=merchant_id, external_id=collection_id)
    if not row:
        raise NotFoundError("Collection not found")
    if caller.actor_type == "api_key" and row.get("environment", "live") != caller.environment:
        # Sandbox and live are isolated data-wise, not just at creation
        # time — a live key can't be used to snoop on sandbox test data
        # or vice versa. Treated as not-found, same as a cross-merchant
        # lookup, rather than 403 (never confirm the id exists at all).
        raise NotFoundError("Collection not found")
    return APIResponse(data=_status_response(row))


@router.post("/{collection_id}/refresh-status", response_model=APIResponse[CollectionStatusResponse])
async def refresh_collection_status(
    collection_id: uuid.UUID,
    merchant_id: uuid.UUID,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
):
    """Queries Selcom directly and applies the same reversal-safe
    completion logic the webhook uses
    (app/services/checkout_reconciliation.py) — safe to call repeatedly,
    never double-credits or double-reverses. A no-op (returns the
    current state unchanged) if `collection_id` names a payment page
    with no method chosen yet — there's nothing to refresh."""
    authorize_merchant_action(caller, merchant_id, *_DASHBOARD_ROLES)
    require_api_key_scope(caller, "collections:write")
    client = get_supabase_admin()

    row = find_collection_by_external_id(client, merchant_id=merchant_id, external_id=collection_id)
    if not row:
        raise NotFoundError("Collection not found")

    if not row.get("checkout_order_id"):
        return APIResponse(data=_status_response(row))

    try:
        resolved = await refresh_checkout_collection_status(client, collection_id=uuid.UUID(row["id"]))
    except ConflictError:
        return APIResponse(data=_status_response(row))

    write_audit_log(
        client,
        actor_id=caller.actor_id,
        actor_type=caller.actor_type,
        merchant_id=merchant_id,
        action="collection.status_refreshed",
        resource_type="collection",
        resource_id=uuid.UUID(row["id"]),
        metadata={"status": resolved["status"]},
    )
    return APIResponse(data=_status_response(resolved))
