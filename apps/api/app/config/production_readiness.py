"""Refuses to start a production API that is missing what it needs.

Every one of these settings defaults to an empty string, so a missing
environment variable does not stop the service booting -- it surfaces
later, as a 500 on a real request from a real merchant. That is the
worst place to find out. A deploy that cannot work should fail at the
deploy, where the platform shows it immediately and the previous
release stays live.

Deliberately split in two. BLOCKING is the short list this service
cannot do anything useful without, and each entry is certain: a blank
value is always wrong in production, never a deliberate choice. Anything
conditional -- credentials for a feature that may legitimately be
switched off -- warns instead, because refusing to boot over a feature
nobody enabled would be its own outage.

Pure function, no imports from app.main, so the decision can be tested
without starting an app.
"""

from __future__ import annotations

from app.config.settings import Settings


def production_config_problems(settings: Settings) -> list[str]:
    """Reasons this configuration must not serve production traffic.

    Empty list means safe to start. Returns every problem rather than
    the first, so one restart surfaces the whole list instead of
    revealing them one deploy at a time.
    """
    if settings.environment != "production":
        return []

    problems: list[str] = []

    if not settings.supabase_url:
        problems.append("SUPABASE_URL is not set")
    if not settings.supabase_service_role_key:
        problems.append("SUPABASE_SERVICE_ROLE_KEY is not set")

    # Either verification method is fine; neither is not. app/auth/jwt.py
    # raises on this at request time, which means every authenticated
    # call 500s instead of the deploy failing.
    if not settings.supabase_jwt_secret and not settings.supabase_jwks_url:
        problems.append("Neither SUPABASE_JWT_SECRET nor SUPABASE_JWKS_URL is set")

    # A wildcard origin is NOT checked here: Settings' own model_validator
    # already refuses to construct outside development, so the app cannot
    # start with one at all. Public API docs are not checked either —
    # docs_enabled is a computed property that is false in production by
    # construction, with no environment variable to get wrong.
    origins = settings.cors_origins
    if not origins:
        problems.append("CORS_ORIGINS is empty — the portal cannot reach this API")
    insecure = [o for o in origins if o.startswith("http://") and "localhost" not in o and "127.0.0.1" not in o]
    if insecure:
        problems.append(f"CORS_ORIGINS contains non-HTTPS origins: {', '.join(insecure)}")

    return problems


def production_config_warnings(settings: Settings) -> list[str]:
    """Things that are probably wrong but might be deliberate.

    A feature switched off on purpose must not stop the service, so
    these are logged and never raised.
    """
    if settings.environment != "production":
        return []

    warnings: list[str] = []

    if settings.enable_collections and not settings.selcom_checkout_api_secret:
        warnings.append("Collections are enabled but SELCOM_CHECKOUT_API_SECRET is not set")
    if not settings.resend_api_key:
        warnings.append("RESEND_API_KEY is not set — no email will be sent, including withdrawal approval alerts")
    if not settings.ceo_emails:
        warnings.append("CEO_EMAIL is not set — nobody is told when a withdrawal needs approval")
    if not settings.webhook_delivery_interval_seconds:
        warnings.append("WEBHOOK_DELIVERY_INTERVAL_SECONDS is 0 — merchant webhooks are queued but never sent")

    return warnings
