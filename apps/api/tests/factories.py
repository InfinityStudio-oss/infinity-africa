"""Shared test data helpers — used by test_routers.py, test_payment_links.py,
and any future router test module. Not fixtures (those stay local to each
test file, e.g. the JWT-secret/provider-settings autouse fixture each
declares) — just plain functions for seeding the FakeSupabaseClient and
minting a bearer token.
"""

import itertools
import time
import uuid

import jwt

from app.core.time import utc_now_iso

TEST_JWT_SECRET = "test-secret-do-not-use-in-production"

_merchant_code_seq = itertools.count(100000)


def _next_test_merchant_code() -> str:
    """A fresh, unique 27****** Merchant ID for each seeded test merchant —
    mirrors app/services/merchant_code.py's format without needing a real
    (or fake) database uniqueness check in test setup."""
    return f"27{next(_merchant_code_seq):06d}"


def token_for(user_id: uuid.UUID, *, aal: str | None = None) -> str:
    """`aal` mirrors Supabase's own assurance-level claim: "aal1" for a
    password-only session, "aal2" once a second factor has been
    presented. Omitted by default so every existing test keeps building
    the token it always did."""
    payload = {
        "sub": str(user_id),
        "email": "user@example.com",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    if aal is not None:
        payload["aal"] = aal
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def auth_headers(user_id: uuid.UUID, *, aal: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token_for(user_id, aal=aal)}"}


def make_super_admin(fake_client, user_id: uuid.UUID) -> None:
    fake_client.seed("platform_admins", {"user_id": str(user_id), "role": "SUPER_ADMIN"})


def make_merchant_member(fake_client, merchant_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
    fake_client.seed(
        "merchant_users",
        {"merchant_id": str(merchant_id), "user_id": str(user_id), "role": role, "status": "active"},
    )


def create_merchant(fake_client, **overrides) -> dict:
    data = {
        "business_name": "Test Merchant",
        "merchant_code": _next_test_merchant_code(),
        "legal_name": None,
        "country": "TZ",
        "currency": "TZS",
        "contact_email": "merchant@example.com",
        "contact_phone": None,
        "status": "active",
        "kyc_status": "verified",
        **overrides,
    }
    return fake_client.seed("merchants", data)


def create_pricing_rule(fake_client, *, merchant_id: uuid.UUID | None = None, **overrides) -> dict:
    """Seeds a merchant_pricing_rules row. merchant_id=None means a
    platform fallback rule. Defaults to a zero-fee, always-active,
    no-scope (channel/destination_code both null) rule — override
    whichever fields a given test needs to exercise precedence/fee math."""
    now = utc_now_iso()
    data = {
        "merchant_id": str(merchant_id) if merchant_id else None,
        "channel": None,
        "destination_code": None,
        "percentage_fee": "0",
        "flat_fee": "0",
        "minimum_fee": None,
        "maximum_fee": None,
        "processor_fee_flat": "0",
        "processor_fee_pass_through": False,
        "effective_from": now,
        "effective_to": None,
        "is_active": True,
        "label": None,
        "created_by": None,
        **overrides,
    }
    return fake_client.seed("merchant_pricing_rules", data)


def create_collection_pricing_rule(fake_client, *, merchant_id: uuid.UUID | None = None, **overrides) -> dict:
    """Seeds a merchant_collection_pricing_rules row (see
    app/services/collection_pricing.py) — the collection-side sibling of
    create_pricing_rule above. merchant_id=None means a platform fallback
    rule. Defaults to a zero-fee, always-active, no-channel-scope rule —
    override whichever fields a given test needs to exercise
    precedence/fee math."""
    now = utc_now_iso()
    data = {
        "merchant_id": str(merchant_id) if merchant_id else None,
        "channel": None,
        "percentage_fee": "0",
        "flat_fee": "0",
        "minimum_fee": None,
        "maximum_fee": None,
        "effective_from": now,
        "effective_to": None,
        "is_active": True,
        "label": None,
        "notes": None,
        "created_by": None,
        **overrides,
    }
    return fake_client.seed("merchant_collection_pricing_rules", data)


def seed_fraud_rules(fake_client, *rule_codes: str, config_overrides: dict | None = None) -> None:
    """Seeds only the given fraud_rules rows (enabled), matching
    supabase/migrations/20260817090000_fraud_monitoring.sql's defaults —
    fraud_monitoring_service.py no-ops for any rule not present/enabled in
    this table, so a test must seed exactly the rule(s) it's exercising."""
    defaults = {
        "SAME_PHONE_SAME_AMOUNT_SECONDS": {"window_seconds": 30},
        "SAME_PHONE_TOO_MANY_ATTEMPTS": {"window_minutes": 10, "max_attempts": 5},
        "DUPLICATE_REFERENCE": {},
        "PAYMENT_AFTER_LINK_EXPIRY": {},
        "HIGH_VALUE_TRANSACTION": {"threshold_amount": 5000000},
        "HIGH_CHARGEBACK_MERCHANT": {"window_days": 30, "max_dispute_count": 3, "max_dispute_ratio": 0.05},
        "SELF_PAYMENT_OWN_TILL": {},
    }
    overrides = config_overrides or {}
    for code in rule_codes:
        config = {**defaults[code], **overrides.get(code, {})}
        fake_client.seed(
            "fraud_rules",
            {"rule_code": code, "label": code, "description": None, "enabled": True, "config": config},
        )


def create_transaction(fake_client, merchant_id: uuid.UUID, **overrides) -> dict:
    data = {
        "merchant_id": str(merchant_id),
        "reference": f"TXN-TEST-{uuid.uuid4().hex[:8].upper()}",
        "type": "collection",
        "method": "USSD_PUSH",
        "gross_amount": "1000",
        "fee_amount": "0",
        "net_amount": "1000",
        "currency": "TZS",
        "status": "successful",
        "metadata": {},
        **overrides,
    }
    return fake_client.seed("transactions", data)


def make_api_key(
    fake_client,
    merchant_id: uuid.UUID,
    *,
    environment: str = "live",
    scopes: list[str] | None = None,
    ip_whitelist_enabled: bool = False,
) -> tuple[str, dict]:
    """Seeds an active api_keys row and returns (raw_key, row) — the raw key
    is what a test sends as X-API-Key; only its hash is ever stored, exactly
    as app/routers/merchant_portal.py::create_my_api_key does it for real.

    Defaults to every scope (API_KEY_SCOPES) so existing tests that aren't
    specifically about scope enforcement don't need to know the scope list —
    pass an explicit, narrower `scopes` to test scope restriction itself.

    ip_whitelist_enabled defaults to False (the merchant's "continue without
    IP whitelisting" default) — pass True for tests exercising allowlist
    enforcement (app.services.ip_allowlist.is_ip_allowed)."""
    from app.auth import hash_api_key
    from app.schemas.api_keys import API_KEY_SCOPES

    raw_key = f"inf_{environment}_{uuid.uuid4().hex}"
    row = fake_client.seed(
        "api_keys",
        {
            "merchant_id": str(merchant_id),
            "name": "Test key",
            "environment": environment,
            "key_prefix": raw_key[:16],
            "key_last4": raw_key[-4:],
            "hashed_key": hash_api_key(raw_key),
            "scopes": list(API_KEY_SCOPES) if scopes is None else scopes,
            "status": "active",
            "ip_whitelist_enabled": ip_whitelist_enabled,
            "continue_without_ip_whitelist": not ip_whitelist_enabled,
        },
    )
    return raw_key, row
