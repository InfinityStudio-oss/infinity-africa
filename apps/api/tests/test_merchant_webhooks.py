"""Self-service webhook configuration: /v1/merchant/webhook-config,
/v1/merchant/webhook-config/test, /v1/merchant/webhook-events.
"""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.secret_box import decrypt_secret
from app.main import app
from app.routers import merchant_webhooks
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


def _merchant_and_member(fake_client, role: str = "MERCHANT_ADMIN"):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, role)
    return merchant_id, user_id


def test_get_webhook_config_before_setup_is_all_nulls(fake_client):
    _merchant_id, user_id = _merchant_and_member(fake_client)

    response = client.get("/v1/merchant/webhook-config", headers=auth_headers(user_id))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["webhook_url"] is None
    assert data["has_secret"] is False
    assert data["last_delivery"] is None


def test_patch_webhook_config_sets_url_and_regenerates_secret_once(fake_client):
    _merchant_id, user_id = _merchant_and_member(fake_client)

    response = client.patch(
        "/v1/merchant/webhook-config",
        headers=auth_headers(user_id),
        json={"webhook_url": "https://example.com/hooks/infinity", "regenerate_secret": True},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["webhook_url"] == "https://example.com/hooks/infinity"
    assert data["has_secret"] is True
    assert data["secret"] is not None
    secret_shown_once = data["secret"]

    follow_up = client.get("/v1/merchant/webhook-config", headers=auth_headers(user_id))
    assert follow_up.json()["data"]["has_secret"] is True
    assert "secret" not in follow_up.json()["data"]
    assert secret_shown_once  # sanity — was non-empty


def test_webhook_secret_is_stored_encrypted_never_plaintext(fake_client):
    merchant_id, user_id = _merchant_and_member(fake_client)

    response = client.patch(
        "/v1/merchant/webhook-config",
        headers=auth_headers(user_id),
        json={"webhook_url": "https://example.com/hooks/infinity", "regenerate_secret": True},
    )
    shown_secret = response.json()["data"]["secret"]

    row = fake_client.table("merchants").select("*").eq("id", str(merchant_id)).maybe_single().execute().data
    assert row.get("webhook_secret") is None  # legacy plaintext column is never written to
    stored = row["webhook_secret_encrypted"]
    assert stored != shown_secret  # not stored as plaintext
    assert decrypt_secret(stored) == shown_secret  # but recoverable under the encryption key, for signing


def test_staff_can_view_but_not_update_webhook_config(fake_client):
    _merchant_id, user_id = _merchant_and_member(fake_client, role="MERCHANT_STAFF")

    read = client.get("/v1/merchant/webhook-config", headers=auth_headers(user_id))
    assert read.status_code == 200

    write = client.patch(
        "/v1/merchant/webhook-config",
        headers=auth_headers(user_id),
        json={"webhook_url": "https://example.com/hooks/infinity"},
    )
    assert write.status_code == 403


def test_send_test_webhook_without_url_configured_rejected(fake_client):
    _merchant_id, user_id = _merchant_and_member(fake_client)

    response = client.post("/v1/merchant/webhook-config/test", headers=auth_headers(user_id))

    assert response.status_code == 422


def test_send_test_webhook_reports_delivered_result(fake_client, monkeypatch):
    _merchant_id, user_id = _merchant_and_member(fake_client)
    client.patch(
        "/v1/merchant/webhook-config",
        headers=auth_headers(user_id),
        json={"webhook_url": "https://example.com/hooks/infinity", "regenerate_secret": True},
    )

    def _fake_post(url, *, content, headers, timeout):
        assert "X-Infinity-Signature" in headers
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(merchant_webhooks.httpx, "post", _fake_post)

    response = client.post("/v1/merchant/webhook-config/test", headers=auth_headers(user_id))

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["delivered"] is True
    assert data["http_status"] == 200


def test_send_test_webhook_reports_unreachable_endpoint(fake_client, monkeypatch):
    _merchant_id, user_id = _merchant_and_member(fake_client)
    client.patch(
        "/v1/merchant/webhook-config",
        headers=auth_headers(user_id),
        # regenerate_secret because a new endpoint is no longer allowed to
        # be created unsigned (see test_webhook_signing_requirement.py).
        # This test is about reporting an unreachable endpoint, so it just
        # needs a valid endpoint to exist.
        json={"webhook_url": "https://example.com/hooks/infinity", "regenerate_secret": True},
    )

    def _fake_post(url, *, content, headers, timeout):
        raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(merchant_webhooks.httpx, "post", _fake_post)

    response = client.post("/v1/merchant/webhook-config/test", headers=auth_headers(user_id))

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["delivered"] is False
    assert data["http_status"] is None


def test_list_webhook_events_empty(fake_client):
    _merchant_id, user_id = _merchant_and_member(fake_client)

    response = client.get("/v1/merchant/webhook-events", headers=auth_headers(user_id))

    assert response.status_code == 200
    assert response.json()["data"] == []
