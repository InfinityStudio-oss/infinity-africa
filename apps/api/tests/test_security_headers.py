"""app/middleware/security_headers.py — MVP security-hardening pass. Every
response from this API carries a standard set of defensive headers; see
that module's own docstring for why Cross-Origin-Resource-Policy and
Cross-Origin-Opener-Policy are deliberately NOT among them (this API is
consumed cross-origin, by design, from apps/web).

Swagger/OpenAPI docs being reachable at all is itself environment-gated —
see test_settings.py's docs_enabled tests for that; this file only confirms
the headers on an ordinary response, and that the CSP is skipped on the
docs paths themselves (which need their own inline scripts/styles).
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_security_headers_present_on_an_ordinary_response():
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "max-age=63072000" in response.headers["strict-transport-security"]
    assert "camera=()" in response.headers["permissions-policy"]


def test_content_security_policy_present_on_an_ordinary_response():
    response = client.get("/health")
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_no_cross_origin_resource_policy_on_the_api():
    """Deliberately absent — see this module's own docstring and
    app/middleware/security_headers.py's: CORP: same-origin would block
    apps/web's own legitimate cross-origin fetch() calls to this API even
    though CORS explicitly permits them."""
    response = client.get("/health")
    assert "cross-origin-resource-policy" not in response.headers


def test_content_security_policy_skipped_on_docs_path():
    """The strict `default-src 'none'` CSP would break Swagger UI's own
    inline scripts/styles and CDN assets — skipped specifically on
    /docs, /redoc, /openapi.json rather than weakened for every route.
    (Docs are enabled here because tests don't run with ENVIRONMENT=
    production — see test_settings.py's docs_enabled tests for the
    production-disabled case.)"""
    response = client.get("/docs")
    assert response.status_code == 200
    assert "content-security-policy" not in response.headers
    # The other headers still apply everywhere, docs included.
    assert response.headers["x-content-type-options"] == "nosniff"


def test_no_response_may_be_stored_by_a_shared_cache():
    """Every response says Cache-Control: no-store.

    Until 2026-10-14 nothing did. A cache with no explicit policy falls
    back to heuristics, and the only thing keeping merchant data out of
    intermediaries was the convention that a response to an
    Authorization-bearing request is not stored - an accident, not a
    decision.

    This matters because putting a CDN in front of this API is under
    consideration. One over-broad cache rule against a silent origin
    could store one merchant's wallet response and hand it to another;
    that is not a stale page, it is one business reading another's money.
    """
    response = client.get("/health")

    assert response.headers["Cache-Control"] == "no-store"


def test_an_unauthenticated_read_is_also_no_store():
    """The public endpoints are the ones a CDN is most likely to be
    pointed at, and they include payment status polling - which is a
    financial decision path and must always come from the database."""
    response = client.get("/health/db-latency")

    assert response.headers["Cache-Control"] == "no-store"
