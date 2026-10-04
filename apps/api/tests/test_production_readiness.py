"""Refusing to start a production API that cannot work.

Every setting checked here defaults to an empty string, so a missing
environment variable does not stop the service booting — it surfaces
later as a 500 on a real merchant's request. These pin that a
misconfigured production deploy fails at the deploy instead, where the
platform shows it and the previous release stays live.
"""

import pytest

from app.config import get_settings
from app.config.production_readiness import (
    production_config_problems,
    production_config_warnings,
)


@pytest.fixture
def prod(monkeypatch):
    """A production environment with everything required present.
    Each test removes one thing."""

    def _configure(**overrides):
        base = {
            "ENVIRONMENT": "production",
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role-value",
            "SUPABASE_JWT_SECRET": "jwt-secret-value",
            "SUPABASE_JWKS_URL": "",
            "CORS_ORIGINS": "https://infinitypay.me",
            # Both default to a simulated provider, so a correctly
            # configured production has to say so explicitly.
            "SELCOM_MODE": "live",
            "SELCOM_BUSINESS_MODE": "live",
        }
        base.update(overrides)
        for key, value in base.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        return get_settings()

    yield _configure
    get_settings.cache_clear()


def test_a_fully_configured_production_starts(prod):
    assert production_config_problems(prod()) == []


def test_development_is_never_blocked(prod):
    """Local work must not need production secrets."""
    assert production_config_problems(prod(ENVIRONMENT="development", SUPABASE_URL="")) == []


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        ("SUPABASE_URL", "SUPABASE_URL"),
        ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    ],
)
def test_a_missing_required_secret_blocks_startup(prod, missing, expected):
    problems = production_config_problems(prod(**{missing: ""}))
    assert any(expected in problem for problem in problems)


def test_no_way_to_verify_a_token_blocks_startup(prod):
    """app/auth/jwt.py raises on this at request time, so every
    authenticated call 500s instead of the deploy failing."""
    problems = production_config_problems(prod(SUPABASE_JWT_SECRET="", SUPABASE_JWKS_URL=""))
    assert any("SUPABASE_JWT_SECRET" in problem for problem in problems)


def test_either_verification_method_alone_is_enough(prod):
    assert production_config_problems(
        prod(SUPABASE_JWT_SECRET="", SUPABASE_JWKS_URL="https://project.supabase.co/.well-known/jwks.json")
    ) == []


def test_a_wildcard_cors_origin_cannot_even_be_configured(prod):
    """Not this module's check: Settings' own model_validator refuses to
    construct outside development, so the app never starts with one.
    Pinned here because that guard is what makes the omission safe."""
    with pytest.raises(Exception, match=r'must not contain "\*"'):
        prod(CORS_ORIGINS="*")


def test_an_empty_cors_list_blocks_startup(prod):
    problems = production_config_problems(prod(CORS_ORIGINS=""))
    assert any("CORS_ORIGINS is empty" in problem for problem in problems)


def test_a_plaintext_origin_blocks_startup(prod):
    problems = production_config_problems(prod(CORS_ORIGINS="http://infinitypay.me"))
    assert any("non-HTTPS" in problem for problem in problems)


def test_localhost_origins_are_tolerated(prod):
    """Only http:// on a real host is a mistake; a local origin left in
    the list is untidy, not a vulnerability."""
    problems = production_config_problems(prod(CORS_ORIGINS="https://infinitypay.me,http://localhost:3000"))
    assert not any("non-HTTPS" in problem for problem in problems)


def test_public_api_docs_are_impossible_in_production(prod):
    """docs_enabled is computed from the environment, with no variable to
    get wrong — so /docs, /redoc and /openapi.json are never wired up."""
    assert prod().docs_enabled is False


def test_every_problem_is_reported_at_once(prod):
    """One restart should surface the whole list, not reveal them one
    deploy at a time."""
    problems = production_config_problems(
        prod(SUPABASE_URL="", SUPABASE_SERVICE_ROLE_KEY="", CORS_ORIGINS="")
    )
    assert len(problems) >= 3


# --- warnings: probably wrong, possibly deliberate -------------------------


def test_a_disabled_feature_never_blocks_startup(prod):
    """Refusing to boot over a feature nobody switched on would be its
    own outage."""
    settings = prod(RESEND_API_KEY="", CEO_EMAIL="", WEBHOOK_DELIVERY_INTERVAL_SECONDS="0")
    assert production_config_problems(settings) == []
    assert len(production_config_warnings(settings)) >= 3


def test_silent_webhook_queue_is_warned_about(prod):
    """A zero interval means merchant webhooks queue and never send —
    which has happened here before."""
    warnings = production_config_warnings(prod(WEBHOOK_DELIVERY_INTERVAL_SECONDS="0"))
    assert any("never sent" in warning for warning in warnings)


def test_nobody_watching_withdrawals_is_warned_about(prod):
    warnings = production_config_warnings(prod(CEO_EMAIL=""))
    assert any("CEO_EMAIL" in warning for warning in warnings)


# --- the app itself, not just the function --------------------------------


def test_a_misconfigured_production_app_refuses_to_start(monkeypatch):
    """The check only protects anything if the lifespan actually runs it.

    Entering TestClient as a context manager is what executes lifespan —
    importing app, or calling it without `with`, does not. A startup
    regression here has reached production once before precisely because
    an import-only check passed.
    """
    import importlib

    from fastapi.testclient import TestClient

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("CORS_ORIGINS", "https://infinitypay.me")
    get_settings.cache_clear()

    import app.main

    importlib.reload(app.main)
    try:
        with (
            pytest.raises(RuntimeError, match="production configuration is incomplete"),
            TestClient(app.main.app),
        ):
            pass
    finally:
        get_settings.cache_clear()
        importlib.reload(app.main)


def test_a_correctly_configured_app_starts(monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-value")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "jwt-secret-value")
    monkeypatch.setenv("CORS_ORIGINS", "https://infinitypay.me")
    # Both providers default to simulated, so a production deploy has to
    # name them explicitly — see test_simulated_collections_block_startup.
    monkeypatch.setenv("SELCOM_MODE", "live")
    monkeypatch.setenv("SELCOM_BUSINESS_MODE", "live")
    get_settings.cache_clear()

    import app.main

    importlib.reload(app.main)
    try:
        with TestClient(app.main.app) as client:
            assert client.get("/health").status_code == 200
    finally:
        get_settings.cache_clear()
        importlib.reload(app.main)


def test_simulated_collections_block_startup(prod):
    """The worst failure available to this platform.

    MockSelcomClient resolves a collection to "successful" most of the
    time, and execute_collection() resolves one the moment it is created
    — so a production deploy left on the default would credit real
    merchant wallets for money nobody ever paid. SELCOM_MODE is not
    "live" unless someone says so, which makes forgetting it the easy
    mistake.
    """
    problems = production_config_problems(prod(SELCOM_MODE="mock"))
    assert any("SELCOM_MODE" in p for p in problems)
    assert any("never happened" in p for p in problems)


def test_an_unset_selcom_mode_blocks_startup(prod):
    """Not just the literal string "mock" — anything that is not "live"
    gets the mock client, including a typo and an empty value."""
    for value in ("", "sandbox", "Live", "LIVE", "liv"):
        assert any("SELCOM_MODE" in p for p in production_config_problems(prod(SELCOM_MODE=value))), value


def test_simulated_withdrawals_block_startup(prod):
    """The disbursement client refuses mock on its own, but only when it
    is constructed — the first real withdrawal 502s. This catches it at
    the deploy instead."""
    problems = production_config_problems(prod(SELCOM_BUSINESS_MODE="mock"))
    assert any("SELCOM_BUSINESS_MODE" in p for p in problems)


def test_sandbox_withdrawals_are_allowed(prod):
    """Deliberately not blocked: a sandbox payout provider is a normal
    way to run a pilot where collections are live but payouts are still
    being proven. Only a fake one is refused."""
    assert production_config_problems(prod(SELCOM_BUSINESS_MODE="sandbox")) == []
