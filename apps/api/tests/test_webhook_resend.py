"""A given-up webhook must be recoverable.

Outbound delivery retries five times and then marks the row `failed`.
Nothing ever touches it again - `_pending_events()` scans only `pending`
and `retrying` - so a merchant whose endpoint is down longer than that
loses the notification permanently.

For a platform where a webhook is how a partner learns that money
arrived, that is a hole with no floor. It cost a real merchant on
2026-10-22: their callback answered five deliveries with a redirect to an
error page, and five payments plus a payout had to be read back to them
by reference so they could credit customers by hand.

The endpoint cannot move money. It re-queues a notification describing
something that already happened. The row keeps its own id, so the
redelivery carries the same `X-Infinity-Delivery` as the original - a
receiver that did process the first attempt deduplicates it exactly as
the integration guide instructs, and one that never got it receives it
for the first time.
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

RESEND = "/v1/admin/merchant-webhooks/{}/resend"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def admin(fake_client):
    user_id = uuid.uuid4()
    make_super_admin(fake_client, user_id)
    return user_id


def _event(fake_client, *, status="failed", attempts=5, code=500):
    merchant = create_merchant(fake_client)
    return fake_client.seed(
        "webhook_events",
        {
            "merchant_id": merchant["id"],
            "event_name": "collection.success",
            "target_url": "https://merchant.example/callback",
            "payload": {"amount": "500.00", "currency": "TZS"},
            "status": status,
            "attempts": attempts,
            "response_status_code": code,
        },
    )


def _row(fake_client, event_id):
    return next(
        r for r in fake_client.table("webhook_events")._table.rows if str(r["id"]) == str(event_id)
    )


# --- the recovery it exists for ----------------------------------------


def test_a_failed_delivery_goes_back_in_the_queue(fake_client, admin):
    event = _event(fake_client)

    response = client.post(RESEND.format(event["id"]), headers=auth_headers(admin))

    assert response.status_code == 200, response.text
    assert _row(fake_client, event["id"])["status"] == "retrying"


def test_attempts_reset_so_the_next_sweep_takes_it(fake_client, admin):
    """_BACKOFF_SECONDS[0] is 0. Leaving attempts at 5 would leave the row
    waiting out the half-hour interval the final attempt had reached - or
    be immediately re-failed for exceeding _MAX_ATTEMPTS."""
    event = _event(fake_client, attempts=5)

    client.post(RESEND.format(event["id"]), headers=auth_headers(admin))

    assert _row(fake_client, event["id"])["attempts"] == 0


def test_the_stale_response_code_is_cleared(fake_client, admin):
    event = _event(fake_client, code=500)

    client.post(RESEND.format(event["id"]), headers=auth_headers(admin))

    assert _row(fake_client, event["id"])["response_status_code"] is None


def test_the_delivery_id_is_unchanged_so_receivers_can_deduplicate(fake_client, admin):
    """The whole safety argument. X-Infinity-Delivery is this row's id, so
    a receiver that already processed the original discards the resend."""
    event = _event(fake_client)
    original_id = str(event["id"])

    client.post(RESEND.format(event["id"]), headers=auth_headers(admin))

    assert str(_row(fake_client, event["id"])["id"]) == original_id


def test_the_payload_is_not_rewritten(fake_client, admin):
    """It redescribes something that already happened; changing the body
    would make the resend a different event from the one being recovered."""
    event = _event(fake_client)
    before = dict(_row(fake_client, event["id"])["payload"])

    client.post(RESEND.format(event["id"]), headers=auth_headers(admin))

    assert _row(fake_client, event["id"])["payload"] == before


def test_it_is_audited_against_the_admin_who_asked(fake_client, admin):
    event = _event(fake_client)

    client.post(RESEND.format(event["id"]), headers=auth_headers(admin))

    rows = fake_client.table("audit_logs")._table.rows
    entry = next(r for r in rows if r["action"] == "webhook.resend_requested")
    assert str(entry["actor_id"]) == str(admin)
    assert entry["metadata"]["previous_status_code"] == 500


# --- what it refuses ---------------------------------------------------


def test_a_delivered_event_cannot_be_resent(fake_client, admin):
    """Otherwise this becomes a way to send a merchant the same event
    twice deliberately."""
    event = _event(fake_client, status="delivered", attempts=1, code=200)

    response = client.post(RESEND.format(event["id"]), headers=auth_headers(admin))

    assert response.status_code == 422
    assert _row(fake_client, event["id"])["status"] == "delivered"


@pytest.mark.parametrize("status", ["pending", "retrying"])
def test_an_event_already_queued_is_left_alone(fake_client, admin, status):
    """Resetting attempts on a row the sweep is already working would
    restart its backoff and could keep it cycling."""
    event = _event(fake_client, status=status, attempts=2)

    response = client.post(RESEND.format(event["id"]), headers=auth_headers(admin))

    assert response.status_code == 422
    assert _row(fake_client, event["id"])["attempts"] == 2


def test_an_unknown_event_is_a_404(fake_client, admin):
    response = client.post(RESEND.format(uuid.uuid4()), headers=auth_headers(admin))

    assert response.status_code == 404


# --- who may call it ---------------------------------------------------


def test_an_ordinary_merchant_cannot_resend(fake_client):
    """A merchant could otherwise replay notifications into their own
    system at will."""
    event = _event(fake_client)
    merchant = create_merchant(fake_client)
    user_id = uuid.uuid4()
    from tests.factories import make_merchant_member

    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), user_id, "MERCHANT_ADMIN")

    response = client.post(RESEND.format(event["id"]), headers=auth_headers(user_id))

    assert response.status_code == 403
    assert _row(fake_client, event["id"])["status"] == "failed"


def test_an_unauthenticated_caller_cannot_resend(fake_client):
    event = _event(fake_client)

    response = client.post(RESEND.format(event["id"]))

    assert response.status_code in (401, 403)
    assert _row(fake_client, event["id"])["status"] == "failed"
