"""Every API endpoint advertised on the public developer-docs pages must
actually exist on this backend.

Written after the docs were found advertising two endpoints that 404:
`POST /v1/collections/dynamic-qr` (the real API-key route is
`/v1/collections/qr`; `dynamic-qr` only exists on the merchant-portal
surface as `/v1/merchant/collections/dynamic-qr`) and
`POST /v1/collections/stk-push` (the API-key equivalent is
`/v1/collections/wallet-push`). Nothing caught it, because the docs are
static JSX in apps/web and the routes live here — this test is the seam.

It lives in the backend suite deliberately: the FastAPI app is the source
of truth for what exists, so the assertion belongs where that truth is.
"""

import re
from pathlib import Path

import pytest

from app.main import app

_DOCS_DIR = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "app" / "developers"

# `path="/v1/..."` on an <EndpointRow>, and absolute URLs inside cURL/Python
# code samples. Both are things a developer copies and runs verbatim.
_ENDPOINT_ROW = re.compile(r'path="(/v1/[^"]*)"')
_SAMPLE_URL = re.compile(r'https://api\.infinitypay\.me(/v1/[^\s"\'\\]*)')
_SAMPLE_PATH = re.compile(r'"(/v1/[^"]*)"')


def _app_route_templates() -> set[str]:
    """Every registered path, with its parameter names normalized away so
    `/v1/collections/{collection_id}` matches a doc's `{id}`."""
    return {re.sub(r"\{[^}]*\}", "{}", route.path) for route in app.routes}


def _normalize(path: str) -> str:
    path = path.split("?")[0]
    path = re.sub(r"\{[^}]*\}", "{}", path)
    # Doc samples use concrete example values where a route has a parameter.
    path = re.sub(r"/(TXN-[A-Za-z0-9]+|INVOICE_ID|[0-9a-f]{8}-[0-9a-f-]{27})", "/{}", path)
    return path.rstrip("/") or "/"


def _documented_paths() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for page in _DOCS_DIR.rglob("page.tsx"):
        source = page.read_text(encoding="utf-8")
        rel = str(page.relative_to(_DOCS_DIR.parent))
        for pattern in (_ENDPOINT_ROW, _SAMPLE_URL):
            for match in pattern.finditer(source):
                found.add((rel, match.group(1)))
        # Bare "/v1/..." string literals inside code samples (the Python
        # helper passes a path, not a full URL).
        for match in _SAMPLE_PATH.finditer(source):
            if match.group(1).startswith("/v1/"):
                found.add((rel, match.group(1)))
    return found


def test_the_docs_pages_are_actually_being_scanned():
    """Guard on the scan itself — a glob that silently matched nothing would
    make the assertion below vacuously true."""
    documented = _documented_paths()
    assert len(documented) > 20, f"only found {len(documented)} documented endpoints"


@pytest.mark.parametrize("page,path", sorted(_documented_paths()))
def test_documented_endpoint_exists_on_the_backend(page: str, path: str):
    normalized = _normalize(path)
    routes = _app_route_templates()
    assert normalized in routes, (
        f"{page} documents {path!r}, which is not a route on this backend. "
        f"Closest registered routes: "
        f"{sorted(r for r in routes if r.rsplit('/', 1)[0] == normalized.rsplit('/', 1)[0])}"
    )
