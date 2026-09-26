"""Swagger, ReDoc and the raw OpenAPI schema must not exist in production.

test_settings.py already proves `docs_enabled` is False when
ENVIRONMENT=production. That is a property on a settings object — it says
nothing about whether app.main actually acts on it. The wiring is a
conditional evaluated once at import, so a refactor could drop it and every
existing test would still pass.

This rebuilds the app under a production environment and asserts the paths
are genuinely gone. An unauthenticated machine-readable map of every
endpoint on a payments backend is exactly what an attacker would start
from.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

DOC_PATHS = ["/docs", "/redoc", "/openapi.json"]


def _app_for(environment: str, monkeypatch):
    """Re-import app.main so the docs_url/redoc_url/openapi_url arguments —
    evaluated once at construction — are recomputed for this environment."""
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret-do-not-use-in-production")

    from app.config import get_settings

    get_settings.cache_clear()

    import app.main as main_module

    reloaded = importlib.reload(main_module)
    return reloaded.app


@pytest.fixture(autouse=True)
def _restore_module(monkeypatch):
    yield
    # Leave app.main as the rest of the suite expects to find it.
    monkeypatch.undo()
    from app.config import get_settings

    get_settings.cache_clear()
    import app.main as main_module

    importlib.reload(main_module)


@pytest.mark.parametrize("path", DOC_PATHS)
def test_docs_paths_are_absent_in_production(path, monkeypatch):
    app = _app_for("production", monkeypatch)

    response = TestClient(app).get(path)

    assert response.status_code == 404, f"{path} is reachable in production"


@pytest.mark.parametrize("path", DOC_PATHS)
def test_docs_paths_are_available_outside_production(path, monkeypatch):
    """The lockdown must be specific to production — losing the docs on
    staging would push people to read them somewhere less current."""
    app = _app_for("staging", monkeypatch)

    response = TestClient(app).get(path)

    assert response.status_code == 200, f"{path} should be served on staging"


def test_the_openapi_schema_is_not_reachable_by_another_name(monkeypatch):
    """FastAPI only serves the schema at openapi_url, so disabling it
    removes it entirely — asserted here so a future change that reinstates
    it under a different path has to justify itself."""
    app = _app_for("production", monkeypatch)
    client = TestClient(app)

    for path in ("/openapi.json", "/api/openapi.json", "/v1/openapi.json", "/swagger.json"):
        assert client.get(path).status_code == 404, path


def test_health_reveals_nothing_beyond_liveness(monkeypatch):
    """Health is public by necessity. It should say the service is up and
    nothing an attacker could use — no versions, no config, no secrets."""
    app = _app_for("production", monkeypatch)

    body = TestClient(app).get("/health").json()

    assert set(body.keys()) <= {"status", "environment"}
    serialized = str(body).lower()
    for leak in ("key", "secret", "token", "password", "url", "supabase", "selcom", "resend"):
        assert leak not in serialized, f"health response mentions {leak}"
