-- Make "did this person's payment go through?" answerable by phone.
--
-- collections.customer_phone has carried no index since the table was
-- created in August. Measured against production today, at 149,417
-- rows:
--
--   exact match  (customer_phone = '255762474101')   331 ms
--   suffix match (customer_phone ilike '%878545')    650 ms
--
-- Both are sequential scans of the whole table, and both are inside the
-- 8s statement timeout - so this is not a fix for something broken. It
-- is for what happens next: those numbers grow with the table, and this
-- query is about to go from "never run" to "run on every support call".
-- A number that is tolerable today at 150k rows is a timeout at 1M.
--
-- --- Why two indexes, and why NOT a (merchant_id, customer_phone) one
--
-- The obvious design is a composite btree on (merchant_id,
-- customer_phone), because the merchant dashboard filters both. It was
-- built and measured on a 20,000-row cluster, and the planner did not
-- use it: given merchant_id AND customer_phone it chose the phone-only
-- index and filtered merchant_id afterwards.
--
-- That is the right choice, and it generalises. A phone number is
-- already extremely selective - the busiest number in production today
-- matches 27 rows out of 149,417. Narrowing 27 rows by merchant_id is
-- free. Putting merchant_id ahead of the phone in an index key buys
-- nothing and costs an index entry on every insert and update of a
-- table that is being written to continuously by live payments.
--
-- So the standalone btree on customer_phone serves BOTH paths: the
-- merchant dashboard (plus a merchant_id filter) and Super Admin
-- (across all merchants).
--
-- A btree cannot serve a SUFFIX. `ilike '%878545'` is unanchored, so
-- no btree ordering applies, and an operator holding only the tail of a
-- number is a real and frequent case - it is how people read numbers
-- out over the phone. That is what pg_trgm is for: a GIN trigram index
-- can satisfy an unanchored ILIKE as long as the pattern has at least 3
-- consecutive literal characters. The search floor is 6 digits
-- (MIN_PARTIAL_DIGITS in app/services/phone_search.py), comfortably
-- above that, and the floor exists partly so this index can be used.
--
-- Every phone here begins "255", so that one trigram is in every row
-- and contributes nothing. The selectivity comes from the rest, which
-- is why the floor is 6 digits and not 3.
--
-- --- Why there is no begin/commit in this file
--
-- CREATE INDEX CONCURRENTLY cannot run inside a transaction block, and
-- every statement here uses it deliberately. A plain CREATE INDEX takes
-- a lock that blocks INSERTs for the duration of the build - on a table
-- that is receiving live customer payments, several seconds of blocked
-- writes is a few real payments failing. CONCURRENTLY trades a slower
-- build for not doing that.
--
-- The cost of that trade: if a CONCURRENTLY build fails partway, it
-- leaves an INVALID index behind that is never used and must be dropped
-- by hand before retrying. The verification query at the bottom of this
-- file reports exactly that, so a half-finished run is visible rather
-- than silent.

create extension if not exists pg_trgm;

-- Whole numbers, for both the merchant dashboard and Super Admin. A
-- phone is selective enough that the merchant_id filter rides along for
-- free - see above for why there is no composite index here.
create index concurrently if not exists collections_customer_phone_idx
  on public.collections (customer_phone);

-- The partial-number path, for both: `ilike '%474101'`, which the btree
-- above cannot answer. Verified in use: on 20,000 rows the planner
-- chose a Bitmap Index Scan on this index rather than a seq scan.
create index concurrently if not exists collections_customer_phone_trgm_idx
  on public.collections using gin (customer_phone gin_trgm_ops);

comment on index public.collections_customer_phone_trgm_idx is
  'Serves suffix phone search (ilike %NNNNNN) from app/services/phone_search.py. '
  'Requires >=3 literal characters in the pattern; the search enforces >=6.';

-- Verification. Expect two rows, both valid = true. A row with
-- valid = false is a CONCURRENTLY build that did not finish: drop that
-- index explicitly and re-run its statement.
select
  i.relname as index_name,
  idx.indisvalid as valid
from pg_class i
join pg_index idx on idx.indexrelid = i.oid
where i.relname in (
  'collections_customer_phone_idx',
  'collections_customer_phone_trgm_idx'
)
order by i.relname;
