-- Make "did this person's payment go through?" answerable by phone.
--
-- collections.customer_phone has carried no index since the table was
-- created in August. Measured against production today, at 149,417
-- rows:
--
--   exact match  (customer_phone = '255755123456')   331 ms
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
-- --- Why this does NOT use CREATE INDEX CONCURRENTLY
--
-- CONCURRENTLY is the usual advice for a table taking live writes,
-- because a plain CREATE INDEX blocks INSERTs while it builds. It was
-- the first version of this migration, and it cannot be applied here:
-- CONCURRENTLY cannot run inside a transaction block, and the Supabase
-- SQL editor - the only way migrations reach this database - wraps
-- whatever it is given in one. It fails with 25001 however the
-- statements are split up.
--
-- So this blocks writes, and the only honest question is for how long
-- against how much traffic. Measured, not assumed:
--
--   btree build, 149,417 rows ........ 1.9 s
--   GIN trigram build, same rows ..... 0.8 s
--   collections arriving ............. ~4 per minute (0.07/sec)
--   statement timeout ................ 8 s
--
-- A payment arriving mid-build waits for the lock; it fails only if it
-- waits past the statement timeout, which is 8s against a sub-3s
-- build. At four payments a minute that is about one payment delayed
-- by under three seconds.
--
-- If this table grows by an order of magnitude, re-measure before
-- re-running anything like it: the build time grows with the row
-- count and the 8s timeout does not.
--
-- No explicit begin/commit. The Supabase SQL editor already wraps what
-- you paste in a transaction, so adding another produced a harmless but
-- confusing "there is no transaction in progress" warning on COMMIT.
-- Left out, this is also better anywhere that does NOT wrap: each
-- statement then commits on its own and releases its lock sooner.

create extension if not exists pg_trgm;

-- Whole numbers, for both the merchant dashboard and Super Admin. A
-- phone is selective enough that the merchant_id filter rides along for
-- free - see above for why there is no composite index here.
create index if not exists collections_customer_phone_idx
  on public.collections (customer_phone);

-- The partial-number path, for both: `ilike '%123456'`, which the btree
-- above cannot answer. Verified in use: on a comparable table the
-- planner chose a Bitmap Index Scan on this index over a seq scan.
create index if not exists collections_customer_phone_trgm_idx
  on public.collections using gin (customer_phone gin_trgm_ops);

comment on index public.collections_customer_phone_trgm_idx is
  'Serves suffix phone search (ilike %NNNNNN) from app/services/phone_search.py. '
  'Requires >=3 literal characters in the pattern; the search enforces >=6.';

