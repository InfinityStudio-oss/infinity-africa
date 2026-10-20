"""A security control must not be switchable off by accident.

REQUIRE_SUPER_ADMIN_MFA gates the second factor on every /v1/admin route,
including withdrawal approval. It defaults to False on purpose: enabling it
before any admin has enrolled would stop payouts, so a fresh deploy has to
start permissive and the operator turns it on deliberately.

That default made two silent routes to "no second factor":

1. **An unreadable value.** The tolerant boolean parsing added after the
   2026-10-16 outage falls back to the field's own default so a mistyped
   feature flag cannot stop payments. Correct for a feature flag, wrong
   here: `REQUIRE_SUPER_ADMIN_MFA=ture` resolved to False and logged a
   single ERROR line.

2. **The variable going missing in production.** Absent reads exactly like
   a deliberate False, so a variable dropped during unrelated
   configuration work would disable MFA with no signal at all.

Both now fail closed. An explicit value is still honoured in every
environment - only garbage and absence changed meaning.

Failing closed is affordable because MFA enrolment and verification happen
in the browser against Supabase directly, not through this API: an admin
caught by this can enrol and get back in. It delays withdrawal approval; it
does not lock anyone out.

These tests construct Settings directly rather than going through
get_settings(), so nothing here touches the cached application settings.
"""

import logging
from contextlib import contextmanager

import pytest

from app.config.settings import _SECURITY_CRITICAL_BOOLEANS, Settings

# The logger these messages go to. Not "app.config.settings" - every logger
# in this app is named "infinity.X".
_LOGGER_NAME = "infinity.config"


@contextmanager
def capture_logs(level: int):
    """Capture records from `infinity.config` regardless of propagation.

    Plain `caplog` is not usable here, and this is not a style preference.
    app/main.py sets `propagate = False` on the "infinity" logger, so its
    records never reach the root handler that caplog installs. Whether that
    has happened depends on whether anything has imported app.main yet -
    which depends on what else is in the test session.

    The first version of these three tests used caplog and passed when run
    alone, because this file imports only app.config.settings so
    propagation was still on. In the full suite, where something else
    imports app.main first, they failed. Passing in isolation and failing
    together is the signature of a test asserting on a coincidence, and the
    direction that would have mattered is the other one: they could just as
    easily have passed everywhere while capturing nothing at all.

    Attaching a handler to the logger itself sidesteps propagation
    entirely, so the result does not depend on import order.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collect(level=level)
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(level)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

BASE = {
    "supabase_url": "https://example.supabase.co",
    "supabase_service_role_key": "test-key-not-a-real-credential",
    "supabase_jwt_secret": "test-secret-do-not-use",
    "cors_origins": "https://portal.example.com",
}


def build(**overrides) -> Settings:
    return Settings(**{**BASE, **overrides})


# --- the registry itself -----------------------------------------------


def test_mfa_is_registered_as_security_critical():
    """If this entry is ever removed, both protections below silently stop
    applying - so the registry is asserted, not assumed."""
    assert _SECURITY_CRITICAL_BOOLEANS.get("require_super_admin_mfa") is True


def test_every_registered_field_exists_and_is_a_bool():
    for name in _SECURITY_CRITICAL_BOOLEANS:
        field = Settings.model_fields.get(name)
        assert field is not None, f"{name} is registered but is not a Settings field"
        assert field.annotation is bool, f"{name} is registered but is not a bool"


# --- 1. an unreadable value fails closed -------------------------------


@pytest.mark.parametrize("garbage", ["ture", "yess", "maybe", "2", "on!", "disabledd"])
def test_an_unreadable_mfa_value_fails_closed(garbage):
    """Before this, every one of these resolved to False."""
    settings = build(environment="development", require_super_admin_mfa=garbage)

    assert settings.require_super_admin_mfa is True


def test_an_unreadable_mfa_value_is_logged_at_critical():
    """ERROR was not loud enough: the original fallback logged one ERROR
    line and nobody was watching for it."""
    with capture_logs(logging.CRITICAL) as records:
        build(environment="development", require_super_admin_mfa="ture")

    assert records, "nothing was captured at all - the capture itself is broken"
    assert any(
        "settings_security_bool_unparsable" in r.getMessage()
        and r.levelno == logging.CRITICAL
        for r in records
    )


def test_an_empty_mfa_value_is_not_accepted_as_an_opt_out():
    """An empty string is a deliberate false for a feature flag, but for a
    security control it is indistinguishable from the variable being
    blanked by accident."""
    settings = build(environment="production", require_super_admin_mfa="")

    assert settings.require_super_admin_mfa is True


@pytest.mark.parametrize("garbage", ["ture", "nope"])
def test_an_unreadable_ordinary_flag_still_falls_back_to_its_default(garbage):
    """The outage fix must survive: a mistyped *feature* flag still degrades
    to the field default rather than failing closed or raising."""
    settings = build(environment="development", oasis_sms_enabled=garbage)

    assert settings.oasis_sms_enabled is Settings.model_fields["oasis_sms_enabled"].default


# --- 2. absence in production fails closed -----------------------------


def test_absent_in_production_defaults_to_enforced():
    settings = build(environment="production")

    assert settings.require_super_admin_mfa is True


def test_absent_outside_production_keeps_the_permissive_default():
    """Explicit development and test behaviour is preserved - a fresh local
    checkout must not need MFA to use the admin surface."""
    for environment in ("development", "test", "staging"):
        settings = build(environment=environment)

        assert settings.require_super_admin_mfa is False, environment


def test_absence_in_production_is_logged_at_critical():
    with capture_logs(logging.CRITICAL) as records:
        build(environment="production")

    assert records, "nothing was captured at all - the capture itself is broken"
    assert any(
        "settings_security_control_defaulted_closed" in r.getMessage() for r in records
    )


# --- explicit values are still obeyed ----------------------------------


def test_an_explicit_false_in_production_is_honoured():
    """The operator keeps the final say. This is the documented way to defer
    the change, and the whole rollback - it must not be overridden."""
    settings = build(environment="production", require_super_admin_mfa=False)

    assert settings.require_super_admin_mfa is False


def test_an_explicit_false_in_production_is_logged_as_a_relaxation():
    """Honoured, but never silent."""
    with capture_logs(logging.WARNING) as records:
        build(environment="production", require_super_admin_mfa=False)

    assert records, "nothing was captured at all - the capture itself is broken"
    assert any(
        "settings_security_control_explicitly_relaxed" in r.getMessage() for r in records
    )


@pytest.mark.parametrize("word", ["false", "0", "no", "off", "disabled", "n"])
def test_explicit_false_spellings_are_all_honoured_in_production(word):
    settings = build(environment="production", require_super_admin_mfa=word)

    assert settings.require_super_admin_mfa is False


@pytest.mark.parametrize("word", ["true", "1", "yes", "on", "enabled", "y"])
def test_explicit_true_spellings_all_enforce(word):
    settings = build(environment="production", require_super_admin_mfa=word)

    assert settings.require_super_admin_mfa is True


# --- it must not be able to stop the API booting -----------------------


@pytest.mark.parametrize(
    "value", ["ture", "", "maybe", None, 0, 1, True, False, "true", "false"]
)
def test_no_mfa_value_can_prevent_settings_from_constructing(value):
    """The 2026-10-16 outage was a settings error at module import taking
    the whole API down. A security control that can do that is a worse
    bargain than the thing it protects against, so every input - valid,
    invalid or absurd - must still produce a usable Settings object."""
    settings = build(environment="production", require_super_admin_mfa=value)

    assert isinstance(settings.require_super_admin_mfa, bool)
