"""Seed idempotent test/demo accounts for local development and first
Merchant Portal / Super Admin testing: one SUPER_ADMIN and one
already-approved MERCHANT_ADMIN.

Usage (from apps/api, with SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY already
set in .env — same client this backend uses, see app/database/session.py):

    export SEED_SUPER_ADMIN_PASSWORD='...'      # PowerShell: $env:SEED_SUPER_ADMIN_PASSWORD='...'
    export SEED_MERCHANT_PASSWORD='...'
    python -m scripts.seed_test_accounts

No password is hardcoded anywhere in this file — both are required
environment variables (see docs/test-accounts.md for suggested values and
the full runbook). The script never prints a password, a service_role key,
or a full access token; only emails/IDs/status are echoed back.

Safe to re-run: every write below looks up the existing row first (by
email / user_id / merchant_id / contact_email) and updates it in place
rather than inserting a duplicate.

Production safety: if ENVIRONMENT (see app/config/settings.py) is not
"development", the script refuses to run unless SEED_CONFIRM_PRODUCTION=yes
is also set. Either way, both seeded Supabase Auth users are tagged
user_metadata={"seed_test_account": true, "must_change_password": true} —
change these passwords immediately after first login and remove the
accounts entirely before a real go-live (see docs/test-accounts.md).
"""

from __future__ import annotations

import os
import sys
import uuid

from supabase import Client

from app.config import get_settings
from app.core.time import utc_now_iso
from app.database.session import get_supabase_admin
from app.services.crud import execute_maybe_single, insert_row, update_row

SUPER_ADMIN_EMAIL_DEFAULT = "ceo@infinitypay.me"
MERCHANT_EMAIL_DEFAULT = "paulmasanja008@gmail.com"
MERCHANT_BUSINESS_NAME_DEFAULT = "InfinityPay Test Merchant"
MERCHANT_CONTACT_PHONE_DEFAULT = "+255747730270"

_LIST_USERS_PAGE_SIZE = 200
_LIST_USERS_MAX_PAGES = 25  # safety cap (5,000 users) for a seed script


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"Missing required environment variable {name}. "
            "Set it before running this script — see docs/test-accounts.md. "
            "Passwords are never hardcoded in this script."
        )
    return value


def _find_auth_user_by_email(client: Client, email: str):
    admin = client.auth.admin
    target = email.strip().lower()
    for page in range(1, _LIST_USERS_MAX_PAGES + 1):
        users = admin.list_users(page=page, per_page=_LIST_USERS_PAGE_SIZE)
        if not users:
            break
        for user in users:
            if (user.email or "").strip().lower() == target:
                return user
        if len(users) < _LIST_USERS_PAGE_SIZE:
            break
    return None


def upsert_auth_user(client: Client, *, email: str, password: str, extra_metadata: dict) -> uuid.UUID:
    """Create the Supabase Auth user if it doesn't exist, or reset its
    password + metadata in place if it does. Returns the auth user_id.
    """
    metadata = {"seed_test_account": True, "must_change_password": True, **extra_metadata}

    existing = _find_auth_user_by_email(client, email)
    if existing is not None:
        client.auth.admin.update_user_by_id(
            existing.id,
            {
                "password": password,
                "email_confirm": True,
                "user_metadata": {**(existing.user_metadata or {}), **metadata},
            },
        )
        return uuid.UUID(existing.id)

    created = client.auth.admin.create_user(
        {
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": metadata,
        }
    )
    return uuid.UUID(created.user.id)


def upsert_platform_admin(client: Client, user_id: uuid.UUID) -> None:
    existing = execute_maybe_single(
        client.table("platform_admins").select("id").eq("user_id", str(user_id)).maybe_single()
    )
    if existing:
        return
    insert_row(client, "platform_admins", {"user_id": str(user_id), "role": "SUPER_ADMIN"})


def upsert_merchant(
    client: Client, *, contact_email: str, business_name: str, contact_phone: str, country: str = "TZ"
) -> uuid.UUID:
    """Approved for testing: status=active, kyc_status=verified (the real
    schema's vocabulary — see supabase/migrations/20260814090001_merchants.sql
    — there is no separate "APPROVED_FOR_TESTING" value).

    Looks up by exact contact_email match — safe because this script always
    passes the same literal, already-lowercase email; the table's real
    uniqueness constraint is on lower(contact_email)."""
    fields = {
        "business_name": business_name,
        "contact_phone": contact_phone,
        "country": country,
        "status": "active",
        "kyc_status": "verified",
    }

    existing = execute_maybe_single(
        client.table("merchants").select("id").eq("contact_email", contact_email).maybe_single()
    )
    if existing:
        merchant_id = uuid.UUID(existing["id"])
        update_row(client, "merchants", merchant_id, fields)
        return merchant_id

    row = insert_row(
        client,
        "merchants",
        {"contact_email": contact_email, "currency": "TZS", **fields},
    )
    return uuid.UUID(row["id"])


def upsert_merchant_user(client: Client, *, merchant_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
    existing = execute_maybe_single(
        client.table("merchant_users")
        .select("id")
        .eq("merchant_id", str(merchant_id))
        .eq("user_id", str(user_id))
        .maybe_single()
    )
    fields = {"role": role, "status": "active"}
    if existing:
        update_row(client, "merchant_users", uuid.UUID(existing["id"]), fields)
        return
    insert_row(
        client,
        "merchant_users",
        {"merchant_id": str(merchant_id), "user_id": str(user_id), **fields},
    )


def upsert_onboarding_submission(client: Client, *, merchant_id: uuid.UUID, reviewer_id: uuid.UUID) -> None:
    """Marks onboarding as already VERIFIED so /merchant/overview in
    apps/web renders the real dashboard immediately (see
    app/services/onboarding.py::get_onboarding_status — next_path is only
    "/merchant/overview" once review_status is in _ONBOARDED_STATUSES)."""
    fields = {
        "review_status": "VERIFIED",
        "review_note": None,
        "reviewed_by": str(reviewer_id),
        "reviewed_at": utc_now_iso(),
    }

    existing = execute_maybe_single(
        client.table("onboarding_submissions").select("id").eq("merchant_id", str(merchant_id)).maybe_single()
    )
    if existing:
        update_row(client, "onboarding_submissions", uuid.UUID(existing["id"]), fields)
        return

    insert_row(
        client,
        "onboarding_submissions",
        {
            "merchant_id": str(merchant_id),
            "nature_of_business": "Testing / QA",
            "business_category": "Other",
            "physical_address": "N/A (seeded test account)",
            "region_city": "Dar es Salaam",
            "website_url": None,
            "services_needed": [],
            "accepted_terms": True,
            "accepted_privacy": True,
            "accepted_at": utc_now_iso(),
            "submitted_at": utc_now_iso(),
            **fields,
        },
    )


def _guard_production(settings) -> None:
    if settings.environment == "development":
        return
    if (_env("SEED_CONFIRM_PRODUCTION") or "").lower() == "yes":
        print(
            f"WARNING: ENVIRONMENT={settings.environment!r} — seeding test accounts against a "
            "non-development environment. Both accounts are tagged must_change_password=true; "
            "remove them before go-live."
        )
        return
    raise SystemExit(
        f"Refusing to run: ENVIRONMENT={settings.environment!r} is not 'development'. "
        "If you really intend to seed test accounts here, set SEED_CONFIRM_PRODUCTION=yes "
        "and re-run. Change these passwords immediately after first login and delete the "
        "accounts before real go-live — see docs/test-accounts.md."
    )


def main() -> int:
    settings = get_settings()
    _guard_production(settings)

    super_admin_password = _require_env("SEED_SUPER_ADMIN_PASSWORD")
    merchant_password = _require_env("SEED_MERCHANT_PASSWORD")

    super_admin_email = _env("SEED_SUPER_ADMIN_EMAIL", SUPER_ADMIN_EMAIL_DEFAULT)
    merchant_email = _env("SEED_MERCHANT_EMAIL", MERCHANT_EMAIL_DEFAULT)
    merchant_business_name = _env("SEED_MERCHANT_BUSINESS_NAME", MERCHANT_BUSINESS_NAME_DEFAULT)
    merchant_contact_phone = _env("SEED_MERCHANT_CONTACT_PHONE", MERCHANT_CONTACT_PHONE_DEFAULT)

    client = get_supabase_admin()

    super_admin_id = upsert_auth_user(
        client,
        email=super_admin_email,
        password=super_admin_password,
        extra_metadata={"role": "SUPER_ADMIN"},
    )
    upsert_platform_admin(client, super_admin_id)

    merchant_user_id = upsert_auth_user(
        client,
        email=merchant_email,
        password=merchant_password,
        extra_metadata={"role": "MERCHANT_ADMIN"},
    )
    merchant_id = upsert_merchant(
        client,
        contact_email=merchant_email,
        business_name=merchant_business_name,
        contact_phone=merchant_contact_phone,
    )
    upsert_merchant_user(client, merchant_id=merchant_id, user_id=merchant_user_id, role="MERCHANT_ADMIN")
    upsert_onboarding_submission(client, merchant_id=merchant_id, reviewer_id=super_admin_id)

    print("Seed complete. Passwords and the service_role key are never printed by this script.\n")
    print(f"  SUPER_ADMIN  email={super_admin_email}  user_id={super_admin_id}")
    print(f"  MERCHANT     email={merchant_email}  user_id={merchant_user_id}  merchant_id={merchant_id}")
    print("               merchant.status=active  merchant.kyc_status=verified  onboarding=VERIFIED")
    print("\nBoth accounts are tagged must_change_password=true — change passwords after first login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
