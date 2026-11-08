-- The Super Admin Collections list orders by created_at across every
-- merchant, newest first. collections has (merchant_id, created_at desc)
-- but nothing on created_at alone, and a merchant-leading composite
-- cannot serve an ordering that has no merchant to lead with - so
-- Postgres sorted all 85,000 rows to hand back the newest 100, on every
-- page load.
--
-- Measured against production, that sort was ~178ms of the statement's
-- server time. Not fatal alone, but this endpoint was failing with
-- APIError 57014, a statement timeout, and everything it does not have
-- to do is budget it gets back. With the index the ORDER BY ... LIMIT
-- walks 100 index entries instead of sorting 85,000 rows, and it stops
-- getting slower as the table grows - which the sort does, by about
-- 4,000 rows a day.
--
-- desc to match the query. Postgres can read a btree backwards, so a
-- plain index would also work; declaring the direction keeps the intent
-- legible next to the query it serves.
create index if not exists collections_created_at_idx
  on public.collections (created_at desc);
