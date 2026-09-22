# Production Migration Runbook — Withdrawal Automation (2026-09-22)

Covers the three migrations introduced by commits `435286a` and `dacaed3`.

> **Deploy order is not optional.** `execute_disbursement` calls
> `finalize_withdrawal_limits()` on **every** withdrawal — manual ones
> included, not just automated ones — and writes `auto_decision_reason` on
> every row. Deploying the API before step 3 breaks **all** withdrawals, not
> just automation. Migrations first, API second.

> **Do not set `AUTO_WITHDRAWALS_ENABLED=true` until the advisory lock has
> been proven against a real PostgreSQL instance.** The unit tests run
> against an in-memory fake that is single-threaded — they verify the
> decision rules but cannot prove that `pg_advisory_xact_lock` actually
> serializes anything. Until the "Proving the advisory lock" section at the
> bottom of this runbook has been completed successfully on staging, launch
> with manual approval:
>
> ```
> AUTO_WITHDRAWALS_ENABLED=false
> REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS=true
> ```
>
> These are the code defaults, so no Railway change is needed to get them.
> Applying the migrations does **not** enable automation — with these flags
> the function only records a reason string and returns `manual`.
>
> `AUTO_WITHDRAWAL_MAX_AMOUNT_TZS` (500,000) and
> `AUTO_WITHDRAWAL_DAILY_LIMIT_TZS` (1,000,000) are conservative
> placeholders, not business-derived figures. Treat them as deliberate
> business decisions requiring sign-off before automation is turned on, not
> as values to inherit.

All three are additive: they add two columns, one column, one partial index
and one function. Nothing is dropped, truncated, renamed or backfilled with
new values, and no merchant, wallet, ledger or existing disbursement row is
modified. All three are re-runnable (`add column if not exists`,
`create index if not exists`, `create or replace function`).

`add column ... not null default false` on `disbursements.auto_approved` is a
metadata-only operation on PostgreSQL 11+ — no table rewrite, no lock held
for the size of the table. Existing rows read back as `false`, which is
correct: none of them were auto-approved.

---

## Order

### 1. Apply the migrations, in this order

```
supabase/migrations/20260922010000_disbursements_auto_withdrawal.sql
supabase/migrations/20260922020000_onboarding_notes.sql
supabase/migrations/20260922030000_finalize_withdrawal_limits.sql
```

`20260922030000` depends on the columns added by `20260922010000` — it reads
and writes `auto_approved` and `auto_decision_reason`. Applying it first will
fail (cleanly, before creating anything).

### 2. Verify the database objects exist

Run all of these **before** deploying the API. Each one states the expected
result; anything else means stop and investigate.

```sql
-- (a) Both new disbursement columns exist, with the right types/defaults.
--     Expect exactly 2 rows: auto_approved (boolean, not null, default false)
--     and auto_decision_reason (text, nullable).
select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public'
  and table_name = 'disbursements'
  and column_name in ('auto_approved', 'auto_decision_reason')
order by column_name;

-- (b) The onboarding notes column exists. Expect 1 row: notes, text, YES.
select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public'
  and table_name = 'onboarding_submissions'
  and column_name = 'notes';

-- (c) The partial index exists. Expect 1 row.
select indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and tablename = 'disbursements'
  and indexname = 'disbursements_auto_approved_idx';

-- (d) The function exists with the expected signature. Expect 1 row:
--     args "uuid, numeric, numeric, numeric, boolean", returns "jsonb".
select p.proname,
       pg_get_function_arguments(p.oid) as args,
       pg_get_function_result(p.oid)    as returns,
       p.prosecdef                      as security_definer
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname = 'finalize_withdrawal_limits';

-- (e) Only service_role may execute it. Expect no rows.
select grantee, privilege_type
from information_schema.role_routine_grants
where routine_schema = 'public'
  and routine_name = 'finalize_withdrawal_limits'
  and grantee in ('anon', 'authenticated', 'PUBLIC');
```

### 3. Confirm existing disbursement data is undamaged

```sql
-- (f) Row count and money totals must be identical to the pre-migration
--     values. Record these BEFORE applying, and compare after.
select count(*)                       as total_rows,
       sum(amount)                     as total_amount,
       count(*) filter (where status = 'SUCCESS')   as successful,
       count(*) filter (where status = 'PENDING_ADMIN_APPROVAL') as pending
from public.disbursements;

-- (g) Every pre-existing row must have been defaulted, not decided:
--     auto_approved false everywhere, auto_decision_reason null everywhere.
--     Expect 0.
select count(*)
from public.disbursements
where auto_approved is true
   or auto_decision_reason is not null;

-- (h) No status was altered by the migration. Compare to a pre-migration
--     snapshot of the same query.
select status, count(*) from public.disbursements group by status order by status;
```

### 4. Deploy the backend/API (Railway)

Only after (a)–(h) pass.

### 5. Deploy the frontend (Vercel) if it changed

The frontend reads `auto_approved` / `auto_decision_reason` in the Super
Admin withdrawals table. It tolerates their absence, so frontend order is not
critical — but deploy it after the API, not before.

### 6. Production smoke tests

With the recommended first-real-users settings (automation **off**):

1. A merchant submits a withdrawal → lands `PENDING_ADMIN_APPROVAL`.
2. `auto_approved` is `false` and `auto_decision_reason` reads
   *"Manual approval required: withdrawal automation is not enabled."*
3. No Selcom call was made at request time (check the provider logs).
4. Super Admin approves → payout runs, wallet debits once, ledger balances.
5. Super Admin rejects a different one → no debit, wallet unchanged.
6. The Super Admin withdrawals queue renders the new columns without error.

---

## Rollback

The API can be rolled back to a build before `435286a` at any time; the added
columns and function are simply unused by it. **Do not drop the columns to
roll back** — a newer API pod still serving traffic would start failing
immediately. Leave them in place.

To disable the function's effect without a migration, no action is needed:
with `AUTO_WITHDRAWALS_ENABLED=false` it only ever records a reason string
and returns `manual`.

---

## Proving the advisory lock (staging, not CI)

The unit tests in `apps/api/tests/test_withdrawal_automation.py` run against
an in-memory fake client, which is single-threaded. They verify the
*decision rules* — including the `(initiated_at, id)` strict-ordering tiebreak
and the "count earlier undecided rows" predicate — but they **cannot** prove
`pg_advisory_xact_lock` actually serializes anything. That needs a real
Postgres.

Run this against **staging** (never production) in two `psql` sessions
against the same database. It proves session B blocks on session A's lock
rather than reading a stale total.

```sql
-- Session A
begin;
select pg_advisory_xact_lock(hashtext('withdrawal:' || '<merchant-uuid>'));
-- Hold here. Do not commit yet.

-- Session B (a second psql, at the same time)
begin;
select now();
select pg_advisory_xact_lock(hashtext('withdrawal:' || '<merchant-uuid>'));
-- This BLOCKS. It must not return while session A holds the lock.
select now();   -- the gap between the two now() values is the wait
commit;

-- Back in session A
commit;         -- session B now unblocks and proceeds
```

Then, still on staging, the end-to-end version: seed a merchant whose
`AUTO_WITHDRAWAL_DAILY_LIMIT_TZS` leaves room for exactly one of two
withdrawals, fire both concurrently (e.g. two `curl` calls backgrounded with
`&`, each with its own `Idempotency-Key`), and confirm:

- exactly one row comes back `auto_approved = true`;
- the other is `PENDING_ADMIN_APPROVAL` with a
  *"would exceed ... daily limit for automatic processing"* reason;
- the wallet was debited exactly once;
- `select sum(amount) from disbursements where auto_approved and status not in ('REJECTED','FAILED')`
  is within `AUTO_WITHDRAWAL_DAILY_LIMIT_TZS`.

Repeat with the hard cap (`DAILY_WITHDRAWAL_LIMIT_TZS`) to confirm the later
request is rejected outright and marked `REJECTED` rather than left pending.
