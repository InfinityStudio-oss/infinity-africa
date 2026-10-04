"""The monitoring diagnostics routes, and who may reach them.

These exist so "is Sentry actually live?" can be answered without
deliberately failing a real request on a platform that moves money. That
makes them a pair of authenticated endpoints that emit events on demand,
so the things worth pinning are: only a Super Admin can call them, they
leak nothing about the request, and they cannot themselves become a way
to break the API.
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

ROUTES = ("/v1/admin/diagnostics/sentry-test", "/v1/admin/diagnostics/posthog-test")


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- who may call them ------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES)
def test_an_unauthenticated_caller_is_refused(fake_client, route):
    assert client.post(route).status_code in (401, 403)


@pytest.mark.parametrize("route", ROUTES)
def test_a_merchant_is_refused(fake_client, route):
    """A merchant admin is still not a platform admin. These routes emit
    events into the platform's own monitoring; no merchant has business
    reaching them."""
    merchant = create_merchant(fake_client)
    member_id = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), member_id, "MERCHANT_ADMIN")

    response = client.post(route, headers=auth_headers(member_id))
    assert response.status_code in (401, 403), response.text


@pytest.mark.parametrize("route", ROUTES)
def test_a_super_admin_is_allowed(fake_client, route):
    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)

    response = client.post(route, headers=auth_headers(super_admin_id))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["ok"] is False  # unconfigured in tests
    assert "not configured" in response.json()["data"]["message"]


# --- they say what they did, and nothing else -------------------------------


@pytest.mark.parametrize("route", ROUTES)
def test_the_response_never_contains_a_secret(fake_client, route, monkeypatch):
    """The reply is read by a human in a browser and may be pasted into a
    ticket. It carries a status and a sentence, never configuration."""
    monkeypatch.setenv("SENTRY_DSN", "https://examplekey@o1.ingest.de.sentry.io/2")
    monkeypatch.setenv("POSTHOG_API_KEY", "phc_examplekey")
    get_settings.cache_clear()

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    body = client.post(route, headers=auth_headers(super_admin_id)).text

    for secret in ("examplekey", "sentry.io", "phc_", "ingest"):
        assert secret not in body, f"{secret!r} leaked into {route}"


@pytest.mark.parametrize("route", ROUTES)
def test_it_reports_honestly_when_monitoring_is_not_configured(fake_client, route, monkeypatch):
    """A blank DSN is the default on every deploy that has not opted in.
    Saying so is the whole point — the alternative is an operator
    concluding monitoring works because the call returned 200."""
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setenv("POSTHOG_API_KEY", "")
    get_settings.cache_clear()

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)

    response = client.post(route, headers=auth_headers(super_admin_id))
    assert response.status_code == 200
    assert response.json()["data"] == {
        "ok": False,
        "message": response.json()["data"]["message"],
    } or response.json()["data"]["ok"] is False


# --- they cannot break anything ---------------------------------------------


def test_a_broken_sentry_does_not_fail_the_request(fake_client, monkeypatch):
    """Monitoring being broken is exactly what is being tested for, so it
    must come back as a readable answer rather than a 500."""
    import app.routers.admin_diagnostics as diagnostics

    monkeypatch.setenv("SENTRY_DSN", "https://examplekey@o1.ingest.de.sentry.io/2")
    get_settings.cache_clear()
    monkeypatch.setattr(
        diagnostics,
        "capture_message",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sentry exploded")),
    )

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)

    response = client.post(ROUTES[0], headers=auth_headers(super_admin_id))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["ok"] is False


def test_a_broken_posthog_does_not_fail_the_request(fake_client, monkeypatch):
    import app.routers.admin_diagnostics as diagnostics

    monkeypatch.setenv("POSTHOG_API_KEY", "phc_examplekey")
    get_settings.cache_clear()
    monkeypatch.setattr(
        diagnostics, "track", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("posthog exploded"))
    )

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)

    response = client.post(ROUTES[1], headers=auth_headers(super_admin_id))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["ok"] is False


def test_calling_repeatedly_is_harmless_then_rate_limited(fake_client):
    """Worst case is a few extra events in a dashboard already being
    watched. The limit is there so it cannot become a way to flood the
    monitoring quota."""
    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)

    statuses = [
        client.post(ROUTES[0], headers=auth_headers(super_admin_id)).status_code for _ in range(14)
    ]
    assert statuses[0] == 200
    assert 429 in statuses, "diagnostics route is not rate limited"


def test_the_posthog_diagnostic_sends_no_merchant_and_only_safe_properties(fake_client, monkeypatch):
    """A diagnostic must not create a person profile or carry anything
    identifying."""
    from app.core import analytics

    monkeypatch.setenv("POSTHOG_API_KEY", "phc_examplekey")
    get_settings.cache_clear()

    captured: list[dict] = []

    class _Recording:
        def capture(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(analytics, "_client", _Recording())

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    assert client.post(ROUTES[1], headers=auth_headers(super_admin_id)).status_code == 200

    assert len(captured) == 1
    assert captured[0]["distinct_id"] == "platform"
    assert captured[0]["event"] == "monitoring_diagnostic"
    assert set(captured[0]["properties"]) <= {"environment"}
    # Above all: not the admin who ran it.
    assert str(super_admin_id) not in str(captured[0])
