"""Self-service merchant team management — /v1/merchant/users*
(app/routers/merchant_portal.py's "Team / Users" section). Same
FakeSupabaseClient pattern as test_merchant_portal.py.
"""

import uuid

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
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
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def fake_resend(monkeypatch):
    """Inviting a teammate now sends a real (mocked) email — see
    tests/test_invoices.py's identical fixture for why this patches
    resend.Emails.send directly."""

    def _send(params: dict) -> dict:
        return {"id": "resend-test-message-id"}

    monkeypatch.setattr(resend.Emails, "send", _send)


def _admin(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    fake_client.seed_auth_user(admin_id, email="admin@example.com", full_name="Amina Admin")
    return merchant_id, admin_id


# --- GET /users/me ------------------------------------------------------------


def test_get_my_membership_returns_own_profile(fake_client):
    _merchant_id, admin_id = _admin(fake_client)
    response = client.get("/v1/merchant/users/me", headers=auth_headers(admin_id))
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["full_name"] == "Amina Admin"
    assert body["email"] == "admin@example.com"
    assert body["role"] == "MERCHANT_ADMIN"


def test_get_my_membership_works_for_staff_too(fake_client):
    merchant_id, _admin_id = _admin(fake_client)
    staff_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, staff_id, "MERCHANT_STAFF")
    fake_client.seed_auth_user(staff_id, email="staff@example.com", full_name="Sam Staff")
    response = client.get("/v1/merchant/users/me", headers=auth_headers(staff_id))
    assert response.status_code == 200
    assert response.json()["data"]["role"] == "MERCHANT_STAFF"


# --- POST /users (create/invite) ----------------------------------------------


def test_admin_can_invite_a_new_merchant_user(fake_client):
    _merchant_id, admin_id = _admin(fake_client)
    response = client.post(
        "/v1/merchant/users",
        headers=auth_headers(admin_id),
        json={"full_name": "David Komba", "email": "david@example.com", "role": "MERCHANT_STAFF"},
    )
    assert response.status_code == 201, response.text
    body = response.json()["data"]
    assert body["full_name"] == "David Komba"
    assert body["email"] == "david@example.com"
    assert body["role"] == "MERCHANT_STAFF"
    assert body["status"] == "invited"

    listing = client.get("/v1/merchant/users", headers=auth_headers(admin_id))
    names = [row["full_name"] for row in listing.json()["data"]]
    assert "David Komba" in names


def test_staff_cannot_invite_a_new_merchant_user(fake_client):
    merchant_id, _admin_id = _admin(fake_client)
    staff_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, staff_id, "MERCHANT_STAFF")
    response = client.post(
        "/v1/merchant/users",
        headers=auth_headers(staff_id),
        json={"full_name": "David Komba", "email": "david@example.com", "role": "MERCHANT_STAFF"},
    )
    assert response.status_code == 403


def test_invite_is_rate_limited(fake_client):
    """Wiring test for app/core/rate_limit.py's staff_invite scope (added
    during the MVP-readiness rate-limiting sweep) — pre-fills the shared
    in-memory bucket directly rather than firing 10 real invites, then
    confirms one more real request is actually rejected."""
    from app.core.rate_limit import _limiter

    _merchant_id, admin_id = _admin(fake_client)
    for _ in range(10):
        _limiter.check("staff_invite:testclient", limit=10, window_seconds=60)

    response = client.post(
        "/v1/merchant/users",
        headers=auth_headers(admin_id),
        json={"full_name": "David Komba", "email": "david@example.com", "role": "MERCHANT_STAFF"},
    )
    assert response.status_code == 429


def test_invite_requires_a_full_name(fake_client):
    _merchant_id, admin_id = _admin(fake_client)
    response = client.post(
        "/v1/merchant/users",
        headers=auth_headers(admin_id),
        json={"full_name": "  ", "email": "david@example.com", "role": "MERCHANT_STAFF"},
    )
    assert response.status_code == 422


def test_invite_rejects_super_admin_role(fake_client):
    _merchant_id, admin_id = _admin(fake_client)
    response = client.post(
        "/v1/merchant/users",
        headers=auth_headers(admin_id),
        json={"full_name": "David Komba", "email": "david@example.com", "role": "SUPER_ADMIN"},
    )
    assert response.status_code == 422


def test_invite_rejects_already_registered_email(fake_client):
    _merchant_id, admin_id = _admin(fake_client)
    response = client.post(
        "/v1/merchant/users",
        headers=auth_headers(admin_id),
        json={"full_name": "Amina Duplicate", "email": "admin@example.com", "role": "MERCHANT_STAFF"},
    )
    assert response.status_code == 409


# --- PATCH /users/{id} ---------------------------------------------------------


def test_admin_can_update_a_teammates_role(fake_client):
    merchant_id, admin_id = _admin(fake_client)
    staff_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, staff_id, "MERCHANT_STAFF")
    listing = client.get("/v1/merchant/users", headers=auth_headers(admin_id)).json()["data"]
    row_id = next(r["id"] for r in listing if r["user_id"] == str(staff_id))

    response = client.patch(
        f"/v1/merchant/users/{row_id}", headers=auth_headers(admin_id), json={"role": "DEVELOPER"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["role"] == "DEVELOPER"


def test_admin_cannot_change_their_own_role_via_this_endpoint(fake_client):
    _merchant_id, admin_id = _admin(fake_client)
    listing = client.get("/v1/merchant/users", headers=auth_headers(admin_id)).json()["data"]
    own_row_id = next(r["id"] for r in listing if r["user_id"] == str(admin_id))

    response = client.patch(
        f"/v1/merchant/users/{own_row_id}", headers=auth_headers(admin_id), json={"role": "MERCHANT_STAFF"}
    )
    assert response.status_code == 409


# --- POST /users/{id}/deactivate ----------------------------------------------


def test_admin_can_deactivate_a_teammate(fake_client):
    merchant_id, admin_id = _admin(fake_client)
    staff_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, staff_id, "MERCHANT_STAFF")
    listing = client.get("/v1/merchant/users", headers=auth_headers(admin_id)).json()["data"]
    row_id = next(r["id"] for r in listing if r["user_id"] == str(staff_id))

    response = client.post(f"/v1/merchant/users/{row_id}/deactivate", headers=auth_headers(admin_id))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "suspended"


def test_admin_cannot_deactivate_themself(fake_client):
    _merchant_id, admin_id = _admin(fake_client)
    listing = client.get("/v1/merchant/users", headers=auth_headers(admin_id)).json()["data"]
    own_row_id = next(r["id"] for r in listing if r["user_id"] == str(admin_id))

    response = client.post(f"/v1/merchant/users/{own_row_id}/deactivate", headers=auth_headers(admin_id))
    assert response.status_code == 409


# --- Invite redirect_to ---------------------------------------------------------


def test_invite_redirect_url_points_to_the_accept_invite_page_not_login(fake_client, monkeypatch):
    """The whole bug being fixed: a freshly-invited staff member has no
    password yet, so an invite email that lands on /dashboard/login leaves
    them stuck. It must point at the password-setup page instead."""
    _merchant_id, admin_id = _admin(fake_client)
    captured: dict = {}
    original = fake_client.auth.admin.generate_link

    def _spy(params: dict):
        captured["params"] = params
        return original(params)

    monkeypatch.setattr(fake_client.auth.admin, "generate_link", _spy)

    response = client.post(
        "/v1/merchant/users",
        headers=auth_headers(admin_id),
        json={"full_name": "David Komba", "email": "david@example.com", "role": "MERCHANT_STAFF"},
    )
    assert response.status_code == 201, response.text
    assert captured["params"]["type"] == "invite"
    redirect_to = captured["params"]["options"]["redirect_to"]
    assert redirect_to.endswith("/dashboard/invite/accept")
    assert "/dashboard/login" not in redirect_to


def test_invite_uses_resend_branded_email_not_supabase_default(fake_client, monkeypatch):
    """The other half of the same bug fix: generate_link (unlike
    invite_user_by_email) never sends Supabase's own email — this
    endpoint must send its own branded one instead, or the invite would
    go out with no email at all."""
    _merchant_id, admin_id = _admin(fake_client)
    captured: dict = {}
    original_send = resend.Emails.send

    def _spy(params: dict):
        captured["params"] = params
        return original_send(params)

    monkeypatch.setattr(resend.Emails, "send", _spy)

    response = client.post(
        "/v1/merchant/users",
        headers=auth_headers(admin_id),
        json={"full_name": "David Komba", "email": "david@example.com", "role": "MERCHANT_STAFF"},
    )
    assert response.status_code == 201, response.text
    assert captured["params"]["to"] == ["david@example.com"]
    assert captured["params"]["subject"] == "You're invited to InfinityPay Merchant Portal"
    assert "info@infinitypay.me" in captured["params"]["html"]


# --- POST /users/{id}/resend-invite --------------------------------------------


def test_admin_can_resend_a_pending_invite(fake_client):
    merchant_id, admin_id = _admin(fake_client)
    staff_id = _seed_invited_staff(fake_client, merchant_id, admin_id)
    row_id = fake_client.table("merchant_users")._table.rows[-1]["id"]
    assert fake_client.table("merchant_users")._table.rows[-1]["user_id"] == str(staff_id)

    response = client.post(f"/v1/merchant/users/{row_id}/resend-invite", headers=auth_headers(admin_id))
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["email"] == "staff@example.com"
    assert body["status"] == "invited"


def test_resend_invite_uses_recovery_link_not_invite(fake_client, monkeypatch):
    """The staff member's Supabase Auth account already exists from the
    original invite — generate_link(type="invite") would reject a
    duplicate email, so this must use type="recovery" instead."""
    merchant_id, admin_id = _admin(fake_client)
    _seed_invited_staff(fake_client, merchant_id, admin_id)
    row_id = fake_client.table("merchant_users")._table.rows[-1]["id"]

    captured: dict = {}
    original = fake_client.auth.admin.generate_link

    def _spy(params: dict):
        captured["params"] = params
        return original(params)

    monkeypatch.setattr(fake_client.auth.admin, "generate_link", _spy)

    response = client.post(f"/v1/merchant/users/{row_id}/resend-invite", headers=auth_headers(admin_id))
    assert response.status_code == 200, response.text
    assert captured["params"]["type"] == "recovery"
    assert captured["params"]["email"] == "staff@example.com"
    assert captured["params"]["options"]["redirect_to"].endswith("/dashboard/invite/accept")


def test_resend_invite_sends_another_branded_email(fake_client, monkeypatch):
    merchant_id, admin_id = _admin(fake_client)
    _seed_invited_staff(fake_client, merchant_id, admin_id)
    row_id = fake_client.table("merchant_users")._table.rows[-1]["id"]

    captured: dict = {}
    original_send = resend.Emails.send

    def _spy(params: dict):
        captured["params"] = params
        return original_send(params)

    monkeypatch.setattr(resend.Emails, "send", _spy)

    response = client.post(f"/v1/merchant/users/{row_id}/resend-invite", headers=auth_headers(admin_id))
    assert response.status_code == 200, response.text
    assert captured["params"]["to"] == ["staff@example.com"]
    assert captured["params"]["subject"] == "You're invited to InfinityPay Merchant Portal"


def test_staff_cannot_resend_an_invite(fake_client):
    merchant_id, admin_id = _admin(fake_client)
    _seed_invited_staff(fake_client, merchant_id, admin_id)
    row_id = fake_client.table("merchant_users")._table.rows[-1]["id"]
    other_staff_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, other_staff_id, "MERCHANT_STAFF")

    response = client.post(f"/v1/merchant/users/{row_id}/resend-invite", headers=auth_headers(other_staff_id))
    assert response.status_code == 403


def test_cannot_resend_invite_for_an_already_active_teammate(fake_client):
    merchant_id, admin_id = _admin(fake_client)
    staff_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, staff_id, "MERCHANT_STAFF")
    listing = client.get("/v1/merchant/users", headers=auth_headers(admin_id)).json()["data"]
    row_id = next(r["id"] for r in listing if r["user_id"] == str(staff_id))

    response = client.post(f"/v1/merchant/users/{row_id}/resend-invite", headers=auth_headers(admin_id))
    assert response.status_code == 409


def test_resend_invite_never_touches_another_merchants_invite(fake_client):
    merchant_a, admin_a = _admin(fake_client)
    merchant_b, admin_b = _admin(fake_client)
    _seed_invited_staff(fake_client, merchant_a, admin_a)
    staff_a_row_id = fake_client.table("merchant_users")._table.rows[-1]["id"]
    assert fake_client.table("merchant_users")._table.rows[-1]["merchant_id"] == str(merchant_a)

    _seed_invited_staff(fake_client, merchant_b, admin_b)

    # admin_b has no visibility into merchant_a's invite row.
    response = client.post(f"/v1/merchant/users/{staff_a_row_id}/resend-invite", headers=auth_headers(admin_b))
    assert response.status_code == 404


# --- POST /users/me/accept-invite -----------------------------------------------


def _seed_invited_staff(fake_client, merchant_id: uuid.UUID, invited_by: uuid.UUID, role: str = "MERCHANT_STAFF"):
    staff_id = uuid.uuid4()
    fake_client.seed(
        "merchant_users",
        {
            "merchant_id": str(merchant_id),
            "user_id": str(staff_id),
            "role": role,
            "status": "invited",
            "invited_by": str(invited_by),
        },
    )
    fake_client.seed_auth_user(staff_id, email="staff@example.com", full_name="Sam Staff")
    return staff_id


def test_accepting_an_invite_activates_the_membership_and_preserves_merchant_and_role(fake_client):
    merchant_id, admin_id = _admin(fake_client)
    staff_id = _seed_invited_staff(fake_client, merchant_id, admin_id, role="MERCHANT_STAFF")

    response = client.post("/v1/merchant/users/me/accept-invite", headers=auth_headers(staff_id))
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["status"] == "active"
    assert body["merchant_id"] == str(merchant_id)
    assert body["role"] == "MERCHANT_STAFF"
    assert body["user_id"] == str(staff_id)


def test_accept_invite_does_not_require_an_active_membership_first(fake_client):
    """The whole point of this endpoint: it must work while the caller's
    only merchant_users row is still 'invited' — require_own_merchant_role
    would 404 here, which is exactly the trap this endpoint exists to avoid."""
    merchant_id, admin_id = _admin(fake_client)
    staff_id = _seed_invited_staff(fake_client, merchant_id, admin_id)

    before = client.get("/v1/merchant/users/me", headers=auth_headers(staff_id))
    assert before.status_code == 404  # not active yet — proves the trap is real

    accept = client.post("/v1/merchant/users/me/accept-invite", headers=auth_headers(staff_id))
    assert accept.status_code == 200

    after = client.get("/v1/merchant/users/me", headers=auth_headers(staff_id))
    assert after.status_code == 200
    assert after.json()["data"]["status"] == "active"


def test_accept_invite_is_idempotent_once_already_active(fake_client):
    merchant_id, _admin_id = _admin(fake_client)
    staff_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, staff_id, "MERCHANT_STAFF")

    response = client.post("/v1/merchant/users/me/accept-invite", headers=auth_headers(staff_id))
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "active"


def test_accept_invite_404s_with_no_pending_invitation(fake_client):
    response = client.post("/v1/merchant/users/me/accept-invite", headers=auth_headers(uuid.uuid4()))
    assert response.status_code == 404


def test_accept_invite_never_touches_another_merchants_pending_invite(fake_client):
    merchant_a, admin_a = _admin(fake_client)
    merchant_b, admin_b = _admin(fake_client)
    staff_a = _seed_invited_staff(fake_client, merchant_a, admin_a)
    staff_b = _seed_invited_staff(fake_client, merchant_b, admin_b)

    response = client.post("/v1/merchant/users/me/accept-invite", headers=auth_headers(staff_a))
    assert response.status_code == 200
    assert response.json()["data"]["merchant_id"] == str(merchant_a)

    # merchant B's invite must be completely untouched by A's acceptance.
    listing_b = client.get("/v1/merchant/users", headers=auth_headers(admin_b)).json()["data"]
    row_b = next(r for r in listing_b if r["user_id"] == str(staff_b))
    assert row_b["status"] == "invited"
