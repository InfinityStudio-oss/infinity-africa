"""The payout money invariants, on a real Postgres.

Every other test of this feature runs against the in-memory fake, which
is single-threaded. That makes it structurally incapable of failing the
tests that matter most here: `for update` and a missing `for update`
produce identical results when only one thing ever runs at a time, and
`pg_advisory_xact_lock` is a no-op against a dictionary. So the suite can
be green while two concurrent payouts both spend the same balance.

These run the real SQL on independent connections in overlapping
transactions. What they are for:

1. Concurrent payouts cannot overspend the payout wallet.
2. Concurrent payouts cannot breach the rolling 24-hour limit.
3. Authorising one payout twice reserves once.
4. Concurrent funding and a legacy withdrawal cannot overdraw Collections.
5. A refused reservation leaves nothing behind - no ledger posting and no
   orphaned transactions row.

(4) matters because the payout wallet is funded *out of* the Collections
balance that withdrawals also spend. If those two paths do not serialise
against each other, a merchant can move the same money twice: once into
the payout wallet and once out to their bank.

(5) matters because the reservation creates a transactions row for the
ledger entries to hang off. If the row survives a refusal, the payout is
cancelled but the platform still carries a transaction in `processing`
that no ledger entry will ever balance.

Runs only when TEST_PAYOUT_DATABASE_URL points at a disposable database
holding the full migration set. **A skip is not a pass.** Its own
variable, separate from TEST_DATABASE_URL, because the policy locking
tests drop and rebuild their tables and would take this schema with them.
"""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed; payout locking checks skipped")

DATABASE_URL = os.environ.get("TEST_PAYOUT_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TEST_PAYOUT_DATABASE_URL is not set; the payout money invariants are NOT exercised in this run",
)


def _guard_against_a_real_database(url: str) -> None:
    lowered = url.lower()
    for marker in ("supabase.co", "supabase.com", "pooler."):
        if marker in lowered:
            pytest.fail(f"TEST_PAYOUT_DATABASE_URL points at {marker}. Use a disposable local database.")
    name = lowered.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    if "test" not in name:
        pytest.fail(
            f"TEST_PAYOUT_DATABASE_URL database name {name!r} does not contain 'test'. "
            "These tests move money; point them at a disposable database."
        )


def _connect():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn


@pytest.fixture(scope="module")
def admin():
    _guard_against_a_real_database(DATABASE_URL)
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("select to_regclass('public.payouts'), to_regproc('public.authorize_payout')")
        table, function = cur.fetchone()
    if table is None or function is None:
        conn.close()
        pytest.fail(
            "TEST_PAYOUT_DATABASE_URL database has no payouts table or authorize_payout function. "
            "Apply the full migration set to it first."
        )
    yield conn
    conn.close()


@pytest.fixture
def merchant(admin):
    """A merchant with an empty payout wallet and an approved destination."""
    suffix = uuid.uuid4().hex[:8]
    # merchant_code is checked against ^27[0-9]{6}$ in the real schema.
    code = "27" + f"{uuid.uuid4().int % 1000000:06d}"
    with admin.cursor() as cur:
        cur.execute(
            "insert into public.merchants (business_name, contact_email, merchant_code) "
            "values (%s, %s, %s) returning id",
            (f"Payout Test {suffix}", f"payout-{suffix}@example.test", code),
        )
        merchant_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.payout_beneficiaries "
            "(merchant_id, environment, name, method, destination_code, destination_identifier) "
            "values (%s, 'live', 'Test Destination', 'MOBILE_MONEY', 'VODACOM', '255700000000') "
            "returning id",
            (merchant_id,),
        )
        beneficiary_id = cur.fetchone()[0]
    return merchant_id, beneficiary_id


def _account(conn, merchant_id, purpose, account_type, balance="0"):
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.ledger_accounts "
            "(merchant_id, name, account_type, purpose, currency, environment, balance) "
            "values (%s, %s, %s, %s, 'TZS', 'live', %s) returning id",
            (merchant_id, f"{purpose} {str(merchant_id)[:8]}", account_type, purpose, balance),
        )
        return cur.fetchone()[0]


def _wallet(conn, merchant_id, *, available="0", reserved="0"):
    return (
        _account(conn, merchant_id, "payout_available", "liability", available),
        _account(conn, merchant_id, "payout_reserved", "liability", reserved),
    )


def _balance(conn, account_id):
    with conn.cursor() as cur:
        cur.execute("select balance from public.ledger_accounts where id = %s", (account_id,))
        return cur.fetchone()[0]


def _queue_payout(conn, merchant_id, beneficiary_id, amount, *, fee="0"):
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.payouts "
            "(merchant_id, environment, beneficiary_id, amount, fee_amount, total_debit, "
            " currency, status, provider_reference) "
            "values (%s, 'live', %s, %s, %s, %s::numeric + %s::numeric, 'TZS', 'queued', %s) "
            "returning id",
            (
                merchant_id,
                beneficiary_id,
                amount,
                fee,
                amount,
                fee,
                f"PO-{uuid.uuid4().hex[:16]}",
            ),
        )
        return cur.fetchone()[0]


def _authorize(conn, payout_id, daily_limit=None):
    with conn.cursor() as cur:
        cur.execute("select public.authorize_payout(%s, %s)", (str(payout_id), daily_limit))
        return cur.fetchone()[0]


def _in_parallel(calls):
    """Run each callable on its own connection, released together.

    A barrier rather than a sleep: every thread is inside the function
    before any of them is allowed past, so the contention is real and the
    test does not depend on timing.
    """
    barrier = threading.Barrier(len(calls))

    def run(call):
        conn = _connect()
        try:
            barrier.wait(timeout=10)
            return call(conn)
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [f.result(timeout=30) for f in [pool.submit(run, c) for c in calls]]


# --- the payout wallet cannot be overspent -----------------------------------


def test_two_concurrent_payouts_cannot_both_spend_one_balance(admin, merchant):
    """The headline invariant. 10,000 funded, two payouts of 6,000 each
    released at the same instant: one must be refused."""
    merchant_id, beneficiary_id = merchant
    available, reserved = _wallet(admin, merchant_id, available="10000.00")
    first = _queue_payout(admin, merchant_id, beneficiary_id, "6000.00")
    second = _queue_payout(admin, merchant_id, beneficiary_id, "6000.00")

    results = _in_parallel([
        lambda c, p=first: _authorize(c, p),
        lambda c, p=second: _authorize(c, p),
    ])

    outcomes = sorted(r["outcome"] for r in results)
    assert outcomes == ["authorized", "insufficient_funds"], outcomes
    assert _balance(admin, available) == 4000
    assert _balance(admin, reserved) == 6000


def test_the_wallet_never_goes_negative_under_a_burst(admin, merchant):
    """Eight simultaneous payouts against a balance that covers three."""
    merchant_id, beneficiary_id = merchant
    available, reserved = _wallet(admin, merchant_id, available="3000.00")
    payouts = [_queue_payout(admin, merchant_id, beneficiary_id, "1000.00") for _ in range(8)]

    results = _in_parallel([(lambda c, p=p: _authorize(c, p)) for p in payouts])

    authorized = [r for r in results if r["outcome"] == "authorized"]
    assert len(authorized) == 3, [r["outcome"] for r in results]
    assert _balance(admin, available) == 0
    assert _balance(admin, reserved) == 3000


def test_reserved_and_available_always_sum_to_what_was_funded(admin, merchant):
    """Reservation moves money between two pots; it never creates or
    destroys any. This is the arithmetic a double entry exists to keep."""
    merchant_id, beneficiary_id = merchant
    available, reserved = _wallet(admin, merchant_id, available="5000.00")
    payouts = [_queue_payout(admin, merchant_id, beneficiary_id, "900.00") for _ in range(5)]

    _in_parallel([(lambda c, p=p: _authorize(c, p)) for p in payouts])

    assert _balance(admin, available) + _balance(admin, reserved) == 5000


# --- the rolling limit -------------------------------------------------------


def test_concurrent_payouts_cannot_breach_the_rolling_limit(admin, merchant):
    """Funded well past the limit, so only the limit can stop them."""
    merchant_id, beneficiary_id = merchant
    _wallet(admin, merchant_id, available="1000000.00")
    first = _queue_payout(admin, merchant_id, beneficiary_id, "6000.00")
    second = _queue_payout(admin, merchant_id, beneficiary_id, "6000.00")

    results = _in_parallel([
        lambda c, p=first: _authorize(c, p, "10000"),
        lambda c, p=second: _authorize(c, p, "10000"),
    ])

    outcomes = sorted(r["outcome"] for r in results)
    assert outcomes == ["authorized", "daily_limit"], outcomes


def test_a_burst_cannot_sum_past_the_rolling_limit(admin, merchant):
    """Six payouts of 2,000 against a 5,000 limit: at most two may pass,
    and what was authorised must not exceed the limit."""
    merchant_id, beneficiary_id = merchant
    _wallet(admin, merchant_id, available="1000000.00")
    payouts = [_queue_payout(admin, merchant_id, beneficiary_id, "2000.00") for _ in range(6)]

    _in_parallel([(lambda c, p=p: _authorize(c, p, "5000")) for p in payouts])

    with admin.cursor() as cur:
        cur.execute(
            "select coalesce(sum(total_debit), 0) from public.payouts "
            "where merchant_id = %s and status in ('queued','processing','successful')",
            (merchant_id,),
        )
        authorized_total = cur.fetchone()[0]
    assert authorized_total <= 5000, f"authorised {authorized_total} against a 5000 limit"


def test_the_fee_counts_against_the_limit_not_just_the_amount(admin, merchant):
    """total_debit, not amount. A merchant whose fees were excluded could
    exceed the limit by the sum of them."""
    merchant_id, beneficiary_id = merchant
    _wallet(admin, merchant_id, available="1000000.00")
    first = _queue_payout(admin, merchant_id, beneficiary_id, "4000.00", fee="1000.00")
    second = _queue_payout(admin, merchant_id, beneficiary_id, "1000.00", fee="500.00")

    assert _authorize(admin, first, "5000")["outcome"] == "authorized"
    assert _authorize(admin, second, "5000")["outcome"] == "daily_limit"


# --- duplicate requests ------------------------------------------------------


def test_authorising_the_same_payout_twice_reserves_once(admin, merchant):
    """A retry, a duplicate worker tick, a client resending. The second
    call must find the payout no longer queued."""
    merchant_id, beneficiary_id = merchant
    available, reserved = _wallet(admin, merchant_id, available="10000.00")
    payout = _queue_payout(admin, merchant_id, beneficiary_id, "1000.00")

    first = _authorize(admin, payout)
    second = _authorize(admin, payout)

    assert first["outcome"] == "authorized"
    assert second["outcome"] == "not_queued"
    assert _balance(admin, available) == 9000
    assert _balance(admin, reserved) == 1000


def test_two_threads_authorising_one_payout_reserve_once(admin, merchant):
    """The same thing as a race rather than a sequence."""
    merchant_id, beneficiary_id = merchant
    available, reserved = _wallet(admin, merchant_id, available="10000.00")
    payout = _queue_payout(admin, merchant_id, beneficiary_id, "1000.00")

    results = _in_parallel([
        lambda c: _authorize(c, payout),
        lambda c: _authorize(c, payout),
    ])

    assert sorted(r["outcome"] for r in results) == ["authorized", "not_queued"]
    assert _balance(admin, available) == 9000
    assert _balance(admin, reserved) == 1000
    with admin.cursor() as cur:
        cur.execute("select count(*) from public.transactions where payout_id = %s", (payout,))
        assert cur.fetchone()[0] == 1, "a second transactions row means it reserved twice"


# --- a refusal leaves nothing behind -----------------------------------------


def test_a_refused_reservation_posts_no_ledger_entry(admin, merchant):
    merchant_id, beneficiary_id = merchant
    available, reserved = _wallet(admin, merchant_id, available="100.00")
    payout = _queue_payout(admin, merchant_id, beneficiary_id, "5000.00")

    assert _authorize(admin, payout)["outcome"] == "insufficient_funds"

    assert _balance(admin, available) == 100
    assert _balance(admin, reserved) == 0
    with admin.cursor() as cur:
        cur.execute(
            "select count(*) from public.ledger_entries where ledger_account_id in (%s, %s)",
            (available, reserved),
        )
        assert cur.fetchone()[0] == 0


def test_a_refused_reservation_leaves_no_orphan_transaction(admin, merchant):
    """The transactions row is created before the balance is checked, so
    a refusal must not leave it behind.

    An orphan here is not cosmetic: it is a transactions row in
    `processing`, of type `payout`, that no ledger entry will ever
    balance. It inflates the merchant's transaction history with a
    payment that never happened, and it is exactly the shape of row a
    reconciliation sweep picks up and tries to finish.
    """
    merchant_id, beneficiary_id = merchant
    _wallet(admin, merchant_id, available="100.00")
    payout = _queue_payout(admin, merchant_id, beneficiary_id, "5000.00")

    assert _authorize(admin, payout)["outcome"] == "insufficient_funds"

    with admin.cursor() as cur:
        cur.execute(
            "select id, status, type from public.transactions where payout_id = %s",
            (payout,),
        )
        leftovers = cur.fetchall()
    assert leftovers == [], f"refused payout left {len(leftovers)} transactions row(s): {leftovers}"


def test_a_payout_with_no_wallet_at_all_is_cancelled_cleanly(admin, merchant):
    """A merchant who has never funded. No accounts, so nothing to lock."""
    merchant_id, beneficiary_id = merchant
    payout = _queue_payout(admin, merchant_id, beneficiary_id, "1000.00")

    assert _authorize(admin, payout)["outcome"] == "insufficient_funds"

    with admin.cursor() as cur:
        cur.execute("select status, failure_code from public.payouts where id = %s", (payout,))
        assert cur.fetchone() == ("cancelled", "insufficient_funds")
        cur.execute("select count(*) from public.transactions where payout_id = %s", (payout,))
        assert cur.fetchone()[0] == 0


# --- Collections cannot be overdrawn by two paths at once --------------------


def _fund_payout_wallet(conn, merchant_id, collections_id, available_id, amount):
    """One funding: Collections down, payout_available up, under the same
    advisory lock the payout path takes."""
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select pg_advisory_xact_lock(hashtext('payout:' || %s))", (str(merchant_id),)
            )
            cur.execute(
                "insert into public.transactions "
                "(merchant_id, reference, type, method, gross_amount, fee_amount, net_amount, currency, status) "
                "values (%s, %s, 'adjustment', 'MOBILE_MONEY', %s, 0, %s, 'TZS', 'successful') returning id",
                (merchant_id, f"FUND-{uuid.uuid4().hex[:12]}", amount, amount),
            )
            transaction_id = cur.fetchone()[0]
            cur.execute(
                "select public.post_ledger_entries(jsonb_build_array("
                "  jsonb_build_object('transaction_id', %s::uuid, 'ledger_account_id', %s::uuid,"
                "    'direction', 'debit', 'amount', %s::numeric, 'currency', 'TZS',"
                "    'description', 'Funded payout wallet'),"
                "  jsonb_build_object('transaction_id', %s::uuid, 'ledger_account_id', %s::uuid,"
                "    'direction', 'credit', 'amount', %s::numeric, 'currency', 'TZS',"
                "    'description', 'Payout wallet funded')))",
                (transaction_id, collections_id, amount, transaction_id, available_id, amount),
            )
        conn.commit()
        return "funded"
    except psycopg2.Error as exc:
        conn.rollback()
        if "INSUFFICIENT_BALANCE" in str(exc):
            return "insufficient_funds"
        raise
    finally:
        conn.autocommit = True


def _spend_collections(conn, merchant_id, collections_id, payable_id, amount):
    """A legacy withdrawal: Collections down, disbursement_payable up."""
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select pg_advisory_xact_lock(hashtext('payout:' || %s))", (str(merchant_id),)
            )
            cur.execute(
                "insert into public.transactions "
                "(merchant_id, reference, type, method, gross_amount, fee_amount, net_amount, currency, status) "
                "values (%s, %s, 'disbursement', 'MOBILE_MONEY', %s, 0, %s, 'TZS', 'processing') returning id",
                (merchant_id, f"WD-{uuid.uuid4().hex[:12]}", amount, amount),
            )
            transaction_id = cur.fetchone()[0]
            cur.execute(
                "select public.post_ledger_entries(jsonb_build_array("
                "  jsonb_build_object('transaction_id', %s::uuid, 'ledger_account_id', %s::uuid,"
                "    'direction', 'debit', 'amount', %s::numeric, 'currency', 'TZS',"
                "    'description', 'Withdrawal'),"
                "  jsonb_build_object('transaction_id', %s::uuid, 'ledger_account_id', %s::uuid,"
                "    'direction', 'credit', 'amount', %s::numeric, 'currency', 'TZS',"
                "    'description', 'Withdrawal payable')))",
                (transaction_id, collections_id, amount, transaction_id, payable_id, amount),
            )
        conn.commit()
        return "withdrawn"
    except psycopg2.Error as exc:
        conn.rollback()
        if "INSUFFICIENT_BALANCE" in str(exc):
            return "insufficient_funds"
        raise
    finally:
        conn.autocommit = True


def test_funding_and_a_withdrawal_cannot_both_spend_one_collections_balance(admin, merchant):
    """The cross-path invariant, and the one most likely to be missed.

    Funding the payout wallet and taking a legacy withdrawal spend the
    same Collections balance through entirely different code. 6,000 held,
    each wanting 5,000: exactly one may succeed.
    """
    merchant_id, _beneficiary_id = merchant
    collections = _account(admin, merchant_id, "merchant_wallet", "liability", "6000.00")
    available, _reserved = _wallet(admin, merchant_id)
    payable = _account(admin, merchant_id, "disbursement_payable", "liability", "0")

    results = _in_parallel([
        lambda c: _fund_payout_wallet(c, merchant_id, collections, available, "5000.00"),
        lambda c: _spend_collections(c, merchant_id, collections, payable, "5000.00"),
    ])

    assert sorted(results) == ["insufficient_funds", "withdrawn"] or sorted(results) == [
        "funded",
        "insufficient_funds",
    ], results
    assert _balance(admin, collections) == 1000
    assert _balance(admin, collections) >= 0


def test_collections_never_goes_negative_under_mixed_contention(admin, merchant):
    """Four fundings and four withdrawals at once against a balance that
    covers five of the eight."""
    merchant_id, _beneficiary_id = merchant
    collections = _account(admin, merchant_id, "merchant_wallet", "liability", "5000.00")
    available, _reserved = _wallet(admin, merchant_id)
    payable = _account(admin, merchant_id, "disbursement_payable", "liability", "0")

    calls = []
    for _ in range(4):
        calls.append(lambda c: _fund_payout_wallet(c, merchant_id, collections, available, "1000.00"))
        calls.append(lambda c: _spend_collections(c, merchant_id, collections, payable, "1000.00"))

    results = _in_parallel(calls)

    assert _balance(admin, collections) == 0, results
    succeeded = [r for r in results if r != "insufficient_funds"]
    assert len(succeeded) == 5, results
    # Nothing was invented: what left Collections arrived somewhere.
    assert _balance(admin, available) + _balance(admin, payable) == 5000


def test_money_moved_into_the_payout_wallet_left_collections(admin, merchant):
    """A funding that credited the payout wallet without debiting
    Collections would be free money, and the balances would still look
    plausible read one at a time."""
    merchant_id, _beneficiary_id = merchant
    collections = _account(admin, merchant_id, "merchant_wallet", "liability", "4000.00")
    available, _reserved = _wallet(admin, merchant_id)

    _in_parallel([
        lambda c: _fund_payout_wallet(c, merchant_id, collections, available, "1000.00"),
        lambda c: _fund_payout_wallet(c, merchant_id, collections, available, "1000.00"),
        lambda c: _fund_payout_wallet(c, merchant_id, collections, available, "1000.00"),
    ])

    assert _balance(admin, collections) + _balance(admin, available) == 4000
