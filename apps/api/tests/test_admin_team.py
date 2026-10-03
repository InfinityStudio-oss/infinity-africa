"""GET /v1/admin/team — the real platform_admins roster.

The dashboard used to render three invented people with Operations and
Support tiers that have never existed, on a page a Super Admin reaches
from their own sidebar. Answering "who can reach every merchant's money?"
with fiction is worse than answering it with nothing.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _admin(fake_client, *, email, full_name=None, last_sign_in_at=None):
    user_id = uuid.uuid4()
    make_super_admin(fake_client, user_id)
    fake_client.seed_auth_user(user_id, email=email, full_name=full_name)
    fake_client.auth.admin._users[str(user_id)].last_sign_in_at = last_sign_in_at
    return user_id


def _get(user_id):
    return client.get("/v1/admin/team", headers=auth_headers(user_id))


def test_the_roster_is_the_real_platform_admins_table(fake_client):
    caller = _admin(fake_client, email="ceo@infinitypay.me", last_sign_in_at="2026-10-01T18:00:00Z")
    _admin(fake_client, email="backup@infinitypay.me")

    response = _get(caller)

    assert response.status_code == 200, response.text
    emails = {row["email"] for row in response.json()["data"]}
    assert emails == {"ceo@infinitypay.me", "backup@infinitypay.me"}


def test_an_admin_who_has_never_signed_in_is_visible_as_such(fake_client):
    """The whole reason this column exists. An account that has never been
    used satisfies "a second admin exists" on paper while being unproven
    in practice — see docs/SUPER_ADMIN_MFA_RUNBOOK.md."""
    caller = _admin(fake_client, email="ceo@infinitypay.me", last_sign_in_at="2026-10-01T18:00:00Z")
    _admin(fake_client, email="backup@infinitypay.me")

    rows = {row["email"]: row for row in _get(caller).json()["data"]}

    assert rows["backup@infinitypay.me"]["last_sign_in_at"] is None
    assert rows["ceo@infinitypay.me"]["last_sign_in_at"] == "2026-10-01T18:00:00Z"


def test_every_row_reports_the_only_role_that_exists(fake_client):
    """platform_admins.role has a CHECK constraint permitting SUPER_ADMIN
    alone. Operations and Support tiers were invented by the mock."""
    caller = _admin(fake_client, email="ceo@infinitypay.me")

    assert {row["role"] for row in _get(caller).json()["data"]} == {"SUPER_ADMIN"}


def test_a_merchant_cannot_read_the_roster(fake_client):
    """Who holds platform-wide access is not a merchant's business."""
    merchant = create_merchant(fake_client)
    user_id = uuid.uuid4()
    from tests.factories import make_merchant_member

    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), user_id, "MERCHANT_ADMIN")

    assert _get(user_id).status_code in (401, 403)


def test_an_unauthenticated_caller_cannot_read_the_roster(fake_client):
    assert client.get("/v1/admin/team").status_code in (401, 403)


def test_an_admin_whose_auth_user_is_gone_still_lists(fake_client):
    """A deleted auth user must degrade to a row without an email, not
    drop the admin from the roster — a grant nobody can see is worse than
    one with a missing name."""
    caller = _admin(fake_client, email="ceo@infinitypay.me")
    orphan_id = uuid.uuid4()
    make_super_admin(fake_client, orphan_id)  # no seeded auth user

    rows = _get(caller).json()["data"]

    assert len(rows) == 2
    orphan = next(row for row in rows if row["user_id"] == str(orphan_id))
    assert orphan["email"] is None
    assert orphan["role"] == "SUPER_ADMIN"
