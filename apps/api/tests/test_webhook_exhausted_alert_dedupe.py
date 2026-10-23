"""An ongoing problem should be reported once, not eighteen times a day.

When outbound delivery gives up, the merchant will never receive that
event and there is no replay - so it is captured to Sentry, where it can
raise an alert. Correct, and it did not scale.

One merchant's endpoint erroring about 0.5% of the time across a thousand
deliveries a day produced roughly eighteen separate "merchant will not
receive this event" alerts, every one describing the same ongoing
condition. That is how a genuinely new failure gets lost - buried among
repetitions of a known one.

The condition is now alerted once per merchant per window. What does
**not** change is everything that makes it recoverable: the row is still
marked failed, the warning is still logged for every event, and the
delivery is still counted. Only the alert is suppressed.

A merchant whose endpoint stays broken still raises a fresh alert every
window, and a *different* merchant failing is never suppressed by the
first one - which is the property that keeps this a noise reduction
rather than a blindfold.
"""

import uuid

import pytest

from app.config import get_settings
from app.services import webhook_delivery
from app.services.security_alerts import should_alert_once


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret-do-not-use")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def captured(monkeypatch):
    """Every Sentry capture the delivery code makes."""
    seen: list[dict] = []
    monkeypatch.setattr(
        webhook_delivery,
        "capture_message",
        lambda message, **kw: seen.append({"message": message, **kw}),
    )
    return seen


def _exhaust(fake_client, merchant_id, *, attempts=5):
    """One delivery that has run out of attempts."""
    event = fake_client.seed(
        "webhook_events",
        {
            "merchant_id": str(merchant_id),
            "event_name": "collection.success",
            "target_url": "https://merchant.example/callback",
            "payload": {"amount": "500.00"},
            "status": "retrying",
            "attempts": attempts - 1,
        },
    )

    def _fail(url, *, content, headers, timeout):
        import httpx

        return httpx.Response(500, request=httpx.Request("POST", url))

    import httpx as _httpx

    original = _httpx.post
    _httpx.post = _fail
    try:
        return webhook_delivery.deliver_event(fake_client, {**event, "attempts": attempts - 1})
    finally:
        _httpx.post = original


# --- the suppression ---------------------------------------------------


def test_the_same_merchant_failing_repeatedly_alerts_once(fake_client, captured):
    merchant_id = uuid.uuid4()

    for _ in range(5):
        _exhaust(fake_client, merchant_id)

    assert len(captured) == 1, f"expected one alert, got {len(captured)}"


def test_a_different_merchant_is_never_suppressed_by_the_first(fake_client, captured):
    """The property that keeps this a noise reduction rather than a
    blindfold: one broken endpoint must not hide another."""
    _exhaust(fake_client, uuid.uuid4())
    _exhaust(fake_client, uuid.uuid4())

    assert len(captured) == 2


def test_the_window_is_configurable_and_expiring_it_allows_another(fake_client, captured, monkeypatch):
    merchant_id = uuid.uuid4()
    _exhaust(fake_client, merchant_id)

    # A window of zero means nothing is ever suppressed.
    monkeypatch.setenv("WEBHOOK_EXHAUSTED_ALERT_WINDOW_SECONDS", "0")
    get_settings.cache_clear()
    _exhaust(fake_client, merchant_id)

    assert len(captured) == 2


# --- what must not be suppressed ---------------------------------------


def test_every_exhausted_delivery_is_still_marked_failed(fake_client, captured):
    """The alert is throttled; the record is not. Suppressing the row
    would lose the event itself, not just the notification."""
    merchant_id = uuid.uuid4()

    for _ in range(4):
        _exhaust(fake_client, merchant_id)

    rows = [
        r for r in fake_client.table("webhook_events")._table.rows if r["status"] == "failed"
    ]
    assert len(rows) == 4


def test_the_alert_still_names_the_merchant(fake_client, captured):
    """Whoever reads it has to know whose endpoint to chase."""
    merchant_id = uuid.uuid4()

    _exhaust(fake_client, merchant_id)

    assert captured[0]["tags"]["merchant_id"] == str(merchant_id)


def test_the_alert_carries_the_last_status_code(fake_client, captured):
    _exhaust(fake_client, uuid.uuid4())

    assert captured[0]["tags"]["last_status"] == "500"


# --- the helper itself -------------------------------------------------


def test_the_deduper_allows_the_first_and_suppresses_the_rest():
    key = f"test:{uuid.uuid4()}"

    assert should_alert_once(key, window_seconds=60) is True
    assert should_alert_once(key, window_seconds=60) is False


def test_the_deduper_keys_are_independent():
    a, b = f"test:{uuid.uuid4()}", f"test:{uuid.uuid4()}"

    assert should_alert_once(a, window_seconds=60) is True
    assert should_alert_once(b, window_seconds=60) is True
