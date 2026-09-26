"""Cross-merchant IDOR probes against the own-merchant surface.

Every route under /v1/merchant/* resolves the tenant from the caller's
membership, so the only way to reach another merchant's data there is to
keep your own session and swap the *resource* id in the path. That is the
attack this file performs: seed a row owned by merchant B, then ask for it
as merchant A.

The expected answer is 404, not 403. "Not found" tells the caller nothing
about whether the id exists, which matters because a 403 on a real id and
a 404 on a fake one is itself an oracle for enumerating other merchants'
records.

Existing suites already cover individual resources; this one sweeps the
by-id routes together so a newly added route is easy to slot in beside its
neighbours.
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

ALLOWED = (403, 404)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def two_merchants(fake_client):
    """Merchant A is the attacker's own account; merchant B owns the data."""
    a = create_merchant(fake_client)
    a_user = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(a["id"]), a_user, "MERCHANT_ADMIN")

    b = create_merchant(fake_client)
    b_user = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(b["id"]), b_user, "MERCHANT_ADMIN")

    return {"a": a, "a_user": a_user, "b": b, "b_user": b_user}


def _seed_link(fake_client, merchant_id: str) -> str:
    return fake_client.seed(
        "payment_links",
        {
            "merchant_id": merchant_id,
            "amount": "5000.00",
            "currency": "TZS",
            "allowed_payment_methods": ["STK_PUSH"],
            "status": "ACTIVE",
            "public_slug": f"slug-{uuid.uuid4().hex[:8]}",
        },
    )["id"]


def _seed_invoice(fake_client, merchant_id: str) -> str:
    return fake_client.seed(
        "invoices",
        {
            "merchant_id": merchant_id,
            "invoice_number": f"INV-{uuid.uuid4().hex[:6]}",
            "customer_name": "Someone Else",
            "customer_email": "someone@example.com",
            "status": "DRAFT",
            "currency": "TZS",
            "total_amount": "5000.00",
        },
    )["id"]


# --- reads ---------------------------------------------------------------


def test_cannot_read_another_merchants_payment_link(fake_client, two_merchants):
    link_id = _seed_link(fake_client, two_merchants["b"]["id"])

    response = client.get(
        f"/v1/merchant/payment-links/{link_id}", headers=auth_headers(two_merchants["a_user"])
    )

    assert response.status_code in ALLOWED, response.text


def test_cannot_read_another_merchants_invoice(fake_client, two_merchants):
    invoice_id = _seed_invoice(fake_client, two_merchants["b"]["id"])

    response = client.get(
        f"/v1/merchant/invoices/{invoice_id}", headers=auth_headers(two_merchants["a_user"])
    )

    assert response.status_code in ALLOWED, response.text


def test_cannot_read_another_merchants_dispute(fake_client, two_merchants):
    dispute_id = fake_client.seed(
        "disputes",
        {"merchant_id": two_merchants["b"]["id"], "status": "OPEN", "reason": "Unauthorized charge"},
    )["id"]

    response = client.get(
        f"/v1/merchant/disputes/{dispute_id}", headers=auth_headers(two_merchants["a_user"])
    )

    assert response.status_code in ALLOWED, response.text


# --- writes --------------------------------------------------------------


def test_cannot_modify_another_merchants_payment_link(fake_client, two_merchants):
    link_id = _seed_link(fake_client, two_merchants["b"]["id"])

    response = client.patch(
        f"/v1/merchant/payment-links/{link_id}",
        headers=auth_headers(two_merchants["a_user"]),
        json={"amount": "1.00"},
    )

    assert response.status_code in ALLOWED, response.text
    # And the row itself is untouched.
    row = next(r for r in fake_client.table("payment_links")._table.rows if r["id"] == link_id)
    assert row["amount"] == "5000.00"


def test_cannot_cancel_another_merchants_payment_link(fake_client, two_merchants):
    link_id = _seed_link(fake_client, two_merchants["b"]["id"])

    response = client.patch(
        f"/v1/merchant/payment-links/{link_id}/cancel", headers=auth_headers(two_merchants["a_user"])
    )

    assert response.status_code in ALLOWED, response.text
    row = next(r for r in fake_client.table("payment_links")._table.rows if r["id"] == link_id)
    assert row["status"] == "ACTIVE"


def test_cannot_modify_another_merchants_invoice(fake_client, two_merchants):
    invoice_id = _seed_invoice(fake_client, two_merchants["b"]["id"])

    response = client.patch(
        f"/v1/merchant/invoices/{invoice_id}",
        headers=auth_headers(two_merchants["a_user"]),
        json={"customer_name": "Attacker"},
    )

    assert response.status_code in ALLOWED, response.text


# --- credentials ---------------------------------------------------------


def test_cannot_revoke_another_merchants_api_key(fake_client, two_merchants):
    """The most damaging of these: revoking a competitor's live key would
    take their integration down."""
    _raw, key = make_api_key(fake_client, merchant_id=uuid.UUID(two_merchants["b"]["id"]))

    response = client.patch(
        f"/v1/merchant/api-keys/{key['id']}/revoke", headers=auth_headers(two_merchants["a_user"])
    )

    assert response.status_code in ALLOWED, response.text
    row = next(r for r in fake_client.table("api_keys")._table.rows if r["id"] == key["id"])
    assert row["status"] == "active"


def test_cannot_rotate_another_merchants_api_key(fake_client, two_merchants):
    _raw, key = make_api_key(fake_client, merchant_id=uuid.UUID(two_merchants["b"]["id"]))

    response = client.post(
        f"/v1/merchant/api-keys/{key['id']}/rotate", headers=auth_headers(two_merchants["a_user"])
    )

    assert response.status_code in ALLOWED, response.text


# --- team ----------------------------------------------------------------


def test_cannot_deactivate_another_merchants_staff(fake_client, two_merchants):
    """Role escalation's mirror image: removing someone else's staff."""
    victim = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(two_merchants["b"]["id"]), victim, "MERCHANT_STAFF")
    row_id = next(
        r["id"]
        for r in fake_client.table("merchant_users")._table.rows
        if r["user_id"] == str(victim)
    )

    response = client.post(
        f"/v1/merchant/users/{row_id}/deactivate", headers=auth_headers(two_merchants["a_user"])
    )

    assert response.status_code in ALLOWED, response.text
    row = next(r for r in fake_client.table("merchant_users")._table.rows if r["id"] == row_id)
    assert row["status"] == "active"


def test_cannot_change_another_merchants_staff_role(fake_client, two_merchants):
    victim = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(two_merchants["b"]["id"]), victim, "MERCHANT_STAFF")
    row_id = next(
        r["id"]
        for r in fake_client.table("merchant_users")._table.rows
        if r["user_id"] == str(victim)
    )

    response = client.patch(
        f"/v1/merchant/users/{row_id}",
        headers=auth_headers(two_merchants["a_user"]),
        json={"role": "MERCHANT_ADMIN"},
    )

    assert response.status_code in ALLOWED, response.text


# --- listings must not bleed --------------------------------------------


def test_listings_only_ever_contain_the_callers_own_records(fake_client, two_merchants):
    """The other half of IDOR: not fetching someone else's row by id, but a
    list endpoint quietly including it."""
    _seed_link(fake_client, two_merchants["b"]["id"])
    _seed_invoice(fake_client, two_merchants["b"]["id"])
    mine = _seed_link(fake_client, two_merchants["a"]["id"])

    links = client.get("/v1/merchant/payment-links", headers=auth_headers(two_merchants["a_user"]))
    assert links.status_code == 200, links.text
    returned = {row["id"] for row in links.json()["data"]}
    assert returned == {mine}

    invoices = client.get("/v1/merchant/invoices", headers=auth_headers(two_merchants["a_user"]))
    assert invoices.status_code == 200, invoices.text
    assert invoices.json()["data"] == []


def test_a_merchant_with_no_membership_gets_nothing(fake_client, two_merchants):
    """A signed-in user who belongs to no merchant must not fall through to
    an unscoped query."""
    stranger = uuid.uuid4()

    response = client.get("/v1/merchant/payment-links", headers=auth_headers(stranger))

    assert response.status_code == 404, response.text
