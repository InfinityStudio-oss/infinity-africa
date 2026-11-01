"""Who may change a merchant's collection notification settings.

GET/PATCH `/v1/merchant/notification-settings` and GET/PATCH
`/v1/admin/merchants/{id}/notification-settings`. See
`app/services/merchant_notifications.py` for the shared validation and
`supabase/migrations/20260901010000_merchant_notification_settings.sql`
for the table. Sending the email itself is covered in
`tests/test_merchant_collection_notification_email.py`.

**The policy these tests encode, and when it changed.** SMS became a
Super Admin control on 2026-10-17, because every message costs money from
a shared provider account. The collection *email* settings followed on
2026-11-01, for a different reason: who is told about a merchant's money,
and at which address, is a support decision. A merchant who switched
their own notifications off and forgot would later report that payments
had stopped arriving.

So a merchant may still **read** their settings — the portal shows a
read-only summary — and may change **nothing**. This file used to assert
the opposite, because that used to be true; it is rewritten rather than
relaxed, and every "merchant can save" case below has become a "merchant
is refused" case.

Refusal is explicit, never silent. A caller that sent these fields and
got a 200 would reasonably believe they had taken effect and would have
no way to find out otherwise.
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

MERCHANT_PATH = "/v1/merchant/notification-settings"


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "false")
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


def _super_admin(fake_client) -> uuid.UUID:
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    return admin_id


def _admin_path(merchant_id: uuid.UUID) -> str:
    return f"/v1/admin/merchants/{merchant_id}/notification-settings"


def _stored(fake_client, merchant_id: uuid.UUID) -> dict | None:
    rows = fake_client.table("merchant_notification_settings")._table.rows
    return next((r for r in rows if str(r["merchant_id"]) == str(merchant_id)), None)


# --- A merchant can still see what is configured for them -------------------


def test_a_merchant_can_read_their_own_settings(fake_client):
    """The portal shows a read-only summary, so the read has to work."""
    _merchant_id, user_id = _merchant_admin(fake_client)

    response = client.get(MERCHANT_PATH, headers=auth_headers(user_id))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["collection_notifications_enabled"] is True
    assert data["primary_notification_email"] is None


def test_a_merchant_cannot_read_another_merchants_settings(fake_client):
    merchant_a, _user_a = _merchant_admin(fake_client)
    _merchant_b, user_b = _merchant_admin(fake_client, business_name="Other Shop")

    response = client.get(
        _admin_path(merchant_a), headers=auth_headers(user_b)
    )

    assert response.status_code == 403


# --- A merchant may change nothing ------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"collection_notifications_enabled": False}, id="switching-off"),
        pytest.param(
            {"primary_notification_email": "new@example.com", "collection_notifications_enabled": True},
            id="changing-the-address",
        ),
        pytest.param(
            {
                "primary_notification_email": "a@example.com",
                "secondary_notification_email": "b@example.com",
                "collection_notifications_enabled": True,
            },
            id="changing-both-addresses",
        ),
        pytest.param({"collection_sms_enabled": True}, id="sms-toggle"),
        pytest.param({"sms_notification_phone": "255700000000"}, id="sms-number"),
    ],
)
def test_a_merchant_is_refused(fake_client, body):
    _merchant_id, user_id = _merchant_admin(fake_client)

    response = client.patch(MERCHANT_PATH, headers=auth_headers(user_id), json=body)

    assert response.status_code == 403
    assert "managed by InfinityPay" in response.json()["error"]["message"]


def test_the_refusal_writes_nothing(fake_client):
    """Refused, not partially applied. A body that mixes a protected
    field with anything else must change nothing at all — the route
    raises before any write."""
    merchant_id, user_id = _merchant_admin(fake_client)
    before = _stored(fake_client, merchant_id)

    client.patch(
        MERCHANT_PATH,
        headers=auth_headers(user_id),
        json={
            "primary_notification_email": "attacker@example.com",
            "secondary_notification_email": "also@example.com",
            "collection_notifications_enabled": False,
            "collection_sms_enabled": True,
            "sms_notification_phone": "255700000000",
        },
    )

    assert _stored(fake_client, merchant_id) == before


def test_a_merchant_cannot_switch_their_own_notifications_off(fake_client):
    """The specific thing this policy exists to stop: a merchant turning
    off their own payment notifications and then reporting that payments
    have stopped arriving."""
    merchant_id, user_id = _merchant_admin(fake_client)
    admin_id = _super_admin(fake_client)
    client.patch(
        _admin_path(merchant_id),
        headers=auth_headers(admin_id),
        json={"primary_notification_email": "owner@example.com", "collection_notifications_enabled": True},
    )

    client.patch(
        MERCHANT_PATH,
        headers=auth_headers(user_id),
        json={"collection_notifications_enabled": False},
    )

    assert _stored(fake_client, merchant_id)["collection_notifications_enabled"] is True


def test_merchant_staff_are_refused_too(fake_client):
    merchant_id, _admin = _merchant_admin(fake_client)
    staff_id = _merchant_staff(fake_client, merchant_id)

    response = client.patch(
        MERCHANT_PATH,
        headers=auth_headers(staff_id),
        json={"collection_notifications_enabled": False},
    )

    assert response.status_code == 403


def test_an_unauthenticated_caller_is_refused(fake_client):
    response = client.patch(MERCHANT_PATH, json={"collection_notifications_enabled": False})

    assert response.status_code in (401, 403)


# --- A Super Admin may change everything ------------------------------------


def test_a_super_admin_can_read_a_merchants_settings(fake_client):
    merchant_id, _user_id = _merchant_admin(fake_client)
    admin_id = _super_admin(fake_client)

    response = client.get(_admin_path(merchant_id), headers=auth_headers(admin_id))

    assert response.status_code == 200
    assert response.json()["data"]["collection_notifications_enabled"] is True


def test_a_super_admin_can_set_the_recipient(fake_client):
    merchant_id, _user_id = _merchant_admin(fake_client)
    admin_id = _super_admin(fake_client)

    response = client.patch(
        _admin_path(merchant_id),
        headers=auth_headers(admin_id),
        json={"primary_notification_email": "owner@example.com", "collection_notifications_enabled": True},
    )

    assert response.status_code == 200
    assert response.json()["data"]["primary_notification_email"] == "owner@example.com"
    assert _stored(fake_client, merchant_id)["primary_notification_email"] == "owner@example.com"


def test_a_super_admin_can_switch_a_merchant_off_and_on(fake_client):
    merchant_id, _user_id = _merchant_admin(fake_client)
    admin_id = _super_admin(fake_client)

    off = client.patch(
        _admin_path(merchant_id),
        headers=auth_headers(admin_id),
        json={"collection_notifications_enabled": False},
    )
    assert off.status_code == 200
    assert _stored(fake_client, merchant_id)["collection_notifications_enabled"] is False

    on = client.patch(
        _admin_path(merchant_id),
        headers=auth_headers(admin_id),
        json={"primary_notification_email": "owner@example.com", "collection_notifications_enabled": True},
    )
    assert on.status_code == 200
    assert _stored(fake_client, merchant_id)["collection_notifications_enabled"] is True


def test_a_super_admin_change_is_audited(fake_client):
    merchant_id, _user_id = _merchant_admin(fake_client)
    admin_id = _super_admin(fake_client)

    client.patch(
        _admin_path(merchant_id),
        headers=auth_headers(admin_id),
        json={"primary_notification_email": "owner@example.com", "collection_notifications_enabled": True},
    )

    # The admin route has always used its own action name, distinct from
    # the merchant one — worth keeping now that the merchant one can no
    # longer be written at all, because it says who the actor was without
    # reading the row.
    rows = [
        r
        for r in fake_client.table("audit_logs")._table.rows
        if r["action"] == "notification_settings.updated_by_admin"
    ]
    assert len(rows) == 1
    assert rows[0]["actor_id"] == str(admin_id)
    # The address itself is personal data; the audit row records the
    # change, not a mailbox to harvest.
    assert "owner@example.com" not in str(rows[0].get("metadata"))


def test_only_a_super_admin_reaches_the_admin_route(fake_client):
    merchant_id, user_id = _merchant_admin(fake_client)

    response = client.patch(
        _admin_path(merchant_id),
        headers=auth_headers(user_id),
        json={"collection_notifications_enabled": False},
    )

    assert response.status_code == 403
    assert _stored(fake_client, merchant_id) is None or (
        _stored(fake_client, merchant_id)["collection_notifications_enabled"] is True
    )


# --- Validation still belongs to the server ---------------------------------


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"primary_notification_email": "not-an-email", "collection_notifications_enabled": True}, id="malformed"),
        pytest.param(
            {
                "primary_notification_email": "same@example.com",
                "secondary_notification_email": "same@example.com",
                "collection_notifications_enabled": True,
            },
            id="duplicate",
        ),
    ],
)
def test_a_super_admin_cannot_store_an_unusable_address(fake_client, body):
    merchant_id, _user_id = _merchant_admin(fake_client)
    admin_id = _super_admin(fake_client)

    response = client.patch(_admin_path(merchant_id), headers=auth_headers(admin_id), json=body)

    assert response.status_code in (400, 409, 422)


def test_notifications_may_be_on_with_no_address(fake_client):
    """The state every merchant starts in. The sending path falls back to
    the account's contact_email — see
    send_merchant_collection_notification_email — so "on with no address"
    is a real, working configuration rather than a silent nothing."""
    merchant_id, _user_id = _merchant_admin(fake_client)
    admin_id = _super_admin(fake_client)

    response = client.patch(
        _admin_path(merchant_id),
        headers=auth_headers(admin_id),
        json={"collection_notifications_enabled": True},
    )

    assert response.status_code == 200
    assert response.json()["data"]["primary_notification_email"] is None


def test_addresses_may_be_blank_when_notifications_are_off(fake_client):
    merchant_id, _user_id = _merchant_admin(fake_client)
    admin_id = _super_admin(fake_client)

    response = client.patch(
        _admin_path(merchant_id),
        headers=auth_headers(admin_id),
        json={"collection_notifications_enabled": False},
    )

    assert response.status_code == 200
    assert response.json()["data"]["collection_notifications_enabled"] is False


# --- The database is the guarantee, not the endpoint ------------------------


def test_the_settings_table_has_no_write_policy():
    """The endpoint above is a polite refusal. This is the one that
    actually holds: merchant_notification_settings carries SELECT
    policies for merchant members and Super Admins and NO
    insert/update/delete policy at all, so a merchant JWT going straight
    to PostgREST writes nothing — with or without the API.

    Read from the migration rather than asserted in prose, so a policy
    added later fails here instead of quietly opening the table.
    """
    import pathlib
    import re

    sql = (
        pathlib.Path(__file__).resolve().parents[3]
        / "supabase"
        / "migrations"
        / "20260901010000_merchant_notification_settings.sql"
    ).read_text(encoding="utf-8")
    # Strip comments, or the explanatory prose below counts as policy.
    sql = re.sub(r"--[^\n]*", "", sql)

    policies = re.findall(
        r"create policy[\s\S]*?on public\.merchant_notification_settings\s+for\s+(\w+)", sql, re.IGNORECASE
    )
    assert policies, "no policies parsed - the parser is stale"
    assert {p.lower() for p in policies} == {"select"}, (
        f"merchant_notification_settings gained a non-SELECT policy: {policies}. "
        "These settings are a Super Admin control; a write policy here would let a "
        "merchant JWT bypass the API entirely."
    )


# --- The Super Admin list screen -------------------------------------------

LIST_PATH = "/v1/admin/notification-settings"


def test_the_list_includes_merchants_nobody_has_configured(fake_client):
    """Driven from merchants, not from the settings table.

    A merchant with no settings row is NOT off — the sending path treats
    a missing row as enabled and falls back to the account address. A
    list built from the settings table would show only the merchants
    somebody had already looked at, hiding exactly the ones worth
    checking.
    """
    create_merchant(fake_client, business_name="Never Touched", contact_email="owner@never.co.tz")
    admin_id = _super_admin(fake_client)

    response = client.get(LIST_PATH, headers=auth_headers(admin_id))

    assert response.status_code == 200
    row = next(r for r in response.json()["data"] if r["merchant_name"] == "Never Touched")
    assert row["configured"] is False
    assert row["collection_notifications_enabled"] is True
    assert row["effective_recipient"] == "owner@never.co.tz"
    assert row["uses_account_email_fallback"] is True


def test_the_list_shows_where_an_email_would_actually_go(fake_client):
    merchant_id, _user_id = _merchant_admin(fake_client, business_name="Configured Co")
    admin_id = _super_admin(fake_client)
    client.patch(
        _admin_path(merchant_id),
        headers=auth_headers(admin_id),
        json={"primary_notification_email": "finance@shop.co.tz", "collection_notifications_enabled": True},
    )

    response = client.get(LIST_PATH, headers=auth_headers(admin_id))

    row = next(r for r in response.json()["data"] if r["merchant_name"] == "Configured Co")
    assert row["effective_recipient"] == "finance@shop.co.tz"
    assert row["uses_account_email_fallback"] is False
    assert row["configured"] is True


def test_a_disabled_merchant_has_no_recipient(fake_client):
    """Null rather than an address, because when it is off there is no
    recipient — showing one would imply a copy still goes somewhere."""
    merchant_id, _user_id = _merchant_admin(fake_client, business_name="Switched Off Ltd")
    admin_id = _super_admin(fake_client)
    client.patch(
        _admin_path(merchant_id),
        headers=auth_headers(admin_id),
        json={"collection_notifications_enabled": False},
    )

    response = client.get(LIST_PATH, headers=auth_headers(admin_id))

    row = next(r for r in response.json()["data"] if r["merchant_name"] == "Switched Off Ltd")
    assert row["collection_notifications_enabled"] is False
    assert row["effective_recipient"] is None


def test_the_list_searches_in_the_database(fake_client):
    """Not in the browser. This list is every merchant on the platform,
    and filtering one fetched page client-side searches only the rows
    that happened to arrive."""
    create_merchant(fake_client, business_name="Findable Traders")
    create_merchant(fake_client, business_name="Something Else")
    admin_id = _super_admin(fake_client)

    response = client.get(f"{LIST_PATH}?search=Findable", headers=auth_headers(admin_id))

    names = [r["merchant_name"] for r in response.json()["data"]]
    assert "Findable Traders" in names
    assert "Something Else" not in names


def test_the_list_is_paged(fake_client):
    for index in range(7):
        create_merchant(fake_client, business_name=f"Shop {index:02d}")
    admin_id = _super_admin(fake_client)

    response = client.get(f"{LIST_PATH}?page=1&page_size=3", headers=auth_headers(admin_id))

    assert response.status_code == 200
    assert len(response.json()["data"]) == 3
    assert response.json()["meta"]["total_pages"] >= 3


def test_a_merchant_cannot_read_the_platform_wide_list(fake_client):
    """It carries every merchant's notification address. Admin only."""
    _merchant_id, user_id = _merchant_admin(fake_client)

    assert client.get(LIST_PATH, headers=auth_headers(user_id)).status_code == 403


def test_an_unauthenticated_caller_cannot_read_the_list(fake_client):
    assert client.get(LIST_PATH).status_code in (401, 403)


def test_the_list_requires_a_second_factor_when_mfa_is_enforced(fake_client, monkeypatch):
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "true")
    get_settings.cache_clear()
    admin_id = _super_admin(fake_client)

    assert client.get(LIST_PATH, headers=auth_headers(admin_id)).status_code == 403
    assert client.get(LIST_PATH, headers=auth_headers(admin_id, aal="aal2")).status_code == 200
