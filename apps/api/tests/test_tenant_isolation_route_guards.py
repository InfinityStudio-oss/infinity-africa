"""Every route must be deliberately classified for tenant isolation.

This is a structural guard, not a behavioural test. It enumerates the live
route table and fails when a route's protection does not match its path
family — so a new endpoint cannot ship without someone having decided how
it is scoped.

Why structural: the cross-merchant behaviour is already covered across
~15 test files (merchant A cannot read merchant B's invoice, ledger,
payment link, and so on). What those cannot catch is a *new* route added
next month with no guard at all — nobody writes the negative test for an
endpoint they forgot to protect. This file catches exactly that.

The four rules mirror how the codebase actually scopes things:

- ``/v1/admin/*``            platform surface -> require_super_admin
- ``/v1/merchant/*``         own-merchant surface -> require_own_merchant_role,
                             which resolves merchant_id from the caller's
                             membership and accepts none from the request
- ``/v1/merchants/{id}/*``   merchant in the path -> require_role or
                             get_merchant_actor, both of which check the
                             path id against the caller
- flat routes                merchant known only after the fact ->
                             get_authenticated_caller plus an explicit
                             authorize_merchant_action once it is known

Anything public is listed by hand below, so adding a public route is a
deliberate edit to this file rather than an omission.
"""

import inspect

import pytest
from fastapi.routing import APIRoute

from app.main import app

# Routes intentionally reachable with no authentication. Each one is public
# because a customer, a payment provider, or a prospective merchant has to
# reach it before any session exists.
PUBLIC_ROUTES = {
    ("GET", "/health"),
    # Customer-facing payment pages and their status polling.
    ("GET", "/public/pay-by-link/{slug}"),
    ("POST", "/public/pay-by-link/{slug}/checkout"),
    ("GET", "/public/payment-links/{public_slug}"),
    ("POST", "/public/payment-links/{public_slug}/collect"),
    ("POST", "/public/payment-links/{public_slug}/pay"),
    ("POST", "/public/payment-links/{public_slug}/pay/checkout"),
    ("POST", "/public/payment-links/{public_slug}/pay/wallet-push"),
    ("GET", "/public/payment-links/{public_slug}/collections/{collection_id}/status"),
    ("GET", "/public/payment-links/{public_slug}/collections/{collection_id}/receipt"),
    # Provider callbacks — authenticated by signature, not by session.
    ("GET", "/v1/webhooks/selcom"),
    ("POST", "/v1/webhooks/selcom"),
    ("GET", "/v1/webhooks/selcom/checkout"),
    ("POST", "/v1/webhooks/selcom/checkout"),
    # Pre-session flows.
    ("POST", "/v1/auth/forgot-password"),
    ("POST", "/v1/onboarding/signup"),
    ("POST", "/v1/public/disputes/report"),
    ("POST", "/v1/public/inquiries"),
}

# Authenticated routes that legitimately have no merchant scope, because
# they act on the caller themselves and resolve any merchant from the
# caller's own user_id — never from the request.
SELF_SCOPED_ROUTES = {
    ("POST", "/v1/merchant/users/me/accept-invite"),
    ("POST", "/v1/onboarding/merchant-account"),
    ("GET", "/v1/onboarding/status"),
}


def _guards(route: APIRoute) -> set[str]:
    names: set[str] = set()

    def walk(dep):
        for sub in dep.dependencies:
            call = sub.call
            names.add(getattr(call, "__qualname__", getattr(call, "__name__", str(call))))
            walk(sub)

    walk(route.dependant)
    return names


def _has(route: APIRoute, *needles: str) -> bool:
    return any(needle in name for needle in needles for name in _guards(route))


def _routes() -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute)]


def _cases():
    out = []
    for route in _routes():
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            out.append(pytest.param(method, route.path, route, id=f"{method} {route.path}"))
    return out


CASES = _cases()


def test_the_route_table_is_not_empty():
    """Guards against every test below vacuously passing if route
    collection ever breaks."""
    assert len(CASES) > 150


@pytest.mark.parametrize("method,path,route", CASES)
def test_every_route_is_deliberately_classified(method, path, route):
    """A new route must land in one of the known families. If this fails
    for something you just added, decide how it is scoped and either give
    it a guard or list it above — do not widen the rules to make it pass."""
    if (method, path) in PUBLIC_ROUTES or (method, path) in SELF_SCOPED_ROUTES:
        return

    assert _has(
        route,
        "require_super_admin",
        "require_own_merchant_role",
        # get_own_merchant on its own is a real scope: it resolves the
        # merchant from the caller's membership and takes none from the
        # request. It just adds no role restriction on top.
        "get_own_merchant",
        "require_role",
        "get_merchant_actor",
        "get_authenticated_caller",
        "verify_api_key",
    ), (
        f"{method} {path} has no tenant guard. Add one, or add it to "
        f"PUBLIC_ROUTES/SELF_SCOPED_ROUTES with a reason."
    )


@pytest.mark.parametrize("method,path,route", CASES)
def test_admin_routes_require_a_platform_admin(method, path, route):
    if not path.startswith("/v1/admin"):
        return
    assert _has(route, "require_super_admin"), f"{method} {path} is on /v1/admin without require_super_admin"


@pytest.mark.parametrize("method,path,route", CASES)
def test_own_merchant_routes_never_take_the_tenant_from_the_request(method, path, route):
    """/v1/merchant/* resolves the merchant from the caller's membership.
    A merchant_id path parameter here would mean the tenant came from the
    request, which is the IDOR this whole surface exists to avoid."""
    if not path.startswith("/v1/merchant/") or (method, path) in SELF_SCOPED_ROUTES:
        return
    assert _has(route, "require_own_merchant_role", "get_own_merchant"), (
        f"{method} {path} is on /v1/merchant/* without require_own_merchant_role"
    )
    assert "{merchant_id}" not in path, (
        f"{method} {path} takes merchant_id from the path on a surface that must "
        f"resolve it from the caller's own membership"
    )


@pytest.mark.parametrize("method,path,route", CASES)
def test_path_scoped_merchant_routes_check_the_path_id(method, path, route):
    if "/v1/merchants/{merchant_id}" not in path:
        return
    assert _has(route, "require_role", "get_merchant_actor", "require_super_admin"), (
        f"{method} {path} takes merchant_id in the path without a guard that checks it"
    )


@pytest.mark.parametrize("method,path,route", CASES)
def test_flat_routes_authorize_the_merchant_once_it_is_known(method, path, route):
    """get_authenticated_caller only says *who* is calling — the merchant
    is not known until the body or a fetched row supplies it, so the
    handler must call authorize_merchant_action itself. Several handlers
    delegate to a shared helper, so one level of delegation is followed."""
    if not _has(route, "get_authenticated_caller"):
        return

    try:
        source = inspect.getsource(route.endpoint)
    except OSError:  # pragma: no cover - source always available here
        pytest.skip("source unavailable")

    if "authorize_merchant_action" in source:
        return

    module = inspect.getmodule(route.endpoint)
    for helper_name in ("_create_push_collection", "_create_disbursement", "_create_qr_collection"):
        helper = getattr(module, helper_name, None)
        if helper and helper_name in source and "authorize_merchant_action" in inspect.getsource(helper):
            return

    pytest.fail(
        f"{method} {path} uses get_authenticated_caller but never reaches "
        f"authorize_merchant_action — the merchant from the request body is unchecked"
    )
