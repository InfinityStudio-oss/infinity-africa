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
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth import require_super_admin
from app.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationAPIError
from app.core.pagination import PaginationParams, build_page_meta, pagination_params
from app.core.rate_limit import rate_limit
from app.core.request_ip import client_ip
from app.core.time import utc_now_iso
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse
from app.schemas.payout_access import (
    AdminPayoutRow,
    MerchantPayoutAccessResponse,
    PayoutAccessUpdate,
    PayoutFeeUpdate,
    PayoutLiveAccessUpdate,
    PayoutPauseUpdate,
    PayoutReleaseRequest,
    PayoutRequestDismiss,
    PlatformPayoutTariffResponse,
    PlatformPayoutTariffUpdate,
    ProviderHealthResponse,
)
from app.services.audit import write_audit_log
from app.services.crud import execute_maybe_single, get_by_id
from app.services.ledger import get_payout_wallet_balances
from app.services.payout_dispatch import release_parked_payout
from app.services.selcom_business.client import get_selcom_business_client

logger = logging.getLogger("infinity.admin.payout_access")

router = APIRouter(prefix="/admin/payout-access", tags=["admin-payout-access"])

# The tariff is platform-wide, not a property of any one merchant, so it
# gets its own prefix rather than sitting under /{merchant_id}/. Same
# guards: everything in this module is require_super_admin.
tariff_router = APIRouter(prefix="/admin/payout-tariff", tags=["admin-payout-access"])

# Acting on ONE payout, rather than on a merchant's access. Separate
# prefix so a route that hands money back can never be confused with one
# that changes a permission.
payouts_router = APIRouter(prefix="/admin/payouts", tags=["admin-payout-access"])

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
    # Audited because clearing it is a decision - "we are not doing this
    # for them" - and the before/after is the only trace that a request
    # existed at all once the stamp is gone.
    "access_requested_at",
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
        access_requested_at=row.get("access_requested_at"),
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
    extra_metadata: dict | None = None,
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
            # Anything the caller must record beyond the field diff - a
            # dismissal's reason, for instance, which is the only account
            # of WHY once the request stamp is gone.
            **(extra_metadata or {}),
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


@payouts_router.post("/{payout_id}/release", response_model=APIResponse[dict])
def release_payout_reserve(
    payout_id: uuid.UUID,
    payload: PayoutReleaseRequest,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="admin_payout_release", limit=5, window_seconds=60))
    ],
):
    """Return the funds held by a payout stuck in reconciliation.

    A parked payout holds its reserve indefinitely and no partner-facing
    route can clear it, which is correct - only the provider knows what
    happened. But "indefinitely" turned out to mean exactly that: a
    payout dispatched at a sandbox endpoint that 404s parked with TZS
    1,010 held and no way out except editing the database.
    
    The service refuses unless the payout is parked AND the provider
    never acknowledged it. Read release_parked_payout before using this:
    if the provider did pay, this hands the merchant money that has
    already left, and the platform covers the difference.
    """
    client = get_supabase_admin()
    row = release_parked_payout(
        client, payout_id=payout_id, reason=payload.reason, actor_id=admin.id
    )
    return APIResponse(
        data={
            "id": str(payout_id),
            "status": row["status"],
            "released": str(row["total_debit"]),
            "currency": row["currency"],
        }
    )


@payouts_router.get("", response_model=APIResponse[list[AdminPayoutRow]])
def list_payouts_for_admin(
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    status_filter: str | None = None,
    environment: str | None = None,
):
    """Payouts across every merchant, newest first.

    Defaults to the ones that need a human: `needs_reconciliation` is
    money held with no answer from the provider, and it is the only
    status an operator has to do anything about. Pass status=all for
    everything.
    """
    client = get_supabase_admin()
    query = client.table("payouts").select("*", count="exact")

    if status_filter is None:
        query = query.eq("status", "needs_reconciliation")
    elif status_filter != "all":
        query = query.eq("status", status_filter)
    if environment:
        query = query.eq("environment", environment)

    result = (
        query.order("created_at", desc=True)
        .range(pagination.offset, pagination.offset + pagination.page_size - 1)
        .execute()
    )
    rows = result.data or []

    # One lookup per merchant, not one per payout: a busy day's list is
    # mostly the same handful of merchants.
    merchants: dict[str, dict] = {}
    for row in rows:
        mid = row["merchant_id"]
        if mid not in merchants:
            merchants[mid] = get_by_id(client, "merchants", uuid.UUID(mid)) or {}

    data = [
        AdminPayoutRow(
            id=row["id"],
            merchant_id=row["merchant_id"],
            business_name=merchants[row["merchant_id"]].get("business_name"),
            merchant_code=merchants[row["merchant_id"]].get("merchant_code"),
            environment=row["environment"],
            status=row["status"],
            amount=row["amount"],
            fee_amount=row["fee_amount"],
            total_debit=row["total_debit"],
            currency=row["currency"],
            failure_code=row.get("failure_code"),
            failure_reason=row.get("failure_reason"),
            provider_acknowledged=bool(row.get("provider_transid") or row.get("provider_raw_response")),
            dispatch_attempts=int(row.get("dispatch_attempts") or 0),
            created_at=row["created_at"],
            completed_at=row.get("completed_at"),
        )
        for row in rows
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, getattr(result, "count", None) or 0))


@payouts_router.get("/provider-health", response_model=APIResponse[ProviderHealthResponse])
async def check_provider_health(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="admin_payout_health", limit=10, window_seconds=60))
    ],
    environment: str = "sandbox",
):
    """Can we actually reach the payout provider for this environment?

    A real signed call - `balance` - not a ping. Reaching the host
    proves nothing: the Selcom Business sandbox base URL answers, and
    answers 404, which is exactly how the first sandbox payout failed
    while looking like a provider timeout. Only a genuine request
    exercises the URL, the credentials and the signing together.

    Read-only: balance moves no money and creates nothing.
    """
    if environment not in ("sandbox", "live"):
        raise ValidationAPIError("environment must be 'sandbox' or 'live'.")

    settings = get_settings()
    account = settings.selcom_business_account_number
    checked_at = datetime.now(timezone.utc)

    if not account:
        return APIResponse(
            data=ProviderHealthResponse(
                environment=environment,
                reachable=False,
                detail="No SELCOM_BUSINESS_ACCOUNT_NUMBER is configured, so the provider cannot be checked.",
                checked_at=checked_at,
            )
        )

    try:
        provider = get_selcom_business_client(environment)
        await provider.balance(account_number=account)
    except Exception as exc:  # noqa: BLE001 - every failure is the answer here
        # The exception type and message, not a generic "unavailable":
        # a 404 from a wrong base URL and a signature rejection are
        # different problems with different fixes, and the operator
        # needs to be able to tell them apart.
        return APIResponse(
            data=ProviderHealthResponse(
                environment=environment,
                reachable=False,
                detail=f"{type(exc).__name__}: {str(exc)[:200]}",
                checked_at=checked_at,
            )
        )

    return APIResponse(
        data=ProviderHealthResponse(
            environment=environment,
            reachable=True,
            detail="A signed balance request succeeded.",
            checked_at=checked_at,
        )
    )


@router.patch("/{merchant_id}/dismiss-request", response_model=APIResponse[MerchantPayoutAccessResponse])
def dismiss_payout_request(
    merchant_id: uuid.UUID,
    payload: PayoutRequestDismiss,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    request: Request,
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="admin_payout_access_write", limit=20, window_seconds=60))
    ],
):
    """Clear a pending access request, granting nothing.

    Not enabling a merchant is already a refusal - their row grants
    nothing and they see the same not-enabled screen. What this fixes is
    the queue: a request nobody intends to act on sat at the top of the
    list forever, sorted above everyone else, so "new, needs a decision"
    and "looked at months ago, no" became indistinguishable.

    The merchant is not told and is not blocked. They can ask again, and
    that re-stamps the row and puts them back in the queue - which is
    the right behaviour for a business whose circumstances change.
    """
    client = get_supabase_admin()
    before = _load(client, merchant_id)

    if not before.get("access_requested_at"):
        raise ConflictError("There is no pending request on this account to dismiss.")

    after = _write(
        client,
        merchant_id=merchant_id,
        before=before,
        changes={"access_requested_at": None, "access_requested_by": None},
        expected_version=payload.version,
        admin=admin,
        request=request,
        action="payout_access.request_dismissed",
        extra_metadata={"reason": payload.reason},
    )
    logger.info(
        "payout_access_request_dismissed merchant=%s admin=%s reason=%s",
        merchant_id,
        admin.id,
        payload.reason,
    )
    return APIResponse(data=_response(client, after))
