"""Pay by Link: a merchant's permanent public checkout page
(/pay/{slug}) — see docs/PAY_BY_LINK.md and app/services/pay_by_link.py.

Deliberately does NOT re-test collection-credit safety (successful
payment credits the wallet once, duplicate reconciliation/webhook can't
double-credit, pending/failed/reversed never credit, receipt email after
success) — Pay by Link's checkout endpoint only ever creates an ordinary
payment_links row (created_via="pay_by_link") and hands off to the exact
same code path every other payment link already uses, so every one of
those guarantees is already proven, once, in test_collections.py /
test_payment_links.py / test_checkout_reconciliation.py and applies here
unchanged by construction — see execute_pay_by_link_checkout's own
docstring for why. What's actually new and tested here: slug management,
the create/update/enable-disable merchant endpoints, the public
lookup/checkout endpoints, source tagging, and that this feature is
additive (an existing generated payment link's slug is never shadowed).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.collection_source import resolve_payment_link_collection_source
from app.services.selcom.client import get_selcom_client
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "0")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    get_settings.cache_clear()
    get_selcom_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_selcom_client.cache_clear()


def _merchant_and_admin(fake_client, **merchant_overrides):
    merchant = create_merchant(fake_client, **merchant_overrides)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    return merchant_id, admin_id


def _create(admin_id: uuid.UUID, **overrides) -> dict:
    response = client.post("/v1/merchant/pay-by-link", headers=auth_headers(admin_id), json=overrides)
    assert response.status_code == 201, response.text
    return response.json()["data"]


_VALID_CHECKOUT_BODY = {
    "first_name": "Grace",
    "last_name": "Mwakalinga",
    "email": "grace@example.com",
    "phone": "255747730270",
    "amount": "25000",
    "currency": "TZS",
    "description": "Order #42",
}


def _checkout(slug: str, idem_key: str | None = None, **overrides):
    body = {**_VALID_CHECKOUT_BODY, **overrides}
    return client.post(
        f"/public/pay-by-link/{slug}/checkout",
        headers={"Idempotency-Key": idem_key or str(uuid.uuid4())},
        json=body,
    )


# --- Merchant creation ---------------------------------------------------------


def test_merchant_can_create_pay_by_link(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    created = _create(admin_id)

    assert created["display_name"] == "Paul Masanja"
    assert created["slug"] == "paul-masanja"
    assert created["is_active"] is True
    assert created["public_url"].endswith("/pay/paul-masanja")


def test_default_slug_generated_from_merchant_name(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Kariakoo Fresh Produce")
    created = _create(admin_id)
    assert created["slug"] == "kariakoo-fresh-produce"


def test_duplicate_slug_is_rejected(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)

    _other_merchant_id, other_admin_id = _merchant_and_admin(fake_client, business_name="Someone Else")
    response = client.post(
        "/v1/merchant/pay-by-link", headers=auth_headers(other_admin_id), json={"slug": "paul-masanja"}
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["message"] == "This slug is already taken."


def test_auto_suffix_when_default_slug_collides(fake_client):
    """Two merchants with the same business name both get usable slugs —
    "paul-masanja" then "paul-masanja-2" — rather than the second
    merchant's creation failing outright."""
    _m1, admin1 = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _m2, admin2 = _merchant_and_admin(fake_client, business_name="Paul Masanja")

    first = _create(admin1)
    second = _create(admin2)

    assert first["slug"] == "paul-masanja"
    assert second["slug"] == "paul-masanja-2"


@pytest.mark.parametrize("reserved", ["admin", "api", "webhooks", "payment-links"])
def test_reserved_slug_is_rejected(fake_client, reserved):
    _merchant_id, admin_id = _merchant_and_admin(fake_client)
    response = client.post("/v1/merchant/pay-by-link", headers=auth_headers(admin_id), json={"slug": reserved})
    assert response.status_code == 422, response.text


def test_slug_cannot_collide_with_an_existing_generated_payment_link(fake_client):
    """A merchant-chosen slug must not shadow another merchant's already-
    shared, unrelated generated payment_links.public_slug — checked
    case-insensitively, since a Pay by Link slug is always lowercase but
    a generated public_slug (secrets.token_urlsafe) isn't. Either a 409
    (case-insensitive collision found) or a 422 (the token contains a
    character, e.g. `_`, that isn't valid slug format at all) is a
    correct rejection here — what must never happen is a 201."""
    other_merchant_id, other_admin_id = _merchant_and_admin(fake_client)
    link = client.post(
        "/v1/payment-links",
        headers={**auth_headers(other_admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(other_merchant_id), "amount": "1000.00", "currency": "TZS"},
    ).json()["data"]
    taken_slug = link["public_slug"]

    _merchant_id, admin_id = _merchant_and_admin(fake_client)
    response = client.post(
        "/v1/merchant/pay-by-link", headers=auth_headers(admin_id), json={"slug": taken_slug}
    )
    assert response.status_code in (409, 422), response.text


def test_slug_cannot_collide_with_an_existing_generated_payment_link_case_insensitively(fake_client):
    """Directly exercises the case-insensitive path (rather than relying
    on a randomly-generated token happening to be all-lowercase-alnum,
    as the test above does): a Pay by Link slug is rejected even when it
    only matches an existing generated public_slug after lowercasing."""
    other_merchant_id, other_admin_id = _merchant_and_admin(fake_client)
    client.post(
        "/v1/payment-links",
        headers={**auth_headers(other_admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(other_merchant_id), "amount": "1000.00", "currency": "TZS"},
    )
    fake_client.table("payment_links")._table.rows[0]["public_slug"] = "MixedCaseSlug"

    _merchant_id, admin_id = _merchant_and_admin(fake_client)
    response = client.post(
        "/v1/merchant/pay-by-link", headers=auth_headers(admin_id), json={"slug": "mixedcaseslug"}
    )
    assert response.status_code == 409, response.text


def test_merchant_cannot_create_a_second_pay_by_link(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client)
    _create(admin_id)

    response = client.post("/v1/merchant/pay-by-link", headers=auth_headers(admin_id), json={})
    assert response.status_code == 409, response.text


def test_suspended_merchant_cannot_create_pay_by_link(fake_client):
    """403 since 2026-10-11, not the 409 this used to assert.

    The refusal moved earlier and got blunter: suspension now fails in
    get_own_merchant, so the request never reaches
    ensure_merchant_accepts_payments and its ConflictError. Same answer -
    no Pay by Link for a suspended business - from a gate that covers
    every /v1/merchant/* route at once instead of this one endpoint.
    """
    _merchant_id, admin_id = _merchant_and_admin(fake_client, status="suspended")
    response = client.post("/v1/merchant/pay-by-link", headers=auth_headers(admin_id), json={})
    assert response.status_code == 403, response.text
    assert "suspended" in response.text


def test_staff_cannot_create_pay_by_link_for_a_different_merchant(fake_client):
    """No merchant_id field exists on the create request at all — the
    caller's own merchant is the only one that can ever be affected,
    structurally, not just by convention."""
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Merchant A")
    other_merchant_id, _other_admin_id = _merchant_and_admin(fake_client, business_name="Merchant B")

    created = _create(admin_id)
    assert created["merchant_id"] == str(_merchant_id)
    assert created["merchant_id"] != str(other_merchant_id)


def test_get_my_pay_by_link_is_null_before_creation(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client)
    response = client.get("/v1/merchant/pay-by-link/me", headers=auth_headers(admin_id))
    assert response.status_code == 200
    assert response.json()["data"] is None


# --- Merchant update / enable-disable ------------------------------------------


def test_merchant_can_update_display_name_and_description(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client)
    _create(admin_id)

    response = client.patch(
        "/v1/merchant/pay-by-link/me",
        headers=auth_headers(admin_id),
        json={"display_name": "New Name", "description": "Updated description"},
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["display_name"] == "New Name"
    assert body["description"] == "Updated description"


def test_merchant_can_disable_and_reenable(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client)
    created = _create(admin_id)

    disabled = client.patch(
        "/v1/merchant/pay-by-link/me", headers=auth_headers(admin_id), json={"is_active": False}
    ).json()["data"]
    assert disabled["is_active"] is False

    reenabled = client.patch(
        "/v1/merchant/pay-by-link/me", headers=auth_headers(admin_id), json={"is_active": True}
    ).json()["data"]
    assert reenabled["is_active"] is True
    assert reenabled["slug"] == created["slug"]


def test_audit_logs_written_for_create_update_and_disable(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client)
    _create(admin_id)
    client.patch("/v1/merchant/pay-by-link/me", headers=auth_headers(admin_id), json={"is_active": False})

    actions = [a["action"] for a in fake_client.table("audit_logs")._table.rows]
    assert "pay_by_link.created" in actions
    assert "pay_by_link.disabled" in actions


# --- Public page ----------------------------------------------------------------


def test_public_lookup_returns_safe_fields_only(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id, description="Freelance services")

    response = client.get("/public/pay-by-link/paul-masanja")
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body == {"display_name": "Paul Masanja", "description": "Freelance services", "is_active": True}


def test_public_lookup_unknown_slug_404s(fake_client):
    response = client.get("/public/pay-by-link/does-not-exist")
    assert response.status_code == 404


def test_public_lookup_reflects_disabled_status(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)
    client.patch("/v1/merchant/pay-by-link/me", headers=auth_headers(admin_id), json={"is_active": False})

    response = client.get("/public/pay-by-link/paul-masanja")
    assert response.status_code == 200
    assert response.json()["data"]["is_active"] is False


def test_generated_payment_link_slug_is_unaffected_by_pay_by_link_feature(fake_client):
    """The resolver rule lives in the frontend (app/pay/[slug]/page.tsx
    tries fetchPublicPaymentLink first); on the backend, confirms the two
    lookups are on genuinely separate tables with no overlap — a payment
    link's public_slug 404s against the pay-by-link endpoint and vice
    versa."""
    _merchant_id, admin_id = _merchant_and_admin(fake_client)
    link = client.post(
        "/v1/payment-links",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={"merchant_id": str(_merchant_id), "amount": "1000.00", "currency": "TZS"},
    ).json()["data"]

    # The existing payment link is completely unaffected: still resolves
    # via its own endpoint.
    still_works = client.get(f"/public/payment-links/{link['public_slug']}")
    assert still_works.status_code == 200

    # And is correctly absent from the new, separate pay-by-link table.
    not_a_pay_by_link = client.get(f"/public/pay-by-link/{link['public_slug']}")
    assert not_a_pay_by_link.status_code == 404


# --- Checkout ---------------------------------------------------------------


def test_checkout_creates_a_payment_link_for_the_correct_merchant(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)

    response = _checkout("paul-masanja")
    assert response.status_code == 201, response.text
    body = response.json()["data"]
    assert body.get("redirect_url")

    link_row = next(
        r for r in fake_client.table("payment_links")._table.rows if r["id"] == body["payment_link_id"]
    )
    assert link_row["merchant_id"] == str(_merchant_id)
    assert link_row["amount"] == "25000"
    assert link_row["customer_name"] == "Grace Mwakalinga"
    assert link_row["customer_email"] == "grace@example.com"
    assert link_row["customer_phone"] == "255747730270"
    assert link_row["created_via"] == "pay_by_link"
    assert link_row["status"] == "ACTIVE"
    assert body["redirect_url"].endswith(f"/pay/{link_row['public_slug']}")


def test_checkout_ignores_a_merchant_id_in_the_request_body(fake_client):
    """merchant_id isn't even a field on PayByLinkCheckoutRequest — an
    extra, unrecognized key in the JSON body is silently ignored by
    Pydantic, never used to pick the merchant. The slug lookup is the
    only source of truth."""
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)
    other_merchant_id, _ = _merchant_and_admin(fake_client, business_name="Attacker Inc")

    response = _checkout("paul-masanja", merchant_id=str(other_merchant_id))
    assert response.status_code == 201, response.text

    link_row = next(
        r
        for r in fake_client.table("payment_links")._table.rows
        if r["id"] == response.json()["data"]["payment_link_id"]
    )
    assert link_row["merchant_id"] == str(_merchant_id)


def test_checkout_unknown_slug_404s(fake_client):
    response = _checkout("does-not-exist")
    assert response.status_code == 404


def test_checkout_rejected_when_page_disabled(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)
    client.patch("/v1/merchant/pay-by-link/me", headers=auth_headers(admin_id), json={"is_active": False})

    response = _checkout("paul-masanja")
    assert response.status_code == 409, response.text


def test_checkout_rejected_when_merchant_suspended_after_page_created(fake_client):
    """Re-checked at submission time, every time — same "never trust
    stale state" rule as withdrawal approval."""
    merchant = create_merchant(fake_client, business_name="Paul Masanja")
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    _create(admin_id)

    next(r for r in fake_client.table("merchants")._table.rows if r["id"] == str(merchant_id))["status"] = (
        "suspended"
    )

    response = _checkout("paul-masanja")
    assert response.status_code == 409, response.text


def test_checkout_invalid_amount_rejected(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)
    response = _checkout("paul-masanja", amount="0")
    assert response.status_code == 422


def test_checkout_invalid_email_rejected(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)
    response = _checkout("paul-masanja", email="not-an-email")
    assert response.status_code == 422


def test_checkout_invalid_phone_rejected(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)
    response = _checkout("paul-masanja", phone="123")
    assert response.status_code == 422


def test_checkout_blank_first_name_rejected(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)
    response = _checkout("paul-masanja", first_name="   ")
    assert response.status_code == 422


def test_checkout_is_idempotent(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)

    key = str(uuid.uuid4())
    first = _checkout("paul-masanja", idem_key=key)
    second = _checkout("paul-masanja", idem_key=key)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["data"]["payment_link_id"] == second.json()["data"]["payment_link_id"]

    created_links = [
        r for r in fake_client.table("payment_links")._table.rows if r["created_via"] == "pay_by_link"
    ]
    assert len(created_links) == 1


def test_checkout_audit_logs_amount_and_currency_but_not_customer_pii(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)
    _checkout("paul-masanja")

    events = [a for a in fake_client.table("audit_logs")._table.rows if a["action"] == "pay_by_link.payment_initiated"]
    assert len(events) == 1
    event = events[0]
    assert event["actor_type"] == "system"
    assert event["metadata"]["amount"] == "25000"
    assert event["metadata"]["currency"] == "TZS"
    assert "email" not in event["metadata"]
    assert "phone" not in event["metadata"]
    assert "grace@example.com" not in str(event["metadata"])


# --- Source tagging ------------------------------------------------------------


def test_collection_source_resolves_to_pay_by_link(fake_client):
    """Unit-tests the exact function every eventual collection created
    against a Pay by Link-originated payment_links row is tagged
    through — the same chokepoint every other source (PAYMENT_LINK,
    INVOICE, DASHBOARD_REQUEST, ...) already goes through."""
    payment_link = {"id": str(uuid.uuid4()), "created_via": "pay_by_link", "api_key_id": None}
    assert resolve_payment_link_collection_source(fake_client, payment_link=payment_link).value == "PAY_BY_LINK"


def test_checkout_created_link_resolves_to_pay_by_link_source(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)
    response = _checkout("paul-masanja")
    link_row = next(
        r
        for r in fake_client.table("payment_links")._table.rows
        if r["id"] == response.json()["data"]["payment_link_id"]
    )
    assert resolve_payment_link_collection_source(fake_client, payment_link=link_row).value == "PAY_BY_LINK"


# --- Super Admin visibility ------------------------------------------------------


def test_admin_can_view_a_merchants_pay_by_link(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    response = client.get(
        f"/v1/admin/merchants/{_merchant_id}/pay-by-link", headers=auth_headers(super_admin_id)
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["slug"] == "paul-masanja"


def test_admin_view_is_null_when_merchant_has_no_pay_by_link(fake_client):
    _merchant_id, _admin_id = _merchant_and_admin(fake_client)
    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    response = client.get(
        f"/v1/admin/merchants/{_merchant_id}/pay-by-link", headers=auth_headers(super_admin_id)
    )
    assert response.status_code == 200
    assert response.json()["data"] is None


def test_non_super_admin_cannot_view_via_admin_endpoint(fake_client):
    merchant_id, admin_id = _merchant_and_admin(fake_client)
    response = client.get(f"/v1/admin/merchants/{merchant_id}/pay-by-link", headers=auth_headers(admin_id))
    assert response.status_code == 403


# --- Super Admin platform-wide monitoring ---------------------------------------


def test_admin_can_list_all_pay_by_links(fake_client):
    """GET /v1/admin/pay-by-link — separate from /v1/admin/payment-links
    (which lists the payments created *through* a Pay by Link page,
    tagged created_via="pay_by_link", alongside every other payment
    link) — this lists the permanent pages themselves, platform-wide."""
    _m1, admin1 = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _m2, admin2 = _merchant_and_admin(fake_client, business_name="Kariakoo Fresh Produce")
    _create(admin1)
    _create(admin2)

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    response = client.get("/v1/admin/pay-by-link", headers=auth_headers(super_admin_id))
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    assert len(rows) == 2
    slugs = {row["slug"] for row in rows}
    assert slugs == {"paul-masanja", "kariakoo-fresh-produce"}
    row = next(r for r in rows if r["slug"] == "paul-masanja")
    assert row["merchant_name"] == "Paul Masanja"
    assert row["is_active"] is True
    assert row["last_used_at"] is None


def test_admin_list_reflects_disabled_status_and_last_used(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)
    _checkout("paul-masanja")
    client.patch("/v1/merchant/pay-by-link/me", headers=auth_headers(admin_id), json={"is_active": False})

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    response = client.get("/v1/admin/pay-by-link", headers=auth_headers(super_admin_id))
    row = response.json()["data"][0]
    assert row["is_active"] is False
    assert row["last_used_at"] is not None


def test_admin_list_can_filter_by_merchant_and_active_status(fake_client):
    m1, admin1 = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _m2, admin2 = _merchant_and_admin(fake_client, business_name="Kariakoo Fresh Produce")
    _create(admin1)
    _create(admin2)
    client.patch("/v1/merchant/pay-by-link/me", headers=auth_headers(admin2), json={"is_active": False})

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)

    by_merchant = client.get(
        f"/v1/admin/pay-by-link?merchant_id={m1}", headers=auth_headers(super_admin_id)
    ).json()["data"]
    assert len(by_merchant) == 1
    assert by_merchant[0]["merchant_name"] == "Paul Masanja"

    active_only = client.get(
        "/v1/admin/pay-by-link?is_active=true", headers=auth_headers(super_admin_id)
    ).json()["data"]
    assert len(active_only) == 1
    assert active_only[0]["merchant_name"] == "Paul Masanja"


def test_non_super_admin_cannot_list_pay_by_links(fake_client):
    _merchant_id, admin_id = _merchant_and_admin(fake_client)
    response = client.get("/v1/admin/pay-by-link", headers=auth_headers(admin_id))
    assert response.status_code == 403


# --- Rate limiting -------------------------------------------------------------


def test_checkout_endpoint_is_rate_limited(fake_client):
    from app.core.rate_limit import _limiter

    _merchant_id, admin_id = _merchant_and_admin(fake_client, business_name="Paul Masanja")
    _create(admin_id)
    for _ in range(20):
        _limiter.check("pay_by_link_checkout:testclient", limit=20, window_seconds=60)

    response = _checkout("paul-masanja")
    assert response.status_code == 429
