import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.enums import UserRole

# Same pattern app/schemas/merchant_portal.py's _EMAIL_PATTERN uses —
# deliberately not pydantic's EmailStr, which needs the email-validator
# package this codebase doesn't otherwise depend on.
_EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


class ForgotPasswordRequest(BaseModel):
    """POST /v1/auth/forgot-password — redirect_path is deliberately a
    closed set of two values, not an arbitrary URL, so a caller cannot
    point a real Supabase recovery link at a host they control. The
    Literal below IS the allow-list; Supabase's own redirect allow-list
    (docs/AUTH_SECURITY_CHECKLIST.md) is the second layer."""

    email: str = Field(pattern=_EMAIL_PATTERN)
    redirect_path: Literal["/dashboard/reset-password", "/admin-login/reset-password"] = "/dashboard/reset-password"


class AuthenticatedUser(BaseModel):
    """The caller identified by a verified Supabase Auth JWT."""

    id: uuid.UUID
    email: str | None = None
    # Supabase's own `aal` claim: "aal1" for password-only, "aal2" once a
    # second factor has been presented on THIS session. Safe to trust
    # because it is inside the signed token and set by Supabase, unlike
    # user_metadata, which the user can influence. None when the token
    # predates MFA or the claim is absent — treated as "not aal2".
    assurance_level: str | None = None


class MerchantMembership(BaseModel):
    """A user's active role within a specific merchant (merchant_users row)."""

    merchant_id: uuid.UUID
    user_id: uuid.UUID
    role: UserRole


class ApiKeyContext(BaseModel):
    """The merchant/environment identified by a verified merchant API key."""

    id: uuid.UUID
    merchant_id: uuid.UUID
    environment: str
    status: str
    scopes: list[str] = []


class MerchantActor(BaseModel):
    """The caller for endpoints that accept either a dashboard JWT or a
    merchant API key — e.g. initiating a collection or disbursement."""

    merchant_id: uuid.UUID
    actor_type: Literal["user", "api_key"]
    actor_id: uuid.UUID | None = None
    scopes: list[str] = []  # only meaningful for actor_type == "api_key"


class AuthenticatedCaller(BaseModel):
    """An authenticated caller (API key or dashboard JWT) *before* they're
    pinned to a specific merchant — for flat resource routes (e.g.
    /v1/payment-links) that have no merchant_id path segment to resolve it
    from. An API key already implies its merchant_id; a user's doesn't,
    until authorize_merchant_action() checks it against one."""

    actor_type: Literal["user", "api_key"]
    actor_id: uuid.UUID
    merchant_id: uuid.UUID | None = None  # known immediately for api_key callers
    user: AuthenticatedUser | None = None  # set for user callers, for the membership check
    scopes: list[str] = []  # only meaningful for actor_type == "api_key"
    environment: str | None = None  # "sandbox" | "live" — only set for actor_type == "api_key"
