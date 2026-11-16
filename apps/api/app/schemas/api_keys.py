import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.ip_allowlist import _validate_ip_or_cidr

# Permission scopes a merchant can grant to a STANDARD API key. Dashboard
# JWT sessions are never scope-checked — only API-key callers are (see
# app.auth.dependencies.require_api_key_scope).
API_KEY_SCOPES: tuple[str, ...] = (
    "collections:write",
    "collections:read",
    "payment_links:write",
    "payment_links:read",
    "invoices:write",
    "invoices:read",
    "transactions:read",
    "webhooks:manage",
)

# Scopes a PAYOUT key may hold, and the only ones it may hold. Kept apart
# from API_KEY_SCOPES rather than appended to it, because the two lists are
# mutually exclusive by design: one credential that can both take money in
# and send money out makes the blast radius of a leak the whole business
# instead of one capability.
PAYOUT_KEY_SCOPES: tuple[str, ...] = (
    "payouts:create",
    "payouts:read",
)

# Deliberately in NEITHER list, and so grantable from nowhere.
#
# /v1/disbursements — the older, Collections-funded withdrawal route — asks
# for these. Leaving them ungrantable is what keeps that route reachable by
# dashboard sessions only, which is the only way it has ever been used: no
# API key has ever created a payout through it. A payout key carries
# payouts:* instead, which does not satisfy disbursements:*, so it cannot
# create, list or fetch a legacy withdrawal and cannot reach Collections
# funds that way.
#
# Granting either of these again is a deliberate act that should be argued
# for, not a box to tick. tests/test_disbursement_api_key_scopes.py fails
# if they appear in a grantable list.
LEGACY_DISBURSEMENT_SCOPES: tuple[str, ...] = (
    "disbursements:write",
    "disbursements:read",
)


def scopes_for_key_type(key_type: str) -> tuple[str, ...]:
    """The grantable scope list for a key type. Unknown types get nothing
    rather than everything — a typo must not widen a credential."""
    return PAYOUT_KEY_SCOPES if key_type == "payout" else API_KEY_SCOPES


class InlineIpAllowlistEntry(BaseModel):
    """One row of the "Enable IP whitelisting" form's inline IP list —
    submitted alongside ApiKeyCreate, not a separate POST /ip-allowlist
    call. label is optional (falls back to the IP itself for display)."""

    ip_address_or_cidr: str
    label: str | None = None

    @field_validator("ip_address_or_cidr")
    @classmethod
    def _check_ip(cls, value: str) -> str:
        return _validate_ip_or_cidr(value)


class ApiKeyCreate(BaseModel):
    name: str
    environment: str = Field(default="sandbox", pattern="^(sandbox|live)$")
    # Defaults to standard, so every existing caller and every stored
    # request body keeps meaning exactly what it meant before.
    key_type: str = Field(default="standard", pattern="^(standard|payout)$")
    scopes: list[str] = Field(default_factory=list)
    # The merchant's Part 6 choice, made once at creation. Only one of these
    # is meaningful at a time — ip_whitelist_enabled wins if both are sent,
    # see the validator below.
    ip_whitelist_enabled: bool = False
    continue_without_ip_whitelist: bool = True
    # Required (min 1) when ip_whitelist_enabled=true — the inline "Allowed
    # server IPs" list on the same form, so a merchant enabling whitelisting
    # doesn't have to leave and come back from the separate IP Allowlist
    # page before the key is even usable.
    allowed_ips: list[InlineIpAllowlistEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_scopes_against_key_type(self) -> "ApiKeyCreate":
        """Validated against the key TYPE, not one global list.

        A field_validator cannot do this: it runs before key_type is
        known, so it could only ever check the union of both lists - and
        the union is precisely what must not be grantable. A key holding
        collections:write and payouts:create together is one credential
        that both takes money in and sends it out.

        The message names the offending scopes and the type they do not
        belong to, because "unknown scope" sends an integrator looking
        for a typo when the real answer is that they asked for the wrong
        kind of key.
        """
        allowed = scopes_for_key_type(self.key_type)
        unknown = set(self.scopes) - set(allowed)
        if unknown:
            other = set(PAYOUT_KEY_SCOPES if self.key_type != "payout" else API_KEY_SCOPES)
            wrong_type = sorted(unknown & other)
            if wrong_type:
                raise ValueError(
                    f"{', '.join(wrong_type)} cannot be granted to a {self.key_type} key. "
                    "Payout keys spend the Payout Wallet and hold payouts:* only; "
                    "standard keys hold everything else."
                )
            raise ValueError(f"Unknown scope(s): {', '.join(sorted(unknown))}")
        return self

    @model_validator(mode="after")
    def _payout_keys_need_a_scope(self) -> "ApiKeyCreate":
        """A scopeless standard key is a merchant's own business - it just
        cannot call anything. A scopeless PAYOUT key is a credential that
        exists for one purpose and cannot serve it, which is far more
        likely a mistake than an intention."""
        if self.key_type == "payout" and not self.scopes:
            raise ValueError(
                "A payout key needs at least one of: " + ", ".join(PAYOUT_KEY_SCOPES)
            )
        return self

    @model_validator(mode="after")
    def _reconcile_ip_whitelist_choice(self) -> "ApiKeyCreate":
        if self.ip_whitelist_enabled:
            self.continue_without_ip_whitelist = False
        else:
            self.continue_without_ip_whitelist = True
            self.allowed_ips = []
        return self

    @model_validator(mode="after")
    def _require_at_least_one_ip_when_enabled(self) -> "ApiKeyCreate":
        if self.ip_whitelist_enabled and not self.allowed_ips:
            raise ValueError(
                "Add at least one allowed server IP or choose Continue without IP whitelisting."
            )
        return self

    @model_validator(mode="after")
    def _reject_duplicate_ips(self) -> "ApiKeyCreate":
        seen: set[str] = set()
        for entry in self.allowed_ips:
            normalized = entry.ip_address_or_cidr.strip().lower()
            if normalized in seen:
                raise ValueError(f"Duplicate IP/CIDR in the list: {entry.ip_address_or_cidr}")
            seen.add(normalized)
        return self


class ApiKeyRename(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyIpWhitelistUpdate(BaseModel):
    """Switch an existing key's IP-whitelisting choice after creation
    (Merchant Portal API key detail panel). Switching TO enabled requires
    the key to already have at least one non-rejected linked allowlist
    entry — add IPs first via POST /v1/merchant/ip-allowlist with this
    key's id, then flip this."""

    ip_whitelist_enabled: bool


class ApiKeyCreateResponse(BaseModel):
    """The ONLY response that ever carries the secret key.

    Only the secret's hash is stored, so it cannot be re-read later by
    anyone — including Super Admin and including us. The public key is
    stored in plaintext and appears in every later response, because it
    identifies the key rather than authorizing it.
    """

    id: uuid.UUID
    name: str
    environment: str
    public_key: str | None = None
    key_prefix: str
    key_last4: str | None = None
    scopes: list[str]
    ip_whitelist_enabled: bool = False
    continue_without_ip_whitelist: bool = True
    plaintext_key: str
    created_at: datetime


class ApiKeyResponse(BaseModel):
    """Every response except creation. Deliberately has no field that
    could carry the secret — not even an optional one, so no future
    handler can populate it by accident. public_key is null for keys
    issued before the pk/sk pair existed."""

    id: uuid.UUID
    name: str
    environment: str
    public_key: str | None = None
    key_prefix: str
    key_last4: str | None = None
    scopes: list[str]
    status: str
    ip_whitelist_enabled: bool = False
    continue_without_ip_whitelist: bool = True
    last_used_at: datetime | None = None
    last_used_ip: str | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
