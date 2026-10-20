"""The daily security check must not lie about the schema.

A security check that reports the wrong numbers is worse than no check,
because it is believed. The first version of
scripts/security_daily_check.py did not strip SQL comments, so it read
`create policy` inside commented-out "planned shape" sketches as real
policy. It reported:

    83 policies   where the live database has 64
    11 deny-all   where there are 13

Both errors point the same dangerous way. It overstated how much policy
coverage exists, and it understated how many tables are deny-all - which
means it would have described two backend-only tables, checkout_orders and
merchant_pay_links, as client-reachable when they are not. An inspection
acting on those numbers would look for policy problems that do not exist
and miss the tables whose protection is actually application-side.

The live figures below (64 policies, 13 deny-all) were confirmed against
pg_policies in the production project, so these are not self-referential
assertions - they pin the parser to reality rather than to itself.

Nothing here touches a database. These tests read migrations.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "security_daily_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("security_daily_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("security_daily_check", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def check():
    if not SCRIPT.is_file():
        pytest.fail(f"the daily security check is missing: {SCRIPT}")
    return _load()


# --- the defect itself -------------------------------------------------


def test_commented_out_sql_is_not_counted_as_sql(check):
    """The exact shape of the bug, as it appears in
    20260822180000_checkout_orders.sql."""
    sql = """
    alter table public.checkout_orders enable row level security;

    -- Planned shape (same convention as public.collections):
    --   create policy "merchant staff can view their own checkout orders"
    --     on public.checkout_orders for select
    --     using (merchant_id in (select merchant_id from public.merchant_users));
    """
    stripped = check._strip_sql_comments(sql)

    assert "enable row level security" in stripped
    assert "create policy" not in stripped.lower()


def test_block_comments_are_stripped_too(check):
    stripped = check._strip_sql_comments(
        '/* create policy "nope" on public.ledger_entries for all using (true); */\n'
        "alter table public.ledger_entries enable row level security;"
    )

    assert "create policy" not in stripped.lower()
    assert "enable row level security" in stripped


# --- pinned to what production actually has ----------------------------


def test_the_scan_actually_reads_the_migrations(check):
    """Guards every assertion below against passing vacuously on an empty
    parse - the failure mode that makes a green check meaningless."""
    created, rls_on, policies = check._schema_facts()

    assert len(created) >= 40, f"only parsed {len(created)} tables - the regex is broken"
    assert "merchants" in created
    assert "ledger_entries" in created
    assert sum(policies.values()) >= 50, "policy regex is broken"


def test_policy_count_matches_the_live_database(check):
    """64 in pg_policies, confirmed live. 83 was the comment bug."""
    _created, _rls, policies = check._schema_facts()

    assert sum(policies.values()) == 64, (
        f"migrations now yield {sum(policies.values())} policies, not the 64 confirmed "
        f"live. Either a policy changed - in which case re-verify against pg_policies "
        f"and update this number - or the parser has regressed."
    )


def test_every_created_table_has_rls_enabled(check):
    created, rls_on, _policies = check._schema_facts()

    assert not sorted(created - rls_on), (
        "a table is created without 'enable row level security'. The anon key ships "
        "in the web bundle and the Android app, so such a table is readable by anyone."
    )


def test_the_deny_all_tables_are_the_expected_thirteen(check):
    """RLS on with no policy denies every anon and authenticated request.
    That is the intended, stronger state for these - they are reached only
    by the service-role backend, which enforces merchant ownership in
    application code (tests/test_tenant_isolation_route_guards.py).

    Pinned by name rather than by count so that a *new* backend-only table
    is noticed here, and so that silently adding a permissive policy to
    one of these - the wrong way to clear an advisor warning - fails.
    """
    _created, rls_on, policies = check._schema_facts()
    deny_all = sorted(t for t in rls_on if policies[t] == 0)

    assert deny_all == [
        "api_ip_allowlist",
        "api_request_logs",
        "checkout_orders",
        "idempotency_keys",
        "merchant_pay_links",
        "merchant_referrals",
        "merchant_withdrawal_otp_challenges",
        "referral_commissions",
        "scheduler_leases",
        "selcom_webhook_events",
        "sms_campaigns",
        "sms_messages",
        "sms_provider_events",
    ], (
        "the set of deny-all tables changed. If a policy was added to one of these, "
        "confirm it was deliberate and not an attempt to silence an advisor warning: "
        "these tables are meant to be unreachable with the anon key."
    )


# --- the checks report honestly ----------------------------------------


def test_a_check_that_cannot_run_is_not_reported_as_passing(check):
    """Silence is not evidence. A check whose source is unreachable must
    be SKIPPED, and SKIPPED must fail the run."""
    result = check.Result("made up", check.SKIP, "source unavailable")

    assert result.status == check.SKIP
    assert check.SKIP != check.PASS


def test_search_path_check_sees_every_function_as_pinned(check):
    """All 8 functions pin search_path once 20261020090000 is applied. The
    three ALTER statements in that migration are what makes this pass, so
    a revert of it fails here."""
    result = check.check_function_search_path()

    assert result.status == check.PASS, result.detail


def test_drift_check_would_catch_an_uncovered_credential(check, monkeypatch, tmp_path):
    """The drift check earned its place by finding four. This proves it
    still fires rather than having been quietly neutralised by the
    NOT_CREDENTIALS allowlist growing too broad."""
    settings = tmp_path / "settings.py"
    settings.write_text(
        "class Settings:\n"
        "    a_totally_new_provider_api_key: str = \"\"\n",
        encoding="utf-8",
    )
    scanner = tmp_path / "scan.ts"
    scanner.write_text('const FORBIDDEN = ["SUPABASE_JWT_SECRET"];\n', encoding="utf-8")

    monkeypatch.setattr(check, "SETTINGS", settings)
    monkeypatch.setattr(check, "WEB_SCANNER", scanner)

    result = check.check_secret_name_drift()

    assert result.status == check.FAIL
    assert "A_TOTALLY_NEW_PROVIDER_API_KEY" in result.detail


def test_the_not_credentials_allowlist_stays_small_and_justified(check):
    """A broad allowlist here silently defeats the drift check, which is
    the one check that caught a real gap."""
    assert len(check.NOT_CREDENTIALS) <= 20, (
        "the allowlist is growing. Each entry must be a name whose appearance in the "
        "frontend is genuinely not a finding, with the reason recorded beside it."
    )


def test_reports_never_contain_a_credential_value(check):
    """Every check returns a path, a type and a remediation. A value
    appearing in a report would put a secret into CI logs."""
    results = [
        check.check_secret_name_drift(),
        check.check_rls_coverage(),
        check.check_function_search_path(),
    ]

    joined = " ".join(r.detail for r in results)
    for shape in (r"eyJ[A-Za-z0-9_-]{20,}", r"sk_live_[A-Za-z0-9]{12,}", r"\bre_[A-Za-z0-9]{20,}"):
        assert not re.search(shape, joined), f"a credential-shaped value reached a report: {shape}"


# --- the prepared migration must not fail on apply ---------------------

MIGRATION = REPO_ROOT / "supabase" / "migrations" / "20261020090000_pin_function_search_path.sql"


def test_the_search_path_migration_exists():
    assert MIGRATION.is_file(), f"missing: {MIGRATION}"


def test_every_altered_function_is_one_the_migrations_actually_define():
    """`alter function` fails outright if the name and argument list do not
    match an existing function exactly. There is no isolated Postgres in
    this environment to apply the migration against, so this is the next
    best thing: it pins the migration to the definitions in the same tree,
    so a rename or a signature change breaks here rather than at apply
    time against production.
    """
    sql = MIGRATION.read_text(encoding="utf-8")
    altered = set(re.findall(r"alter\s+function\s+public\.([a-z0-9_]+)\s*\(\s*\)", sql, re.I))

    assert altered, "no zero-argument alter function statements parsed - regex broken"

    defined = set()
    for path in sorted((REPO_ROOT / "supabase" / "migrations").glob("*.sql")):
        body = path.read_text(encoding="utf-8", errors="ignore")
        defined |= {
            m.group(1).lower()
            for m in re.finditer(
                r"create\s+or\s+replace\s+function\s+public\.([a-z0-9_]+)\s*\(\s*\)", body, re.I
            )
        }

    missing = sorted(altered - defined)
    assert not missing, (
        f"the migration alters {missing}, which no migration defines with a zero-argument "
        f"signature. `alter function` would fail on apply."
    )


def test_the_migration_does_not_redefine_any_function_body():
    """ALTER rather than CREATE OR REPLACE is the whole safety argument:
    restating enforce_ledger_balance - the deferred check proving debits
    equal credits - would risk changing financial behaviour to fix a
    linter warning."""
    sql = MIGRATION.read_text(encoding="utf-8")
    uncommented = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())

    assert "create or replace function" not in uncommented.lower()
    assert "$$" not in uncommented


def test_the_migration_touches_no_table():
    """Catalog-only. A table rewrite under ACCESS EXCLUSIVE is exactly what
    this must not do on a live database."""
    sql = "\n".join(
        line.split("--", 1)[0]
        for line in MIGRATION.read_text(encoding="utf-8").splitlines()
    ).lower()

    for forbidden in ("alter table", "update ", "insert ", "delete ", "drop ", "create table"):
        assert forbidden not in sql, f"migration contains '{forbidden.strip()}'"


# --- "the tests passed" must mean tests actually ran --------------------


class _FakeProc:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def test_a_suite_that_collected_almost_nothing_does_not_pass(check, monkeypatch):
    """pytest exits 0 when it collects nothing matching, so a zero exit code
    is not proof the tests ran. A suite that silently stopped running would
    otherwise report success forever - and a green check is believed.

    The first CI run of this workflow finished in 36 seconds. From outside,
    a fast Linux runner and a step that had quietly stopped executing look
    identical, and reading the log needs admin rights the person on call may
    not have. So the check states the number and refuses an implausible one.
    """
    monkeypatch.setattr(
        check.subprocess, "run", lambda *a, **k: _FakeProc("3 passed in 0.10s")
    )

    result = check.check_security_tests()

    assert result.status == check.FAIL
    assert "only 3 tests ran" in result.detail


def test_a_full_suite_passes(check, monkeypatch):
    monkeypatch.setattr(
        check.subprocess, "run", lambda *a, **k: _FakeProc("987 passed in 42.00s")
    )

    assert check.check_security_tests().status == check.PASS


def test_a_zero_exit_with_no_summary_line_does_not_pass(check, monkeypatch):
    """No parsable summary means no evidence, and no evidence is not a pass."""
    monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: _FakeProc(""))

    assert check.check_security_tests().status == check.FAIL


def test_a_real_failure_is_still_reported_as_failure(check, monkeypatch):
    monkeypatch.setattr(
        check.subprocess,
        "run",
        lambda *a, **k: _FakeProc("1 failed, 900 passed in 42.00s", returncode=1),
    )

    assert check.check_security_tests().status == check.FAIL


def test_the_floor_is_below_the_real_count_but_not_trivial(check):
    """A floor set too low protects nothing; set above the real count it
    fails every run and gets deleted."""
    assert 100 <= check._MIN_SECURITY_TESTS <= 2000
