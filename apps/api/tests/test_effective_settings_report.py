"""Read back what the process actually believes.

A variable that is absent, misspelled, or unreadable all produce the same
outcome - the field's default - and two of those three are completely
silent. On 2026-10-22 that cost several rounds of guessing: Selcom
callbacks kept being rejected with "invalid or missing signature" after
SELCOM_CHECKOUT_ACCEPT_UNSIGNED_CALLBACKS had reportedly been set to
true, 177 callbacks went unprocessed after a confirmed deploy, and there
was no way from outside to tell whether the process had ever seen the
variable.

`source` is the field that answers it. `env` means something supplied
this value; `default` means nothing did - which is precisely what a
missing or misspelled variable looks like from the inside.

The hard rule is that no secret appears here, in any form. These tests
assert that by name and by shape, because a diagnostic endpoint that
leaks a credential is worse than no diagnostic at all.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.routers.admin_diagnostics import _REPORTED_SETTINGS
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
    make_super_admin,
)

client = TestClient(app)
URL = "/v1/admin/diagnostics/settings"

SECRET_WORDS = ("secret", "key", "password", "token", "dsn", "url", "private")


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


# --- the question it exists to answer ----------------------------------


def test_it_reports_the_callback_flag(fake_client, admin):
    body = client.get(URL, headers=auth_headers(admin)).json()["data"]["settings"]

    assert "selcom_checkout_accept_unsigned_callbacks" in body


def test_a_field_nothing_supplied_is_marked_default(fake_client, admin, monkeypatch):
    """The case that was invisible: a variable that was never set reads as
    `default`, which is what a missing or misspelled name looks like."""
    monkeypatch.delenv("SELCOM_CHECKOUT_ACCEPT_UNSIGNED_CALLBACKS", raising=False)
    get_settings.cache_clear()

    body = client.get(URL, headers=auth_headers(admin)).json()["data"]["settings"]

    entry = body["selcom_checkout_accept_unsigned_callbacks"]
    assert entry["source"] == "default"
    assert entry["value"] is False


def test_a_field_supplied_by_the_environment_is_marked_env(fake_client, admin, monkeypatch):
    monkeypatch.setenv("SELCOM_CHECKOUT_ACCEPT_UNSIGNED_CALLBACKS", "true")
    get_settings.cache_clear()

    body = client.get(URL, headers=auth_headers(admin)).json()["data"]["settings"]

    entry = body["selcom_checkout_accept_unsigned_callbacks"]
    assert entry["source"] == "env"
    assert entry["value"] is True


def test_numeric_ceilings_are_reported(fake_client, admin):
    """The throughput limits behind slow settlement - worth being able to
    confirm without reading a deploy log."""
    body = client.get(URL, headers=auth_headers(admin)).json()["data"]["settings"]

    for name in ("selcom_outbound_max_per_minute", "selcom_outbound_max_concurrent"):
        assert isinstance(body[name]["value"], int)


# --- it must never leak a secret ---------------------------------------


def test_no_reported_field_is_a_credential():
    """Asserted against the list itself, so adding a secret to it fails
    here rather than in production."""
    for name in _REPORTED_SETTINGS:
        if name == "environment":
            continue
        assert not any(word in name for word in SECRET_WORDS), f"{name} looks like a credential"


def test_every_reported_value_is_a_bool_int_or_short_string(fake_client, admin):
    """A credential would arrive as a long opaque string. Nothing here
    should be one."""
    body = client.get(URL, headers=auth_headers(admin)).json()["data"]["settings"]

    for name, entry in body.items():
        value = entry["value"]
        assert isinstance(value, (bool, int, str)), name
        if isinstance(value, str):
            assert len(value) <= 32, f"{name} returned a suspiciously long string"


def test_the_response_contains_no_known_secret_value(fake_client, admin, monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "super-secret-service-role-value")
    get_settings.cache_clear()

    raw = client.get(URL, headers=auth_headers(admin)).text

    assert "super-secret-service-role-value" not in raw
    assert TEST_JWT_SECRET not in raw


# --- who may read it ---------------------------------------------------


def test_a_merchant_cannot_read_the_settings(fake_client):
    merchant = create_merchant(fake_client)
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), user_id, "MERCHANT_ADMIN")

    assert client.get(URL, headers=auth_headers(user_id)).status_code == 403


def test_an_unauthenticated_caller_cannot_read_the_settings(fake_client):
    assert client.get(URL).status_code in (401, 403)


def test_the_super_admin_sms_flags_are_reported(fake_client, admin, monkeypatch):
    """A flag set but misspelled, or set on the wrong service, reads as
    `default` here rather than `env` - which is the only way to tell
    "configured" from "looks configured" before a merchant happens to
    register.

    Without this, confirming the feature was switched on meant waiting for
    a qualifying event, which on a quiet night is hours away.
    """
    monkeypatch.setenv("SUPER_ADMIN_SMS_ENABLED", "true")
    monkeypatch.delenv("SUPER_ADMIN_SMS_NEW_MERCHANT_ENABLED", raising=False)
    get_settings.cache_clear()

    body = client.get(URL, headers=auth_headers(admin)).json()["data"]["settings"]

    assert body["super_admin_sms_enabled"]["value"] is True
    assert body["super_admin_sms_enabled"]["source"] == "env"
    # Absent, so running on its default - the case this endpoint exists for.
    assert body["super_admin_sms_new_merchant_enabled"]["value"] is False
    assert body["super_admin_sms_new_merchant_enabled"]["source"] == "default"


def test_the_operator_phone_number_is_never_reported(fake_client, admin, monkeypatch):
    """Booleans and numbers only. An operator's phone number is not
    something to render in a diagnostics page, and whether one is
    configured shows up as a skipped row with a reason instead."""
    monkeypatch.setenv("SUPER_ADMIN_SMS_RECIPIENTS", "255700000001")
    get_settings.cache_clear()

    response = client.get(URL, headers=auth_headers(admin))

    assert "super_admin_sms_recipients" not in response.json()["data"]["settings"]
    assert "255700000001" not in response.text
