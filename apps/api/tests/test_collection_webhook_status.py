"""A merchant should be told when a payment worked but their own system
was never informed.

A collection can be entirely successful here - customer charged, wallet
credited, ledger balanced - while the merchant's endpoint returned an
error and the notification never landed. Their Collections page said
"Success" and their own system showed nothing, so the customer was never
activated. The failure lived in webhook_events, which merchants cannot
see.

On 2026-10-23 that was nine customers in one day for a single partner,
every one activated by hand after they complained, plus payout
notifications that had never once been delivered to that endpoint.

So the delivery outcome is now read back alongside the payment. The rules
that matter:

  * it never changes the payment's own status - a successful collection
    stays successful whatever the merchant's server said;
  * it is merchant-scoped, so one merchant can never see another's
    delivery history;
  * it costs one query for a page, not one per row.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.webhook_status import batch_collection_webhook_status
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _collection(fake_client, merchant_id, *, status="successful", amount="1000"):
    return fake_client.seed(
        "collections",
        {
            "merchant_id": str(merchant_id),
            "method": "PUSH",
            "amount": amount,
            "currency": "TZS",
            "status": status,
            "customer_phone": "255712345678",
            "initiated_at": "2026-10-23T10:00:00+00:00",
        },
    )


def _event(fake_client, merchant_id, collection_id, *, status, code=None,
           attempts=5, event_name="collection.success", created_at="2026-10-23T10:01:00+00:00"):
    return fake_client.seed(
        "webhook_events",
        {
            "merchant_id": str(merchant_id),
            "event_name": event_name,
            "target_url": "https://merchant.example/callback",
            "payload": {"collection_id": str(collection_id), "amount": "1000"},
            "status": status,
            "attempts": attempts,
            "response_status_code": code,
            "created_at": created_at,
        },
    )


# --- the lookup --------------------------------------------------------


def test_a_failed_delivery_is_reported_against_its_collection(fake_client):
    merchant_id = uuid.uuid4()
    col = _collection(fake_client, merchant_id)
    _event(fake_client, merchant_id, col["id"], status="failed", code=500)

    found = batch_collection_webhook_status(
        fake_client, merchant_id=merchant_id, collection_ids=[col["id"]]
    )

    assert found[str(col["id"])]["status"] == "failed"
    assert found[str(col["id"])]["response_code"] == 500
    assert found[str(col["id"])]["attempts"] == 5


def test_a_collection_with_no_event_is_absent(fake_client):
    """Absent, not "unknown" - covers both "no webhook configured" and
    "the event has not been raised yet", and the caller shows nothing."""
    merchant_id = uuid.uuid4()
    col = _collection(fake_client, merchant_id)

    assert batch_collection_webhook_status(
        fake_client, merchant_id=merchant_id, collection_ids=[col["id"]]
    ) == {}


def test_another_merchants_delivery_is_never_returned(fake_client):
    """The isolation that matters. The filter is on merchant_id as well as
    the ids, so passing an id you do not own returns nothing."""
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    their_col = _collection(fake_client, theirs)
    _event(fake_client, theirs, their_col["id"], status="failed", code=500)

    found = batch_collection_webhook_status(
        fake_client, merchant_id=mine, collection_ids=[their_col["id"]]
    )

    assert found == {}


def test_the_most_recent_event_wins(fake_client):
    """A collection can raise more than one event; the latest one is the
    current truth about whether their system knows."""
    merchant_id = uuid.uuid4()
    col = _collection(fake_client, merchant_id)
    _event(fake_client, merchant_id, col["id"], status="failed", code=500,
           created_at="2026-10-23T10:01:00+00:00")
    _event(fake_client, merchant_id, col["id"], status="delivered", code=200,
           created_at="2026-10-23T11:00:00+00:00")

    found = batch_collection_webhook_status(
        fake_client, merchant_id=merchant_id, collection_ids=[col["id"]]
    )

    assert found[str(col["id"])]["status"] == "delivered"


def test_an_unrelated_event_type_is_ignored(fake_client):
    """A merchant does not need to be told their endpoint missed an event
    that was never about money reaching them."""
    merchant_id = uuid.uuid4()
    col = _collection(fake_client, merchant_id)
    _event(fake_client, merchant_id, col["id"], status="failed", code=500,
           event_name="payment_link.paid")

    assert batch_collection_webhook_status(
        fake_client, merchant_id=merchant_id, collection_ids=[col["id"]]
    ) == {}


def test_no_collections_asks_nothing(fake_client):
    assert batch_collection_webhook_status(
        fake_client, merchant_id=uuid.uuid4(), collection_ids=[]
    ) == {}


# --- the fake itself ---------------------------------------------------


def test_the_json_path_filter_actually_selects_rows(fake_client):
    """Guards the change this feature needed in the fake.

    webhook_events has no collection_id column - the link is inside the
    payload, matched with PostgREST's `payload->>collection_id`. The fake
    used to resolve that to None for every row, so the filter matched
    nothing and any test built on it would have passed because no rows
    came back rather than because the right ones did.

    Asserted in both directions: the matching row is found, and a
    non-matching one is excluded.
    """
    merchant_id = uuid.uuid4()
    wanted, other = uuid.uuid4(), uuid.uuid4()
    _event(fake_client, merchant_id, wanted, status="failed", code=500)
    _event(fake_client, merchant_id, other, status="failed", code=503)

    rows = (
        fake_client.table("webhook_events")
        .select("payload, status, response_status_code")
        .in_("payload->>collection_id", [str(wanted)])
        .execute()
    ).data

    assert len(rows) == 1
    assert rows[0]["response_status_code"] == 500


# --- what the merchant sees -------------------------------------------


def _list(fake_client, merchant_id, user_id):
    response = client.get(
        f"/v1/merchants/{merchant_id}/collections",
        headers=auth_headers(user_id),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _merchant_admin(fake_client):
    merchant = create_merchant(fake_client)
    user_id = uuid.uuid4()
    fake_client.seed(
        "merchant_users",
        {
            "merchant_id": merchant["id"],
            "user_id": str(user_id),
            "role": "MERCHANT_ADMIN",
            "status": "active",
        },
    )
    return merchant, user_id


def test_the_merchant_sees_the_failed_delivery_on_their_payment(fake_client):
    merchant, user_id = _merchant_admin(fake_client)
    col = _collection(fake_client, merchant["id"])
    _event(fake_client, merchant["id"], col["id"], status="failed", code=500)

    row = next(r for r in _list(fake_client, merchant["id"], user_id) if r["id"] == col["id"])

    assert row["webhook_delivery_status"] == "failed"
    assert row["webhook_response_code"] == 500
    assert row["webhook_attempts"] == 5


def test_the_payment_itself_still_reads_successful(fake_client):
    """The guarantee. A merchant's broken endpoint must never make a
    payment we completed look like it did not happen - the money moved."""
    merchant, user_id = _merchant_admin(fake_client)
    col = _collection(fake_client, merchant["id"], status="successful")
    _event(fake_client, merchant["id"], col["id"], status="failed", code=500)

    row = next(r for r in _list(fake_client, merchant["id"], user_id) if r["id"] == col["id"])

    assert row["status"] == "successful"
    assert row["amount"] == "1000.00" or str(row["amount"]).startswith("1000")


def test_a_payment_whose_notification_landed_says_nothing_alarming(fake_client):
    merchant, user_id = _merchant_admin(fake_client)
    col = _collection(fake_client, merchant["id"])
    _event(fake_client, merchant["id"], col["id"], status="delivered", code=200, attempts=1)

    row = next(r for r in _list(fake_client, merchant["id"], user_id) if r["id"] == col["id"])

    assert row["webhook_delivery_status"] == "delivered"


def test_a_merchant_with_no_webhook_sees_nothing(fake_client):
    """Most merchants have no endpoint at all. They must not grow a new
    empty column of warnings."""
    merchant, user_id = _merchant_admin(fake_client)
    col = _collection(fake_client, merchant["id"])

    row = next(r for r in _list(fake_client, merchant["id"], user_id) if r["id"] == col["id"])

    assert row["webhook_delivery_status"] is None
    assert row["webhook_response_code"] is None


def test_listing_costs_one_query_however_many_collections(fake_client, monkeypatch):
    """This sits on the merchant's busiest page. A lookup per row would
    repeat the mistake just fixed on the Super Admin Businesses page."""
    merchant, user_id = _merchant_admin(fake_client)
    for _ in range(10):
        col = _collection(fake_client, merchant["id"])
        _event(fake_client, merchant["id"], col["id"], status="failed", code=500)

    calls: list[str] = []
    original = fake_client.table
    monkeypatch.setattr(fake_client, "table", lambda name: (calls.append(name), original(name))[1])

    rows = _list(fake_client, merchant["id"], user_id)

    assert len(rows) >= 10
    assert calls.count("webhook_events") == 1, calls


# --- the Super Admin view ----------------------------------------------
#
# Super Admin is who gets asked "my customer paid and was never
# connected", and until 2026-10-27 that was the one screen with no answer:
# the merchant could see the delivery failure on their own page, the
# person fielding the complaint could not.


def test_super_admin_sees_the_failure_across_merchants(fake_client):
    """Deliberately unscoped — it must return rows for merchants the caller
    has no membership of, which is exactly why it is a separate function
    from the merchant-scoped one."""
    from app.services.webhook_status import admin_batch_collection_webhook_status

    first, second = uuid.uuid4(), uuid.uuid4()
    a = _collection(fake_client, first)
    b = _collection(fake_client, second)
    _event(fake_client, first, a["id"], status="failed", code=500)
    _event(fake_client, second, b["id"], status="delivered", code=200)

    found = admin_batch_collection_webhook_status(fake_client, [a["id"], b["id"]])

    assert found[str(a["id"])]["status"] == "failed"
    assert found[str(a["id"])]["response_code"] == 500
    assert found[str(b["id"])]["status"] == "delivered"


def test_the_admin_lookup_agrees_with_the_merchant_one(fake_client):
    """Same answer, different scope. If these ever disagreed, the merchant
    and the Super Admin would be reading different truths about the same
    payment."""
    from app.services.webhook_status import admin_batch_collection_webhook_status

    merchant_id = uuid.uuid4()
    col = _collection(fake_client, merchant_id)
    _event(fake_client, merchant_id, col["id"], status="failed", code=503)

    scoped = batch_collection_webhook_status(
        fake_client, merchant_id=merchant_id, collection_ids=[col["id"]]
    )
    unscoped = admin_batch_collection_webhook_status(fake_client, [col["id"]])

    assert scoped[str(col["id"])] == unscoped[str(col["id"])]


def test_the_admin_lookup_asks_nothing_for_no_collections(fake_client):
    from app.services.webhook_status import admin_batch_collection_webhook_status

    assert admin_batch_collection_webhook_status(fake_client, []) == {}
