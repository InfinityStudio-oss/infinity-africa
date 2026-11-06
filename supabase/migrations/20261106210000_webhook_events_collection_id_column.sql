-- Supersedes the expression index added minutes earlier in
-- 20261106200000_webhook_events_collection_id_index.sql.
--
-- That index was correct but the planner would not reliably use it: the
-- Super Admin Collections page asks for 100 collection ids at a time, and
-- at that width Postgres costed 100 probes into a text expression index
-- above a single sequential pass, so cold runs still took five seconds and
-- the statement timeout still cancelled them.
--
-- A stored generated column is the honest fix. The link was always in the
-- payload; this lifts it into a real uuid column that Postgres maintains
-- on every write, so an ordinary compact btree serves the lookup and the
-- planner has no reason to avoid it. It also means the lookup no longer
-- has to select the payload blob merely to read one field out of it.
--
-- Safe to run on a live table: the column is derived, nothing writes it,
-- and the two events that legitimately have no collection (disbursement
-- success and failure - 247 rows at the time of writing) simply get null.

alter table public.webhook_events
  add column if not exists collection_id uuid
  generated always as ((payload ->> 'collection_id')::uuid) stored;

comment on column public.webhook_events.collection_id is
  'Derived from payload->>collection_id. Null for disbursement events, '
  'which belong to no collection. Generated - never write it directly.';

create index if not exists webhook_events_collection_id_idx
  on public.webhook_events (collection_id)
  where collection_id is not null;

-- No longer reachable: nothing filters on the JSON expression now.
drop index if exists public.webhook_events_payload_collection_id_idx;
