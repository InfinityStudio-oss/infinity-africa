-- Pin search_path on the three trigger functions that do not set it.
--
-- Raised by Supabase's own linter (function_search_path_mutable) and
-- re-confirmed by a static read of this migrations directory on
-- 2026-10-20: of the 8 functions defined here, 5 already pin search_path
-- and these 3 do not.
--
--   public.set_updated_at()
--   public.forbid_mutation()
--   public.enforce_ledger_balance()
--
-- Why it matters. A function without a pinned search_path resolves
-- unqualified names using whatever search_path the *caller* happens to
-- have. Anyone able to create an object in a schema that sits earlier on
-- that path can shadow a name the function body relies on and have their
-- own code run in its place.
--
-- The exposure here is smaller than the linter's warning suggests, and it
-- is worth being precise rather than alarmed: all three are SECURITY
-- INVOKER, so a hijack would execute with the caller's own rights, not
-- with the owner's. None of the 5 SECURITY DEFINER functions - the ones
-- where a hijack *would* escalate - is unpinned. So this is hardening and
-- linter hygiene, not an open hole.
--
-- It is still worth closing, and enforce_ledger_balance is the reason:
-- it is the deferred constraint that proves debits = credits for every
-- transaction. A function that can be made to lie about that is a
-- financial-integrity problem, not a style problem.
--
-- Why ALTER rather than CREATE OR REPLACE. ALTER FUNCTION ... SET
-- search_path attaches the setting and does not touch the body, so there
-- is no way for this migration to change what any of these functions
-- does. Re-creating them would mean restating three bodies - including
-- the ledger balance check - and a typo there is a far bigger risk than
-- the thing being fixed. It is catalog-only: no table is read, locked or
-- rewritten, so it is safe on a live database and runs in milliseconds.
--
-- pg_catalog first, then public, then pg_temp. pg_temp is pinned last on
-- purpose: left implicit it is searched *first*, which is itself the
-- shadowing vector, since any session can create a temp object.
--
-- Safe to re-run: ALTER ... SET is idempotent.
--
-- Verified safe for these three bodies specifically - every name each one
-- resolves is either a plpgsql variable, a pg_catalog builtin, or already
-- schema-qualified:
--   set_updated_at         -> now() [pg_catalog], new.updated_at [record]
--   forbid_mutation        -> tg_table_name [plpgsql]
--   enforce_ledger_balance -> public.ledger_entries [qualified],
--                             sum/coalesce [pg_catalog]

alter function public.set_updated_at()
  set search_path = pg_catalog, public, pg_temp;

alter function public.forbid_mutation()
  set search_path = pg_catalog, public, pg_temp;

alter function public.enforce_ledger_balance()
  set search_path = pg_catalog, public, pg_temp;

-- Post-apply check. Expect 8 of 8 functions pinned, and 0 rows from the
-- second query:
--
--   select p.proname,
--          p.prosecdef as security_definer,
--          p.proconfig as settings
--     from pg_proc p
--     join pg_namespace n on n.oid = p.pronamespace
--    where n.nspname = 'public'
--      and p.prokind = 'f'
--    order by p.proname;
--
--   select p.proname
--     from pg_proc p
--     join pg_namespace n on n.oid = p.pronamespace
--    where n.nspname = 'public'
--      and p.prokind = 'f'
--      and (p.proconfig is null
--           or not exists (select 1 from unnest(p.proconfig) c
--                           where c like 'search\_path=%'));
