"""The guarantees only a real Postgres can give.

The in-memory fake mirrors what finalize_withdrawal_limits *decides*. It
cannot mirror what it *locks*, because it is single-threaded: a correct
`for share` and a missing one produce identical results there. Everything
about this feature that depends on locking is therefore unproven by the
rest of the suite, and a docstring saying "this is race-proof" is not a
test.

So these run the real SQL, on separate connections, in overlapping
transactions, and coordinate deterministically — no sleeps, no "probably
long enough". Where a test needs one transaction to be mid-flight while
another starts, it holds the first open and proves the second BLOCKS by
giving it a statement_timeout and catching the cancellation.

**What is proven here:**

1. OFF committed before authorisation is seen (the race this closed).
2. A decision already in flight is not disturbed by a later OFF, and the
   OFF waits for it rather than interleaving.
3. A lowered ceiling binds the next authorisation.
4. Two administrators holding the same expected version: one wins, one
   gets a conflict.
5. A failing audit insert takes the policy change with it.
6. Concurrent withdrawals cannot both consume one merchant's remaining
   rolling allowance.
7. The compatibility signature cannot authorise against a policy saying
   no.

Runs only when TEST_DATABASE_URL points at a disposable database, and
refuses anything that looks like production. **A skip is not a pass**: if
this file skipped, the locking was not exercised and should be reported
as untested. CI provides a throwaway Postgres service for it.
"""

import os
import pathlib
import re
import threading
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed; locking checks skipped")

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TEST_DATABASE_URL is not set; the locking guarantees are NOT exercised in this run",
)

MIGRATIONS = pathlib.Path(__file__).resolve().parents[3] / "supabase" / "migrations"
POLICY_MIGRATION = MIGRATIONS / "20261031010000_withdrawal_automation_policy.sql"
LOCK_MIGRATION = MIGRATIONS / "20261031040000_withdrawal_policy_authorization_lock.sql"

# Enough of the real schema for these functions to run. Deliberately not
# the whole thing: this is a test of locking, and reproducing every table
# would make it a slow, drifting copy of the migrations.
SCHEMA = """
drop table if exists public.disbursements cascade;
drop table if exists public.withdrawal_automation_policy cascade;
drop table if exists public.audit_logs cascade;

create table public.disbursements (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null,
  amount numeric(14, 2) not null,
  status text not null default 'PENDING_ADMIN_APPROVAL',
  auto_approved boolean not null default false,
  auto_decision_reason text,
  auto_decision_code text,
  auto_policy_version integer,
  auto_decided_at timestamptz,
  initiated_at timestamptz not null default now()
);

create table public.withdrawal_automation_policy (
  id boolean primary key default true check (id),
  enabled boolean not null default false,
  max_amount_tzs numeric(14, 2) not null default 500000.00 check (max_amount_tzs >= 0),
  merchant_rolling_24h_limit_tzs numeric(14, 2) not null default 1000000.00
    check (merchant_rolling_24h_limit_tzs >= 0),
  version integer not null default 1 check (version > 0),
  updated_at timestamptz not null default now(),
  updated_by uuid,
  constraint withdrawal_automation_policy_enabled_limits_positive check (
    not enabled or (max_amount_tzs > 0 and merchant_rolling_24h_limit_tzs > 0)
  )
);

create table public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid,
  actor_type text not null,
  action text not null,
  resource_type text,
  resource_id uuid,
  ip_address text,
  user_agent text,
  metadata jsonb,
  created_at timestamptz not null default now()
);

insert into public.withdrawal_automation_policy (id, enabled, max_amount_tzs, merchant_rolling_24h_limit_tzs)
values (true, true, 100000.00, 1000000.00);
"""

# The grants in the migrations name Supabase's roles. Creating them means
# the grants apply as written rather than being stripped out, so the test
# exercises the real statements.
ROLES = """
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role; end if;
end
$$;
"""


def _guard_against_a_real_database(url: str) -> None:
    """This file drops and recreates tables. It must never be pointed at
    anything real, so Supabase hosts are refused outright and the database
    name has to say it is for testing."""
    lowered = url.lower()
    for marker in ("supabase.co", "supabase.com", "pooler."):
        if marker in lowered:
            pytest.fail(f"TEST_DATABASE_URL points at {marker}. Use a disposable local database.")
    name = lowered.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    if "test" not in name:
        pytest.fail(
            f"TEST_DATABASE_URL database name {name!r} does not contain 'test'. "
            "This file drops and recreates tables; point it at a disposable database."
        )


def _statements(path: pathlib.Path) -> str:
    """The create/comment/grant statements from a migration, skipping its
    prose. Dollar-quoted function bodies are kept whole."""
    text = path.read_text(encoding="utf-8")
    pattern = r"(create (?:or replace )?(?:function|table)[\s\S]*?(?:\$\$;|\);))|(comment on [\s\S]*?;)|((?:revoke|grant)[^;]*;)"
    return "\n".join(match.group(0) for match in re.finditer(pattern, text))


@pytest.fixture
def db():
    _guard_against_a_real_database(DATABASE_URL)
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(ROLES)
        cur.execute(SCHEMA)
        # Order matters: the lock migration replaces the function bodies
        # the policy migration created.
        cur.execute(_statements(POLICY_MIGRATION))
        cur.execute(_statements(LOCK_MIGRATION))
    yield conn
    conn.close()


def _connect():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn


def _insert(conn, merchant_id, amount, *, offset_seconds=0):
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.disbursements (merchant_id, amount, initiated_at) "
            "values (%s, %s, now() + make_interval(secs => %s)) returning id",
            (str(merchant_id), amount, offset_seconds),
        )
        return cur.fetchone()[0]


def _finalize(conn, disbursement_id, *, daily="10000000", deploy_max="500000",
              deploy_rolling="1000000", deploy_allows=True):
    """Deployment ceiling and permission only — the function reads the
    live policy itself. That split is the fix being tested."""
    with conn.cursor() as cur:
        cur.execute(
            "select public.finalize_withdrawal_limits(%s, %s, %s, %s, %s, %s)",
            (str(disbursement_id), daily, deploy_max, deploy_rolling, deploy_allows, None),
        )
        return cur.fetchone()[0]


def _set_policy(conn, *, enabled=None, max_amount=None, rolling=None):
    sets, values = [], []
    if enabled is not None:
        sets.append("enabled = %s")
        values.append(enabled)
    if max_amount is not None:
        sets.append("max_amount_tzs = %s")
        values.append(max_amount)
    if rolling is not None:
        sets.append("merchant_rolling_24h_limit_tzs = %s")
        values.append(rolling)
    with conn.cursor() as cur:
        cur.execute(f"update public.withdrawal_automation_policy set {', '.join(sets)} where id = true", values)


# --- 1. The race this closed ----------------------------------------------


def test_off_committed_before_authorisation_is_seen(db):
    """The whole point. Before 20261031040000 the API read the policy and
    passed the answer in, so an OFF committing in between was invisible.
    The function reads the policy itself now."""
    merchant_id = uuid.uuid4()
    disbursement_id = _insert(db, merchant_id, "5000")

    _set_policy(db, enabled=False)

    # The caller still says the deployment permits automation. The policy
    # says no, and the policy is what the transaction reads.
    result = _finalize(db, disbursement_id, deploy_allows=True)

    assert result["outcome"] == "manual"
    assert result["code"] == "AUTO_POLICY_DISABLED"


def test_a_caller_cannot_re_enable_automation_the_policy_has_switched_off(db):
    """A stale or malicious caller passing True must not be able to
    override a stored OFF. AND, never OR."""
    merchant_id = uuid.uuid4()
    _set_policy(db, enabled=False)

    result = _finalize(db, _insert(db, merchant_id, "100"), deploy_allows=True)

    assert result["outcome"] == "manual"


def test_a_deployment_prohibition_beats_an_enabled_policy(db):
    """Runtime may tighten, never loosen. The policy says ON; the
    deployment says no."""
    merchant_id = uuid.uuid4()

    result = _finalize(db, _insert(db, merchant_id, "5000"), deploy_allows=False)

    assert result["outcome"] == "manual"
    assert result["code"] == "AUTO_POLICY_DISABLED"


def test_a_deployment_ceiling_clamps_a_higher_policy_limit(db):
    """LEAST, not the policy's own number. Policy allows 100,000; the
    deployment caps automation at 2,000."""
    merchant_id = uuid.uuid4()

    result = _finalize(db, _insert(db, merchant_id, "5000"), deploy_max="2000")

    assert result["outcome"] == "manual"
    assert result["code"] == "AUTO_AMOUNT_LIMIT_EXCEEDED"


def test_a_missing_policy_is_not_an_enabled_one(db):
    """Unknown must never mean yes."""
    merchant_id = uuid.uuid4()
    with db.cursor() as cur:
        cur.execute("delete from public.withdrawal_automation_policy")

    result = _finalize(db, _insert(db, merchant_id, "5000"))

    assert result["outcome"] == "manual"
    assert result["code"] == "AUTO_POLICY_UNAVAILABLE"
    assert result["policy_version"] is None


# --- 2. The lock itself, proved by blocking -------------------------------


def test_a_policy_change_waits_for_a_decision_already_in_flight(db):
    """`for share` on the policy row, demonstrated rather than asserted.

    One connection authorises a payout and holds its transaction open. A
    second connection tries to switch automation off; with a short
    statement_timeout it is cancelled, because it is waiting. Releasing
    the first lets it through — which proves the timeout was the lock and
    not something else being broken.
    """
    merchant_id = uuid.uuid4()
    disbursement_id = _insert(db, merchant_id, "5000")

    decider = psycopg2.connect(DATABASE_URL)
    decider.autocommit = False
    try:
        with decider.cursor() as cur:
            cur.execute(
                "select public.finalize_withdrawal_limits(%s, %s, %s, %s, %s, %s)",
                (str(disbursement_id), "10000000", "500000", "1000000", True, None),
            )
            assert cur.fetchone()[0]["outcome"] == "auto"

        switcher = _connect()
        try:
            with switcher.cursor() as cur:
                cur.execute("set statement_timeout = 1500")
                with pytest.raises(psycopg2.errors.QueryCanceled):
                    cur.execute(
                        "update public.withdrawal_automation_policy set enabled = false where id = true"
                    )
        finally:
            switcher.close()

        decider.commit()

        after = _connect()
        try:
            with after.cursor() as cur:
                cur.execute("update public.withdrawal_automation_policy set enabled = false where id = true")
                cur.execute("select enabled from public.withdrawal_automation_policy where id = true")
                assert cur.fetchone()[0] is False
        finally:
            after.close()
    finally:
        decider.close()


def test_a_decision_started_after_off_commits_sees_the_off(db):
    """The other side of the same lock, with the order reversed."""
    merchant_id = uuid.uuid4()

    switcher = _connect()
    try:
        _set_policy(switcher, enabled=False)
    finally:
        switcher.close()

    result = _finalize(db, _insert(db, merchant_id, "5000"))

    assert result["outcome"] == "manual"
    assert result["code"] == "AUTO_POLICY_DISABLED"


def test_a_payout_already_authorised_is_not_recalled_by_a_later_off(db):
    """The honest boundary. OFF stops new authorisations; it cannot undo
    one that has committed, because by then the instruction is on its way
    to a provider."""
    merchant_id = uuid.uuid4()
    disbursement_id = _insert(db, merchant_id, "5000")

    assert _finalize(db, disbursement_id)["outcome"] == "auto"
    _set_policy(db, enabled=False)

    with db.cursor() as cur:
        cur.execute(
            "select auto_approved, auto_decision_code from public.disbursements where id = %s",
            (str(disbursement_id),),
        )
        auto_approved, code = cur.fetchone()

    assert auto_approved is True
    assert code == "AUTO_ELIGIBLE"


def test_a_lowered_ceiling_binds_the_next_authorisation(db):
    """No deploy, no restart: the next decision reads the new number."""
    merchant_id = uuid.uuid4()

    assert _finalize(db, _insert(db, merchant_id, "50000"))["outcome"] == "auto"

    _set_policy(db, max_amount="1000")

    second = _finalize(db, _insert(db, merchant_id, "50000", offset_seconds=1))
    assert second["outcome"] == "manual"
    assert second["code"] == "AUTO_AMOUNT_LIMIT_EXCEEDED"


# --- 3. Two administrators ------------------------------------------------


def test_two_administrators_with_the_same_expected_version(db):
    """Both read version 1. One write lands, the other is told so."""
    actor = str(uuid.uuid4())

    def attempt(max_amount: str):
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "select public.update_withdrawal_automation_policy("
                    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (True, max_amount, "1000000", 1, actor, "corr", True, True, "500000", "1000000", None, None),
                )
                return cur.fetchone()[0]
        finally:
            conn.close()

    first = attempt("20000")
    second = attempt("90000")

    assert first["outcome"] == "ok"
    assert first["version"] == 2
    assert second["outcome"] == "conflict"
    assert second["current_version"] == 2

    with db.cursor() as cur:
        cur.execute("select max_amount_tzs from public.withdrawal_automation_policy where id = true")
        # The loser's number was never written.
        assert str(cur.fetchone()[0]) == "20000.00"


def test_the_policy_change_and_its_audit_row_commit_together(db):
    """One transaction. The audit row exists because the change did."""
    actor = str(uuid.uuid4())
    with db.cursor() as cur:
        cur.execute(
            "select public.update_withdrawal_automation_policy("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (False, "20000", "1000000", 1, actor, "corr-1", False, True, "500000", "1000000", None, None),
        )
        assert cur.fetchone()[0]["outcome"] == "ok"

        cur.execute(
            "select metadata from public.audit_logs where action = 'withdrawal_automation_policy.updated'"
        )
        rows = cur.fetchall()

    assert len(rows) == 1
    metadata = rows[0][0]
    assert metadata["correlation_id"] == "corr-1"
    assert metadata["previous"]["version"] == 1
    assert metadata["new"]["version"] == 2
    assert metadata["previous"]["enabled"] is True
    assert metadata["new"]["enabled"] is False


def test_a_failing_audit_insert_takes_the_policy_change_with_it(db):
    """The defect this closed: the update committed, the audit insert
    failed, and the control over unattended payouts had moved with nothing
    recording it and an error shown to the administrator who had in fact
    succeeded.

    actor_type is NOT NULL here, so a trigger that nulls it makes the
    insert fail for a reason the function does not catch.
    """
    with db.cursor() as cur:
        cur.execute(
            """
            create or replace function public.break_audit() returns trigger
            language plpgsql as $fn$
            begin
              raise exception 'audit storage is unavailable';
            end
            $fn$;
            create trigger break_audit_trigger before insert on public.audit_logs
            for each row execute function public.break_audit();
            """
        )

    actor = str(uuid.uuid4())
    with db.cursor() as cur, pytest.raises(psycopg2.Error):
        cur.execute(
            "select public.update_withdrawal_automation_policy("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (False, "20000", "1000000", 1, actor, "corr-2", False, True, "500000", "1000000", None, None),
        )

    with db.cursor() as cur:
        cur.execute("select version, enabled from public.withdrawal_automation_policy where id = true")
        version, enabled = cur.fetchone()

    # Untouched. The administrator was told it failed, and it did.
    assert version == 1
    assert enabled is True


# --- 4. One merchant, many requests ---------------------------------------


def test_concurrent_withdrawals_cannot_both_consume_one_allowance(db):
    """The per-merchant advisory lock. A 100,000 rolling allowance and two
    60,000 withdrawals at the same instant: exactly one may process, or
    120,000 leaves against a 100,000 cap. Repeated, because a race that
    passes once has not been shown to be impossible."""
    _set_policy(db, max_amount="100000", rolling="100000")

    for _ in range(15):
        merchant_id = uuid.uuid4()
        first = _insert(db, merchant_id, "60000")
        second = _insert(db, merchant_id, "60000", offset_seconds=1)

        outcomes: dict[str, dict] = {}
        barrier = threading.Barrier(2)

        def run(disbursement_id, label, barrier=barrier, outcomes=outcomes):
            conn = _connect()
            try:
                barrier.wait(timeout=10)
                outcomes[label] = _finalize(conn, disbursement_id, deploy_rolling="100000")
            finally:
                conn.close()

        threads = [
            threading.Thread(target=run, args=(first, "first")),
            threading.Thread(target=run, args=(second, "second")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert set(outcomes) == {"first", "second"}, "a worker did not finish"
        autos = [label for label, result in outcomes.items() if result["outcome"] == "auto"]
        assert autos == ["first"], outcomes
        assert outcomes["second"]["code"] == "AUTO_ROLLING_LIMIT_EXCEEDED"


def test_a_concurrent_pair_cannot_breach_the_hard_daily_limit(db):
    """Same race one level up: the hard limit that applies to automatic
    and manual withdrawals alike. The loser is REJECTED, not downgraded."""
    merchant_id = uuid.uuid4()
    first = _insert(db, merchant_id, "60000")
    second = _insert(db, merchant_id, "60000", offset_seconds=1)

    outcomes: dict[str, dict] = {}
    barrier = threading.Barrier(2)

    def run(disbursement_id, label):
        conn = _connect()
        try:
            barrier.wait(timeout=10)
            outcomes[label] = _finalize(conn, disbursement_id, daily="100000")
        finally:
            conn.close()

    threads = [
        threading.Thread(target=run, args=(first, "first")),
        threading.Thread(target=run, args=(second, "second")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert outcomes["first"]["outcome"] == "auto"
    assert outcomes["second"]["outcome"] == "rejected"
    assert outcomes["second"]["code"] == "DAILY_LIMIT_EXCEEDED"

    with db.cursor() as cur:
        cur.execute("select status from public.disbursements where id = %s", (str(second),))
        assert cur.fetchone()[0] == "REJECTED"


def test_deciding_the_same_withdrawal_twice_does_not_double_authorise(db):
    """Two workers, one row. The second call re-decides the same
    disbursement; it must not produce a second authorisation or count the
    row against itself."""
    _set_policy(db, rolling="100000")
    merchant_id = uuid.uuid4()
    disbursement_id = _insert(db, merchant_id, "60000")

    first = _finalize(db, disbursement_id, deploy_rolling="100000")
    second = _finalize(db, disbursement_id, deploy_rolling="100000")

    assert first["outcome"] == "auto"
    assert second["outcome"] == "auto"

    with db.cursor() as cur:
        cur.execute(
            "select count(*) from public.disbursements where merchant_id = %s and auto_approved",
            (str(merchant_id),),
        )
        assert cur.fetchone()[0] == 1


# --- 5. The compatibility signature ---------------------------------------


def test_the_five_argument_wrapper_cannot_authorise_against_an_off_policy(db):
    """An older API build reaches the wrapper. It must not be a way past
    the off switch."""
    merchant_id = uuid.uuid4()
    _set_policy(db, enabled=False)

    with db.cursor() as cur:
        cur.execute(
            "select public.finalize_withdrawal_limits(%s, %s, %s, %s, %s)",
            (str(_insert(db, merchant_id, "5000")), "10000000", "500000", "1000000", True),
        )
        result = cur.fetchone()[0]

    assert result["outcome"] == "manual"
    assert result["code"] == "AUTO_POLICY_DISABLED"


def test_the_five_argument_wrapper_still_works_when_the_policy_allows_it(db):
    """Fail-closed must not mean fail-always."""
    merchant_id = uuid.uuid4()

    with db.cursor() as cur:
        cur.execute(
            "select public.finalize_withdrawal_limits(%s, %s, %s, %s, %s)",
            (str(_insert(db, merchant_id, "5000")), "10000000", "500000", "1000000", True),
        )
        assert cur.fetchone()[0]["outcome"] == "auto"


# --- 6. Grants ------------------------------------------------------------


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_a_browser_role_cannot_execute_either_function(db, role):
    """These decide whether money leaves. The anon key ships in the web
    bundle and the Android app."""
    with db.cursor() as cur:
        cur.execute(
            "select has_function_privilege(%s, 'public.finalize_withdrawal_limits"
            "(uuid, numeric, numeric, numeric, boolean, integer)', 'execute')",
            (role,),
        )
        assert cur.fetchone()[0] is False

        cur.execute(
            "select has_function_privilege(%s, 'public.update_withdrawal_automation_policy"
            "(boolean, numeric, numeric, integer, uuid, text, boolean, boolean, numeric, numeric, text, text)',"
            " 'execute')",
            (role,),
        )
        assert cur.fetchone()[0] is False


def test_both_functions_pin_their_search_path(db):
    """A SECURITY DEFINER function with a mutable search_path can be
    redirected at objects an attacker controls."""
    with db.cursor() as cur:
        cur.execute(
            "select proname, proconfig from pg_proc "
            "where proname in ('finalize_withdrawal_limits', 'update_withdrawal_automation_policy')"
        )
        rows = cur.fetchall()

    assert rows, "the functions are missing"
    for name, config in rows:
        assert config and any(entry.startswith("search_path=") for entry in config), name
