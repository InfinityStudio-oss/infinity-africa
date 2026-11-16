"""Which build is running — behind Super Admin, never on /health.

A public build marker was tried and reverted. This repository is public,
so a commit hash on an unauthenticated endpoint lets anyone resolve the
running build's exact dependency tree and look up which advisories apply
to it. That is a worse trade than the convenience it buys, and
test_health_reveals_nothing_beyond_liveness already encodes the rule.
The question is still worth answering — just not to everyone.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import TEST_JWT_SECRET, auth_headers, make_super_admin

client = TestClient(app)

PATH = "/v1/admin/diagnostics/deployment"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _admin(fake_client):
    user_id = uuid.uuid4()
    make_super_admin(fake_client, user_id)
    return user_id


def test_it_reports_the_commit_the_container_was_built_from(fake_client, monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "a26a87e1234567890abcdef")
    admin_id = _admin(fake_client)

    body = client.get(PATH, headers=auth_headers(admin_id, aal="aal2")).json()["data"]

    assert body["revision"] == "a26a87e12345"
    assert body["source"] == "RAILWAY_GIT_COMMIT_SHA"


def test_it_says_nothing_rather_than_guessing(fake_client, monkeypatch):
    for name in (
        "RAILWAY_GIT_COMMIT_SHA",
        "VERCEL_GIT_COMMIT_SHA",
        "RENDER_GIT_COMMIT",
        "SOURCE_COMMIT",
        "GIT_COMMIT",
    ):
        monkeypatch.delenv(name, raising=False)
    admin_id = _admin(fake_client)

    body = client.get(PATH, headers=auth_headers(admin_id, aal="aal2")).json()["data"]

    assert body["revision"] is None


def test_a_merchant_cannot_read_it(fake_client):
    from tests.factories import create_merchant, make_merchant_member

    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")

    response = client.get(PATH, headers=auth_headers(user_id, aal="aal2"))

    assert response.status_code == 403, response.text


def test_an_api_key_cannot_read_it(fake_client):
    from tests.factories import create_merchant, make_api_key

    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    raw_key, _row = make_api_key(fake_client, merchant_id, scopes=["transactions:read"])

    response = client.get(PATH, headers={"X-API-Key": raw_key})

    assert response.status_code in (401, 403), response.text


def test_an_unauthenticated_request_cannot_read_it(fake_client):
    assert client.get(PATH).status_code == 401


def test_a_super_admin_without_mfa_cannot_read_it(fake_client):
    admin_id = _admin(fake_client)

    response = client.get(PATH, headers=auth_headers(admin_id))

    assert response.status_code == 403, response.text


def test_the_public_health_endpoint_still_says_nothing_about_the_build(fake_client, monkeypatch):
    """The guard this feature must not break. Liveness is public; the
    build is not."""
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "a26a87e1234567890abcdef")

    body = client.get("/health").json()

    assert set(body.keys()) <= {"status", "environment"}
    assert "a26a87e" not in str(body)
