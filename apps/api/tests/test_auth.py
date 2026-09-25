import time
import uuid
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import dependencies as deps
from app.auth.jwt import InvalidTokenError, decode_access_token
from app.config import get_settings
from app.schemas.auth import AuthenticatedUser
from app.schemas.enums import UserRole

TEST_JWT_SECRET = "test-secret-do-not-use-in-production"


@pytest.fixture(autouse=True)
def _configure_jwt_secret(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_token(**overrides) -> str:
    payload = {
        "sub": str(uuid.uuid4()),
        "email": "user@example.com",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
        **overrides,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    """Mimics the subset of supabase-py's fluent query builder these
    dependencies use: .select().eq()...eq().maybe_single().execute()."""

    def __init__(self, data):
        self._data = data

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return _FakeResult(self._data)


class _FakeClient:
    """A fake service_role client returning canned data per table, so the
    role-enforcement logic can be tested without a real Supabase project."""

    def __init__(self, table_data: dict):
        self._table_data = table_data

    def table(self, name: str):
        return _FakeQuery(self._table_data.get(name))


class _FakeRequest:
    """Just enough of a Starlette Request for verify_api_key's IP lookup
    (client_ip()) and its post-auth `request.state.api_key_context`
    stash — real request/response plumbing is exercised end-to-end via
    TestClient elsewhere (tests/test_ip_allowlist.py), this is only for
    unit-testing verify_api_key's own logic in isolation."""

    def __init__(self):
        self.headers: dict = {}
        self.client = None
        self.state = SimpleNamespace()


# --- decode_access_token / get_current_user -------------------------------


def test_decode_access_token_returns_claims():
    user_id = str(uuid.uuid4())
    token = _make_token(sub=user_id)

    claims = decode_access_token(token)

    assert claims["sub"] == user_id
    assert claims["email"] == "user@example.com"


def test_decode_access_token_rejects_bad_signature():
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "aud": "authenticated", "exp": int(time.time()) + 3600},
        "wrong-secret",
        algorithm="HS256",
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_expired_token():
    token = _make_token(exp=int(time.time()) - 10)

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_get_current_user_extracts_id_and_email():
    user_id = str(uuid.uuid4())
    token = _make_token(sub=user_id)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = deps.get_current_user(credentials)

    assert isinstance(user, AuthenticatedUser)
    assert str(user.id) == user_id
    assert user.email == "user@example.com"


def test_get_current_user_rejects_missing_credentials():
    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_user(None)

    assert exc_info.value.status_code == 401


# --- hash_api_key / verify_api_key -----------------------------------------


def test_hash_api_key_is_deterministic_sha256_hex():
    digest = deps.hash_api_key("ik_live_abc123")

    assert digest == deps.hash_api_key("ik_live_abc123")
    assert digest != deps.hash_api_key("ik_live_abc124")
    assert len(digest) == 64
    int(digest, 16)  # raises ValueError if not valid hex


def test_verify_api_key_accepts_active_key(monkeypatch):
    merchant_id = uuid.uuid4()
    key_id = uuid.uuid4()

    monkeypatch.setattr(
        deps,
        "get_supabase_admin",
        lambda: _FakeClient(
            {
                "api_keys": {
                    "id": str(key_id),
                    "merchant_id": str(merchant_id),
                    "environment": "live",
                    "status": "active",
                }
            }
        ),
    )

    context = deps.verify_api_key(_FakeRequest(), "ik_live_abc123")

    assert context.id == key_id
    assert context.merchant_id == merchant_id
    assert context.environment == "live"


def test_verify_api_key_rejects_unknown_or_revoked_key(monkeypatch):
    monkeypatch.setattr(deps, "get_supabase_admin", lambda: _FakeClient({"api_keys": None}))

    with pytest.raises(HTTPException) as exc_info:
        deps.verify_api_key(_FakeRequest(), "ik_live_doesnotexist")

    assert exc_info.value.status_code == 401


def test_verify_api_key_rejects_missing_header():
    with pytest.raises(HTTPException) as exc_info:
        deps.verify_api_key(_FakeRequest(), None)

    assert exc_info.value.status_code == 401


# --- get_merchant_membership / require_role / require_super_admin ---------


def test_get_merchant_membership_returns_role_when_active(monkeypatch):
    merchant_id = uuid.uuid4()
    user = AuthenticatedUser(id=uuid.uuid4(), email="staff@example.com")

    monkeypatch.setattr(
        deps,
        "get_supabase_admin",
        lambda: _FakeClient({"merchant_users": {"role": "MERCHANT_STAFF"}}),
    )

    membership = deps.get_merchant_membership(merchant_id, user)

    assert membership is not None
    assert membership.role == UserRole.MERCHANT_STAFF
    assert membership.merchant_id == merchant_id


def test_get_merchant_membership_returns_none_when_not_a_member(monkeypatch):
    merchant_id = uuid.uuid4()
    user = AuthenticatedUser(id=uuid.uuid4())

    monkeypatch.setattr(
        deps, "get_supabase_admin", lambda: _FakeClient({"merchant_users": None})
    )

    assert deps.get_merchant_membership(merchant_id, user) is None


def test_require_role_denies_non_member(monkeypatch):
    merchant_id = uuid.uuid4()
    user = AuthenticatedUser(id=uuid.uuid4())

    monkeypatch.setattr(
        deps,
        "get_supabase_admin",
        lambda: _FakeClient({"merchant_users": None, "platform_admins": None}),
    )

    with pytest.raises(HTTPException) as exc_info:
        deps.require_role(UserRole.MERCHANT_ADMIN)(merchant_id, user)

    assert exc_info.value.status_code == 403


def test_require_role_denies_wrong_role(monkeypatch):
    merchant_id = uuid.uuid4()
    user = AuthenticatedUser(id=uuid.uuid4())

    monkeypatch.setattr(
        deps,
        "get_supabase_admin",
        lambda: _FakeClient(
            {"merchant_users": {"role": "DEVELOPER"}, "platform_admins": None}
        ),
    )

    # A developer may manage api_keys but not e.g. customers.
    with pytest.raises(HTTPException) as exc_info:
        deps.require_role(UserRole.MERCHANT_ADMIN, UserRole.MERCHANT_STAFF)(merchant_id, user)

    assert exc_info.value.status_code == 403


def test_require_role_allows_matching_role(monkeypatch):
    merchant_id = uuid.uuid4()
    user = AuthenticatedUser(id=uuid.uuid4())

    monkeypatch.setattr(
        deps,
        "get_supabase_admin",
        lambda: _FakeClient(
            {"merchant_users": {"role": "MERCHANT_STAFF"}, "platform_admins": None}
        ),
    )

    assert deps.require_role(UserRole.MERCHANT_STAFF)(merchant_id, user) is user


def test_require_role_lets_super_admin_bypass_merchant_check(monkeypatch):
    """Mirrors the RLS policies: a super admin can access any merchant's
    data even with no merchant_users row of their own."""
    merchant_id = uuid.uuid4()
    user = AuthenticatedUser(id=uuid.uuid4())

    monkeypatch.setattr(
        deps,
        "get_supabase_admin",
        lambda: _FakeClient(
            {"merchant_users": None, "platform_admins": {"id": str(uuid.uuid4())}}
        ),
    )

    assert deps.require_role(UserRole.MERCHANT_ADMIN)(merchant_id, user) is user


def test_require_super_admin_denies_regular_user(monkeypatch):
    user = AuthenticatedUser(id=uuid.uuid4())

    monkeypatch.setattr(
        deps, "get_supabase_admin", lambda: _FakeClient({"platform_admins": None})
    )

    with pytest.raises(HTTPException) as exc_info:
        deps.require_super_admin(_FakeRequest(), user)

    assert exc_info.value.status_code == 403


def test_require_super_admin_allows_admin(monkeypatch):
    user = AuthenticatedUser(id=uuid.uuid4())

    monkeypatch.setattr(
        deps,
        "get_supabase_admin",
        lambda: _FakeClient({"platform_admins": {"id": str(uuid.uuid4())}}),
    )

    assert deps.require_super_admin(_FakeRequest(), user) is user
