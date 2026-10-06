"""What is worth waking someone for.

Sentry's default turns every logger.error() and logger.exception() into
its own alert. That is wrong for this codebase, where catching an error
and carrying on is the design rather than an accident — a reconciliation
sweep logging one bad row and continuing, a provider returning 502 on a
call the next tick will redo, an audit write that must never fail the
request it describes. Twenty-odd such sites existed, and each one paged
on something already handled. The signal drowned in a day of real
traffic.

So an alert now comes only from a deliberate capture_exception() or
capture_message(). These tests pin that split, because it is the kind of
thing a future "let's catch more in Sentry" change quietly undoes.
"""

import logging

import pytest

from app.config import get_settings
from app.core.monitoring import capture_exception, capture_message, init_sentry

_FAKE_DSN = "https://examplekey@o1.ingest.de.sentry.io/2"


@pytest.fixture
def alerts(monkeypatch):
    """A live Sentry client whose transport is intercepted, so the test
    sees exactly what would have left the process. Restores the previous
    global client afterwards: Sentry's client is process-wide, and a test
    that leaves one installed changes the behaviour of every test after
    it."""
    sentry_sdk = pytest.importorskip("sentry_sdk")

    previous = sentry_sdk.get_client()
    monkeypatch.setenv("SENTRY_DSN", _FAKE_DSN)
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    get_settings.cache_clear()

    assert init_sentry() is True
    captured: list = []
    sentry_sdk.get_client().transport.capture_envelope = captured.append

    yield captured

    sentry_sdk.get_client().close(timeout=0)
    sentry_sdk.Scope.get_global_scope().set_client(previous)
    get_settings.cache_clear()


def _flush():
    import sentry_sdk

    sentry_sdk.flush(timeout=3)


# --- the noise that must stay out -------------------------------------------


def test_a_logged_error_does_not_alert(alerts):
    """`logger.error` marks something the code already dealt with. On a
    platform that deliberately logs-and-continues, alerting on it means
    alerting on normal operation."""
    logging.getLogger("infinity.test").error("checkout_reconciliation_row_failed collection_id=abc")
    _flush()
    assert alerts == []


def test_a_logged_exception_does_not_alert(alerts):
    """The Selcom-502-during-a-retry case specifically: caught, logged,
    and retried by the next sweep. Nobody needs an email."""
    try:
        raise RuntimeError("Selcom Checkout API returned HTTP 502")
    except RuntimeError:
        logging.getLogger("infinity.test").exception("collection_expiry_recheck_failed")
    _flush()
    assert alerts == []


@pytest.mark.parametrize("level", ["debug", "info", "warning"])
def test_quieter_levels_do_not_alert(alerts, level):
    getattr(logging.getLogger("infinity.test"), level)("routine %s line", level)
    _flush()
    assert alerts == []


# --- the signal that must get through ---------------------------------------


def test_a_deliberate_capture_alerts(alerts):
    """What the unhandled-exception handler and the worker loops call."""
    try:
        raise RuntimeError("a genuinely unhandled 500")
    except RuntimeError as exc:
        capture_exception(exc)
    _flush()
    assert len(alerts) == 1


def test_a_deliberate_message_alerts(alerts):
    """The webhook-exhausted alert — a merchant will never receive that
    event, and there is no replay."""
    capture_message("webhook delivery exhausted", level="error", tags={"merchant_id": "m-1"})
    _flush()
    assert len(alerts) == 1


def test_a_critical_log_still_alerts(alerts):
    """CRITICAL is left as an escape hatch: nothing logs at that level
    today, so it is available to mean "this one really does page"."""
    logging.getLogger("infinity.test").critical("the wheels have come off")
    _flush()
    assert len(alerts) == 1


# --- the two handled paths that are still worth an alert --------------------


def test_a_failed_audit_write_still_alerts(alerts, fake_client, monkeypatch):
    """An audit row is the compliance record of who moved money. The
    write is deliberately non-fatal to the request it describes, which is
    exactly why losing one must not also be silent."""
    from app.services import audit

    monkeypatch.setattr(
        audit, "write_audit_log", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    audit.write_audit_log_best_effort(fake_client, action="collection.credited", resource_type="collection")
    _flush()
    assert len(alerts) == 1


def test_a_failed_security_alert_still_alerts(alerts, fake_client, monkeypatch):
    """If security alert emails are failing, every other alert this
    platform leans on is going unseen too — including the ones a human
    is supposed to act on."""
    from app.services import security_alerts

    # Without a recipient the function returns before it ever tries to
    # send, so the failure path under test would never be reached.
    monkeypatch.setenv("CEO_EMAIL", "ceo@infinitypay.me")
    monkeypatch.setenv("SECURITY_ALERTS_ENABLED", "true")
    get_settings.cache_clear()

    monkeypatch.setattr(
        security_alerts, "send_email", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("resend down"))
    )
    sent = security_alerts.notify_security_event(
        fake_client, event="withdrawal.approved", title="Withdrawal approved"
    )
    assert sent is False, "the failure path under test was not reached"
    _flush()
    assert len(alerts) >= 1
