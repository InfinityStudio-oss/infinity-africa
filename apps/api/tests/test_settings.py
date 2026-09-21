"""app/config/settings.py's Settings.cors_origins parsing — accepts both a
JSON array and a plain comma-separated string (Railway's env var UI makes
typing quoted JSON error-prone), and refuses a "*" wildcard outside local
development (CORSMiddleware in app/main.py sets allow_credentials=True, so
a wildcard origin is both browser-rejected and a real credential-leak risk
— see app/config/settings.py's _reject_wildcard_cors_outside_development)."""

import pytest

from app.config.settings import Settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_cors_origins_defaults_to_localhost():
    settings = Settings()
    assert settings.cors_origins == ["http://localhost:3000"]


def test_cors_origins_parses_a_json_array(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["https://infinitypay.me","https://www.infinitypay.me"]')
    settings = Settings()
    assert settings.cors_origins == ["https://infinitypay.me", "https://www.infinitypay.me"]


def test_cors_origins_parses_a_comma_separated_string(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://infinitypay.me, https://www.infinitypay.me")
    settings = Settings()
    assert settings.cors_origins == ["https://infinitypay.me", "https://www.infinitypay.me"]


def test_cors_origins_single_origin_comma_separated(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://infinitypay.me")
    settings = Settings()
    assert settings.cors_origins == ["https://infinitypay.me"]


def test_cors_origins_blank_string_parses_to_empty_list(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "")
    settings = Settings()
    assert settings.cors_origins == []


def test_wildcard_cors_origin_rejected_outside_development(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "*")
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="CORS_ORIGINS must not contain"):
        Settings()


def test_wildcard_cors_origin_allowed_in_development(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "*")
    monkeypatch.setenv("ENVIRONMENT", "development")
    settings = Settings()
    assert settings.cors_origins == ["*"]


# --- Swagger/OpenAPI docs (app.main) -----------------------------------------


def test_docs_disabled_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert Settings().docs_enabled is False


def test_docs_enabled_in_development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert Settings().docs_enabled is True


def test_docs_enabled_outside_production_generally():
    """Anything that isn't literally "production" (staging, a preview
    deploy, ...) still gets docs — only the real production environment is
    locked down."""
    assert Settings(environment="staging").docs_enabled is True


# --- Email sender addresses (app/services/email.py) -------------------------


def test_email_from_defaults_to_the_notification_address():
    """Every transactional email except invoice payment requests uses
    this — staff invites, password resets, receipts, welcome emails,
    inquiry notifications (none of those flows exist yet, but whichever
    gets built next should read this same setting rather than hardcoding
    a sender)."""
    settings = Settings()
    assert settings.email_from == "InfinityPay <notification@infinitypay.me>"


def test_invoice_email_from_defaults_to_email_from_when_unset():
    settings = Settings()
    assert settings.invoice_email_from == settings.email_from


def test_invoice_email_from_uses_invoice_email_from_when_set(monkeypatch):
    monkeypatch.setenv("INVOICE_EMAIL_FROM", "InfinityPay Invoices <invoice@infinitypay.me>")
    settings = Settings()
    assert settings.invoice_email_from == "InfinityPay Invoices <invoice@infinitypay.me>"
    # The general sender is untouched by setting the invoice-specific one.
    assert settings.email_from == "InfinityPay <notification@infinitypay.me>"


def test_app_url_falls_back_to_public_app_url_when_unset(monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://infinitypay.me")
    settings = Settings()
    assert settings.app_url == "https://infinitypay.me"


def test_app_url_uses_its_own_value_when_set(monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://infinitypay.me")
    monkeypatch.setenv("APP_URL", "https://www.infinitypay.me")
    settings = Settings()
    assert settings.app_url == "https://www.infinitypay.me"


def test_email_reply_to_defaults_to_the_info_address():
    settings = Settings()
    assert settings.email_reply_to == "info@infinitypay.me"
