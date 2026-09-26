"""Sandbox and live pk/sk key pairs.

The properties worth holding here are the ones whose failure is silent: a
secret leaking into a later response, a public key quietly authenticating,
a sandbox key reaching live money, or an existing merchant's key breaking
when the format changed underneath them.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.hashing import hash_api_key
from app.config import get_settings
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    create_pricing_rule,
    make_api_key,
    make_merchant_member,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def approved(fake_client):
    """A merchant eligible for live keys.

    A pricing rule is part of eligibility, not incidental setup:
    check_production_api_access refuses live keys for an account with
    no pricing, since a live key that transacted at no agreed rate
    would be un-billable."""
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    create_pricing_rule(fake_client, merchant_id=merchant_id)
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    return merchant, user_id


def _create(user_id, environment: str, **extra):
    return client.post(
        "/v1/merchant/api-keys",
        headers=auth_headers(user_id),
        json={"name": f"{environment} key", "scopes": ["collections:write"], **extra,
              "environment": environment},
    )


# --- format --------------------------------------------------------------


def test_sandbox_keys_use_the_test_prefixes(approved):
    _merchant, user_id = approved

    response = _create(user_id, "sandbox")

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["public_key"].startswith("pk_test_")
    assert data["plaintext_key"].startswith("sk_test_")
    assert data["environment"] == "sandbox"


def test_live_keys_use_the_live_prefixes(approved):
    _merchant, user_id = approved

    response = _create(user_id, "live")

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["public_key"].startswith("pk_live_")
    assert data["plaintext_key"].startswith("sk_live_")


def test_the_public_and_secret_halves_are_independent(approved):
    """The public half is shown, quoted and logged freely, so it must reveal
    nothing about the secret."""
    _merchant, user_id = approved

    data = _create(user_id, "live").json()["data"]

    public_body = data["public_key"].split("_", 2)[2]
    secret_body = data["plaintext_key"].split("_", 2)[2]
    assert public_body != secret_body
    assert public_body not in data["plaintext_key"]
    assert secret_body not in data["public_key"]


# --- the secret is shown exactly once ------------------------------------


def test_the_secret_never_appears_again_after_creation(approved, fake_client):
    _merchant, user_id = approved
    created = _create(user_id, "live").json()["data"]
    secret = created["plaintext_key"]

    listed = client.get("/v1/merchant/api-keys", headers=auth_headers(user_id))

    assert listed.status_code == 200, listed.text
    assert secret not in listed.text
    assert "plaintext_key" not in listed.text
    # The public half, by contrast, is meant to be there.
    assert created["public_key"] in listed.text


def test_only_the_hash_of_the_secret_is_stored(approved, fake_client):
    _merchant, user_id = approved
    created = _create(user_id, "live").json()["data"]
    secret = created["plaintext_key"]

    row = next(
        r for r in fake_client.table("api_keys")._table.rows if r["id"] == created["id"]
    )
    assert row["hashed_key"] == hash_api_key(secret)
    assert secret not in str(row)
    # The public key IS stored in the clear — it is not a credential.
    assert row["public_key"] == created["public_key"]


def test_no_secret_reaches_the_audit_trail(approved, fake_client):
    _merchant, user_id = approved
    secret = _create(user_id, "live").json()["data"]["plaintext_key"]

    serialized = str(fake_client.table("audit_logs")._table.rows)
    assert secret not in serialized
    assert secret[8:] not in serialized


# --- a public key is not a credential ------------------------------------


def test_a_public_key_cannot_authenticate(approved, fake_client):
    """The whole point of the split. Rejected with a message naming the
    mistake, since the usual cause is pasting the wrong half."""
    merchant, user_id = approved
    created = _create(user_id, "live").json()["data"]

    response = client.get(
        f"/v1/collections/{uuid.uuid4()}?merchant_id={merchant['id']}",
        headers={"X-API-Key": created["public_key"]},
    )

    assert response.status_code == 401
    assert "public key" in response.text.lower()


def test_a_public_key_is_also_refused_as_a_bearer_token(approved, fake_client):
    merchant, user_id = approved
    created = _create(user_id, "live").json()["data"]

    response = client.get(
        f"/v1/collections/{uuid.uuid4()}?merchant_id={merchant['id']}",
        headers={"Authorization": f"Bearer {created['public_key']}"},
    )

    assert response.status_code == 401


def test_the_secret_key_does_authenticate(approved, fake_client):
    merchant, user_id = approved
    created = _create(user_id, "live").json()["data"]

    response = client.get(
        f"/v1/collections/{uuid.uuid4()}?merchant_id={merchant['id']}",
        headers={"X-API-Key": created["plaintext_key"]},
    )

    # 404 for the made-up collection id — but authentication passed, which
    # is what this asserts.
    assert response.status_code != 401


# --- existing merchants must not break -----------------------------------


def test_keys_issued_before_the_pair_existed_still_authenticate(fake_client):
    """8 keys in production predate this change. They have no public half
    and must keep working: authentication matches hashed_key, which did not
    change."""
    merchant = create_merchant(fake_client)
    raw, row = make_api_key(fake_client, merchant_id=uuid.UUID(merchant["id"]))
    assert raw.startswith("inf_")
    assert row.get("public_key") is None

    response = client.get(
        f"/v1/collections/{uuid.uuid4()}?merchant_id={merchant['id']}",
        headers={"X-API-Key": raw},
    )

    assert response.status_code != 401


def test_a_legacy_key_lists_without_a_public_key_rather_than_erroring(fake_client):
    merchant = create_merchant(fake_client)
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), user_id, "MERCHANT_ADMIN")
    make_api_key(fake_client, merchant_id=uuid.UUID(merchant["id"]))

    response = client.get("/v1/merchant/api-keys", headers=auth_headers(user_id))

    assert response.status_code == 200, response.text
    assert response.json()["data"][0]["public_key"] is None


# --- rotation -------------------------------------------------------------


def test_rotation_replaces_both_halves(approved, fake_client):
    """Keeping the public half would leave a rotated-away secret and its
    replacement sharing an identifier, so a leaked key could not be told
    apart from its successor."""
    _merchant, user_id = approved
    original = _create(user_id, "live").json()["data"]

    rotated = client.post(
        f"/v1/merchant/api-keys/{original['id']}/rotate", headers=auth_headers(user_id)
    )

    assert rotated.status_code in (200, 201), rotated.text
    new = rotated.json()["data"]
    assert new["public_key"] != original["public_key"]
    assert new["plaintext_key"] != original["plaintext_key"]
    assert new["public_key"].startswith("pk_live_")


# --- eligibility ----------------------------------------------------------


def test_an_unapproved_merchant_cannot_mint_keys(fake_client):
    merchant = create_merchant(fake_client, status="pending")
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), user_id, "MERCHANT_ADMIN")

    for environment in ("sandbox", "live"):
        response = _create(user_id, environment)
        assert response.status_code in (403, 409, 422), f"{environment}: {response.text}"


def test_a_merchant_cannot_see_another_merchants_public_keys(fake_client, approved):
    """The public key is not secret, but it is still another merchant's
    business and must not appear in an unrelated listing."""
    _merchant_a, user_a = approved
    created = _create(user_a, "live").json()["data"]

    other = create_merchant(fake_client)
    user_b = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(other["id"]), user_b, "MERCHANT_ADMIN")

    listed = client.get("/v1/merchant/api-keys", headers=auth_headers(user_b))

    assert listed.status_code == 200, listed.text
    assert created["public_key"] not in listed.text
