"""Who controls whether a merchant gets an SMS, and what it costs.

Two things that are easy to get subtly wrong and expensive to discover
late: a settings endpoint that switches SMS off for a merchant simply
because the caller did not mention it, and a cost figure presented as a
quote when it is really our own arithmetic.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import sms_provider
from app.services.sms_messages import collection_sms_enabled_for, resolve_recipient
from app.services.sms_provider import SmsResult
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("OASIS_SMS_ENABLED", "true")
    monkeypatch.setenv("OASIS_SMS_SENDER_ID", "INFINITYPAY")
    monkeypatch.setenv("OASIS_SMS_API_KEY", "test-key-not-real")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_balance_calls(monkeypatch):
    monkeypatch.setattr("app.routers.admin_sms.get_balance", lambda: 1000.0)


def _merchant(fake_client, phone="255712000001"):
    merchant = create_merchant(fake_client, contact_phone=phone)
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), user_id, "MERCHANT_ADMIN")
    return merchant, user_id


def _settings_row(fake_client, merchant_id):
    return next(
        r
        for r in fake_client.table("merchant_notification_settings")._table.rows
        if r["merchant_id"] == merchant_id
    )


# --- the merchant's own control ----------------------------------------


def test_a_merchant_can_turn_their_own_sms_alerts_on(fake_client):
    merchant, user_id = _merchant(fake_client)

    response = client.patch(
        "/v1/merchant/notification-settings",
        json={
            "primary_notification_email": "owner@example.com",
            "secondary_notification_email": None,
            "collection_notifications_enabled": True,
            "collection_sms_enabled": True,
            "sms_notification_phone": "0713111222",
        },
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200
    row = _settings_row(fake_client, merchant["id"])
    assert row["collection_sms_enabled"] is True
    # Normalised on the way in, so the worker can trust what it reads.
    assert row["sms_notification_phone"] == "255713111222"


def test_omitting_the_sms_fields_leaves_them_alone(fake_client):
    """The default-off trap. An older client, or any caller that only
    knows about the email fields, must not silently switch a merchant's
    payment alerts off."""
    merchant, user_id = _merchant(fake_client)
    fake_client.seed(
        "merchant_notification_settings",
        {
            "merchant_id": merchant["id"],
            "collection_notifications_enabled": True,
            "collection_sms_enabled": True,
            "sms_notification_phone": "255713111222",
        },
    )

    client.patch(
        "/v1/merchant/notification-settings",
        json={
            "primary_notification_email": "new@example.com",
            "secondary_notification_email": None,
            "collection_notifications_enabled": True,
        },
        headers=auth_headers(user_id),
    )

    row = _settings_row(fake_client, merchant["id"])
    assert row["collection_sms_enabled"] is True
    assert row["sms_notification_phone"] == "255713111222"


def test_a_blank_number_falls_back_to_the_account_number(fake_client):
    merchant, user_id = _merchant(fake_client, phone="0714999888")

    response = client.patch(
        "/v1/merchant/notification-settings",
        json={
            "primary_notification_email": "owner@example.com",
            "secondary_notification_email": None,
            "collection_notifications_enabled": True,
            "collection_sms_enabled": True,
            "sms_notification_phone": "",
        },
        headers=auth_headers(user_id),
    )
    assert response.status_code == 200

    phone, reason = resolve_recipient(fake_client, uuid.UUID(merchant["id"]))
    assert reason is None
    assert phone == "255714999888"


def test_an_unusable_number_is_refused_at_the_edge(fake_client):
    """Better here, with a message the merchant can act on, than as a
    skipped row they never see."""
    _merchant_row, user_id = _merchant(fake_client)

    response = client.patch(
        "/v1/merchant/notification-settings",
        json={
            "primary_notification_email": "owner@example.com",
            "secondary_notification_email": None,
            "collection_notifications_enabled": True,
            "collection_sms_enabled": True,
            "sms_notification_phone": "12345",
        },
        headers=auth_headers(user_id),
    )

    assert response.status_code in (400, 422)


def test_a_number_change_is_audit_logged(fake_client):
    """It redirects where a merchant's payment alerts go, so it is
    attributable."""
    merchant, user_id = _merchant(fake_client)

    client.patch(
        "/v1/merchant/notification-settings",
        json={
            "primary_notification_email": "owner@example.com",
            "secondary_notification_email": None,
            "collection_notifications_enabled": True,
            "collection_sms_enabled": True,
            "sms_notification_phone": "0713111222",
        },
        headers=auth_headers(user_id),
    )

    entries = [
        r
        for r in fake_client.table("audit_logs")._table.rows
        if r["action"] == "notification_settings.updated"
    ]
    assert len(entries) == 1
    assert entries[0]["merchant_id"] == merchant["id"]
    row = _settings_row(fake_client, merchant["id"])
    assert row["sms_phone_updated_by"] == str(user_id)


# --- Super Admin turning it on merchant by merchant --------------------


def test_a_super_admin_can_enable_sms_for_one_merchant(fake_client):
    """How the rollout in docs/SMS_NOTIFICATIONS.md actually happens."""
    merchant, _user_id = _merchant(fake_client)
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    response = client.patch(
        f"/v1/admin/merchants/{merchant['id']}/notification-settings",
        json={
            "primary_notification_email": "owner@example.com",
            "secondary_notification_email": None,
            "collection_notifications_enabled": True,
            "collection_sms_enabled": True,
            "sms_notification_phone": "0713111222",
        },
        headers=auth_headers(admin_id),
    )

    assert response.status_code == 200
    assert collection_sms_enabled_for(fake_client, uuid.UUID(merchant["id"])) is True


def test_a_merchant_cannot_change_another_merchants_settings(fake_client):
    victim, _victim_user = _merchant(fake_client, phone="255712000777")
    _other, attacker_user = _merchant(fake_client, phone="255712000888")

    response = client.patch(
        f"/v1/admin/merchants/{victim['id']}/notification-settings",
        json={
            "primary_notification_email": "owner@example.com",
            "secondary_notification_email": None,
            "collection_notifications_enabled": True,
            "collection_sms_enabled": True,
        },
        headers=auth_headers(attacker_user),
    )

    assert response.status_code in (401, 403)


# --- cost, and the difference between an estimate and a quote ----------


def test_the_dry_run_returns_a_provider_confirmed_quote(fake_client, monkeypatch):
    merchant, _user_id = _merchant(fake_client)
    fake_client.seed(
        "merchant_notification_settings",
        {"merchant_id": merchant["id"], "announcement_sms_enabled": True},
    )
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    calls: list[dict] = []

    def _send(*, to, sender, message, idempotency_key, dry_run=False):
        calls.append({"dry_run": dry_run, "key": idempotency_key})
        return SmsResult(
            outcome="dry_run", segments=1, credits_required=1.0, enough_credits=True
        )

    monkeypatch.setattr("app.routers.admin_sms.send_sms", _send)

    body = client.post(
        "/v1/admin/sms/dry-run",
        json={"body": "Habari njema"},
        headers=auth_headers(admin_id),
    ).json()["data"]

    assert calls[0]["dry_run"] is True, "a cost check must never actually send"
    assert body["confirmed_by_provider"] is True
    assert body["credits_per_message"] == 1.0
    assert body["credits_total"] == 1.0
    assert body["enough_credits"] is True


def test_the_dry_run_reports_when_credits_are_short(fake_client, monkeypatch):
    merchant, _user_id = _merchant(fake_client)
    fake_client.seed(
        "merchant_notification_settings",
        {"merchant_id": merchant["id"], "announcement_sms_enabled": True},
    )
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    monkeypatch.setattr(
        "app.routers.admin_sms.send_sms",
        lambda **kwargs: SmsResult(
            outcome="dry_run", segments=2, credits_required=2.0, enough_credits=False
        ),
    )

    body = client.post(
        "/v1/admin/sms/dry-run", json={"body": "x"}, headers=auth_headers(admin_id)
    ).json()["data"]

    assert body["enough_credits"] is False


def test_a_dry_run_needs_nobody_to_send_to_before_it_prices_anything(fake_client):
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    response = client.post(
        "/v1/admin/sms/dry-run", json={"body": "x"}, headers=auth_headers(admin_id)
    )

    assert response.status_code in (400, 422)


def test_a_non_admin_cannot_spend_provider_calls_on_a_dry_run(fake_client):
    _merchant_row, user_id = _merchant(fake_client)

    response = client.post(
        "/v1/admin/sms/dry-run", json={"body": "x"}, headers=auth_headers(user_id)
    )

    assert response.status_code in (401, 403)


def test_the_estimate_is_labelled_as_one(fake_client):
    """The preview figure is our arithmetic over the rendered text. Only
    the provider's dry run confirms a price, and the two must never be
    presented as the same thing."""
    merchant, _user_id = _merchant(fake_client)
    fake_client.seed(
        "merchant_notification_settings",
        {"merchant_id": merchant["id"], "announcement_sms_enabled": True},
    )
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    body = client.post(
        "/v1/admin/sms/preview", json={"body": "Habari"}, headers=auth_headers(admin_id)
    ).json()["data"]

    assert body["estimate_only"] is True
    assert "estimated_credits" in body


def test_a_dry_run_is_sent_with_the_dry_run_flag_not_a_real_send(fake_client, monkeypatch):
    """Belt and braces on the adapter itself: a dry run must not carry an
    idempotency key header, because the provider documents dry runs as
    never consuming one and we do not want to find out otherwise."""
    captured: dict = {}

    class _Response:
        status_code = 200
        headers: dict = {}

        @staticmethod
        def json():
            return {"segments": 1, "credits_required": 1, "enough_credits": True}

    def _post(url, json, headers, timeout):
        captured.update({"json": json, "headers": headers})
        return _Response()

    monkeypatch.setattr(sms_provider.httpx, "post", _post)

    sms_provider.send_sms(
        to="255712000001",
        sender="INFINITYPAY",
        message="Habari",
        idempotency_key="ipay-c-should-not-be-used",
        dry_run=True,
    )

    assert captured["json"]["dry_run"] is True
    assert "Idempotency-Key" not in captured["headers"]
