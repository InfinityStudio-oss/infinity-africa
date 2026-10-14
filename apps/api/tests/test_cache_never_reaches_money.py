"""Which modules are allowed to touch the cache at all.

The rule the cache was added under is that nothing cached may decide
whether money exists, moves or is owed. Enforcing that by reading code
carefully works until the next person adds a cache lookup to a module
whose name does not sound financial.

So it is enforced structurally instead: the cache module may only be
imported by an allowlist, and the money paths are not on it. A new import
fails this test and has to be argued for in a diff rather than noticed in
review - the same shape as tests/test_tenant_isolation_route_guards.py,
which is what keeps the authorization rules honest.

Reading from a cache is what makes a stale value dangerous. A module that
cannot import the cache cannot read from one.
"""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

# Modules permitted to import app.core.cache, each with the reason.
ALLOWED = {
    # Caches the dashboard aggregates. Deliberately does NOT cache
    # available_balance - that is read fresh on every call, because it is
    # the number a merchant looks at to decide whether to withdraw.
    "app/services/merchant_overview.py",
    # Caches the merchant settings read and the masked API key list.
    "app/routers/merchant_portal.py",
    # Invalidation only: a write to merchants or api_keys drops that
    # merchant's cached display. Centralised here so a mutation added
    # later cannot forget to.
    "app/services/crud.py",
    # Invalidation only: every ledger write drops the merchant's display.
    "app/services/ledger.py",
}

# Modules that decide, record or verify money movement. If one of these
# ever appears in the allowlist above, something has gone badly wrong.
MONEY_PATHS = {
    "app/services/disbursements.py",
    "app/services/collections.py",
    "app/services/reconciliation.py",
    "app/services/webhooks.py",
    "app/services/wallet_push.py",
    "app/services/checkout_orders.py",
    "app/auth/dependencies.py",
    "app/routers/webhooks.py",
    "app/routers/admin_withdrawals.py",
    "app/routers/collections.py",
    "app/routers/disbursements.py",
}


def _imports_cache(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.core.cache"):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "app.core" and any(
            alias.name == "cache" for alias in node.names
        ):
            return True
        if isinstance(node, ast.Import) and any(
            alias.name.startswith("app.core.cache") for alias in node.names
        ):
            return True
    return False


def _rel(path: Path) -> str:
    return path.relative_to(APP.parent).as_posix()


def test_only_allowlisted_modules_may_import_the_cache():
    offenders = sorted(
        _rel(path)
        for path in APP.rglob("*.py")
        if _rel(path) not in ALLOWED and _imports_cache(path)
    )

    assert not offenders, (
        f"{offenders} import app.core.cache but are not on the allowlist in this test. "
        "A cached value must never reach a decision about money. If this import is a "
        "display read or an invalidation, add it to ALLOWED with the reason; if it is "
        "on a path that decides whether money exists, moves or is owed, it must read "
        "the database."
    )


@pytest.mark.parametrize("module", sorted(MONEY_PATHS))
def test_a_money_path_cannot_read_a_cache(module):
    """Named individually so a failure says which one.

    These are the paths where a stale number becomes a wrong decision: a
    withdrawal authorised against a balance that has already moved, a
    collection credited twice because an idempotency check was answered
    from a cache, an API key accepted after it was revoked.
    """
    path = APP.parent / module
    if not path.exists():
        pytest.skip(f"{module} does not exist in this tree")

    assert not _imports_cache(path), (
        f"{module} imports app.core.cache. This path decides or records money movement "
        "and must read the database."
    )


def test_the_allowlist_itself_is_honest():
    """Guards against the allowlist being padded with modules that have
    since stopped importing the cache - a stale entry is a licence nobody
    reviewed."""
    stale = sorted(
        module
        for module in ALLOWED
        if (APP.parent / module).exists() and not _imports_cache(APP.parent / module)
    )

    assert not stale, f"{stale} are allowlisted but no longer import the cache; remove them"


def test_the_money_path_list_points_at_real_files():
    """A typo here would silently assert nothing."""
    missing = sorted(m for m in MONEY_PATHS if not (APP.parent / m).exists())

    assert len(missing) < len(MONEY_PATHS), (
        f"none of the money-path modules exist at these paths ({missing}); "
        "this test is asserting nothing"
    )
