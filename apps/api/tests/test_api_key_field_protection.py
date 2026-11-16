"""What a merchant may change about an issued credential, and what they
may not.

Three gaps closed here, all of them in the same shape: a key's *type* is
what decides which scopes it can hold and whether the payout enablement
trigger inspects it at all, so anything that can change the type, or
separate the type from the scopes, is an authorization bug wearing
plumbing clothes.

1. Rotation minted the replacement without carrying key_type over. The
   new row took the column default of 'standard' while keeping the old
   key's payout scopes - and assert_payout_key_allowed() returns early
   for anything that is not key_type 'payout', so the replacement was
   never checked against merchant_payout_settings. Rotating was a way to
   get a working payout credential for a merchant whose payouts had
   since been switched off.

2. The mutation schemas ignored unknown fields instead of refusing them.
   The routes only ever wrote the one field they name, so nothing could
   actually be changed - but a caller who sent `scopes` got a 200 and no
   indication their request had been discarded, which on a credential
   reads as "narrowed" when nothing was narrowed.

3. Nothing checked, at authentication time, that a key's stored scopes
   were ones its type can hold. Creation checks it, but creation is not
   the only thing that writes these rows: (1) was one way to end up with
   a mismatched one, and a backfill or a support fix is another.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import get_settings
from app.main import app
from app.schemas.api_keys import (
    API_KEY_SCOPES,
    PAYOUT_KEY_SCOPES,
    ApiKeyCreate,
    ApiKeyIpWhitelistUpdate,
    ApiKeyRename,
)
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
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _request_with_key(raw_key: str):
    """The smallest Request verify_api_key will accept."""
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/transactions",
            "headers": [(b"x-api-key", raw_key.encode())],
            "client": ("203.0.113.10", 1234),
            "query_string": b"",
        }
    )


def _merchant(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    return merchant_id, admin_id


# --- the schemas refuse what they cannot apply -------------------------------


@pytest.mark.parametrize(
    "model, payload",
    [
        (ApiKeyRename, {"name": "renamed", "scopes": ["collections:write"]}),
        (ApiKeyRename, {"name": "renamed", "key_type": "payout"}),
        (ApiKeyRename, {"name": "renamed", "status": "active"}),
        (ApiKeyRename, {"name": "renamed", "merchant_id": str(uuid.uuid4())}),
        (ApiKeyRename, {"name": "renamed", "hashed_key": "x"}),
        (ApiKeyIpWhitelistUpdate, {"ip_whitelist_enabled": True, "key_type": "payout"}),
        (ApiKeyIpWhitelistUpdate, {"ip_whitelist_enabled": True, "scopes": []}),
    ],
)
def test_a_protected_field_is_refused_not_dropped(model, payload):
    """Silently discarding a field on a credential request is the failure
    mode: the caller is told it worked."""
    with pytest.raises(ValidationError) as caught:
        model(**payload)

    assert "extra" in str(caught.value).lower()


def test_the_field_a_merchant_may_change_still_works():
    assert ApiKeyRename(name="Production backend").name == "Production backend"
    assert ApiKeyIpWhitelistUpdate(ip_whitelist_enabled=True).ip_whitelist_enabled is True


def test_create_also_refuses_an_unknown_field():
    with pytest.raises(ValidationError):
        ApiKeyCreate(name="k", environment="sandbox", status="active")


def test_renaming_a_key_with_a_protected_field_is_a_422(fake_client):
    """End to end, because a schema that forbids extras is only useful if
    the route is actually using that schema."""
    merchant_id, admin_id = _merchant(fake_client)
    _raw, row = make_api_key(fake_client, merchant_id)

    response = client.patch(
        f"/v1/merchant/api-keys/{row['id']}",
        json={"name": "renamed", "scopes": list(PAYOUT_KEY_SCOPES)},
        headers=auth_headers(admin_id),
    )

    assert response.status_code == 422, response.text


# --- a key may only act on the scopes its type can hold ----------------------


def test_a_standard_key_does_not_carry_payout_scopes_into_a_request(fake_client):
    """The drifted row (1) produced. It authenticates - it is a real,
    active key - but the payout scopes are not its to hold, so they must
    not be on the caller the routes see.

    Asserted on the authenticated context rather than through a route,
    because the routes that read these scopes are the subject of the next
    milestone; what matters here is that the scope never survives
    authentication in the first place.
    """
    from app.auth.dependencies import verify_api_key

    merchant_id, _admin_id = _merchant(fake_client)
    raw_key, _row = make_api_key(
        fake_client,
        merchant_id,
        scopes=["collections:write", *PAYOUT_KEY_SCOPES],
    )

    request = _request_with_key(raw_key)
    context = verify_api_key(request, raw_key)

    assert set(context.scopes) == {"collections:write"}
    for scope in PAYOUT_KEY_SCOPES:
        assert scope not in context.scopes


def test_narrowing_never_removes_a_scope_the_type_can_hold(fake_client):
    """The check is an intersection, so it can only take away.

    This is the half that would make the fix dangerous if it were wrong:
    a narrowing that overreached would silently revoke working
    integrations, and the symptom would be live merchants getting 403s on
    calls that worked yesterday.
    """
    from app.auth.dependencies import verify_api_key

    merchant_id, _admin_id = _merchant(fake_client)
    legitimate = ["transactions:read", "collections:read", "collections:write"]
    raw_key, _row = make_api_key(
        fake_client, merchant_id, scopes=[*legitimate, "payouts:create"]
    )

    context = verify_api_key(_request_with_key(raw_key), raw_key)

    assert set(context.scopes) == set(legitimate)


def test_a_payout_key_keeps_its_own_scopes(fake_client):
    """The mirror image: narrowing a payout key must not strip the
    scopes that are precisely the ones it exists to carry."""
    from app.auth.dependencies import verify_api_key

    merchant_id, _admin_id = _merchant(fake_client)
    fake_client.seed(
        "merchant_payout_settings",
        {"merchant_id": str(merchant_id), "live_enabled": True, "sandbox_enabled": True},
    )
    raw_key, _row = make_api_key(
        fake_client, merchant_id, scopes=list(PAYOUT_KEY_SCOPES), key_type="payout"
    )

    context = verify_api_key(_request_with_key(raw_key), raw_key)

    assert set(context.scopes) == set(PAYOUT_KEY_SCOPES)


def test_every_payout_scope_is_refused_to_a_standard_key(fake_client):
    """Pins the two lists against each other rather than naming scopes,
    so adding one to either list cannot quietly skip this."""
    assert not set(PAYOUT_KEY_SCOPES) & set(API_KEY_SCOPES), (
        "a scope in both lists would make the key type meaningless"
    )


# --- rotation carries the type with the scopes -------------------------------


def test_rotation_keeps_the_key_type(fake_client):
    """The fix for (1). Rotation copies scopes, so it must copy the type
    that decides whether those scopes are legal - and whether the payout
    enablement trigger looks at the row at all.
    """
    merchant_id, admin_id = _merchant(fake_client)
    create_pricing_rule(fake_client, merchant_id=merchant_id)
    fake_client.seed(
        "merchant_payout_settings",
        {"merchant_id": str(merchant_id), "live_enabled": True, "sandbox_enabled": True},
    )
    _raw, row = make_api_key(
        fake_client,
        merchant_id,
        scopes=list(PAYOUT_KEY_SCOPES),
        key_type="payout",
    )

    response = client.post(
        f"/v1/merchant/api-keys/{row['id']}/rotate",
        headers=auth_headers(admin_id),
    )

    assert response.status_code == 201, response.text
    rotated = [
        r
        for r in fake_client.table("api_keys")._table.rows
        if r["status"] == "active" and r["merchant_id"] == str(merchant_id)
    ]
    assert len(rotated) == 1
    assert rotated[0]["key_type"] == "payout", (
        "a rotated payout key that came back 'standard' keeps the payout scopes "
        "while skipping assert_payout_key_allowed() entirely"
    )
    assert set(rotated[0]["scopes"]) == set(PAYOUT_KEY_SCOPES)


def test_rotating_a_standard_key_stays_standard(fake_client):
    merchant_id, admin_id = _merchant(fake_client)
    create_pricing_rule(fake_client, merchant_id=merchant_id)
    _raw, row = make_api_key(fake_client, merchant_id, scopes=["collections:write"])

    response = client.post(
        f"/v1/merchant/api-keys/{row['id']}/rotate",
        headers=auth_headers(admin_id),
    )

    assert response.status_code == 201, response.text
    rotated = [
        r
        for r in fake_client.table("api_keys")._table.rows
        if r["status"] == "active" and r["merchant_id"] == str(merchant_id)
    ]
    assert rotated[0]["key_type"] == "standard"
