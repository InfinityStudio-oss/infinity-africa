"""Looking up a payment with the key that created it.

From production, 2026-10-15: Kinange Wifi (merchant 27607535) made 70 API
requests. Seven were `POST /v1/collections/wallet-push` and succeeded with
202. **Sixty-one were `GET /v1/collections/{uuid}` and every one returned
422.** Five distinct collections, polled up to twenty-five times each,
roughly every four seconds, never once getting an answer.

The ids were well-formed UUIDs and the key authenticated (a bad key gives
401 here, not 422). So the only thing left to fail was the `merchant_id`
query parameter, which this route required and the four create routes
beside it do not - they call _resolve_merchant_id and take it from the
key.

That inconsistency is ours, and so is the documentation: the partner
integration guide tells integrators to call

    GET https://api.infinitypay.me/v1/collections/{collection_id}
    Authorization: Bearer sk_live_...

with no query string at all. A partner following our own documentation
exactly received 422 sixty-one times, which is the worst possible shape
for this bug - it looks like their mistake.

_resolve_merchant_id's docstring already says why requiring it is wrong:
an integrator "had to go find their own UUID first, which the portal does
not display".
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import TEST_JWT_SECRET, auth_headers, create_merchant, make_api_key

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _setup(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    raw_key, _row = make_api_key(fake_client, merchant_id)
    collection = fake_client.seed(
        "collections",
        {
            "merchant_id": str(merchant_id),
            "amount": "1000.00",
            "currency": "TZS",
            "status": "successful",
            "environment": "live",
            "merchant_reference": "KINANGE-SB2",
            "channel": "TIGOPESA",
        },
    )
    return merchant_id, raw_key, collection


def _key(raw_key):
    return {"X-API-Key": raw_key}


# --- the production incident -------------------------------------------


def test_the_documented_request_works(fake_client):
    """The exact call docs/DIRECT_WALLET_PUSH_PARTNER_INTEGRATION.md
    publishes: an id and a key, no query string. This is what returned
    422 sixty-one times."""
    _merchant_id, raw_key, collection = _setup(fake_client)

    response = client.get(f"/v1/collections/{collection['id']}", headers=_key(raw_key))

    assert response.status_code == 200, response.json()
    assert response.json()["data"]["status"] == "successful"


def test_a_partner_polling_repeatedly_gets_the_same_answer(fake_client):
    """Kinange polled one collection twenty-five times. Whatever the
    answer is, it has to be stable and it has to be an answer."""
    _merchant_id, raw_key, collection = _setup(fake_client)

    statuses = {
        client.get(f"/v1/collections/{collection['id']}", headers=_key(raw_key)).status_code
        for _ in range(5)
    }

    assert statuses == {200}


def test_sending_merchant_id_explicitly_still_works(fake_client):
    """Backwards compatible: an integrator who already passes it, or a
    dashboard session that must, is unaffected."""
    merchant_id, raw_key, collection = _setup(fake_client)

    response = client.get(
        f"/v1/collections/{collection['id']}?merchant_id={merchant_id}", headers=_key(raw_key)
    )

    assert response.status_code == 200


# --- the authorization that must not be loosened -----------------------


def test_a_key_cannot_read_another_merchants_collection(fake_client):
    """The whole reason merchant_id was a parameter. Dropping it must not
    drop the scoping - it comes from the key instead, which is stricter,
    not weaker."""
    _merchant_id, raw_key, _collection = _setup(fake_client)
    other = create_merchant(fake_client)
    theirs = fake_client.seed(
        "collections",
        {
            "merchant_id": other["id"],
            "amount": "5000.00",
            "currency": "TZS",
            "status": "successful",
            "environment": "live",
        },
    )

    response = client.get(f"/v1/collections/{theirs['id']}", headers=_key(raw_key))

    assert response.status_code == 404, "another merchant's payment must not be readable"


def test_claiming_a_different_merchant_id_is_still_refused(fake_client):
    """Supplying someone else's merchant_id alongside your own key was
    rejected before and must stay rejected."""
    _merchant_id, raw_key, collection = _setup(fake_client)
    other = create_merchant(fake_client)

    response = client.get(
        f"/v1/collections/{collection['id']}?merchant_id={other['id']}", headers=_key(raw_key)
    )

    assert response.status_code == 403


def test_an_unauthenticated_lookup_is_refused(fake_client):
    _merchant_id, _raw_key, collection = _setup(fake_client)

    assert client.get(f"/v1/collections/{collection['id']}").status_code in (401, 403)


def test_a_sandbox_key_cannot_read_a_live_payment(fake_client):
    """Environment isolation, unchanged."""
    merchant_id, _live_key, collection = _setup(fake_client)
    sandbox_key, _row = make_api_key(fake_client, merchant_id, environment="sandbox")

    response = client.get(f"/v1/collections/{collection['id']}", headers=_key(sandbox_key))

    assert response.status_code == 404


def test_a_dashboard_session_is_told_what_to_send(fake_client):
    """A user can belong to several merchants, so there is nothing to
    infer from. The error has to say so rather than 422 with a bare
    'field required'."""
    merchant_id, _raw_key, collection = _setup(fake_client)
    user_id = uuid.uuid4()
    from tests.factories import make_merchant_member

    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")

    response = client.get(f"/v1/collections/{collection['id']}", headers=auth_headers(user_id))

    assert response.status_code in (400, 422)
    assert "merchant_id" in response.json()["error"]["message"]


# --- the same gap on refresh-status ------------------------------------


def test_refresh_status_takes_the_merchant_from_the_key_too(fake_client):
    """Same route family, same inconsistency. Fixing only the GET would
    leave a partner able to read a status but not ask us to re-check it."""
    _merchant_id, raw_key, collection = _setup(fake_client)

    response = client.post(
        f"/v1/collections/{collection['id']}/refresh-status", headers=_key(raw_key)
    )

    # Not asserting 200: refresh reaches the provider and may decline for
    # a terminal collection. What matters is that it is no longer a
    # validation error about a parameter the key already implies.
    assert response.status_code != 422, response.json()


# --- what the partner was reaching for ---------------------------------


def test_a_merchant_reference_is_not_a_collection_id(fake_client):
    """Kinange also tried GET /v1/transactions/KINANGE-SB2 twice and got
    404. Their own reference is not an InfinityPay id, and the lookup
    route takes the id we returned at creation."""
    _merchant_id, raw_key, _collection = _setup(fake_client)

    response = client.get("/v1/collections/KINANGE-SB2", headers=_key(raw_key))

    assert response.status_code == 422
    details = response.json()["error"]["details"] or []
    assert any("collection_id" in str(d.get("loc", "")) for d in details), (
        "the error must name collection_id, so an integrator can see which value is wrong"
    )
