"""FastAPI auth dependencies.

Building blocks, usable individually or composed by routers:

- get_current_user       verify the Supabase JWT access token
- get_current_user_id    extract the user ID from it
- get_merchant_membership  look up a user's role on a given merchant
- require_role / require_super_admin  enforce roles (JWT-only, dashboard)
- verify_api_key         verify a merchant's own API key (a separate,
                          non-Supabase-Auth credential for server-to-server
                          integrations)
- get_merchant_actor     accept *either* a JWT or an API key, for
                          merchant-scoped routes (merchant_id in the path)
- get_authenticated_caller / authorize_merchant_action  the same, split in
                          two, for flat routes with no merchant_id in the
                          path (merchant_id known only from the body or a
                          fetched row) — see app/routers/payment_links.py

All role lookups query the database (merchant_users / platform_admins) via
the service_role client in app.database.session — never Supabase Auth's
user_metadata or app_metadata, which callers can influence or which aren't
meant to be treated as an authorization source of truth.
"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.auth.hashing import hash_api_key
from app.auth.jwt import InvalidTokenError, decode_access_token
from app.core.request_ip import client_ip
from app.core.time import utc_now_iso
from app.database.session import get_supabase_admin
from app.schemas.auth import (
    ApiKeyContext,
    AuthenticatedCaller,
    AuthenticatedUser,
    MerchantActor,
    MerchantMembership,
)
from app.schemas.enums import UserRole
from app.services.crud import execute_maybe_single
from app.services.ip_allowlist import is_ip_allowed

_bearer_scheme = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> AuthenticatedUser:
    """Verify the `Authorization: Bearer <token>` header as a Supabase Auth JWT."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        claims = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject claim")

    return AuthenticatedUser(id=user_id, email=claims.get("email"))


def get_current_user_id(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> uuid.UUID:
    return user.id


def get_merchant_membership(
    merchant_id: uuid.UUID,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> MerchantMembership | None:
    """The caller's active role on `merchant_id`, or None if not a member.

    Expects `merchant_id` as a path parameter on the route this is used in
    (FastAPI resolves it automatically by matching the parameter name).
    """
    supabase = get_supabase_admin()
    data = execute_maybe_single(
        supabase.table("merchant_users")
        .select("role")
        .eq("merchant_id", str(merchant_id))
        .eq("user_id", str(user.id))
        .eq("status", "active")
        .maybe_single()
    )

    if not data:
        return None

    return MerchantMembership(merchant_id=merchant_id, user_id=user.id, role=data["role"])


def is_super_admin(user: AuthenticatedUser) -> bool:
    supabase = get_supabase_admin()
    data = execute_maybe_single(
        supabase.table("platform_admins").select("id").eq("user_id", str(user.id)).maybe_single()
    )
    return bool(data)


def require_role(*allowed_roles: UserRole):
    """Dependency factory enforcing the platform's two access rules at once:
    a super admin may always proceed; otherwise the caller must be an active
    member of `merchant_id` (a path parameter) holding one of `allowed_roles`.
    Mirrors the OR'd RLS policies in supabase/migrations/*_rls_policies.sql.
    """

    def _dependency(
        merchant_id: uuid.UUID,
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        if is_super_admin(user):
            return user

        membership = get_merchant_membership(merchant_id, user)
        if membership is None or membership.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this merchant"
            )

        return user

    return _dependency


def require_super_admin(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    """For platform-only endpoints with no merchant_id in the path at all."""
    if not is_super_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    return user


def verify_api_key(
    request: Request,
    raw_key: Annotated[str | None, Depends(_api_key_header)],
) -> ApiKeyContext:
    """Verify the `X-API-Key` header for merchant-to-InfinityPay server integrations.

    A separate credential from Supabase Auth — used by a merchant's own
    backend calling the InfinityPay API directly, not by apps/web.

    Also enforces the merchant's suspended-API-access kill switch and (for
    `live` keys with ip_whitelist_enabled=true) IP allowlist — see
    app/services/api_access.py and app/services/ip_allowlist.py — and
    records last_used_at/last_used_ip on the key. A rejection still writes
    an api_request_logs row and an audit_logs entry before raising, so it
    shows up in the merchant/Super Admin API Logs and audit trail, not
    silently.
    """
    if not raw_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")

    supabase = get_supabase_admin()
    data = execute_maybe_single(
        supabase.table("api_keys")
        .select("id, merchant_id, environment, status, scopes, ip_whitelist_enabled")
        .eq("hashed_key", hash_api_key(raw_key))
        .eq("status", "active")
        .maybe_single()
    )
    ip = client_ip(request)

    if not data:
        _write_auth_audit_log(supabase, request=request, ip=ip, action="api_key.auth_failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")

    merchant = execute_maybe_single(
        supabase.table("merchants")
        .select("api_access_suspended")
        .eq("id", data["merchant_id"])
        .maybe_single()
    )
    if merchant and merchant.get("api_access_suspended"):
        _log_api_request(
            supabase,
            merchant_id=data["merchant_id"],
            api_key_id=data["id"],
            environment=data["environment"],
            request=request,
            status_code=status.HTTP_403_FORBIDDEN,
            ip=ip,
        )
        _write_auth_audit_log(
            supabase,
            request=request,
            ip=ip,
            action="api_key.auth_failed_suspended",
            merchant_id=data["merchant_id"],
            api_key_id=data["id"],
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This merchant's API access has been suspended")

    if data["environment"] == "live" and not is_ip_allowed(
        supabase,
        merchant_id=uuid.UUID(data["merchant_id"]),
        api_key_id=uuid.UUID(data["id"]),
        environment="live",
        ip=ip,
        ip_whitelist_enabled=bool(data.get("ip_whitelist_enabled")),
    ):
        _log_api_request(
            supabase,
            merchant_id=data["merchant_id"],
            api_key_id=data["id"],
            environment=data["environment"],
            request=request,
            status_code=status.HTTP_403_FORBIDDEN,
            ip=ip,
        )
        _write_auth_audit_log(
            supabase,
            request=request,
            ip=ip,
            action="ip_allowlist.rejected",
            merchant_id=data["merchant_id"],
            api_key_id=data["id"],
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request rejected: this IP address is not on the merchant's approved allowlist",
        )

    try:
        supabase.table("api_keys").update({"last_used_at": utc_now_iso(), "last_used_ip": ip}).eq(
            "id", data["id"]
        ).execute()
    except Exception:  # noqa: BLE001, S110 — never let usage tracking fail the request
        pass

    context = ApiKeyContext(**{k: v for k, v in data.items() if k != "ip_whitelist_enabled"})
    # Picked up by ApiRequestLogMiddleware (app/middleware/api_request_log.py)
    # after the response completes — this dependency itself only handles
    # the rejection-path logs above, since those happen before a response
    # exists to log the status of.
    request.state.api_key_context = context
    request.state.client_ip = ip
    return context


def _log_api_request(
    supabase,
    *,
    merchant_id: str,
    api_key_id: str,
    environment: str,
    request: Request,
    status_code: int,
    ip: str | None,
) -> None:
    """Best-effort — a logging failure must never break the actual
    request. The success-path equivalent (every request, not just
    rejections) is ApiRequestLogMiddleware; this one call site exists
    because a rejection happens inside this dependency, before the
    middleware's own after-response hook would otherwise see which
    merchant/key it was for."""
    try:
        supabase.table("api_request_logs").insert(
            {
                "merchant_id": merchant_id,
                "api_key_id": api_key_id,
                "environment": environment,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "ip_address": ip,
            }
        ).execute()
    except Exception:  # noqa: BLE001, S110
        pass


def _write_auth_audit_log(
    supabase,
    *,
    request: Request,
    ip: str | None,
    action: str,
    merchant_id: str | None = None,
    api_key_id: str | None = None,
) -> None:
    """Best-effort audit trail entry for an API-key auth event (failed
    authentication, a suspended-merchant attempt, or a rejected IP) —
    separate from _log_api_request (api_request_logs, the per-request usage
    log): this is the compliance-facing audit_logs table, keyed by
    action/actor rather than by request."""
    try:
        supabase.table("audit_logs").insert(
            {
                "actor_type": "api_key",
                "merchant_id": merchant_id,
                "action": action,
                "resource_type": "api_key",
                "resource_id": api_key_id,
                "ip_address": ip,
                "user_agent": request.headers.get("user-agent"),
            }
        ).execute()
    except Exception:  # noqa: BLE001, S110
        pass


def _coalesce_api_key(
    api_key: str | None, credentials: HTTPAuthorizationCredentials | None
) -> str | None:
    """API keys can be sent either as `X-API-Key: <key>` or, per the public
    docs' `Authorization: Bearer <INFINITY_API_KEY>` convention, as a bearer
    token — distinguished from a Supabase Auth JWT by InfinityPay's own key
    prefix (JWTs never start with it), so a JWT bearer token is never
    mistaken for an API key and vice versa."""
    if api_key:
        return api_key
    if credentials and credentials.credentials.startswith("inf_"):
        return credentials.credentials
    return None


def require_api_key_scope(caller: AuthenticatedCaller | MerchantActor, *scopes: str) -> None:
    """Enforce a scope requirement on an API-key caller. No-ops for
    actor_type == "user" — dashboard JWT sessions already passed a role
    check and scopes are an API-key-only concept per the spec that
    introduced them. Call after get_authenticated_caller/get_merchant_actor,
    same style as authorize_merchant_action.
    """
    if caller.actor_type != "api_key":
        return
    if not scopes or set(scopes).issubset(caller.scopes):
        return
    missing = ", ".join(sorted(set(scopes) - set(caller.scopes)))
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail=f"API key missing required scope: {missing}"
    )


def get_merchant_actor(*allowed_roles: UserRole):
    """Dependency factory, mirroring require_role but accepting *either* an
    `X-API-Key` OR a Supabase dashboard JWT — whichever is present.

    Used by the handful of endpoints (initiating a collection, disbursement,
    payment link, or invoice) that a merchant's own backend can call
    directly with an API key, not only from the dashboard. An API key is
    always merchant-scoped (it's only ever issued to MERCHANT_ADMIN/DEVELOPER
    in the first place — see app/routers/merchant_portal.py::create_my_api_key)
    so `allowed_roles` is enforced on the JWT path only; a super admin always
    passes either way.
    """

    def _dependency(
        request: Request,
        merchant_id: uuid.UUID,
        api_key: Annotated[str | None, Depends(_api_key_header)] = None,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    ) -> MerchantActor:
        resolved_api_key = _coalesce_api_key(api_key, credentials)
        if resolved_api_key:
            key_context = verify_api_key(request, resolved_api_key)
            if key_context.merchant_id != merchant_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="API key does not belong to this merchant"
                )
            return MerchantActor(
                merchant_id=merchant_id, actor_type="api_key", actor_id=key_context.id, scopes=key_context.scopes
            )

        if credentials:
            user = get_current_user(credentials)
            if is_super_admin(user):
                return MerchantActor(merchant_id=merchant_id, actor_type="user", actor_id=user.id)

            membership = get_merchant_membership(merchant_id, user)
            if membership is None or (allowed_roles and membership.role not in allowed_roles):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this merchant"
                )
            return MerchantActor(merchant_id=merchant_id, actor_type="user", actor_id=user.id)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Provide an X-API-Key header or a bearer token"
        )

    return _dependency


def get_own_merchant(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> MerchantMembership:
    """Resolves the caller's own merchant purely from their active
    merchant_users membership — for /v1/merchant/* routes only, which take
    no merchant_id in the path or request body at all (unlike every other
    router, which is either nested under /v1/merchants/{merchant_id}/... or
    flat with merchant_id in the body/query).

    No super-admin bypass, unlike require_role/get_merchant_actor:
    /v1/merchant/* is a merchant-dashboard-only surface for a merchant's own
    team; super-admin tooling stays on /v1/merchants/{id}/....

    404, not 403, when there's no active membership — this deliberately
    signals "no merchant resource exists for you" (e.g. signed up but not
    yet linked to a real merchant) rather than "you exist here but aren't
    allowed," which is what 403 would imply.

    Assumes at most one active membership per user_id, matching the current
    onboarding flow (exactly one merchant per signup). If a user is ever
    allowed to belong to multiple merchants, this needs a merchant selector
    instead of resolving implicitly to the first active row.
    """
    supabase = get_supabase_admin()
    result = (
        supabase.table("merchant_users")
        .select("merchant_id, role")
        .eq("user_id", str(user.id))
        .eq("status", "active")
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No merchant account found for this user"
        )

    row = rows[0]
    return MerchantMembership(
        merchant_id=uuid.UUID(row["merchant_id"]), user_id=user.id, role=UserRole(row["role"])
    )


def require_own_merchant_role(*allowed_roles: UserRole):
    """Like require_role, but for /v1/merchant/* — merchant_id is resolved
    from the caller's own membership (get_own_merchant), never a path
    parameter. No super-admin bypass — see get_own_merchant's docstring."""

    def _dependency(
        membership: Annotated[MerchantMembership, Depends(get_own_merchant)],
    ) -> MerchantMembership:
        if allowed_roles and membership.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this action")
        return membership

    return _dependency


def get_authenticated_caller(
    request: Request,
    api_key: Annotated[str | None, Depends(_api_key_header)] = None,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> AuthenticatedCaller:
    """Like get_merchant_actor, but for *flat* routes with no merchant_id
    path segment (e.g. POST /v1/payment-links) — the target merchant isn't
    known yet at auth time. Pass the result to authorize_merchant_action()
    once it is (from the request body, or a row fetched by ID).
    """
    resolved_api_key = _coalesce_api_key(api_key, credentials)
    if resolved_api_key:
        key_context = verify_api_key(request, resolved_api_key)
        return AuthenticatedCaller(
            actor_type="api_key",
            actor_id=key_context.id,
            merchant_id=key_context.merchant_id,
            scopes=key_context.scopes,
            environment=key_context.environment,
        )

    if credentials:
        user = get_current_user(credentials)
        return AuthenticatedCaller(actor_type="user", actor_id=user.id, user=user)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Provide an X-API-Key header or a bearer token"
    )


def authorize_merchant_action(
    caller: AuthenticatedCaller, merchant_id: uuid.UUID, *allowed_roles: UserRole
) -> None:
    """Check a get_authenticated_caller() result against a merchant_id that's
    only known after the fact. Raises 403 if not authorized. Mirrors
    get_merchant_actor's rules: an API key must belong to the merchant; a
    user must be a super admin or an active member holding one of
    allowed_roles (no roles given -> any active membership suffices).
    """
    if caller.actor_type == "api_key":
        if caller.merchant_id != merchant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="API key does not belong to this merchant"
            )
        return

    assert caller.user is not None  # guaranteed by get_authenticated_caller for actor_type == "user"

    if is_super_admin(caller.user):
        return

    membership = get_merchant_membership(merchant_id, caller.user)
    if membership is None or (allowed_roles and membership.role not in allowed_roles):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this merchant")
