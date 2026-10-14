-- Composite indexes for the "this merchant's rows, newest first" query
-- that every portal list page makes.
--
-- Every index on these tables today is single-column. So a query like
--
--     where merchant_id = $1 order by created_at desc limit 50
--
-- can use the merchant_id index to find that merchant's rows, but then
-- has to sort all of them to honour the ordering before returning the
-- first fifty. A composite on (merchant_id, created_at desc) is already
-- in that order, so Postgres walks it and stops after fifty. No sort.
--
-- The pattern is not new here: api_request_logs has carried
-- (merchant_id, created_at desc) since it was added. It simply was not
-- applied to the tables that grow fastest.
--
-- **Honest about the size of the win today.** The largest of these
-- tables holds 8,067 rows, and sorting a single merchant's few hundred
-- rows is sub-millisecond — Postgres may reasonably ignore some of these
-- indexes at this scale. They are written for where this is heading: a
-- partner integration went live this month with 400+ users, and the cost
-- of adding an index to a 4,000-row table is nothing while the cost of
-- discovering you needed one on a 400,000-row table is a slow portal for
-- the merchants who use you most.
--
-- Deliberately NOT indexed: invoices (7 rows), disbursements (65) and
-- payment_links (120). An index on a table that small is write overhead
-- buying nothing, and a list of indexes nobody can justify is how a
-- schema stops being reviewable.
--
-- No `concurrently`, because Supabase runs each migration in a
-- transaction and CREATE INDEX CONCURRENTLY cannot run inside one. These
-- take a lock that blocks writes — but not reads — for as long as the
-- build takes, which at four to eight thousand rows is milliseconds.
-- Revisit that if these tables reach the millions.
--
-- Nothing here changes a row, a constraint or a financial rule. Indexes
-- affect how Postgres finds data, never what it finds.

-- --------------------------------------------------------------------
-- transactions — the merchant transactions list, and its status filter
-- --------------------------------------------------------------------

create index if not exists transactions_merchant_created_idx
  on public.transactions (merchant_id, created_at desc);

create index if not exists transactions_merchant_status_created_idx
  on public.transactions (merchant_id, status, created_at desc);

-- --------------------------------------------------------------------
-- collections — the busiest read path on the platform, queried this way
-- from seven different services
-- --------------------------------------------------------------------

create index if not exists collections_merchant_created_idx
  on public.collections (merchant_id, created_at desc);

create index if not exists collections_merchant_status_created_idx
  on public.collections (merchant_id, status, created_at desc);

-- --------------------------------------------------------------------
-- ledger_entries — the wallet ledger reads a whole account in date
-- order to replay running balances
-- --------------------------------------------------------------------
--
-- Ascending, not descending: app/services/ledger.py::_wallet_ledger_entries
-- walks oldest-first to accumulate the balance, then reverses for
-- display. An index in the direction the query actually scans is the one
-- that removes the sort.

create index if not exists ledger_entries_account_created_idx
  on public.ledger_entries (ledger_account_id, created_at);

-- --------------------------------------------------------------------
-- webhook_events — merchant-facing delivery history
-- --------------------------------------------------------------------

create index if not exists webhook_events_merchant_created_idx
  on public.webhook_events (merchant_id, created_at desc);

-- --------------------------------------------------------------------
-- checkout_orders — grows one-for-one with collections
-- --------------------------------------------------------------------

create index if not exists checkout_orders_merchant_created_idx
  on public.checkout_orders (merchant_id, created_at desc);

-- --------------------------------------------------------------------
-- audit_logs — append-only and never pruned, so it outgrows everything
-- --------------------------------------------------------------------
--
-- There is already an index on (created_at) for the unfiltered admin
-- view. This one is for the far more common case of reading one
-- merchant's history.

create index if not exists audit_logs_merchant_created_idx
  on public.audit_logs (merchant_id, created_at desc);
