"""Mandatory TOTP for platform admins, behind REQUIRE_SUPER_ADMIN_MFA.

Enforcement lives in require_super_admin, so it covers every /v1/admin
route at once rather than a hand-picked list — including routes written
later. The sweep at the bottom is what keeps that true.

The two checks are independent and must stay that way: MFA proves who the
caller is, the platform_admins row decides what they may do. A second
factor must never stand in for the role.
"""

import uuid

import jwt
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
    make_super_admin,
)

client = TestClient(app)

# One money-moving route, one rejection route, one read — the surfaces the
# rollout brief calls out by name.
SENSITIVE_ROUTES = [
    ("POST", "/v1/admin/withdrawals/{id}/approve"),
    ("POST", "/v1/admin/withdrawals/{id}/reject"),
    ("GET", "/v1/admin/merchants"),
]


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _mfa(monkeypatch, enabled: bool):
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "true" if enabled else "false")
    get_settings.cache_clear()


def _admin(fake_client) -> uuid.UUID:
    user_id = uuid.uuid4()
    make_super_admin(fake_client, user_id)
    return user_id


def _path(template: str) -> str:
    return template.replace("{id}", str(uuid.uuid4()))


# --- flag off: nothing changes ------------------------------------------


@pytest.mark.parametrize("method,path", SENSITIVE_ROUTES)
def test_flag_off_leaves_existing_access_untouched(method, path, fake_client, monkeypatch):
    """The default. Deploying this code must not change behaviour for an
    admin who has not enrolled yet — otherwise the first deploy locks
    everyone out of approving withdrawals."""
    _mfa(monkeypatch, False)
    admin = _admin(fake_client)

    response = client.request(method, _path(path), headers=auth_headers(admin), json={})

    assert response.status_code != 403, response.text


def test_flag_off_accepts_a_session_with_no_aal_claim_at_all(fake_client, monkeypatch):
    _mfa(monkeypatch, False)
    admin = _admin(fake_client)

    assert client.get("/v1/admin/merchants", headers=auth_headers(admin)).status_code == 200


# --- flag on: aal1 refused, aal2 allowed --------------------------------


@pytest.mark.parametrize("method,path", SENSITIVE_ROUTES)
def test_flag_on_refuses_a_password_only_session(method, path, fake_client, monkeypatch):
    _mfa(monkeypatch, True)
    admin = _admin(fake_client)

    response = client.request(method, _path(path), headers=auth_headers(admin, aal="aal1"), json={})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "mfa_required"


@pytest.mark.parametrize("method,path", SENSITIVE_ROUTES)
def test_flag_on_allows_a_second_factor_session(method, path, fake_client, monkeypatch):
    _mfa(monkeypatch, True)
    admin = _admin(fake_client)

    response = client.request(method, _path(path), headers=auth_headers(admin, aal="aal2"), json={})

    assert response.json().get("error", {}).get("code") != "mfa_required"


def test_a_missing_aal_claim_is_not_treated_as_satisfied(fake_client, monkeypatch):
    """An older token minted before MFA existed carries no aal at all. It
    must read as "not verified", never as "nothing to check"."""
    _mfa(monkeypatch, True)
    admin = _admin(fake_client)

    response = client.get("/v1/admin/merchants", headers=auth_headers(admin))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "mfa_required"


# --- MFA must not substitute for the role check -------------------------


def test_aal2_alone_does_not_make_someone_an_admin(fake_client, monkeypatch):
    """The important one. A fully MFA-verified *merchant* is still not a
    platform admin — passing a second factor proves identity, not
    authority."""
    _mfa(monkeypatch, True)
    merchant = create_merchant(fake_client)
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), user_id, "MERCHANT_ADMIN")

    response = client.get("/v1/admin/merchants", headers=auth_headers(user_id, aal="aal2"))

    assert response.status_code == 403
    assert response.json()["error"]["code"] != "mfa_required"


def test_aal2_alone_does_not_make_someone_an_admin_with_the_flag_off(fake_client, monkeypatch):
    _mfa(monkeypatch, False)
    merchant = create_merchant(fake_client)
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), user_id, "MERCHANT_ADMIN")

    assert client.get("/v1/admin/merchants", headers=auth_headers(user_id, aal="aal2")).status_code == 403


def test_forged_claims_plus_aal2_still_grant_nothing(fake_client, monkeypatch):
    """Role claims stuffed into the token, with a valid signature and a
    genuine-looking aal2, must still lose to the platform_admins lookup."""
    _mfa(monkeypatch, True)
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": "authenticated",
            "email": "attacker@example.com",
            "aal": "aal2",
            "role": "super_admin",
            "is_super_admin": True,
            "app_metadata": {"role": "super_admin"},
        },
        get_settings().supabase_jwt_secret,
        algorithm="HS256",
    )

    response = client.get("/v1/admin/merchants", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 403


def test_unauthenticated_is_still_rejected_with_the_flag_on(fake_client, monkeypatch):
    _mfa(monkeypatch, True)

    assert client.get("/v1/admin/merchants").status_code in (401, 403)


# --- a blocked admin is recorded ----------------------------------------


def test_a_blocked_admin_is_audited_without_logging_any_secret(fake_client, monkeypatch):
    _mfa(monkeypatch, True)
    admin = _admin(fake_client)

    client.get("/v1/admin/merchants", headers=auth_headers(admin, aal="aal1"))

    rows = [
        r
        for r in fake_client.table("audit_logs")._table.rows
        if r["action"] == "super_admin.mfa.required_block"
    ]
    assert len(rows) == 1
    assert rows[0]["actor_id"] == str(admin)
    # Never the token, never a code.
    serialized = str(rows[0])
    assert "Bearer" not in serialized
    assert TEST_JWT_SECRET not in serialized


# --- coverage sweep ------------------------------------------------------


def _admin_routes() -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    placeholder = str(uuid.uuid4())
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/v1/admin"):
            continue
        path = route.path
        while "{" in path:
            start = path.index("{")
            end = path.index("}", start)
            path = path[:start] + placeholder + path[end + 1 :]
        for method in route.methods - {"HEAD", "OPTIONS"}:
            routes.append((method, path))
    return sorted(routes)


@pytest.mark.parametrize("method,path", _admin_routes())
def test_every_admin_route_demands_mfa_when_the_flag_is_on(method, path, fake_client, monkeypatch):
    """Enumerated from the live route table, so an admin route added later
    is covered the day it is written rather than whenever someone
    remembers to extend a list."""
    _mfa(monkeypatch, True)
    admin = _admin(fake_client)

    response = client.request(method, path, headers=auth_headers(admin, aal="aal1"), json={})

    assert response.status_code == 403, f"{method} {path} returned {response.status_code}"
    assert response.json()["error"]["code"] == "mfa_required", f"{method} {path} not MFA-guarded"
