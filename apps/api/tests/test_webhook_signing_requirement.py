"""A new webhook endpoint must be signed from its first delivery.

A merchant could save a webhook URL and never generate a signing secret.
With no secret, app/services/webhook_delivery.py omits
X-Infinity-Signature entirely - so the receiver has no way to tell an
InfinityPay event from any other POST to the same URL. Nothing in the
product said so, and a live check found the unsigned state to be the
common case rather than the exception.

For the partner integrations - ISP and WiFi billing platforms that
activate service when a payment event arrives - an unverifiable webhook is
free service to anyone who learns the URL.

Two deliberate halves, and the split is the whole design:

**New endpoints are refused unless a secret is configured.** From here on,
nobody can create the unsigned state.

**Endpoints already live without a secret keep working.** They are
mid-migration with running receivers. Refusing their next save - to add an
event, or fix a typo in the URL - would break a working integration in
order to improve a different one, and it would punish exactly the
merchants who need the most help. They are warned in the portal and listed
for Super Admins instead, and they can add a secret whenever their
receiver is ready without losing their endpoint or their subscribed
events.

Enforcement against the existing ones is a staged rollout with an agreed
date, not a flag flipped here.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.secret_box import decrypt_secret
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
)

client = TestClient(app)

URL = "https://billing.example.net/hooks/infinitypay"
OTHER_URL = "https://billing.example.net/hooks/v2"


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _merchant_and_member(fake_client, role: str = "MERCHANT_ADMIN"):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, role)
    return merchant_id, user_id


def _row(fake_client, merchant_id):
    return next(
        r for r in fake_client.table("merchants")._table.rows if str(r["id"]) == str(merchant_id)
    )


# --- new endpoints -----------------------------------------------------


def test_a_new_endpoint_cannot_be_saved_without_a_signing_secret(fake_client):
    _merchant_id, user_id = _merchant_and_member(fake_client)

    response = client.patch(
        "/v1/merchant/webhook-config",
        json={"webhook_url": URL},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 422, response.text


def test_the_refusal_explains_what_to_do(fake_client):
    """A requirement a merchant cannot act on is an obstacle."""
    _merchant_id, user_id = _merchant_and_member(fake_client)

    response = client.patch(
        "/v1/merchant/webhook-config",
        json={"webhook_url": URL},
        headers=auth_headers(user_id),
    )

    assert "signing secret" in response.text.lower()


def test_a_refused_save_stores_nothing(fake_client):
    """It must not half-apply: a stored URL with no secret is exactly the
    state being prevented."""
    merchant_id, user_id = _merchant_and_member(fake_client)

    client.patch(
        "/v1/merchant/webhook-config", json={"webhook_url": URL}, headers=auth_headers(user_id)
    )

    row = _row(fake_client, merchant_id)
    assert not row.get("webhook_url")


def test_a_new_endpoint_saves_when_a_secret_is_generated_in_the_same_request(fake_client):
    """The portal's first-time setup path: URL and secret in one call, so
    the requirement costs the merchant nothing."""
    merchant_id, user_id = _merchant_and_member(fake_client)

    response = client.patch(
        "/v1/merchant/webhook-config",
        json={"webhook_url": URL, "regenerate_secret": True},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["webhook_url"] == URL
    assert data["has_secret"] is True
    assert data["secret"], "the secret must be revealed exactly once"
    assert _row(fake_client, merchant_id).get("webhook_secret_encrypted")


def test_the_revealed_secret_is_the_one_that_will_sign_deliveries(fake_client):
    """A revealed secret that does not match what is stored would make
    every verification the merchant writes fail."""
    merchant_id, user_id = _merchant_and_member(fake_client)

    response = client.patch(
        "/v1/merchant/webhook-config",
        json={"webhook_url": URL, "regenerate_secret": True},
        headers=auth_headers(user_id),
    )

    revealed = response.json()["data"]["secret"]
    stored = _row(fake_client, merchant_id)["webhook_secret_encrypted"]
    assert decrypt_secret(stored) == revealed


def test_subscribed_events_only_can_still_be_saved_before_any_url_exists(fake_client):
    """The requirement is about creating an endpoint, not about touching
    the form at all."""
    _merchant_id, user_id = _merchant_and_member(fake_client)

    response = client.patch(
        "/v1/merchant/webhook-config",
        json={"subscribed_events": ["collection.successful"]},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200, response.text


# --- existing endpoints are preserved ----------------------------------


def _seed_unsigned_endpoint(fake_client, merchant_id, events=None):
    """The state the 2026-08-to-10 integrations are in: a live URL, no
    secret. Written directly, because the API no longer allows it."""
    row = _row(fake_client, merchant_id)
    row["webhook_url"] = URL
    row["webhook_secret_encrypted"] = None
    row["webhook_subscribed_events"] = events if events is not None else ["collection.successful"]


def test_an_existing_unsigned_endpoint_can_still_be_edited(fake_client):
    """The migration period. Their receiver is running; refusing this save
    breaks a working integration."""
    merchant_id, user_id = _merchant_and_member(fake_client)
    _seed_unsigned_endpoint(fake_client, merchant_id)

    response = client.patch(
        "/v1/merchant/webhook-config",
        json={"subscribed_events": ["collection.successful", "withdrawal.completed"]},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200, response.text


def test_an_existing_unsigned_endpoint_can_change_its_url(fake_client):
    """Still no secret, still allowed: this merchant already has an
    endpoint, so this is not endpoint creation."""
    merchant_id, user_id = _merchant_and_member(fake_client)
    _seed_unsigned_endpoint(fake_client, merchant_id)

    response = client.patch(
        "/v1/merchant/webhook-config",
        json={"webhook_url": OTHER_URL},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200, response.text
    assert _row(fake_client, merchant_id)["webhook_url"] == OTHER_URL


def test_adding_a_secret_later_keeps_the_endpoint_and_subscribed_events(fake_client):
    """The migration step itself, and the thing most likely to go wrong:
    adding a secret must not quietly reset the URL or the event
    subscriptions, or the merchant stops receiving what they rely on at
    the exact moment they improve their security."""
    merchant_id, user_id = _merchant_and_member(fake_client)
    _seed_unsigned_endpoint(
        fake_client, merchant_id, events=["collection.successful", "withdrawal.completed"]
    )

    response = client.patch(
        "/v1/merchant/webhook-config",
        json={"regenerate_secret": True},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["webhook_url"] == URL
    assert data["subscribed_events"] == ["collection.successful", "withdrawal.completed"]
    assert data["has_secret"] is True


def test_rotating_a_secret_replaces_it_and_keeps_the_endpoint(fake_client):
    merchant_id, user_id = _merchant_and_member(fake_client)
    first = client.patch(
        "/v1/merchant/webhook-config",
        json={"webhook_url": URL, "regenerate_secret": True},
        headers=auth_headers(user_id),
    ).json()["data"]["secret"]

    second = client.patch(
        "/v1/merchant/webhook-config",
        json={"regenerate_secret": True},
        headers=auth_headers(user_id),
    ).json()["data"]["secret"]

    assert first != second
    assert decrypt_secret(_row(fake_client, merchant_id)["webhook_secret_encrypted"]) == second
    assert _row(fake_client, merchant_id)["webhook_url"] == URL


# --- the secret is never readable back ---------------------------------


def test_the_get_endpoint_never_returns_the_secret(fake_client):
    _merchant_id, user_id = _merchant_and_member(fake_client)
    client.patch(
        "/v1/merchant/webhook-config",
        json={"webhook_url": URL, "regenerate_secret": True},
        headers=auth_headers(user_id),
    )

    response = client.get("/v1/merchant/webhook-config", headers=auth_headers(user_id))

    body = response.json()["data"]
    assert body["has_secret"] is True
    assert "secret" not in body


def test_a_later_save_does_not_re_reveal_the_secret(fake_client):
    """Shown once. A save that echoed it back would put it in logs and
    browser history for every subsequent edit."""
    _merchant_id, user_id = _merchant_and_member(fake_client)
    client.patch(
        "/v1/merchant/webhook-config",
        json={"webhook_url": URL, "regenerate_secret": True},
        headers=auth_headers(user_id),
    )

    response = client.patch(
        "/v1/merchant/webhook-config",
        json={"subscribed_events": ["collection.successful"]},
        headers=auth_headers(user_id),
    )

    assert response.json()["data"]["secret"] is None


def test_the_stored_secret_is_encrypted_at_rest(fake_client):
    merchant_id, user_id = _merchant_and_member(fake_client)
    revealed = client.patch(
        "/v1/merchant/webhook-config",
        json={"webhook_url": URL, "regenerate_secret": True},
        headers=auth_headers(user_id),
    ).json()["data"]["secret"]

    stored = _row(fake_client, merchant_id)["webhook_secret_encrypted"]
    assert revealed not in str(stored), "the plaintext secret reached the database"


def test_the_signing_secret_is_not_a_merchant_api_key(fake_client):
    """Separate credentials with separate lifetimes: rotating an API key
    must not silently break webhook verification, and a leaked API key
    must not let someone forge events."""
    _merchant_id, user_id = _merchant_and_member(fake_client)

    secret = client.patch(
        "/v1/merchant/webhook-config",
        json={"webhook_url": URL, "regenerate_secret": True},
        headers=auth_headers(user_id),
    ).json()["data"]["secret"]

    assert not secret.startswith(("sk_", "pk_", "inf_"))
    assert len(secret) == 64


# --- ownership ---------------------------------------------------------


def test_a_member_of_another_merchant_cannot_configure_this_one(fake_client):
    merchant_id, _user_id = _merchant_and_member(fake_client)
    _other_merchant_id, outsider = _merchant_and_member(fake_client)

    response = client.patch(
        "/v1/merchant/webhook-config",
        json={"webhook_url": URL, "regenerate_secret": True},
        headers=auth_headers(outsider),
    )

    # The outsider configures their OWN merchant (the endpoint takes the
    # merchant from the session, never from the request), so this must not
    # touch the first merchant.
    assert response.status_code in (200, 403)
    assert not _row(fake_client, merchant_id).get("webhook_url")
