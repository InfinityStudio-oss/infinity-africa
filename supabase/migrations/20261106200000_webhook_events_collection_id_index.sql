-- The Super Admin Collections page looks up, for each payment on screen,
-- whether the merchant's own system was told about it. webhook_events has
-- no collection_id column, so that lookup filters on a JSON expression:
--
--     where payload->>'collection_id' in (...)
--
-- No ordinary index can serve that, so Postgres read every row of
-- webhook_events and extracted the JSON from each one. At ~69,000 rows and
-- growing by ~4,700 a day, a cold-cache run took over five seconds and the
-- statement timeout started cancelling it - which the page renders as
-- "No collections have been recorded yet", because a failed list degrades
-- to an empty one.
--
-- An expression index on the same expression turns that scan into a lookup.
-- The partial clause keeps it small: only disbursement events carry no
-- collection_id, and nothing ever searches for those.

create index if not exists webhook_events_payload_collection_id_idx
  on public.webhook_events ((payload ->> 'collection_id'))
  where payload ->> 'collection_id' is not null;

comment on index public.webhook_events_payload_collection_id_idx is
  'Serves the collection-id lookup behind the "Merchant notified" column; '
  'webhook_events has no collection_id column, only payload JSON.';
