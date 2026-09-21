"""Verifies scripts/seed_test_accounts.py's idempotent upsert helpers
against the in-memory FakeSupabaseClient (same pattern as every other test
module — see tests/conftest.py::fake_client) plus a small local stand-in
for Supabase Auth's admin API, which FakeSupabaseClient doesn't otherwise
model.

Scope: this exercises the DB-write functions directly (they take `client`
as an explicit argument, not a module-level singleton), so no monkeypatch
of app.database.session.get_supabase_admin is needed for most of these —
only main()'s own end-to-end path (not covered here) would need that.
"""

import uuid

from scripts.seed_test_accounts import (
    upsert_auth_user,
    upsert_merchant,
    upsert_merchant_user,
    upsert_onboarding_submission,
    upsert_platform_admin,
)
from tests.factories import create_merchant


def test_upsert_merchant_creates_then_updates_in_place(fake_client):
    first = upsert_merchant(
        fake_client, contact_email="merchant@example.com", business_name="Biz A", contact_phone="+255700000000"
    )
    second = upsert_merchant(
        fake_client, contact_email="merchant@example.com", business_name="Biz A Renamed", contact_phone="+255711111111"
    )

    assert first == second
    rows = fake_client.table("merchants").select("*").eq("contact_email", "merchant@example.com").execute().data
    assert len(rows) == 1
    assert rows[0]["business_name"] == "Biz A Renamed"
    assert rows[0]["status"] == "active"
    assert rows[0]["kyc_status"] == "verified"


def test_upsert_merchant_user_is_idempotent(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()

    upsert_merchant_user(fake_client, merchant_id=merchant_id, user_id=user_id, role="MERCHANT_ADMIN")
    upsert_merchant_user(fake_client, merchant_id=merchant_id, user_id=user_id, role="MERCHANT_ADMIN")

    rows = (
        fake_client.table("merchant_users")
        .select("*")
        .eq("merchant_id", str(merchant_id))
        .eq("user_id", str(user_id))
        .execute()
        .data
    )
    assert len(rows) == 1
    assert rows[0]["role"] == "MERCHANT_ADMIN"
    assert rows[0]["status"] == "active"


def test_upsert_platform_admin_is_idempotent(fake_client):
    user_id = uuid.uuid4()

    upsert_platform_admin(fake_client, user_id)
    upsert_platform_admin(fake_client, user_id)

    rows = fake_client.table("platform_admins").select("*").eq("user_id", str(user_id)).execute().data
    assert len(rows) == 1
    assert rows[0]["role"] == "SUPER_ADMIN"


def test_upsert_onboarding_submission_is_verified_and_idempotent(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    reviewer_id = uuid.uuid4()

    upsert_onboarding_submission(fake_client, merchant_id=merchant_id, reviewer_id=reviewer_id)
    upsert_onboarding_submission(fake_client, merchant_id=merchant_id, reviewer_id=reviewer_id)

    rows = (
        fake_client.table("onboarding_submissions").select("*").eq("merchant_id", str(merchant_id)).execute().data
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["review_status"] == "VERIFIED"
    assert row["reviewed_by"] == str(reviewer_id)
    # NOT NULL columns in the real schema — must never be seeded blank.
    assert row["nature_of_business"]
    assert row["business_category"]
    assert row["physical_address"]
    assert row["region_city"]


class _FakeAuthAdminUser:
    def __init__(self, user_id: str, email: str, user_metadata: dict):
        self.id = user_id
        self.email = email
        self.user_metadata = user_metadata


class _FakeCreatedUser:
    def __init__(self, user: _FakeAuthAdminUser):
        self.user = user


class _FakeAuthAdminAPI:
    """Minimal stand-in for supabase_auth's SyncGoTrueAdminAPI — just the
    three calls upsert_auth_user makes. Local to this test file since
    tests/fakes.py's shared _FakeAuthAdmin only models get_user_by_id
    (what app/services/admin_directory.py needs), not account creation."""

    def __init__(self):
        self.users: dict[str, _FakeAuthAdminUser] = {}
        self.create_calls = 0
        self.update_calls = 0

    def list_users(self, page: int, per_page: int):
        if page > 1:
            return []
        return list(self.users.values())

    def create_user(self, attributes: dict) -> _FakeCreatedUser:
        self.create_calls += 1
        user_id = str(uuid.uuid4())
        user = _FakeAuthAdminUser(user_id, attributes["email"], dict(attributes.get("user_metadata") or {}))
        self.users[user_id] = user
        return _FakeCreatedUser(user)

    def update_user_by_id(self, uid: str, attributes: dict) -> _FakeCreatedUser:
        self.update_calls += 1
        user = self.users[uid]
        user.user_metadata = dict(attributes.get("user_metadata") or user.user_metadata)
        return _FakeCreatedUser(user)


class _FakeAuthNamespace:
    def __init__(self, admin: _FakeAuthAdminAPI):
        self.admin = admin


class _FakeAuthClient:
    """Only exposes .auth.admin — upsert_auth_user never touches .table()."""

    def __init__(self):
        self.auth = _FakeAuthNamespace(_FakeAuthAdminAPI())


def test_upsert_auth_user_creates_once_then_updates_on_rerun():
    client = _FakeAuthClient()

    first_id = upsert_auth_user(
        client, email="ceo@infinitypay.me", password="first-password", extra_metadata={"role": "SUPER_ADMIN"}
    )
    second_id = upsert_auth_user(
        client, email="ceo@infinitypay.me", password="second-password", extra_metadata={"role": "SUPER_ADMIN"}
    )

    assert first_id == second_id
    assert client.auth.admin.create_calls == 1
    assert client.auth.admin.update_calls == 1
    assert len(client.auth.admin.users) == 1

    user = client.auth.admin.users[str(first_id)]
    assert user.user_metadata["must_change_password"] is True
    assert user.user_metadata["seed_test_account"] is True
    assert user.user_metadata["role"] == "SUPER_ADMIN"


def test_upsert_auth_user_lookup_is_case_insensitive_on_email():
    client = _FakeAuthClient()
    upsert_auth_user(client, email="Someone@Example.com", password="pw", extra_metadata={})

    second_id = upsert_auth_user(client, email="someone@example.com", password="pw2", extra_metadata={})

    assert client.auth.admin.create_calls == 1
    assert client.auth.admin.update_calls == 1
    assert str(second_id) in client.auth.admin.users
