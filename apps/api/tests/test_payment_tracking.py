"""Payment tracking for billing integrations.

The complaint this answers: "the customer paid, but our billing system
never activated their internet". Three separate facts are involved and
the timeline must never blur them:

  * the payment       - collections / transactions
  * webhook receipt   - webhook_events (HTTP 2xx proves RECEIPT only)
  * service activation - not recorded anywhere, so never "confirmed"

Also pinned: the shared reference is the existing `collection_id`, it is
searchable by the merchant who owns it and by Super Admin only, and the
response never carries payloads, target URLs or secrets.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.collections import resolve_collection
from app.services.selcom.schemas import CollectionResult
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    create_transaction,
    make_merchant_member,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _merchant(fake_client, *, webhook=True):
    merchant = create_merchant(
        fake_client, webhook_url="https://billing.example/hooks/infinitypay" if webhook else None
    )
    merchant_id = uuid.UUID(merchant["id"])
    user = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user, "MERCHANT_ADMIN")
    return merchant_id, auth_headers(user)


def _paid(fake_client, merchant_id, *, status="successful", **collection_overrides):
    collection = fake_client.seed(
        "collections",
        {
            "merchant_id": str(merchant_id),
            "method": "USSD_PUSH",
            "amount": "15000.00",
            "currency": "TZS",
            "status": status,
            "merchant_reference": "SUB-4471-NOV",
            "provider_reference": "SEL-998877",
            "initiated_at": "2026-11-22T08:00:00+00:00",
            "completed_at": "2026-11-22T08:01:10+00:00" if status == "successful" else None,
            **collection_overrides,
        },
    )
    transaction = create_transaction(
        fake_client,
        merchant_id,
        collection_id=collection["id"],
        status={"successful": "successful", "failed": "failed"}.get(status, "processing"),
        provider_reference="SEL-998877",
        gross_amount="15000.00",
        net_amount="15000.00",
    )
    return collection, transaction


def _delivery(fake_client, merchant_id, collection_id, **overrides):
    return fake_client.seed(
        "webhook_events",
        {
            "merchant_id": str(merchant_id),
            "event_name": "collection.success",
            "payload": {"collection_id": str(collection_id), "secret_marker": "PAYLOAD-MUST-NOT-LEAK"},
            "target_url": "https://billing.example/hooks/infinitypay?token=URL-MUST-NOT-LEAK",
            "status": "pending",
            "attempts": 0,
            **overrides,
        },
    )


def _tracking(headers, transaction_id):
    return client.get(f"/v1/merchant/transactions/{transaction_id}/tracking", headers=headers)


# --- the three facts stay separate -------------------------------------------------


def test_confirmed_payment_with_exhausted_delivery(fake_client):
    """The exact incident: money in, merchant's endpoint returned 500
    five times. The payment is a success; the delivery is not; activation
    is unknown. Three answers, not one."""
    merchant_id, headers = _merchant(fake_client)
    collection, transaction = _paid(fake_client, merchant_id)
    _delivery(
        fake_client,
        merchant_id,
        collection["id"],
        status="failed",
        attempts=5,
        response_status_code=500,
        last_attempted_at="2026-11-22T08:11:10+00:00",
    )

    response = _tracking(headers, transaction["id"])

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [s["code"] for s in data["payment"]] == ["initiated", "confirmed"]
    assert data["payment"][1]["state"] == "done"
    assert data["payment"][1]["at"].startswith("2026-11-22T08:01:10")

    [delivery] = data["webhooks"]["deliveries"]
    assert delivery["state"] == "exhausted"
    assert delivery["label"] == "Webhook delivery exhausted"
    assert delivery["response_status"] == 500
    assert delivery["attempts"] == 5 and delivery["max_attempts"] == 5
    assert delivery["next_retry_at"] is None, "an exhausted delivery is never retried"

    assert data["service_activation"]["status"] == "not_confirmed"
    assert data["service_activation"]["label"] == "Service activation not confirmed"


def test_delivered_webhook_still_does_not_confirm_activation(fake_client):
    """HTTP 2xx means their server received it. Whether it then switched
    the customer on is something only their billing system knows."""
    merchant_id, headers = _merchant(fake_client)
    collection, transaction = _paid(fake_client, merchant_id)
    _delivery(
        fake_client,
        merchant_id,
        collection["id"],
        status="delivered",
        attempts=1,
        response_status_code=200,
        last_attempted_at="2026-11-22T08:01:12+00:00",
        delivered_at="2026-11-22T08:01:12+00:00",
    )

    data = _tracking(headers, transaction["id"]).json()["data"]

    [delivery] = data["webhooks"]["deliveries"]
    assert delivery["state"] == "delivered"
    assert delivery["response_status"] == 200
    assert delivery["delivered_at"].startswith("2026-11-22T08:01:12")
    assert data["service_activation"]["status"] == "not_confirmed"
    assert "billing system" in data["service_activation"]["detail"]


def test_a_retrying_delivery_shows_when_the_worker_will_try_next(fake_client):
    merchant_id, headers = _merchant(fake_client)
    collection, transaction = _paid(fake_client, merchant_id)
    last = datetime(2026, 11, 22, 8, 1, 12, tzinfo=timezone.utc)
    _delivery(
        fake_client,
        merchant_id,
        collection["id"],
        status="retrying",
        attempts=2,
        response_status_code=503,
        last_attempted_at=last.isoformat(),
    )

    [delivery] = _tracking(headers, transaction["id"]).json()["data"]["webhooks"]["deliveries"]

    assert delivery["state"] == "retrying"
    # Attempt 3 waits 90s after attempt 2 - the worker's own schedule.
    assert datetime.fromisoformat(delivery["next_retry_at"]) == last + timedelta(seconds=90)


def test_no_delivery_records_is_said_plainly_not_guessed(fake_client):
    merchant_id, headers = _merchant(fake_client)
    _collection, transaction = _paid(fake_client, merchant_id)

    webhooks = _tracking(headers, transaction["id"]).json()["data"]["webhooks"]

    assert webhooks == {"applicable": True, "configured": True, "available": True, "deliveries": []}


def test_a_merchant_with_no_webhook_endpoint_is_told_so(fake_client):
    merchant_id, headers = _merchant(fake_client, webhook=False)
    _collection, transaction = _paid(fake_client, merchant_id)

    webhooks = _tracking(headers, transaction["id"]).json()["data"]["webhooks"]

    assert webhooks["configured"] is False
    assert webhooks["deliveries"] == []


def test_a_failed_payment_shows_the_merchant_safe_reason_not_the_providers(fake_client):
    merchant_id, headers = _merchant(fake_client)
    _collection, transaction = _paid(
        fake_client,
        merchant_id,
        status="failed",
        failed_at="2026-11-22T08:02:00+00:00",
        failure_reason="PROVIDER-RAW: insufficient funds code 0x51 stack...",
        failure_reason_message="The customer did not have enough balance.",
    )

    data = _tracking(headers, transaction["id"]).json()["data"]

    assert data["payment"][1]["code"] == "failed"
    assert data["payment"][1]["detail"] == "The customer did not have enough balance."
    assert "PROVIDER-RAW" not in str(data)


@pytest.mark.parametrize("status", ["pending", "processing", "pending_review"])
def test_an_unresolved_payment_is_awaiting_confirmation(fake_client, status):
    merchant_id, headers = _merchant(fake_client)
    _collection, transaction = _paid(fake_client, merchant_id, status=status)

    steps = _tracking(headers, transaction["id"]).json()["data"]["payment"]

    assert steps[-1]["code"] == "awaiting"
    assert steps[-1]["state"] == "waiting"
    assert steps[-1]["at"] is None


# --- references --------------------------------------------------------------------


def test_the_three_references_are_returned_separately(fake_client):
    merchant_id, headers = _merchant(fake_client)
    collection, transaction = _paid(fake_client, merchant_id)

    ids = _tracking(headers, transaction["id"]).json()["data"]["identifiers"]

    assert ids == {
        "payment_id": collection["id"],
        "merchant_reference": "SUB-4471-NOV",
        "transaction_reference": transaction["reference"],
        "provider_reference": "SEL-998877",
    }


def test_the_payment_id_is_the_collection_id_the_api_and_webhooks_already_return(fake_client):
    """No new identifier: the tracking view's payment_id must be the same
    value as the webhook payload's collection_id."""
    from app.services.collections import _collection_webhook_payload

    merchant_id, headers = _merchant(fake_client)
    collection, transaction = _paid(fake_client, merchant_id)

    payload = _collection_webhook_payload(collection=collection, external_status="successful", transaction=transaction)
    ids = _tracking(headers, transaction["id"]).json()["data"]["identifiers"]

    assert ids["payment_id"] == payload["collection_id"]
    assert ids["merchant_reference"] == payload["merchant_reference"]


def test_a_withdrawal_has_no_payment_id_and_no_webhook_section(fake_client):
    merchant_id, headers = _merchant(fake_client)
    transaction = create_transaction(fake_client, merchant_id, type="disbursement", method="MOBILE_MONEY")

    data = _tracking(headers, transaction["id"]).json()["data"]

    assert data["identifiers"]["payment_id"] is None
    assert data["webhooks"]["applicable"] is False


# --- isolation and what is never exposed --------------------------------------------


def test_another_merchants_transaction_is_a_404(fake_client):
    owner_id, _owner_headers = _merchant(fake_client)
    _other_id, other_headers = _merchant(fake_client)
    _collection, transaction = _paid(fake_client, owner_id)

    response = _tracking(other_headers, transaction["id"])

    assert response.status_code == 404


def test_another_merchants_delivery_rows_are_never_folded_in(fake_client):
    """Even a delivery row that names this collection is ignored unless it
    belongs to the same merchant."""
    merchant_id, headers = _merchant(fake_client)
    other_id, _ = _merchant(fake_client)
    collection, transaction = _paid(fake_client, merchant_id)
    _delivery(fake_client, other_id, collection["id"], status="delivered", response_status_code=200)

    assert _tracking(headers, transaction["id"]).json()["data"]["webhooks"]["deliveries"] == []


def test_no_payload_target_url_or_secret_is_returned(fake_client):
    merchant_id, headers = _merchant(fake_client)
    collection, transaction = _paid(fake_client, merchant_id)
    _delivery(fake_client, merchant_id, collection["id"], status="failed", attempts=5, response_status_code=500)

    body = _tracking(headers, transaction["id"]).text

    assert "PAYLOAD-MUST-NOT-LEAK" not in body
    assert "URL-MUST-NOT-LEAK" not in body
    assert "billing.example" not in body
    assert "payload" not in body
    assert "target_url" not in body


# --- duplicates ------------------------------------------------------------------------


def test_a_duplicate_provider_callback_queues_one_webhook_and_tracking_shows_one(fake_client):
    """resolve_collection is what every callback, refresh and sweep funnels
    through. Running it twice must leave one collection.success, so the
    timeline cannot show a second, phantom notification."""
    merchant_id, headers = _merchant(fake_client)
    collection, transaction = _paid(fake_client, merchant_id, status="processing")
    result = CollectionResult(provider="selcom", provider_reference="SEL-998877", status="successful")

    resolve_collection(fake_client, collection_id=uuid.UUID(collection["id"]), result=result)
    resolve_collection(fake_client, collection_id=uuid.UUID(collection["id"]), result=result)

    events = [
        e
        for e in fake_client.table("webhook_events")._table.rows
        if e["event_name"] == "collection.success" and e.get("collection_id") == collection["id"]
    ]
    assert len(events) == 1
    data = _tracking(headers, transaction["id"]).json()["data"]
    assert [d["state"] for d in data["webhooks"]["deliveries"]] == ["queued"]
    assert data["payment"][-1]["code"] == "confirmed"


def test_two_delivery_rows_are_listed_separately_never_merged(fake_client):
    """A success followed by a later reversal event: each delivery keeps its
    own outcome, oldest first."""
    merchant_id, headers = _merchant(fake_client)
    collection, transaction = _paid(fake_client, merchant_id)
    _delivery(fake_client, merchant_id, collection["id"], status="delivered", attempts=1, response_status_code=200)
    _delivery(
        fake_client,
        merchant_id,
        collection["id"],
        event_name="collection.failed",
        status="failed",
        attempts=5,
        response_status_code=404,
    )

    deliveries = _tracking(headers, transaction["id"]).json()["data"]["webhooks"]["deliveries"]

    assert [(d["event_name"], d["state"]) for d in deliveries] == [
        ("collection.success", "delivered"),
        ("collection.failed", "exhausted"),
    ]


# --- searching by the shared reference ------------------------------------------------------


def test_a_merchant_can_find_a_payment_by_its_payment_id(fake_client):
    merchant_id, headers = _merchant(fake_client)
    collection, transaction = _paid(fake_client, merchant_id)
    create_transaction(fake_client, merchant_id)  # noise

    response = client.get(f"/v1/merchant/transactions?search={collection['id']}", headers=headers)

    assert response.status_code == 200
    assert [r["id"] for r in response.json()["data"]] == [transaction["id"]]
    assert response.json()["meta"]["total"] == 1


def test_another_merchants_payment_id_finds_nothing(fake_client):
    owner_id, _ = _merchant(fake_client)
    _other_id, other_headers = _merchant(fake_client)
    collection, _transaction = _paid(fake_client, owner_id)

    response = client.get(f"/v1/merchant/transactions?search={collection['id']}", headers=other_headers)

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_an_all_digit_payment_id_is_not_mistaken_for_a_phone_number(fake_client):
    merchant_id, headers = _merchant(fake_client)
    digits = "12345678-1234-4234-8234-123456789012"
    collection, transaction = _paid(fake_client, merchant_id, id=digits)

    response = client.get(f"/v1/merchant/transactions?search={digits}", headers=headers)

    assert [r["id"] for r in response.json()["data"]] == [transaction["id"]]
    assert collection["id"] == digits


def test_super_admin_can_filter_by_payment_id_and_see_it_on_the_row(fake_client):
    merchant_id, _ = _merchant(fake_client)
    collection, transaction = _paid(fake_client, merchant_id)
    create_transaction(fake_client, merchant_id)
    admin = uuid.uuid4()
    make_super_admin(fake_client, admin)

    response = client.get(f"/v1/admin/transactions?collection_id={collection['id']}", headers=auth_headers(admin))

    assert response.status_code == 200
    [row] = response.json()["data"]
    assert row["transaction_id"] == transaction["id"]
    assert row["collection_id"] == collection["id"]


def test_super_admin_tracking_works_across_merchants_and_merchants_cannot_use_it(fake_client):
    merchant_id, merchant_headers = _merchant(fake_client)
    collection, transaction = _paid(fake_client, merchant_id)
    _delivery(fake_client, merchant_id, collection["id"], status="failed", attempts=5, response_status_code=500)
    admin = uuid.uuid4()
    make_super_admin(fake_client, admin)

    as_admin = client.get(f"/v1/admin/transactions/{transaction['id']}/tracking", headers=auth_headers(admin))
    as_merchant = client.get(f"/v1/admin/transactions/{transaction['id']}/tracking", headers=merchant_headers)

    assert as_admin.status_code == 200
    assert as_admin.json()["data"]["webhooks"]["deliveries"][0]["state"] == "exhausted"
    assert as_admin.json()["data"]["service_activation"]["status"] == "not_confirmed"
    assert as_merchant.status_code == 403


def test_tracking_is_read_only(fake_client):
    """Opening the timeline must never resend or retry anything."""
    merchant_id, headers = _merchant(fake_client)
    collection, transaction = _paid(fake_client, merchant_id)
    row = _delivery(fake_client, merchant_id, collection["id"], status="failed", attempts=5, response_status_code=500)
    before = dict(row)

    _tracking(headers, transaction["id"])

    after = next(e for e in fake_client.table("webhook_events")._table.rows if e["id"] == row["id"])
    assert after["status"] == before["status"] == "failed"
    assert after["attempts"] == 5
    assert len(fake_client.table("webhook_events")._table.rows) == 1
