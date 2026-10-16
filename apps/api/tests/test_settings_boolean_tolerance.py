"""A mistyped feature flag must not take the platform down.

From production, 2026-10-16: OASIS_SMS_ENABLED was set to the word
"enabled". Pydantic could not read that as a boolean, Settings() raised,
and because app/main.py builds settings at module import the API failed
to boot at all. Every merchant lost payments for roughly twenty minutes -
no collections, no partner API, every background sweep stopped - because
of one word in a text-message toggle.

The blast radius was the bug, not the typo. A flag that controls whether
we send SMS has no business being able to stop a payment.

These tests hold two lines at once: nothing unparseable may crash the
app, and the things that *should* refuse to boot still do.
"""

import logging

import pytest

from app.config import get_settings
from app.config.settings import Settings


@pytest.fixture(autouse=True)
def _clear():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- the incident ------------------------------------------------------


def test_the_exact_value_that_took_production_down(monkeypatch):
    monkeypatch.setenv("OASIS_SMS_ENABLED", "enabled")

    settings = Settings()

    assert settings.oasis_sms_enabled is True, "and it should mean what the operator meant"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("y", True),
        ("on", True),
        ("enable", True),
        ("enabled", True),
        ("ENABLED", True),
        ("  enabled  ", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("disable", False),
        ("disabled", False),
    ],
)
def test_the_spellings_a_person_actually_types(monkeypatch, value, expected):
    monkeypatch.setenv("OASIS_SMS_ENABLED", value)

    assert Settings().oasis_sms_enabled is expected


def test_genuine_nonsense_falls_back_to_the_default_rather_than_crashing(monkeypatch):
    """The default is the state the platform runs in when the variable is
    not set at all - the configuration every fresh deploy starts from, so
    it is always known-good. Strictly better than refusing to boot."""
    monkeypatch.setenv("OASIS_SMS_ENABLED", "qwerty")

    settings = Settings()

    assert settings.oasis_sms_enabled is False


def test_a_mistyped_flag_is_logged_loudly(monkeypatch, caplog):
    """Falling back quietly would trade an outage for a flag that does
    not do what somebody intended and never says so."""
    monkeypatch.setenv("OASIS_SMS_ENABLED", "qwerty")
    logger = logging.getLogger("infinity.config")
    # infinity.* loggers set propagate=False, so caplog has to attach to
    # this logger directly or the assertion below passes vacuously.
    caplog.set_level(logging.ERROR, logger="infinity.config")
    logger.addHandler(caplog.handler)
    try:
        Settings()
    finally:
        logger.removeHandler(caplog.handler)

    assert "settings_bool_unparsable" in caplog.text
    assert "oasis_sms_enabled" in caplog.text


def test_a_flag_that_defaults_on_falls_back_on(monkeypatch):
    """Falling back to the default means exactly that - not False. A flag
    that ships enabled must not be silently switched off by a typo."""
    monkeypatch.setenv("ENABLE_AUTO_RECONCILIATION", "sure")

    settings = Settings()

    assert settings.enable_auto_reconciliation is Settings.model_fields[
        "enable_auto_reconciliation"
    ].default


def test_every_boolean_flag_survives_a_typo(monkeypatch):
    """Not just the SMS one. Any of these could have been the word that
    took the platform down."""
    boolean_fields = [
        name for name, f in Settings.model_fields.items() if f.annotation is bool
    ]
    assert len(boolean_fields) > 15, "sanity: these should be plentiful"

    for name in boolean_fields:
        monkeypatch.setenv(name.upper(), "enabled-ish")
        Settings()  # must not raise
        monkeypatch.delenv(name.upper())


# --- what must still refuse to boot ------------------------------------


def test_a_wildcard_cors_origin_in_production_still_refuses_to_boot(monkeypatch):
    """The distinction this whole change rests on: a flag that is merely
    wrong should degrade, and a configuration that is dangerous to run
    with should stop the deploy. allow_credentials=True plus a "*" origin
    lets any site call this API with a signed-in merchant's credentials."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ORIGINS", '["*"]')

    with pytest.raises(Exception) as exc:
        Settings()

    assert "CORS_ORIGINS" in str(exc.value)


def test_non_boolean_fields_are_untouched(monkeypatch):
    """The validator runs over every field. It must pass anything that is
    not a boolean straight through, unchanged."""
    monkeypatch.setenv("OASIS_SMS_SENDER_ID", "enabled")
    monkeypatch.setenv("SLOW_QUERY_WARNING_MS", "250")

    settings = Settings()

    assert settings.oasis_sms_sender_id == "enabled", "a string is a string"
    assert settings.slow_query_warning_ms == 250


def test_a_malformed_integer_still_raises(monkeypatch):
    """Only booleans are forgiven. An unparseable number has no sensible
    reading, and quietly substituting one would be worse than failing."""
    monkeypatch.setenv("SLOW_QUERY_WARNING_MS", "soon")

    with pytest.raises(Exception):
        Settings()
