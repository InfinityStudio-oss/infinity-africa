"""Super Admin must be able to see a merchant taking live money whose
partner is never told about it.

This failure is silent by construction, which is why it needs a flag
rather than an alert. A *wrong* webhook URL is loud: deliveries are
queued, they fail, they retry, they exhaust, and Sentry says so - that is
how BEACH WiFi's typo was found. *No* URL queues nothing, attempts
nothing and raises nothing. Nobody hears about it until a partner asks
why their customers were charged and never activated.

Found on 2026-10-16: two partners in exactly this state, ten real
customers and TZS 6,300 between them.
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
    make_api_key,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _admin(fake_client):
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    return admin_id


def _row_for(fake_client, admin_id, merchant_id):
    response = client.get("/v1/admin/merchants", headers=auth_headers(admin_id))
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    return next(r for r in rows if r["merchant_id"] == str(merchant_id))


def test_a_live_key_with_no_webhook_is_flagged(fake_client):
    """The case that cost ten customers their activation."""
    admin_id = _admin(fake_client)
    merchant = create_merchant(fake_client, webhook_url=None)
    merchant_id = uuid.UUID(merchant["id"])
    make_api_key(fake_client, merchant_id, environment="live")

    assert _row_for(fake_client, admin_id, merchant_id)["live_api_without_webhook"] is True


def test_a_live_key_with_a_webhook_is_not_flagged(fake_client):
    admin_id = _admin(fake_client)
    merchant = create_merchant(
        fake_client, webhook_url="https://isp.example.com/callback"
    )
    merchant_id = uuid.UUID(merchant["id"])
    make_api_key(fake_client, merchant_id, environment="live")

    assert _row_for(fake_client, admin_id, merchant_id)["live_api_without_webhook"] is False


def test_a_sandbox_key_alone_is_not_flagged(fake_client):
    """A merchant testing against sandbox has no real customer waiting on
    a callback. Flagging them would fire the warning on every new signup,
    which is how a warning stops being read."""
    admin_id = _admin(fake_client)
    merchant = create_merchant(fake_client, webhook_url=None)
    merchant_id = uuid.UUID(merchant["id"])
    make_api_key(fake_client, merchant_id, environment="sandbox")

    assert _row_for(fake_client, admin_id, merchant_id)["live_api_without_webhook"] is False


def test_no_api_key_at_all_is_not_flagged(fake_client):
    """A portal-only merchant has no integration to notify."""
    admin_id = _admin(fake_client)
    merchant = create_merchant(fake_client, webhook_url=None)

    row = _row_for(fake_client, admin_id, uuid.UUID(merchant["id"]))
    assert row["live_api_without_webhook"] is False


def test_a_blank_webhook_url_counts_as_unset(fake_client):
    """Empty string, or whitespace someone pasted and saved, is not a
    configured endpoint."""
    admin_id = _admin(fake_client)
    merchant = create_merchant(fake_client, webhook_url="   ")
    merchant_id = uuid.UUID(merchant["id"])
    make_api_key(fake_client, merchant_id, environment="live")

    assert _row_for(fake_client, admin_id, merchant_id)["live_api_without_webhook"] is True


def test_a_revoked_live_key_no_longer_flags(fake_client):
    """The merchant cannot take money with a revoked key, so there is
    nothing to warn about."""
    admin_id = _admin(fake_client)
    merchant = create_merchant(fake_client, webhook_url=None)
    merchant_id = uuid.UUID(merchant["id"])
    _raw, key_row = make_api_key(fake_client, merchant_id, environment="live")
    fake_client.table("api_keys").update({"status": "revoked"}).eq("id", key_row["id"]).execute()

    assert _row_for(fake_client, admin_id, merchant_id)["live_api_without_webhook"] is False


def test_one_merchants_state_does_not_leak_onto_another(fake_client):
    """The flag is computed from a batched query, which is exactly the
    shape that gets this wrong."""
    admin_id = _admin(fake_client)
    exposed = create_merchant(fake_client, business_name="Exposed", webhook_url=None)
    safe = create_merchant(fake_client, business_name="Safe", webhook_url="https://ok.example/cb")
    make_api_key(fake_client, uuid.UUID(exposed["id"]), environment="live")
    make_api_key(fake_client, uuid.UUID(safe["id"]), environment="live")

    assert _row_for(fake_client, admin_id, uuid.UUID(exposed["id"]))["live_api_without_webhook"] is True
    assert _row_for(fake_client, admin_id, uuid.UUID(safe["id"]))["live_api_without_webhook"] is False
