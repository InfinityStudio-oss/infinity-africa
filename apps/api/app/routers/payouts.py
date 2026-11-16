"""The Disbursement API: payouts out of a merchant's prefunded Payout
Wallet, and the dashboard-only endpoint that funds it.

Two surfaces with deliberately different credentials, which is the whole
design:

- **Creating and reading payouts** takes a payout-type API key. A partner's
  server calls these; no person approves each one.
- **Funding the wallet** takes a dashboard session with step-up MFA, and
  is closed to API keys entirely. A payout key that could top up the pot
  it spends from would be self-replenishing, and the wallet balance would
  stop being a cap on what a leaked key can cost. The cap is the point:
  it is why this API can exist at all without a human in the loop, while
  /v1/disbursements - which spends the merchant's whole Collections
  balance - cannot be reached by a key at all.

No merchant_id in any request body. A payout key already implies its
merchant and environment, and taking either from the body would mean
validating a client-supplied identifier on a money-moving call.

Nothing here talks to a provider. create_payout reserves funds and leaves
the payout `processing`; the worker dispatches it. So a 201 from this
router means the money is held, not that it has been sent.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status

from app.auth import (
    authorize_merchant_action,
    get_authenticated_caller,
    require_api_key_scope,
)
from app.core.errors import NotFoundError, ValidationAPIError
from app.core.pagination import PaginationParams, build_page_meta, pagination_params
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedCaller
from app.schemas.common import APIResponse
from app.schemas.enums import UserRole
from app.schemas.payouts import (
    PayoutCreateRequest,
    PayoutResponse,
)
from app.services.crud import get_by_id, list_for_merchant
from app.services.idempotency import run_idempotent
from app.services.payouts import (
    assert_payout_allowed,
    create_payout,
    load_payout_settings,
)

router = APIRouter(prefix="/payouts", tags=["payouts"])

# Reading a payout is not moving one.
_READ_ROLES = (UserRole.MERCHANT_ADMIN, UserRole.MERCHANT_STAFF)


def _caller_environment(caller: AuthenticatedCaller) -> str:
    """The environment to act in, taken from the credential.

    A payout key carries its own. A dashboard session does not, so it
    acts on `live` - the sandbox is for API callers, and a person reading
    their own payouts in the portal means the real ones.
    """
    if caller.actor_type == "api_key":
        return caller.environment or "live"
    return "live"


def _merchant_of(caller: AuthenticatedCaller) -> uuid.UUID:
    """The merchant an API key implies.

    KNOWN GAP: caller.merchant_id is set only for api_key callers, so a
    dashboard session reaches this and is refused. That is correct for
    POST - a person creating a payout should go through the portal's own
    flow, not the partner API - but it means **the merchant portal cannot
    yet read payouts**, because the GETs refuse a session too. The portal
    needs a /v1/merchant/payouts pair resolving the merchant from
    membership, the way the rest of that surface does. Not built yet; it
    belongs with the portal UI work rather than here.
    """
    if caller.merchant_id is None:
        raise ValidationAPIError(
            "This endpoint requires a payout API key. Dashboard sessions cannot "
            "use the Disbursement API."
        )
    return caller.merchant_id


# --- the partner-facing API --------------------------------------------------


@router.post("", response_model=APIResponse[PayoutResponse], status_code=status.HTTP_201_CREATED)
async def create_one_payout(
    payload: PayoutCreateRequest,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
):
    """Reserve funds for one payout to an approved beneficiary.

    `Idempotency-Key` is required, not optional. A partner's retry after a
    timeout is the normal case, not the exception: without a key, a
    network failure on a call that actually succeeded is indistinguishable
    from one that did not, and the safe-looking choice - retrying - sends
    the money twice.
    """
    require_api_key_scope(caller, "payouts:create")
    merchant_id = _merchant_of(caller)
    # The merchant comes from the credential, never the body - and this
    # says so where a reader checks. For a payout key it re-proves the
    # key owns the merchant it is acting as; for a dashboard session it
    # proves membership. tests/test_tenant_isolation_route_guards.py
    # requires every get_authenticated_caller route to reach this, and a
    # money route is the last place to want an exemption from that.
    authorize_merchant_action(caller, merchant_id, *_READ_ROLES)
    environment = _caller_environment(caller)
    client = get_supabase_admin()

    settings = load_payout_settings(client, merchant_id=merchant_id, environment=environment)
    assert_payout_allowed(settings, environment=environment)

    async def _handler() -> tuple[int, dict]:
        payout = create_payout(
            client,
            merchant_id=merchant_id,
            environment=environment,
            beneficiary_id=payload.beneficiary_id,
            amount=payload.amount,
            currency=payload.currency,
            api_key_id=caller.actor_id if caller.actor_type == "api_key" else None,
            metadata=payload.metadata,
        )
        return status.HTTP_201_CREATED, PayoutResponse.from_row(payout).model_dump(mode="json")

    _status_code, body = await run_idempotent(
        client,
        merchant_id=merchant_id,
        endpoint="POST /v1/payouts",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )
    return APIResponse(data=PayoutResponse(**body))


@router.get("", response_model=APIResponse[list[PayoutResponse]])
def list_payouts(
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    require_api_key_scope(caller, "payouts:read")
    merchant_id = _merchant_of(caller)
    authorize_merchant_action(caller, merchant_id, *_READ_ROLES)
    client = get_supabase_admin()

    rows, total = list_for_merchant(
        client,
        "payouts",
        merchant_id=merchant_id,
        pagination=pagination,
        filters={"environment": _caller_environment(caller)},
    )
    return APIResponse(
        data=[PayoutResponse.from_row(row) for row in rows],
        meta=build_page_meta(pagination, total),
    )


@router.get("/{payout_id}", response_model=APIResponse[PayoutResponse])
def get_payout(
    payout_id: uuid.UUID,
    caller: Annotated[AuthenticatedCaller, Depends(get_authenticated_caller)],
):
    client = get_supabase_admin()
    row = get_by_id(client, "payouts", payout_id)
    if not row:
        raise NotFoundError("Payout not found")

    # Ownership first, scope second. A caller who does not own the row is
    # told that; a caller who owns it but lacks the scope is told about
    # the scope. The other order would let a key without the read scope
    # learn which payout ids exist by the difference between 403 and 404.
    authorize_merchant_action(caller, uuid.UUID(row["merchant_id"]), *_READ_ROLES)
    require_api_key_scope(caller, "payouts:read")

    if row["environment"] != _caller_environment(caller):
        # A sandbox key must not read live payouts, and the honest answer
        # is that this id is not one of theirs.
        raise NotFoundError("Payout not found")
    return APIResponse(data=PayoutResponse.from_row(row))

