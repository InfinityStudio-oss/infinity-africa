-- One replica at a time may run each background sweep.
--
-- The schedulers (webhook delivery, checkout and disbursement
-- reconciliation, collection expiry, referral recalculation) start in
-- app/main.py's lifespan, which means they start in *every* replica. With
-- one replica that is fine and has always been fine. With two it is not:
-- there is no coordination between them, so both would sweep the same
-- queue at the same time.
--
-- The sharpest consequence is webhook delivery. deliver_event reads a
-- pending row, POSTs it, and only then records the outcome - it does not
-- claim the row first. Two replicas would both read the same event as
-- pending and both POST it, so a merchant receives collection.success
-- twice. BillNasi holds no webhook signing secret and we do not know
-- whether their handler is idempotent, so a duplicate could activate a
-- customer's service twice. Reconciliation has the same shape: two
-- replicas asking Selcom about the same stuck withdrawal.
--
-- **Why a lease table and not a Postgres advisory lock.** The obvious
-- answer is pg_try_advisory_lock, and it does not work through
-- PostgREST. A session-scoped advisory lock would be taken on a pooled
-- connection and never released, leaking the lock until that connection
-- is recycled; a transaction-scoped one (pg_advisory_xact_lock) releases
-- the moment the RPC returns, which is long before the sweep it was
-- meant to guard has finished. A row with an expiry is the mechanism
-- that survives connection pooling.
--
-- How it works: a replica takes a lease by conditionally updating the
-- row only when the current lease has expired. Postgres serialises the
-- two updates, so the second one matches no rows and that replica skips
-- its turn. The holder releases the lease when the sweep finishes, and a
-- replica that dies mid-sweep simply stops renewing - the lease expires
-- on its own and the work resumes elsewhere. No cleanup job, no stuck
-- state.
--
-- Nothing here moves money or changes what a sweep does. It only decides
-- which process runs it.

create table if not exists public.scheduler_leases (
  -- The sweep this lease governs, e.g. 'webhook_delivery'.
  name text primary key,

  -- Which replica holds it. A random per-process id, useful only for
  -- reading the table during an incident - nothing branches on it.
  holder text not null default 'unclaimed',

  acquired_at timestamptz not null default now(),

  -- The lease is free once this passes. Set generously relative to how
  -- long a sweep can take: a webhook sweep is up to 50 sequential POSTs
  -- at an 8 second timeout, so the worst case is several minutes and a
  -- short expiry would let a second replica start while the first was
  -- still working - the exact thing this prevents.
  expires_at timestamptz not null default now(),

  updated_at timestamptz not null default now()
);

comment on table public.scheduler_leases is
  'Which replica may run each background sweep. Prevents two replicas delivering the same webhook twice. Not a financial record - a lost lease costs one skipped tick, never a wrong amount.';

-- Seeded already expired, so whichever replica asks first on the next
-- tick takes it. Inserting on demand instead would mean two replicas
-- racing to create the same row on first boot.
insert into public.scheduler_leases (name, expires_at)
values
  ('webhook_delivery', now()),
  ('checkout_reconciliation', now()),
  ('disbursement_reconciliation', now()),
  ('collection_expiry', now()),
  ('referral_recalculation', now())
on conflict (name) do nothing;

-- Same default-deny shape as every other table the backend owns: reached
-- only by the service role, never from a browser.
alter table public.scheduler_leases enable row level security;
