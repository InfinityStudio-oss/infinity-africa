"""An API key must hold a disbursements scope to move money.

Until now /v1/disbursements was the only API-key surface with no scope
check. authorize_merchant_action proves a key BELONGS to the merchant; it
says nothing about what the key may do. Collections, invoices,
payment_links and transactions all follow it with require_api_key_scope.
This router did not, so any active key - including one issued only for
collections - could request a payout, and with withdrawal automation on
it would not wait for a person.

No key has ever used the route, and `disbursements:write` is deliberately
NOT in API_KEY_SCOPES, so no merchant can grant it from the portal today.
That is the intended end state for now: the capability is reachable only
by a deliberate code change, while dashboard sessions keep working
untouched (require_api_key_scope no-ops for actor_type == "user").

The scope is `disbursements:write`, matching the resource:write naming the
other scopes use, and is deliberately distinct from the
`disbursements:create` scope the prefunded Payout Wallet API will use:
this route spends the merchant's COLLECTIONS balance, which a payout key
must never reach.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.schemas.api_keys import API_KEY_SCOPES
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    create_pricing_rule,
    make_api_key,
    make_merchant_member,
)

client = TestClient(app)

CREATE_ROUTES = ("selcom-pesa", "mobile-money", "bank-account")


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _merchant(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    create_pricing_rule(fake_client)
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Merchant Wallet (test)",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": "TZS",
            "balance": "500000.00",
        },
    )
    return merchant_id, admin_id


def _payout_body(merchant_id, *, bank: bool = False):
    body = {
        "merchant_id": str(merchant_id),
        "amount": "1000.00",
        "destination_name": "Jane Doe",
        "destination_identifier": "+255700000000",
        "destination_code": "MPESA",
    }
    if bank:
        body["bank_name"] = "CRDB"
    return body


# --- the hole this closes -------------------------------------------------


@pytest.mark.parametrize("route", CREATE_ROUTES)
def test_collections_key_cannot_request_a_payout(fake_client, route):
    """The exact shape of the exposure: a key issued for collections,
    authenticating correctly against its OWN merchant, is refused."""
    merchant_id, _admin_id = _merchant(fake_client)
    raw_key, _ = make_api_key(
        fake_client, merchant_id, scopes=["collections:read", "collections:write"]
    )

    response = client.post(
        f"/v1/disbursements/{route}",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json=_payout_body(merchant_id, bank=route == "bank-account"),
    )

    assert response.status_code == 403
    assert "not available to API keys" in response.json()["error"]["message"]


@pytest.mark.parametrize("route", CREATE_ROUTES)
def test_a_full_scope_key_still_cannot_request_a_payout(fake_client, route):
    """make_api_key's default is every grantable scope. That must still
    not be enough, because `disbursements:write` is not one of them - this
    is what stops the 142 live keys in production from paying anyone."""
    merchant_id, _admin_id = _merchant(fake_client)
    raw_key, _ = make_api_key(fake_client, merchant_id)

    response = client.post(
        f"/v1/disbursements/{route}",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json=_payout_body(merchant_id, bank=route == "bank-account"),
    )

    assert response.status_code == 403


def test_the_payout_scope_is_not_grantable_from_the_portal():
    """Belt and braces for the test above: if someone later adds the scope
    to the grantable list, that is a deliberate decision and this test
    should fail and make them say so."""
    assert "disbursements:write" not in API_KEY_SCOPES
    assert "disbursements:create" not in API_KEY_SCOPES


@pytest.mark.parametrize("route", CREATE_ROUTES)
def test_no_api_key_reaches_this_route_whatever_it_holds(fake_client, route):
    """A blanket ban, not a scope check - and this reverses an earlier
    decision here, so it is worth saying why.

    The first fix gave these routes a scope nothing could be granted,
    which left the rule sitting in a tuple in app/schemas/api_keys.py
    rather than on the route. Two things then went wrong at once: the
    route trusts another file to stay correct, and a key that acquires
    the scope some other way - rotation used to mint one - is let
    straight through.

    A key forced to hold `disbursements:write` is exactly that row, so it
    is what this test uses. It must still be refused.
    """
    merchant_id, _admin_id = _merchant(fake_client)
    raw_key, _ = make_api_key(
        fake_client, merchant_id, scopes=["disbursements:write"]
    )

    response = client.post(
        f"/v1/disbursements/{route}",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json=_payout_body(merchant_id, bank=route == "bank-account"),
    )

    assert response.status_code == 403, response.text
    assert "not available to API keys" in response.json()["error"]["message"]


# --- reads ----------------------------------------------------------------


def test_listing_payouts_needs_the_read_scope(fake_client):
    merchant_id, _admin_id = _merchant(fake_client)
    raw_key, _ = make_api_key(fake_client, merchant_id, scopes=["collections:read"])

    response = client.get(
        "/v1/disbursements",
        params={"merchant_id": str(merchant_id)},
        headers={"X-API-Key": raw_key},
    )

    # The ban answers before the scope check, so this is the message a
    # key gets whether or not it holds the scope. That is the point: it
    # tells the caller the route is not for them, instead of naming a
    # scope they can never be granted.
    assert response.status_code == 403
    assert "not available to API keys" in response.json()["error"]["message"]


def test_reading_withdrawals_is_closed_to_keys_holding_the_read_scope(fake_client):
    """Same reversal as the create path: the read routes are a dashboard
    surface, and a key carrying `disbursements:read` is a drifted row
    rather than a legitimate caller."""
    merchant_id, _admin_id = _merchant(fake_client)
    raw_key, _ = make_api_key(fake_client, merchant_id, scopes=["disbursements:read"])

    response = client.get(
        "/v1/disbursements",
        params={"merchant_id": str(merchant_id)},
        headers={"X-API-Key": raw_key},
    )

    assert response.status_code == 403
    assert "not available to API keys" in response.json()["error"]["message"]


def test_a_missing_payout_is_404_before_the_scope_is_considered(fake_client):
    """Ordering matters: the scope check sits AFTER the ownership check on
    the single-row route, so scope probing cannot be used to learn which
    ids exist. An id that does not exist is 404 whatever the key holds."""
    merchant_id, _admin_id = _merchant(fake_client)
    raw_key, _ = make_api_key(fake_client, merchant_id, scopes=["collections:read"])

    response = client.get(
        f"/v1/disbursements/{uuid.uuid4()}", headers={"X-API-Key": raw_key}
    )

    assert response.status_code == 404


# --- what must NOT change -------------------------------------------------


def test_dashboard_sessions_are_unaffected(fake_client):
    """Scopes are an API-key concept. A merchant admin on the dashboard
    passed a role check already and must keep working exactly as before -
    this is the regression guard on the whole change."""
    merchant_id, admin_id = _merchant(fake_client)

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json=_payout_body(merchant_id),
    )

    assert response.status_code != 403, response.text


def test_cross_merchant_denial_still_wins_over_the_scope_message(fake_client):
    """A key reaching for another merchant must be told that, not given a
    scope hint - the ownership check runs first on the create path."""
    merchant_id, _admin_id = _merchant(fake_client)
    other_id, _ = _merchant(fake_client)
    raw_key, _ = make_api_key(fake_client, merchant_id, scopes=["collections:write"])

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json=_payout_body(other_id),
    )

    assert response.status_code == 403
    assert "does not belong to this merchant" in response.json()["error"]["message"]


# --- payout keys must not reach the legacy, Collections-funded route ------
#
# The Payout Wallet API gives merchants a second kind of key. Its read
# scope must not double as the legacy route's read scope, or a payout key
# would be able to list and fetch withdrawals paid out of the Collections
# balance - money it is specifically not allowed to touch.
#
# Resolved by giving payout keys payouts:create / payouts:read, which do
# not satisfy disbursements:write / disbursements:read. These tests are the
# proof, and they cover all five legacy routes for both kinds of key.


def _payout_key(fake_client, merchant_id):
    return make_api_key(fake_client, merchant_id, key_type="payout")[0]


@pytest.mark.parametrize("route", CREATE_ROUTES)
def test_payout_key_cannot_create_a_legacy_withdrawal(fake_client, route):
    merchant_id, _admin_id = _merchant(fake_client)
    raw_key = _payout_key(fake_client, merchant_id)

    response = client.post(
        f"/v1/disbursements/{route}",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json=_payout_body(merchant_id, bank=route == "bank-account"),
    )

    assert response.status_code == 403
    assert "not available to API keys" in response.json()["error"]["message"]


def test_payout_key_cannot_list_legacy_withdrawals(fake_client):
    merchant_id, _admin_id = _merchant(fake_client)
    raw_key = _payout_key(fake_client, merchant_id)

    response = client.get(
        "/v1/disbursements",
        params={"merchant_id": str(merchant_id)},
        headers={"X-API-Key": raw_key},
    )

    assert response.status_code == 403
    assert "not available to API keys" in response.json()["error"]["message"]


def test_payout_key_cannot_fetch_a_legacy_withdrawal(fake_client):
    """Fetched by id, on a row that really exists and really belongs to
    this merchant - so the refusal is the scope and nothing else."""
    merchant_id, admin_id = _merchant(fake_client)
    created = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json=_payout_body(merchant_id),
    )
    assert created.status_code in (200, 202), created.text
    disbursement_id = created.json()["data"]["id"]

    raw_key = _payout_key(fake_client, merchant_id)
    response = client.get(
        f"/v1/disbursements/{disbursement_id}", headers={"X-API-Key": raw_key}
    )

    assert response.status_code == 403
    assert "not available to API keys" in response.json()["error"]["message"]


def test_full_scope_standard_key_cannot_fetch_a_legacy_withdrawal(fake_client):
    """The same row, via a standard key holding every grantable scope."""
    merchant_id, admin_id = _merchant(fake_client)
    created = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json=_payout_body(merchant_id),
    )
    assert created.status_code in (200, 202), created.text
    disbursement_id = created.json()["data"]["id"]

    raw_key, _ = make_api_key(fake_client, merchant_id)
    response = client.get(
        f"/v1/disbursements/{disbursement_id}", headers={"X-API-Key": raw_key}
    )

    assert response.status_code == 403


def test_full_scope_standard_key_cannot_list_legacy_withdrawals(fake_client):
    merchant_id, _admin_id = _merchant(fake_client)
    raw_key, _ = make_api_key(fake_client, merchant_id)

    response = client.get(
        "/v1/disbursements",
        params={"merchant_id": str(merchant_id)},
        headers={"X-API-Key": raw_key},
    )

    assert response.status_code == 403


def test_no_grantable_scope_set_can_reach_the_legacy_route(fake_client):
    """The exhaustive version: every scope a merchant can be granted, on
    either kind of key, all at once. If some future scope is added to a
    grantable list and happens to satisfy the legacy route, this fails."""
    from app.schemas.api_keys import API_KEY_SCOPES as STANDARD
    from app.schemas.api_keys import PAYOUT_KEY_SCOPES

    merchant_id, _admin_id = _merchant(fake_client)
    everything = [*STANDARD, *PAYOUT_KEY_SCOPES]
    raw_key, _ = make_api_key(fake_client, merchant_id, scopes=everything)

    create = client.post(
        "/v1/disbursements/mobile-money",
        headers={"X-API-Key": raw_key, "Idempotency-Key": str(uuid.uuid4())},
        json=_payout_body(merchant_id),
    )
    listing = client.get(
        "/v1/disbursements",
        params={"merchant_id": str(merchant_id)},
        headers={"X-API-Key": raw_key},
    )

    assert create.status_code == 403
    assert listing.status_code == 403


# --- the scope model itself ----------------------------------------------


def test_a_standard_key_cannot_be_granted_payout_scopes():
    from pydantic import ValidationError

    from app.schemas.api_keys import ApiKeyCreate

    with pytest.raises(ValidationError) as exc:
        ApiKeyCreate(name="k", key_type="standard", scopes=["collections:write", "payouts:create"])

    assert "payouts:create" in str(exc.value)


def test_a_payout_key_cannot_be_granted_collection_scopes():
    """The invariant that matters: no single credential both takes money
    in and sends it out."""
    from pydantic import ValidationError

    from app.schemas.api_keys import ApiKeyCreate

    with pytest.raises(ValidationError) as exc:
        ApiKeyCreate(name="k", key_type="payout", scopes=["payouts:create", "collections:write"])

    assert "collections:write" in str(exc.value)


def test_a_payout_key_needs_a_payout_scope():
    from pydantic import ValidationError

    from app.schemas.api_keys import ApiKeyCreate

    with pytest.raises(ValidationError):
        ApiKeyCreate(name="k", key_type="payout", scopes=[])


def test_a_valid_payout_key_request_is_accepted():
    from app.schemas.api_keys import ApiKeyCreate

    created = ApiKeyCreate(name="k", key_type="payout", scopes=["payouts:create", "payouts:read"])

    assert created.key_type == "payout"
    assert set(created.scopes) == {"payouts:create", "payouts:read"}


def test_legacy_scopes_are_grantable_on_neither_key_type():
    from pydantic import ValidationError

    from app.schemas.api_keys import LEGACY_DISBURSEMENT_SCOPES, ApiKeyCreate

    for key_type in ("standard", "payout"):
        for scope in LEGACY_DISBURSEMENT_SCOPES:
            with pytest.raises(ValidationError):
                ApiKeyCreate(name="k", key_type=key_type, scopes=[scope])


def test_an_unspecified_key_type_is_standard():
    """Every existing caller and every stored request body keeps meaning
    what it meant before payout keys existed."""
    from app.schemas.api_keys import ApiKeyCreate

    assert ApiKeyCreate(name="k", scopes=["collections:write"]).key_type == "standard"
