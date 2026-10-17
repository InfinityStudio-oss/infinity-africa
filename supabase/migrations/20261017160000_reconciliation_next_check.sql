-- Per-transaction polling, separate from how often the sweep runs.
--
-- Both reconciliation sweeps selected every row in a pending state and
-- asked Selcom about each one, every tick. That tied the sweep interval
-- to the provider load: halving the interval doubled the questions asked
-- about every pending payment, including the ones that were never going
-- to resolve.
--
-- Measured on 4,024 real collections from 10-17 October:
--
--   flat 120s         15,482 provider calls    3.8 per collection
--   flat  30s         57,529                  14.3   (the interval then)
--   flat  10s        175,706                  43.7
--   tiered 10->300s   50,214                  12.5
--
-- 58% of collections resolve within two minutes; the p90 is 1,909
-- seconds, which is an abandoned push waiting out
-- collection_push_expiry_minutes (30). A flat ten second sweep spends
-- most of its budget asking about those, roughly 190 times each.
--
-- next_check_at separates the two dials, so the sweep can run every ten
-- seconds and still ask about a payment only when it is actually due.
--
-- Nothing here touches money. Both columns are scheduling state, read
-- only by the sweeps. No financial path reads either one, and neither is
-- ever a reason to resolve, resubmit or release anything.

-- Why this is three statements and not one ------------------------------
--
-- The obvious form is `add column next_check_at timestamptz not null
-- default now()`. Do not use it. `now()` is volatile, so Postgres cannot
-- store it as a catalog-level default and must evaluate it per row -
-- which rewrites the whole table under an ACCESS EXCLUSIVE lock. On
-- collections that is 6,964 rows today and growing by thousands a week,
-- on a table that is being inserted into while customers are paying.
--
-- Adding the column nullable is catalog-only and instant. Setting the
-- default afterwards is also catalog-only, and applies to every row
-- inserted from that moment on. Only the rows the sweeps can actually
-- see need a value backfilled, and there are none of those right now.
--
-- Resolved rows keep NULL forever. The sweeps never look at them, so
-- there is nothing to gain from writing 6,964 timestamps that will never
-- be read.

-- Collections ------------------------------------------------------------

alter table public.collections
  add column if not exists next_check_at timestamptz;

alter table public.collections
  alter column next_check_at set default now();

-- Every collection the sweep could pick up. Empty at the time of
-- writing; written anyway because this file may be run later, and a
-- `processing` row with a NULL here would never be swept again - it
-- would sit unresolved and look exactly like "the sweep found no work".
update public.collections
set next_check_at = now()
where next_check_at is null
  and status = 'processing';

comment on column public.collections.next_check_at is
  'When the reconciliation sweep may next ask Selcom about this collection. Scheduling only; no financial path reads it. NULL on rows that have already resolved.';

-- The sweep's whole query: pending, linked to an order, and due. Partial
-- so it covers only the rows that can ever be swept - a few dozen at
-- peak - rather than the entire collections history.
create index if not exists collections_reconcile_due_idx
  on public.collections (next_check_at)
  where status = 'processing' and checkout_order_id is not null;

-- Disbursements ----------------------------------------------------------
--
-- Same shape. This sweep has far less to do - zero rows in a
-- reconcilable state at the time of writing, and none in the last 200
-- payouts - so this is about keeping the two sweeps identical rather than
-- about load.

alter table public.disbursements
  add column if not exists next_check_at timestamptz;

alter table public.disbursements
  alter column next_check_at set default now();

update public.disbursements
set next_check_at = now()
where next_check_at is null
  and status in ('PROCESSING', 'NEEDS_RECONCILIATION');

comment on column public.disbursements.next_check_at is
  'When the reconciliation sweep may next ask Selcom about this payout. Scheduling only; never a reason to resubmit a payout or release a reservation.';

create index if not exists disbursements_reconcile_due_idx
  on public.disbursements (next_check_at)
  where status in ('PROCESSING', 'NEEDS_RECONCILIATION');
