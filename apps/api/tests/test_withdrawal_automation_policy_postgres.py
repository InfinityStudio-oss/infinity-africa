"""The parts of the withdrawal automation policy that only a real
Postgres can prove.

tests/test_withdrawal_automation_policy.py and
tests/test_withdrawal_automation.py run against the in-memory fake, which
mirrors finalize_withdrawal_limits' *decisions* faithfully and its
*locking* not at all - it is single-threaded, so it cannot tell a correct
advisory lock from a missing one. Everything about this feature that
depends on database locking is therefore unproven by those files, and
saying so in a docstring is not the same as testing it.

This file runs the real SQL from
supabase/migrations/20261031010000_withdrawal_automation_policy.sql
against a real Postgres and proves two things:

1. The per-merchant advisory lock actually serializes. A second caller
   genuinely waits on the first; it does not read around it.
2. Two concurrent withdrawals cannot both consume the same remaining
   rolling allowance.

**It skips unless TEST_DATABASE_URL points at a disposable Postgres**, and
psycopg2 is not in requirements.txt, so it also skips wherever that is not
installed. A skip is not a pass: if this file skipped in your run, the
locking behaviour was not exercised and should be reported as untested
rather than as working.

    createdb infinity_policy_test
    TEST_DATABASE_URL=postgresql://localhost/infinity_policy_test \\
        python -m pytest tests/test_withdrawal_automation_policy_postgres.py -q

Nothing here touches production. It refuses to run against a URL that does
not look like a disposable test database.
"""

import os
import pathlib
import re
import threading
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 is not installed; real-Postgres checks skipped")

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TEST_DATABASE_URL is not set; the advisory-lock behaviour is NOT exercised in this run",
)

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20261031010000_withdrawal_automation_policy.sql"
)

# Enough of public.disbursements for the function to run. Deliberately not
# the whole table: this is a test of one function's concurrency, and
# reproducing the full schema here would make it a slow, brittle copy of
# the migrations that would drift.
SCHEMA = """
drop table if exists public.disbursements cascade;
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
"""


def _guard_against_a_real_database(url: str) -> None:
    """A migration that drops and recreates disbursements must never be
    pointed at anything real. Supabase's own hostnames are refused
    outright, and the database name has to say it is for testing."""
    lowered = url.lower()
    if "supabase.co" in lowered or "supabase.com" in lowered or "pooler." in lowered:
        pytest.fail("TEST_DATABASE_URL points at a Supabase host. Use a disposable local database.")
    name = lowered.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    if "test" not in name:
        pytest.fail(
            f"TEST_DATABASE_URL database name {name!r} does not contain 'test'. "
            "This file drops and recreates tables; point it at a disposable database."
        )


def _function_sql() -> str:
    """Just the two function definitions and the policy table from the
    migration - the grants reference roles (service_role, anon) that a
    plain local Postgres does not have."""
    text = MIGRATION.read_text(encoding="utf-8")
    statements = []
    for match in re.finditer(r"create (?:or replace )?(?:function|table)[\s\S]*?(?:\$\$;|\);)", text):
        chunk = match.group(0)
        is_policy_table = (
            "withdrawal_automation_policy" in chunk and "function" not in chunk.split("(")[0]
        )
        if is_policy_table or "finalize_withdrawal_limits" in chunk:
            statements.append(chunk)
    assert any("finalize_withdrawal_limits" in s for s in statements), "migration shape changed"
    return "\n".join(statements)


@pytest.fixture
def db():
    _guard_against_a_real_database(DATABASE_URL)
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
        cur.execute(_function_sql())
    yield conn
    conn.close()


def _insert(conn, merchant_id, amount, *, offset_seconds=0):
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.disbursements (merchant_id, amount, initiated_at) "
            "values (%s, %s, now() + make_interval(secs => %s)) returning id",
            (str(merchant_id), amount, offset_seconds),
        )
        return cur.fetchone()[0]


def _finalize(conn, disbursement_id, *, daily="10000000", auto_max="100000", auto_daily="100000", version=3):
    with conn.cursor() as cur:
        cur.execute(
            "select public.finalize_withdrawal_limits(%s, %s, %s, %s, %s, %s)",
            (str(disbursement_id), daily, auto_max, auto_daily, True, version),
        )
        return cur.fetchone()[0]


def test_the_inclusive_ceiling_holds_in_real_sql(db):
    """Exactly at the limit is eligible; one shilling over is not. The
    same assertion the fake makes, re-made against the real comparison."""
    merchant_id = uuid.uuid4()

    at_limit = _finalize(db, _insert(db, merchant_id, "100000"), auto_daily="10000000")
    assert at_limit["outcome"] == "auto"
    assert at_limit["code"] == "AUTO_ELIGIBLE"

    over = _finalize(db, _insert(db, uuid.uuid4(), "100001"), auto_daily="10000000")
    assert over["outcome"] == "manual"
    assert over["code"] == "AUTO_AMOUNT_LIMIT_EXCEEDED"


def test_the_advisory_lock_really_blocks_a_second_caller(db):
    """The lock, directly.

    One connection takes the same advisory lock the function takes and
    holds it inside an open transaction. A second connection calling the
    function must then WAIT - so with a short statement_timeout it fails
    with a timeout rather than returning an answer. A function that read
    around the lock would answer immediately, and this test is the only
    thing in the suite that can tell those two apart.
    """
    merchant_id = uuid.uuid4()
    disbursement_id = _insert(db, merchant_id, "5000")

    holder = psycopg2.connect(DATABASE_URL)
    try:
        holder.autocommit = False
        with holder.cursor() as cur:
            cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"withdrawal:{merchant_id}",))

        waiter = psycopg2.connect(DATABASE_URL)
        try:
            waiter.autocommit = True
            with waiter.cursor() as cur:
                cur.execute("set statement_timeout = 1500")
                with pytest.raises(psycopg2.errors.QueryCanceled):
                    cur.execute(
                        "select public.finalize_withdrawal_limits(%s, %s, %s, %s, %s, %s)",
                        (str(disbursement_id), "10000000", "100000", "100000", True, 3),
                    )
        finally:
            waiter.close()

        # Releasing the lock lets the same call through, which proves the
        # timeout above was the lock and not something else being broken.
        holder.rollback()
        after = _finalize(db, disbursement_id)
        assert after["outcome"] == "auto"
    finally:
        holder.close()


def test_two_concurrent_withdrawals_cannot_both_consume_the_same_allowance(db):
    """The race the lock exists for.

    A 100,000 rolling allowance and two 60,000 withdrawals submitted at
    the same instant on separate connections. Exactly one may process
    automatically; both doing so would pay out 120,000 against a 100,000
    cap. Repeated, because a race that passes once has not been shown to
    be impossible.
    """
    for _ in range(20):
        merchant_id = uuid.uuid4()
        first = _insert(db, merchant_id, "60000")
        second = _insert(db, merchant_id, "60000", offset_seconds=1)

        outcomes: dict[str, dict] = {}
        barrier = threading.Barrier(2)

        # barrier and outcomes are bound as defaults rather than captured:
        # this closure is redefined each iteration, and a late-binding
        # capture would have every thread of every round waiting on the
        # last barrier created.
        def run(disbursement_id, label, barrier=barrier, outcomes=outcomes):
            conn = psycopg2.connect(DATABASE_URL)
            try:
                conn.autocommit = True
                barrier.wait(timeout=10)
                outcomes[label] = _finalize(conn, disbursement_id)
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
        assert len(autos) == 1, f"both passed the same allowance: {outcomes}"
        # And the earlier one is the winner, which is the documented rule -
        # the later request falls back rather than both being refused.
        assert autos == ["first"], outcomes
        assert outcomes["second"]["code"] == "AUTO_ROLLING_LIMIT_EXCEEDED"


def test_a_concurrent_pair_cannot_breach_the_hard_daily_limit(db):
    """Same race, one level up: the hard rolling limit that applies to
    manual and automatic withdrawals alike. The loser is REJECTED, not
    quietly downgraded."""
    merchant_id = uuid.uuid4()
    first = _insert(db, merchant_id, "60000")
    second = _insert(db, merchant_id, "60000", offset_seconds=1)

    outcomes: dict[str, dict] = {}
    barrier = threading.Barrier(2)

    def run(disbursement_id, label):
        conn = psycopg2.connect(DATABASE_URL)
        try:
            conn.autocommit = True
            barrier.wait(timeout=10)
            outcomes[label] = _finalize(conn, disbursement_id, daily="100000", auto_daily="10000000")
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


def test_the_compatibility_wrapper_behaves_identically(db):
    """An API build deployed before this migration calls the 5-argument
    signature. It must get the same decision, so the migration can go
    first and a rollback of the API is safe."""
    merchant_id = uuid.uuid4()
    disbursement_id = _insert(db, merchant_id, "5000")

    with db.cursor() as cur:
        cur.execute(
            "select public.finalize_withdrawal_limits(%s, %s, %s, %s, %s)",
            (str(disbursement_id), "10000000", "100000", "100000", True),
        )
        result = cur.fetchone()[0]

    assert result["outcome"] == "auto"
    with db.cursor() as cur:
        cur.execute(
            "select auto_approved, auto_policy_version from public.disbursements where id = %s",
            (str(disbursement_id),),
        )
        auto_approved, policy_version = cur.fetchone()
    assert auto_approved is True
    # Null, because the older caller has no policy to name.
    assert policy_version is None


def test_the_policy_table_refuses_a_second_row(db):
    """One policy, forever. A second row would be a setting nobody is
    reading, which is how a switch comes to say OFF while money moves."""
    with db.cursor() as cur:
        cur.execute(
            "insert into public.withdrawal_automation_policy (id, enabled) values (true, false) "
            "on conflict (id) do nothing"
        )
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("insert into public.withdrawal_automation_policy (id, enabled) values (false, true)")


def test_an_enabled_policy_cannot_store_a_zero_limit(db):
    """Enabled with a zero ceiling reads as ON in the portal while
    behaving as OFF. The constraint refuses it; the API refuses it first,
    with a message."""
    with db.cursor() as cur:
        cur.execute(
            "insert into public.withdrawal_automation_policy (id, enabled) values (true, false) "
            "on conflict (id) do nothing"
        )
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("update public.withdrawal_automation_policy set enabled = true, max_amount_tzs = 0")
