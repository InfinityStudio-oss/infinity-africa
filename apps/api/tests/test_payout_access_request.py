"""A merchant asking for payout access.

The Payouts page used to say "contact InfinityPay support" and give no
way to do it. The only merchants who ever asked were the ones who
already knew somebody, and nothing recorded that they had asked.

What matters here is that asking grants NOTHING. The request creates
the same row create_payout_access would, with every flag off, which is
what puts the merchant in the Super Admin queue — and that is the whole
mechanism.
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
    make_merchant_member,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _merchant_admin(fake_client):
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    return merchant_id, user_id


def _row(fake_client, merchant_id):
    return next(
        (
            r
            for r in fake_client.table("merchant_payout_settings")._table.rows
            if r["merchant_id"] == str(merchant_id)
        ),
        None,
    )


def test_requesting_creates_the_row_with_nothing_switched_on(fake_client):
    merchant_id, user_id = _merchant_admin(fake_client)

    response = client.post("/v1/merchant/payout-access-request", headers=auth_headers(user_id))

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "requested"
    row = _row(fake_client, merchant_id)
    assert row is not None
    assert row["sandbox_enabled"] is False, "asking must not grant anything"
    assert row["live_enabled"] is False
    assert row["access_requested_at"] is not None


def test_asking_twice_keeps_the_first_timestamp(fake_client):
    """How long someone has been waiting is the useful fact. Refreshing
    it on every click would hide exactly that."""
    merchant_id, user_id = _merchant_admin(fake_client)

    first = client.post("/v1/merchant/payout-access-request", headers=auth_headers(user_id))
    second = client.post("/v1/merchant/payout-access-request", headers=auth_headers(user_id))

    assert second.status_code == 200, second.text
    assert second.json()["data"]["status"] == "already_requested"
    assert second.json()["data"]["requested_at"] == first.json()["data"]["requested_at"]
    assert _row(fake_client, merchant_id)["access_requested_at"] == first.json()["data"]["requested_at"]


def test_a_merchant_already_enabled_is_told_so(fake_client):
    merchant_id, user_id = _merchant_admin(fake_client)
    fake_client.seed(
        "merchant_payout_settings",
        {
            "merchant_id": str(merchant_id),
            "sandbox_enabled": True,
            "live_enabled": False,
            "paused": False,
            "version": 1,
        },
    )

    response = client.post("/v1/merchant/payout-access-request", headers=auth_headers(user_id))

    assert response.json()["data"]["status"] == "already_enabled"
    # And no request is recorded, because there is nothing to action.
    # .get, not [], because the fake only holds the keys that were
    # seeded - in Postgres the column exists and is NULL.
    assert _row(fake_client, merchant_id).get("access_requested_at") is None


def test_an_api_key_cannot_request_access(fake_client):
    """Dashboard only. A key asking for more permission than it has is
    not a flow this product should have."""
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    raw_key = make_api_key(fake_client, merchant_id)

    response = client.post(
        "/v1/merchant/payout-access-request", headers={"Authorization": f"Bearer {raw_key}"}
    )

    assert response.status_code in (401, 403), response.text
    assert _row(fake_client, merchant_id) is None


def test_the_request_is_audited(fake_client):
    merchant_id, user_id = _merchant_admin(fake_client)

    client.post("/v1/merchant/payout-access-request", headers=auth_headers(user_id))

    entries = [
        r
        for r in fake_client.table("audit_logs")._table.rows
        if r.get("action") == "payout_access.requested"
    ]
    assert len(entries) == 1
    assert entries[0]["merchant_id"] == str(merchant_id)
