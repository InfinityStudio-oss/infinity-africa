"""Row Level Security must be switched on for every table we create.

Nothing enforced this. The audit on 2026-10-11 found all 42 tables
correctly covered — by reading the migrations by hand, which is not a
control. The next migration to add a table and forget
`enable row level security` would leave it readable by anyone holding the
anon key, and the whole suite would stay green.

**Why RLS matters here even though the API uses the service role.**
The service role bypasses RLS, so these policies are not what protects a
request through apps/api — `get_own_merchant` and
`authorize_merchant_action` do that (see
tests/test_tenant_isolation_route_guards.py). RLS is the second line: the
anon key ships in the browser bundle and in the Android app, so anyone who
has used InfinityPay holds a credential that can talk to PostgREST
directly. A table with RLS off is a table they can read.

Most of our tables deliberately have **no policies at all**, which is the
stronger position rather than an omission: RLS on with no policy denies
every anon and authenticated request outright.

Scans supabase/migrations/ rather than a live database, so it runs in CI
with no credentials and describes what a fresh project would get.
"""

import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "supabase" / "migrations"

# `create table if not exists public.foo (` / `create table foo (`
_CREATE = re.compile(
    r"^\s*create\s+table\s+(?:if\s+not\s+exists\s+)?(?:(?P<schema>[a-z_]+)\.)?(?P<name>[a-z_][a-z0-9_]*)",
    re.IGNORECASE | re.MULTILINE,
)
_ENABLE_RLS = re.compile(
    r"^\s*alter\s+table\s+(?:only\s+)?(?:(?P<schema>[a-z_]+)\.)?(?P<name>[a-z_][a-z0-9_]*)\s+"
    r"enable\s+row\s+level\s+security",
    re.IGNORECASE | re.MULTILINE,
)
_DROP = re.compile(
    r"^\s*drop\s+table\s+(?:if\s+exists\s+)?(?:(?P<schema>[a-z_]+)\.)?(?P<name>[a-z_][a-z0-9_]*)",
    re.IGNORECASE | re.MULTILINE,
)


def _strip_sql_comments(sql: str) -> str:
    """Line comments only. An early payment_links migration sketched a
    `create policy "anyone can view an active payment link"` in a comment
    that was never applied, and a scanner that reads commented SQL as real
    SQL would draw exactly the wrong conclusion from it."""
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _migration_sql() -> str:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return "\n".join(_strip_sql_comments(path.read_text(encoding="utf-8")) for path in files)


def _tables_and_rls() -> tuple[set[str], set[str]]:
    sql = _migration_sql()

    def names(pattern) -> set[str]:
        return {
            match.group("name").lower()
            for match in pattern.finditer(sql)
            # Only our own schema. `storage.buckets` rows are inserts into a
            # table Supabase owns and has already secured.
            if (match.group("schema") or "public").lower() == "public"
        }

    return names(_CREATE) - names(_DROP), names(_ENABLE_RLS)


def test_the_scan_actually_reads_the_migrations():
    """A regex that matched nothing would make every assertion below pass.
    42 tables existed when this was written; the floor is deliberately low
    so the test does not need editing every time one is added."""
    tables, rls = _tables_and_rls()
    assert len(tables) >= 40, f"only found {len(tables)} tables — the create-table regex is broken"
    assert len(rls) >= 40, f"only found {len(rls)} RLS statements — the enable-rls regex is broken"
    assert "merchants" in tables
    assert "ledger_entries" in tables


@pytest.mark.parametrize("table", sorted(_tables_and_rls()[0]))
def test_every_table_we_create_has_row_level_security_enabled(table):
    _tables, rls = _tables_and_rls()
    assert table in rls, (
        f"public.{table} is created by a migration but never gets "
        f"'alter table public.{table} enable row level security'. The anon key "
        f"ships in the web bundle and the Android app, so this table is readable "
        f"by anyone who has used InfinityPay. Add the statement - policies are "
        f"optional, enabling RLS is not."
    )
