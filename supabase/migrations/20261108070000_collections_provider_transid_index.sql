-- Every Selcom Checkout callback asks "which payment is this about?" by
-- provider_transid (app/services/checkout_reconciliation.py::
-- find_collection_by_transid). Nothing indexed that column, so each
-- callback scanned the whole of collections - 80,000 rows and growing by
-- several thousand a week.
--
-- It worked until it didn't. The scan is fine at low load and tips over
-- the statement timeout under it, which is why it surfaced as an
-- intermittent 500 rather than a broken endpoint: 18 crashed callbacks
-- in 48 hours out of roughly a thousand.
--
-- Nothing was lost - the reconciliation sweep resolved every one of those
-- payments, between 2 seconds and 4 minutes later - but a customer waited
-- minutes for service that should have switched on in seconds, and the
-- scan gets slower with every payment the platform takes.
--
-- Partial, because a collection with no transid can never be the answer
-- to this lookup, and leaving those rows out keeps the index to the rows
-- that are actually searched.
create index if not exists collections_provider_transid_idx
  on public.collections (provider_transid)
  where provider_transid is not null;
