"""Every /v1/admin* route must refuse a caller who is not a super admin.

This enumerates the live route table rather than listing paths by hand, so
an admin endpoint added later is covered the day it is written — the
failure mode these guard against is a new route shipped without its
dependency, which no hand-maintained list would catch.

A missing guard here is not a small bug: /v1/admin covers approving
withdrawals, approving merchants, pricing and KYC.
"""

import uuid

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
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _admin_routes() -> list[tuple[str, str]]:
    """(method, path) for every admin route, with path params filled in
    with a syntactically valid but nonexistent id. Authorization is checked
    before the resource is looked up, so a made-up id still exercises the
    guard — and if a route ever returned 404 before checking, that would
    itself leak whether the resource exists to an unauthorized caller."""
    routes: list[tuple[str, str]] = []
    placeholder = str(uuid.uuid4())
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/v1/admin"):
            continue
        path = route.path
        while "{" in path:
            start = path.index("{")
            end = path.index("}", start)
            path = path[:start] + placeholder + path[end + 1 :]
        for method in route.methods - {"HEAD", "OPTIONS"}:
            routes.append((method, path))
    return sorted(routes)


def test_there_are_admin_routes_to_check():
    """Guards against this whole file silently passing because the prefix
    was renamed and nothing matched any more."""
    assert len(_admin_routes()) > 20


@pytest.mark.parametrize("method,path", _admin_routes())
def test_admin_route_rejects_unauthenticated_caller(method, path, fake_client):
    response = client.request(method, path, json={})

    assert response.status_code in (401, 403), (
        f"{method} {path} returned {response.status_code} without credentials"
    )


@pytest.mark.parametrize("method,path", _admin_routes())
def test_admin_route_rejects_an_ordinary_merchant(method, path, fake_client):
    """A fully valid merchant-admin session is still not a platform
    session. This is the realistic attack: a genuine customer pointing
    their own token at the admin surface."""
    merchant = create_merchant(fake_client)
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), user_id, "MERCHANT_ADMIN")

    response = client.request(method, path, headers=auth_headers(user_id), json={})

    assert response.status_code == 403, (
        f"{method} {path} returned {response.status_code} for a non-admin merchant user"
    )


def test_super_admin_status_comes_from_the_database_not_the_token(fake_client):
    """Role claims stuffed into the JWT must not grant platform access —
    is_super_admin() reads platform_admins, and this proves it stays that
    way."""
    import jwt

    from app.config import get_settings as _s

    user_id = uuid.uuid4()
    forged = jwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "email": "attacker@example.com",
            "role": "super_admin",
            "is_super_admin": True,
            "app_metadata": {"role": "super_admin", "claims_admin": True},
            "user_metadata": {"role": "super_admin"},
        },
        _s().supabase_jwt_secret,
        algorithm="HS256",
    )

    response = client.get("/v1/admin/merchants", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 403
