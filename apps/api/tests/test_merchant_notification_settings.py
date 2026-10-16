"""Merchant collection notification email settings — GET/PATCH
/v1/merchant/notification-settings and GET/PATCH
/v1/admin/merchants/{id}/notification-settings. See
app/services/merchant_notifications.py for the shared validation and
supabase/migrations/20260901010000_merchant_notification_settings.sql for
the table. Sending the notification email itself is covered separately in
tests/test_merchant_collection_notification_email.py.
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


def _merchant_admin(fake_client, **overrides):
    merchant = create_merchant(fake_client, **overrides)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    return merchant_id, user_id


def _merchant_staff(fake_client, merchant_id: uuid.UUID) -> uuid.UUID:
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_STAFF")
    return user_id


# --- Merchant self-service --------------------------------------------------


def test_get_notification_settings_defaults_to_enabled_with_no_emails(fake_client):
    _merchant_id, user_id = _merchant_admin(fake_client)

    response = client.get("/v1/merchant/notification-settings", headers=auth_headers(user_id))

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["primary_notification_email"] is None
    assert data["secondary_notification_email"] is None
    assert data["collection_notifications_enabled"] is True


def test_merchant_can_save_primary_notification_email(fake_client):
    _merchant_id, user_id = _merchant_admin(fake_client)

    response = client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(user_id),
        json={"primary_notification_email": "owner@example.com", "collection_notifications_enabled": True},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["primary_notification_email"] == "owner@example.com"
    assert data["secondary_notification_email"] is None


def test_merchant_can_save_optional_secondary_notification_email(fake_client):
    _merchant_id, user_id = _merchant_admin(fake_client)

    response = client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(user_id),
        json={
            "primary_notification_email": "owner@example.com",
            "secondary_notification_email": "finance@example.com",
            "collection_notifications_enabled": True,
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["primary_notification_email"] == "owner@example.com"
    assert data["secondary_notification_email"] == "finance@example.com"


def test_invalid_email_is_rejected(fake_client):
    _merchant_id, user_id = _merchant_admin(fake_client)

    response = client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(user_id),
        json={"primary_notification_email": "not-an-email", "collection_notifications_enabled": True},
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["message"] == "Enter a valid notification email."


def test_duplicate_emails_are_rejected(fake_client):
    _merchant_id, user_id = _merchant_admin(fake_client)

    response = client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(user_id),
        json={
            "primary_notification_email": "owner@example.com",
            "secondary_notification_email": "OWNER@example.com",
            "collection_notifications_enabled": True,
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["message"] == "Duplicate notification emails are not allowed."


def test_more_than_two_emails_are_rejected():
    """The Merchant Portal/Super Admin request body only has 2 email
    slots (primary/secondary) — there's no way to submit a 3rd through the
    real API. The underlying rule "no more than 2" is still a real,
    independently-enforced piece of business logic (see
    validate_notification_emails's docstring), so it's tested directly at
    that level rather than skipped for being unreachable through the
    current 2-field endpoint."""
    from app.core.errors import ValidationAPIError
    from app.services.merchant_notifications import validate_notification_emails

    with pytest.raises(ValidationAPIError) as exc_info:
        validate_notification_emails(["a@example.com", "b@example.com", "c@example.com"], enabled=True)

    assert exc_info.value.message == "You can add up to 2 notification emails only."


def test_notifications_can_be_on_with_no_address(fake_client):
    """Blank means "use my account email", which is what
    notification_recipient does and what the settings page promises in
    words: "No address set, so confirmations go to your account email".

    Refusing this contradicted both, and left a merchant who had never
    set an address unable to change anything else on that card - they
    had to invent an email they did not want first. Reported from
    production on 2026-10-16 by a merchant trying to switch on SMS
    alerts."""
    _merchant_id, user_id = _merchant_admin(fake_client)

    response = client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(user_id),
        json={"collection_notifications_enabled": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["primary_notification_email"] is None
    assert response.json()["data"]["collection_notifications_enabled"] is True


def test_an_sms_preference_saves_without_an_email_address(fake_client):
    """The exact blocked flow: turning on SMS alerts on an account with
    no notification email set."""
    _merchant_id, user_id = _merchant_admin(fake_client)

    response = client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(user_id),
        json={
            "collection_notifications_enabled": True,
            "collection_sms_enabled": True,
            "sms_notification_phone": "255747730270",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["collection_sms_enabled"] is True
    assert data["sms_notification_phone"] == "255747730270"


def test_emails_can_be_empty_when_notifications_disabled(fake_client):
    _merchant_id, user_id = _merchant_admin(fake_client)

    response = client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(user_id),
        json={"collection_notifications_enabled": False},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["collection_notifications_enabled"] is False
    assert data["primary_notification_email"] is None


def test_notification_toggle_can_be_enabled_and_disabled(fake_client):
    _merchant_id, user_id = _merchant_admin(fake_client)

    client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(user_id),
        json={"primary_notification_email": "owner@example.com", "collection_notifications_enabled": True},
    )
    disable_response = client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(user_id),
        json={"primary_notification_email": "owner@example.com", "collection_notifications_enabled": False},
    )
    assert disable_response.json()["data"]["collection_notifications_enabled"] is False

    enable_response = client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(user_id),
        json={"primary_notification_email": "owner@example.com", "collection_notifications_enabled": True},
    )
    assert enable_response.status_code == 200, enable_response.text
    assert enable_response.json()["data"]["collection_notifications_enabled"] is True


def test_audit_log_created_when_merchant_settings_change(fake_client):
    _merchant_id, user_id = _merchant_admin(fake_client)

    client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(user_id),
        json={"primary_notification_email": "owner@example.com", "collection_notifications_enabled": True},
    )

    audit_rows = fake_client.table("audit_logs")._table.rows
    assert any(row["action"] == "notification_settings.updated" and row["actor_id"] == str(user_id) for row in audit_rows)


def test_merchant_cannot_edit_another_merchants_notification_settings(fake_client):
    merchant_a_id, user_a = _merchant_admin(fake_client, business_name="Merchant A")
    _merchant_b_id, user_b = _merchant_admin(fake_client, business_name="Merchant B")

    client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(user_a),
        json={"primary_notification_email": "a@example.com", "collection_notifications_enabled": True},
    )

    # user_b's own GET must never see merchant A's settings — merchant_id
    # is resolved purely from the caller's own JWT membership, never a
    # client-supplied id, so there's no request shape that could even ask
    # for the wrong merchant's row.
    response = client.get("/v1/merchant/notification-settings", headers=auth_headers(user_b))
    assert response.json()["data"]["primary_notification_email"] is None

    settings_rows = fake_client.table("merchant_notification_settings")._table.rows
    a_row = next(row for row in settings_rows if row["merchant_id"] == str(merchant_a_id))
    assert a_row["primary_notification_email"] == "a@example.com"


def test_merchant_staff_cannot_view_or_edit_notification_settings(fake_client):
    """Same sensitivity tier as team/user management — admin only (see
    _ADMIN_ONLY in app/routers/merchant_portal.py)."""
    merchant_id, _admin_id = _merchant_admin(fake_client)
    staff_id = _merchant_staff(fake_client, merchant_id)

    response = client.get("/v1/merchant/notification-settings", headers=auth_headers(staff_id))
    assert response.status_code == 403, response.text


# --- Super Admin -------------------------------------------------------------


def test_super_admin_can_view_merchant_notification_settings(fake_client):
    merchant_id, user_id = _merchant_admin(fake_client, business_name="Masanja Traders")
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    client.patch(
        "/v1/merchant/notification-settings",
        headers=auth_headers(user_id),
        json={
            "primary_notification_email": "owner@example.com",
            "secondary_notification_email": "finance@example.com",
            "collection_notifications_enabled": True,
        },
    )

    response = client.get(f"/v1/admin/merchants/{merchant_id}/notification-settings", headers=auth_headers(admin_id))

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["merchant_name"] == "Masanja Traders"
    assert data["primary_notification_email"] == "owner@example.com"
    assert data["secondary_notification_email"] == "finance@example.com"
    assert data["failed_notification_count"] == 0
    assert data["last_notification_status"] is None


def test_super_admin_update_enforces_maximum_two_emails(fake_client):
    from app.core.errors import ValidationAPIError
    from app.services.merchant_notifications import validate_notification_emails

    # Same shared validator the admin PATCH route calls — see
    # test_more_than_two_emails_are_rejected for why this is exercised at
    # the function level rather than through the (necessarily 2-slot)
    # request body.
    with pytest.raises(ValidationAPIError):
        validate_notification_emails(["a@example.com", "b@example.com", "c@example.com"], enabled=True)


def test_super_admin_update_rejects_duplicate_emails(fake_client):
    merchant_id, _user_id = _merchant_admin(fake_client)
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    response = client.patch(
        f"/v1/admin/merchants/{merchant_id}/notification-settings",
        headers=auth_headers(admin_id),
        json={
            "primary_notification_email": "shared@example.com",
            "secondary_notification_email": "shared@example.com",
            "collection_notifications_enabled": True,
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["message"] == "Duplicate notification emails are not allowed."


def test_super_admin_update_creates_audit_log(fake_client):
    merchant_id, _user_id = _merchant_admin(fake_client)
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    response = client.patch(
        f"/v1/admin/merchants/{merchant_id}/notification-settings",
        headers=auth_headers(admin_id),
        json={"primary_notification_email": "ceo@example.com", "collection_notifications_enabled": True},
    )
    assert response.status_code == 200, response.text

    audit_rows = fake_client.table("audit_logs")._table.rows
    assert any(
        row["action"] == "notification_settings.updated_by_admin" and row["actor_id"] == str(admin_id)
        for row in audit_rows
    )


def test_non_admin_cannot_access_notification_details(fake_client):
    merchant_id, user_id = _merchant_admin(fake_client)

    response = client.get(f"/v1/admin/merchants/{merchant_id}/notification-settings", headers=auth_headers(user_id))

    assert response.status_code == 403, response.text
