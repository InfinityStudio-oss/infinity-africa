"""Taking a request out of the queue without granting anything.

Not enabling a merchant is already a refusal - their row grants nothing
and they keep the same not-enabled screen. What this exists for is the
QUEUE: a request nobody intends to act on sat at the top of the list
forever, sorted above everyone else, so "new, needs a decision" and
"looked at months ago, no" became indistinguishable.

The tests are mostly about what dismissing must NOT do.
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
    make_super_admin,
)

client = TestClient(app)


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
    return auth_headers(user_id, aal="aal2")


def _requested(fake_client, **overrides):
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    row = {
        "merchant_id": str(merchant_id),
        "sandbox_enabled": False,
        "live_enabled": False,
        "paused": False,
        "version": 1,
        "access_requested_at": "2026-11-22T13:12:06+00:00",
        "access_requested_by": str(uuid.uuid4()),
    }
    row.update(overrides)
    fake_client.seed("merchant_payout_settings", row)
    return merchant_id


def _row(fake_client, merchant_id):
    return next(
        r
        for r in fake_client.table("merchant_payout_settings")._table.rows
        if r["merchant_id"] == str(merchant_id)
    )


def test_dismissing_clears_the_request(fake_client):
    merchant_id = _requested(fake_client)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/dismiss-request",
        headers=_admin(fake_client),
        json={"version": 1, "reason": "Not taking new payout merchants this quarter."},
    )

    assert response.status_code == 200, response.text
    assert _row(fake_client, merchant_id)["access_requested_at"] is None


def test_dismissing_grants_nothing(fake_client):
    """The whole point. It is an inbox action, not an approval."""
    merchant_id = _requested(fake_client)

    client.patch(
        f"/v1/admin/payout-access/{merchant_id}/dismiss-request",
        headers=_admin(fake_client),
        json={"version": 1, "reason": "Not taking new payout merchants this quarter."},
    )

    row = _row(fake_client, merchant_id)
    assert row["sandbox_enabled"] is False
    assert row["live_enabled"] is False


def test_a_reason_is_required(fake_client):
    """Clearing the stamp destroys the only trace on the row that anyone
    asked, so the reason is the record."""
    merchant_id = _requested(fake_client)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/dismiss-request",
        headers=_admin(fake_client),
        json={"version": 1, "reason": "no"},
    )

    assert response.status_code == 422, response.text
    assert _row(fake_client, merchant_id)["access_requested_at"] is not None


def test_the_reason_is_audited(fake_client):
    merchant_id = _requested(fake_client)
    reason = "Declined for now - no signed agreement in place."

    client.patch(
        f"/v1/admin/payout-access/{merchant_id}/dismiss-request",
        headers=_admin(fake_client),
        json={"version": 1, "reason": reason},
    )

    entries = [
        r
        for r in fake_client.table("audit_logs")._table.rows
        if r.get("action") == "payout_access.request_dismissed"
    ]
    assert len(entries) == 1
    assert entries[0]["metadata"]["reason"] == reason
    # The before/after must still show a request existed.
    assert entries[0]["metadata"]["before"]["access_requested_at"] is not None
    assert entries[0]["metadata"]["after"]["access_requested_at"] is None


def test_dismissing_when_nothing_was_requested_is_refused(fake_client):
    merchant_id = _requested(fake_client, access_requested_at=None, access_requested_by=None)

    response = client.patch(
        f"/v1/admin/payout-access/{merchant_id}/dismiss-request",
        headers=_admin(fake_client),
        json={"version": 1, "reason": "Clearing a request that is not there."},
    )

    assert response.status_code == 409, response.text


def test_the_merchant_can_ask_again_afterwards(fake_client):
    """A dismissal is not a block. Circumstances change, and a business
    that asks again belongs back in the queue."""
    from tests.factories import make_merchant_member

    merchant_id = _requested(fake_client)
    client.patch(
        f"/v1/admin/payout-access/{merchant_id}/dismiss-request",
        headers=_admin(fake_client),
        json={"version": 1, "reason": "Not this quarter, ask again later."},
    )

    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    again = client.post("/v1/merchant/payout-access-request", headers=auth_headers(user_id))

    assert again.status_code == 200, again.text
    assert again.json()["data"]["status"] == "requested"
    assert _row(fake_client, merchant_id)["access_requested_at"] is not None
