"""Super Admin control over which merchants may use the Disbursement API.

Own file and own prefix, matching admin_withdrawal_policy.py, so a route
that grants a merchant payout access can never be mistaken for one that
acts on a single payout.

What guards these routes:

* ``require_super_admin`` on all of them, which refuses a non-admin and
  enforces the second factor (``aal2``) for every ``/v1/admin`` call,
  reads included. There is no separate step-up dependency to add. A
  merchant session and an API key cannot reach this router: keys are only
  accepted by the endpoints that opt into ``get_authenticated_caller``,
  and nothing here does.
* The actor comes from the verified token. The body cannot name an
  administrator, and ``extra="forbid"`` makes trying a 422.
* ``version`` is required on every write - optimistic concurrency, so two
  administrators working from the same page cannot silently overwrite one
  another. One wins; the other is told to re-read.

**Sandbox and live are separate grants, with separate routes.** Granting
live is a different kind of act from switching the sandbox on - real
money, sent by an API key, with nobody approving each request - so it
has its own endpoint and its own body carrying an explicit
acknowledgement, and it cannot happen as a side effect of a sandbox
call.

It was previously impossible here at all, on the reasoning that it is a
commercial decision rather than a switch. That reasoning was right about
the weight of the act and wrong about the remedy: it did not stop live
being granted, it moved it to a hand-written database update with no
validation, no audit entry, and no record of who did it. A deliberate
route that leaves a trail is safer than a forbidden one people work
around.

Every write is audited with the before and after values, because
"who turned this on, and when" is the first question asked after an
incident, and a flag with no history cannot answer it.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth import require_super_admin
from app.core.errors import ConflictError, NotFoundError
from app.core.pagination import PaginationParams, build_page_meta, pagination_params
from app.core.rate_limit import rate_limit
from app.core.request_ip import client_ip
from app.core.time import utc_now_iso
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse
from app.schemas.payout_access import (
    MerchantPayoutAccessResponse,
    PayoutAccessUpdate,
    PayoutFeeUpdate,
    PayoutLiveAccessUpdate,
    PayoutPauseUpdate,
    PlatformPayoutTariffResponse,
    PlatformPayoutTariffUpdate,
)
from app.services.audit import write_audit_log
from app.services.crud import execute_maybe_single, get_by_id
from app.services.ledger import get_payout_wallet_balances

logger = logging.getLogger("infinity.admin.payout_access")

router = APIRouter(prefix="/admin/payout-access", tags=["admin-payout-access"])

# The tariff is platform-wide, not a property of any one merchant, so it
# gets its own prefix rather than sitting under /{merchant_id}/. Same
# guards: everything in this module is require_super_admin.
tariff_router = APIRouter(prefix="/admin/payout-tariff", tags=["admin-payout-access"])

# The columns an operator may change from this screen, and the ones they
# may not. live_enabled is absent by design - see the module docstring.
# There is no `enabled` column: sandbox_enabled and live_enabled ARE
# the enablement, one per environment, and load_payout_settings derives
# access from whichever environment is being asked about. An earlier
# draft of this file wrote an `enabled` flag, which the in-memory test
# fake accepted because it does not validate column names - Postgres
# refused it on the first real call.
_AUDITED_FIELDS = (
    "sandbox_enabled",
    "live_enabled",
    "paused",
    "paused_reason",
    "per_payout_limit_tzs",
    "daily_limit_tzs",
)


def _load(client, merchant_id: uuid.UUID) -> dict:
    row = execute_maybe_single(
        client.table("merchant_payout_settings")
        .select("*")
        .eq("merchant_id", str(merchant_id))
        .maybe_single()
    )
    if not row:
        raise NotFoundError("This merchant has no payout settings yet.")
    return row


def _response(client, row: dict) -> MerchantPayoutAccessResponse:
    merchant = get_by_id(client, "merchants", uuid.UUID(row["merchant_id"])) or {}
    environment = "live" if row.get("live_enabled") else "sandbox"
    available, reserved = get_payout_wallet_balances(
        client,
        merchant_id=uuid.UUID(row["merchant_id"]),
        currency="TZS",
        environment=environment,
    )
    return MerchantPayoutAccessResponse(
        merchant_id=uuid.UUID(row["merchant_id"]),
        business_name=merchant.get("business_name"),
        merchant_code=merchant.get("merchant_code"),
        # Derived, not stored. "Has any access at all" is a question
        # about the two environment flags, and keeping it as a third
        # column would be a third thing to forget to update.
        enabled=bool(row.get("sandbox_enabled")) or bool(row.get("live_enabled")),
        sandbox_enabled=bool(row.get("sandbox_enabled")),
        live_enabled=bool(row.get("live_enabled")),
        paused=bool(row.get("paused")),
        paused_reason=row.get("paused_reason"),
        per_payout_limit_tzs=row.get("per_payout_limit_tzs"),
        daily_limit_tzs=row.get("daily_limit_tzs"),
        fee_flat_tzs=row.get("fee_flat_tzs"),
        fee_percentage=row.get("fee_percentage"),
        version=int(row.get("version") or 1),
        updated_at=row.get("updated_at"),
        # Balances so an operator pausing an account can see what is
        # still committed. Pausing stops new payouts; it does not recall
        # the ones already reserved, and the screen should say so.
        wallet_available=available,
        wallet_reserved=reserved,
        wallet_environment=environment,
    )


def _write(
    client,
    *,
    merchant_id: uuid.UUID,
    before: dict,
    changes: dict,
    expected_version: int,
    admin: AuthenticatedUser,
    request: Request,
    action: str,
) -> dict:
    """Apply `changes` under optimistic concurrency, and audit it.

    The version is matched in the UPDATE itself rather than checked
    first: a read-then-write would leave a window where a second
    administrator's change is read, approved and then overwritten.
    """
    result = (
        client.table("merchant_payout_settings")
        .update(
            {
                **changes,
                "version": expected_version + 1,
                "updated_at": utc_now_iso(),
                "updated_by": str(admin.id),
            }
        )
        .eq("merchant_id", str(merchant_id))
        .eq("version", expected_version)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise ConflictError(
            "These payout settings were changed by someone else. Reload the page "
            "and apply your change again."
        )
    after = rows[0]

    write_audit_log(
        client,
        actor_id=admin.id,
        actor_type="user",
        merchant_id=merchant_id,
        action=action,
        resource_type="merchant_payout_settings",
        resource_id=merchant_id,
        ip_address=client_ip(request),
        metadata={
            # Before and after, not just after. "enabled: true" on its own
            # does not say whether this call changed anything.
            "before": {key: _plain(before.get(key)) for key in _AUDITED_FIELDS},
            "after": {key: _plain(after.get(key)) for key in _AUDITED_FIELDS},
            "version": after.get("version"),
        },
    )
    logger.info(
        "payout_access_changed merchant=%s action=%s by=%s", merchant_id, action, admin.id
    )
    return after


def _plain(value):
    """Audit metadata is JSON. A Decimal here fails the insert, and a
    failed audit insert on a money control is worse than a clumsy type."""
    return str(value) if value is not None and not isinstance(value, (bool, int, str)) else value


@router.get("", response_model=APIResponse[list[MerchantPayoutAccessResponse]])
def list_payout_access(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="admin_payout_access_read", limit=60, window_seconds=60))
    ],
):
    """Every merchant with payout settings. Never cached - this is the
    screen an operator checks to confirm they turned something off."""
    client = get_supabase_admin()
    query = client.table("merchant_payout_settings").select("*", count="exact")
    start = (pagination.page - 1) * pagination.page_size
    result = (
        query.order("updated_at", desc=True)
        .range(start, start + pagination.page_size - 1)
        .execute()
    )
    rows = result.data or []
    total = result.count if result.count is not None else len(rows)
    return APIResponse(
        data=[_response(client, row) for row in rows],
        meta=build_page_meta(pagination, total),
    )


@router.get("/{merchant_id}", response_model=APIResponse[MerchantPayoutAccessResponse])
def read_payout_access(
    merchant_id: uuid.UUID,
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="admin_payout_access_read", limit=60, window_seconds=60))
    ],
):
    client = get_supabase_admin()
    return APIResponse(data=_response(client, _load(client, merchant_id)))


@router.post("/{merchant_id}", response_model=APIResponse[MerchantPayoutAccessResponse])
def create_payout_access(
    merchant_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    request: Request,
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="admin_payout_access_write", limit=20, window_seconds=60))
    ],
):
    """Give a merchant a settings row, with everything off.

    Creating the row is not granting access - it is what makes the
    merchant appear on this screen so access can then be granted
    deliberately, one environment at a time.
    """
    client = get_supabase_admin()
    merchant = get_by_id(client, "merchants", merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")

    existing = execute_maybe_single(
        client.table("merchant_payout_settings")
        .select("*")
        .eq("merchant_id", str(merchant_id))
        .maybe_single()
    )
    if existing:
        raise ConflictError("This merchant already has payout settings.")

    row = (
        client.table("merchant_payout_settings")
        .insert(
            {
                "merchant_id": str(merchant_id),
                "sandbox_enabled": False,
                "live_enabled": False,
                "paused": False,
                "version": 1,
                "updated_by": str(admin.id),
            }
        )
        .execute()
    ).data[0]

    write_audit_log(
        client,
        actor_id=admin.id,
        actor_type="user",
        merchant_id=merchant_id,
        action="payout_access.created",
        resource_type="merchant_payout_settings",
        resource_id=merchant_id,
        ip_address=client_ip(request),
        metadata={"after": {key: _plain(row.get(key)) for key in _AUDITED_FIELDS}},
    )
    return APIResponse(data=_response(client, row))


@router.patch("/{merchant_id}/sandbox", response_model=APIResponse[MerchantPayoutAccessResponse])
def set_sandbox_access(
    merchant_id: uuid.UUID,
    payload: PayoutAccessUpdate,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    request: Request,
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="admin_payout_access_write", limit=20, window_seconds=60))
    ],
):
    """Turn the sandbox on or off, and set the limits that go with it.

    This flag IS the access for the sandbox - there is no separate master
    switch to keep in step with it, which is one fewer thing to leave
    inconsistent. Live access is a different flag and not settable here.
    """
    client = get_supabase_admin()
    before = _load(client, merchant_id)

    changes: dict = {"sandbox_enabled": payload.sandbox_enabled}
    if payload.per_payout_limit_tzs is not None:
        changes["per_payout_limit_tzs"] = str(payload.per_payout_limit_tzs)
    if payload.daily_limit_tzs is not None:
        changes["daily_limit_tzs"] = str(payload.daily_limit_tzs)

    after = _write(
        client,
        merchant_id=merchant_id,
        before=before,
        changes=changes,
        expected_version=payload.version,
        admin=admin,
        request=request,
        action="payout_access.sandbox_enabled" if payload.sandbox_enabled else "payout_access.sandbox_disabled",
    )
    return APIResponse(data=_response(client, after))


@router.patch("/{merchant_id}/pause", response_model=APIResponse[MerchantPayoutAccessResponse])
def set_pause(
    merchant_id: uuid.UUID,
    payload: PayoutPauseUpdate,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    request: Request,
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="admin_payout_access_write", limit=20, window_seconds=60))
    ],
):
    """Stop this merchant creating new payouts, or let them resume.

    Pause is the fast lever: it needs no commercial decision and is the
    right response to a suspected key leak or a runaway integration. It
    does **not** touch payouts already in flight - their funds stay
    reserved and the worker still resolves them, because abandoning an
    in-flight payout is how one ends up paid and unaccounted for.
    """
    client = get_supabase_admin()
    before = _load(client, merchant_id)

    after = _write(
        client,
        merchant_id=merchant_id,
        before=before,
        changes={
            "paused": payload.paused,
            "paused_reason": payload.reason if payload.paused else None,
        },
        expected_version=payload.version,
        admin=admin,
        request=request,
        action="payout_access.paused" if payload.paused else "payout_access.resumed",
    )
    return APIResponse(data=_response(client, after))


@router.patch("/{merchant_id}/live", response_model=APIResponse[MerchantPayoutAccessResponse])
def set_live_access(
    merchant_id: uuid.UUID,
    payload: PayoutLiveAccessUpdate,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    request: Request,
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="admin_payout_access_write", limit=20, window_seconds=60))
    ],
):
    """Grant or withdraw LIVE payout access.

    Its own route, because this is the one that lets an API key move real
    money with nobody approving each request. The body must carry
    `acknowledge` to turn it on, which means it cannot be done by
    replaying the sandbox call with a value changed.

    Granting live does not fund anything and does not lift the pause. The
    ceiling on what a leaked key can cost is still the live payout
    wallet's balance, which only the merchant can top up, from their
    dashboard, behind their own second factor.
    """
    client = get_supabase_admin()
    before = _load(client, merchant_id)

    after = _write(
        client,
        merchant_id=merchant_id,
        before=before,
        changes={"live_enabled": payload.live_enabled},
        expected_version=payload.version,
        admin=admin,
        request=request,
        action="payout_access.live_enabled" if payload.live_enabled else "payout_access.live_disabled",
    )
    logger.warning(
        "payout_live_access_changed merchant=%s live=%s admin=%s",
        merchant_id,
        payload.live_enabled,
        admin.id,
    )
    return APIResponse(data=_response(client, after))


@router.patch("/{merchant_id}/fee", response_model=APIResponse[MerchantPayoutAccessResponse])
def set_payout_fee(
    merchant_id: uuid.UUID,
    payload: PayoutFeeUpdate,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    request: Request,
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="admin_payout_access_write", limit=20, window_seconds=60))
    ],
):
    """Set or clear this merchant's negotiated payout fee.

    Sending both fields null clears the negotiated rate and returns the
    merchant to the platform tariff. That is a real instruction, not an
    omission, which is why these fields are nullable rather than
    "unchanged if absent": "charge them the standard rate" has to be
    expressible, and it is the normal state for most merchants.
    """
    client = get_supabase_admin()
    before = _load(client, merchant_id)

    after = _write(
        client,
        merchant_id=merchant_id,
        before=before,
        changes={
            "fee_flat_tzs": None if payload.fee_flat_tzs is None else str(payload.fee_flat_tzs),
            "fee_percentage": None if payload.fee_percentage is None else str(payload.fee_percentage),
        },
        expected_version=payload.version,
        admin=admin,
        request=request,
        action="payout_access.fee_updated",
    )
    return APIResponse(data=_response(client, after))


# --- the platform tariff -----------------------------------------------------


@tariff_router.get("", response_model=APIResponse[PlatformPayoutTariffResponse])
def read_platform_tariff(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """What a merchant with no negotiated rate pays, on every payout, to
    every destination - all mobile money networks, Selcom Pesa and all
    banks alike."""
    client = get_supabase_admin()
    row = execute_maybe_single(
        client.table("payout_platform_pricing").select("*").limit(1).maybe_single()
    )
    if not row:
        raise NotFoundError("The payout tariff has not been set up yet.")
    return APIResponse(
        data=PlatformPayoutTariffResponse(
            percentage_fee=row["percentage_fee"],
            flat_fee=row["flat_fee"],
            version=row["version"],
            updated_at=row.get("updated_at"),
        )
    )


@tariff_router.patch("", response_model=APIResponse[PlatformPayoutTariffResponse])
def update_platform_tariff(
    payload: PlatformPayoutTariffUpdate,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    request: Request,
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="admin_payout_access_write", limit=20, window_seconds=60))
    ],
):
    """Change the tariff.

    It applies to every merchant without a negotiated rate, immediately
    and to payouts created from now on - priced at creation, so nothing
    already queued or in flight re-prices under it.
    """
    client = get_supabase_admin()
    before = execute_maybe_single(
        client.table("payout_platform_pricing").select("*").limit(1).maybe_single()
    )
    if not before:
        raise NotFoundError("The payout tariff has not been set up yet.")

    result = (
        client.table("payout_platform_pricing")
        .update(
            {
                "percentage_fee": str(payload.percentage_fee),
                "flat_fee": str(payload.flat_fee),
                "version": payload.version + 1,
                "updated_at": utc_now_iso(),
                "updated_by": str(admin.id),
            }
        )
        .eq("id", True)
        .eq("version", payload.version)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise ConflictError(
            "The payout tariff was changed by someone else. Reload the page and apply "
            "your change again."
        )
    after = rows[0]

    write_audit_log(
        client,
        actor_id=admin.id,
        actor_type="user",
        merchant_id=None,
        action="payout_tariff.updated",
        resource_type="payout_platform_pricing",
        resource_id=None,
        ip_address=client_ip(request),
        metadata={
            "before": {"percentage_fee": str(before["percentage_fee"]), "flat_fee": str(before["flat_fee"])},
            "after": {"percentage_fee": str(after["percentage_fee"]), "flat_fee": str(after["flat_fee"])},
        },
    )
    return APIResponse(
        data=PlatformPayoutTariffResponse(
            percentage_fee=after["percentage_fee"],
            flat_fee=after["flat_fee"],
            version=after["version"],
            updated_at=after.get("updated_at"),
        )
    )
