-- The Command Center's six money figures, summed by Postgres instead of
-- by the API.
--
-- Why this exists. app/services/admin_overview.py reads every matching
-- row and adds it up in Python, a thousand rows per request. That was
-- sound when it was written and has quietly stopped being: there are now
-- 28,695 successful collection transactions and 28,710 revenue ledger
-- entries, and month-to-date already spans most of them. Adding lifetime
-- totals the same way would mean roughly sixty sequential PostgREST
-- requests for one dashboard load, growing with every payment the
-- platform ever takes.
--
-- PostgREST's own aggregate syntax (select=amount.sum()) would have
-- avoided a migration entirely, but this project has it disabled -
-- "PGRST123: Use of aggregate functions is not allowed" - and enabling
-- it is a platform-wide setting that is not this change's to make.
--
-- One call returns all six windows, so the daily, monthly and lifetime
-- figures cost one scan of each table rather than three.
--
-- WHAT THE NUMBERS MEAN. Deliberately the same definitions the cards
-- already used, extended backwards; this migration must not change what
-- any existing card reports:
--
--   collections - public.transactions where type = 'collection' and
--     status = 'successful', summing gross_amount. The transactions
--     table, NOT public.collections: one successful payment writes one
--     row in each, and adding both would double every figure. Pending,
--     failed, cancelled and rejected payments are excluded by the status
--     filter. There is no sandbox or test flag on this table, so there is
--     no test-data exclusion to apply - the existing cards have none
--     either.
--
--   revenue - credit entries on the single platform_revenue ledger
--     account (the one with merchant_id is null). Merchant wallets,
--     withdrawal amounts and customer funds live on other accounts and
--     are not touched here.
--
-- REFUNDS AND REVERSALS, PRESERVED AS FOUND. `direction = 'credit'`
-- means reversals are NOT subtracted: on 2026-10-31 nine debit entries
-- totalling TZS 3,728 sat on the revenue account (eight withdrawal fees
-- reversed when a payout failed in August, one platform fee reversed
-- when a provider reversed a collection on 2026-10-25) and none of them
-- reduced any card. Carried forward unchanged and on purpose, because
-- changing what revenue means is a business decision and not a side
-- effect of adding a column. It matters more for a lifetime figure than
-- a daily one, since the distortion only accumulates - raised with the
-- owner rather than silently corrected.
--
-- Amounts are returned as TEXT, not JSON numbers. A numeric(14,2) read
-- back through a JSON number arrives as a float, and these are money.
--
-- SECURITY. security definer so it can read the ledger regardless of the
-- caller's RLS, search_path pinned so it cannot be redirected by a
-- mutable path, and execute granted to service_role only - the same
-- shape every other privileged function here uses. It reads platform-wide
-- totals, so anon and authenticated must never reach it; the API route
-- that calls it is require_super_admin-gated. It writes nothing, and is
-- marked `stable` to say so.
--
-- ROLLBACK: drop the function. app/services/admin_overview.py falls back
-- to its previous per-row summing for the daily and monthly figures and
-- reports the lifetime ones as unavailable, so nothing breaks and no card
-- shows a wrong number. Dropping it is safe at any time.

create or replace function public.admin_overview_money(
  p_day_start timestamptz,
  p_month_start timestamptz
)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  with revenue_account as (
    select id
    from public.ledger_accounts
    where purpose = 'platform_revenue'
      and merchant_id is null
    limit 1
  ),
  collection_totals as (
    select
      coalesce(sum(gross_amount) filter (where created_at >= p_day_start), 0) as today,
      coalesce(sum(gross_amount) filter (where created_at >= p_month_start), 0) as this_month,
      coalesce(sum(gross_amount), 0) as lifetime
    from public.transactions
    where type = 'collection'
      and status = 'successful'
  ),
  revenue_totals as (
    select
      coalesce(sum(amount) filter (where created_at >= p_day_start), 0) as today,
      coalesce(sum(amount) filter (where created_at >= p_month_start), 0) as this_month,
      coalesce(sum(amount), 0) as lifetime
    from public.ledger_entries
    where ledger_account_id = (select id from revenue_account)
      and direction = 'credit'
  )
  select jsonb_build_object(
    'collections_today', collection_totals.today::text,
    'collections_this_month', collection_totals.this_month::text,
    'collections_total', collection_totals.lifetime::text,
    'revenue_today', revenue_totals.today::text,
    'revenue_this_month', revenue_totals.this_month::text,
    'revenue_total', revenue_totals.lifetime::text
  )
  from collection_totals, revenue_totals;
$$;

comment on function public.admin_overview_money(timestamptz, timestamptz) is
  'The Command Center money figures for three windows at once: since p_day_start, since p_month_start, and all time. Collections are successful collection transactions by gross_amount; revenue is credits on the platform_revenue ledger account, with reversals deliberately not subtracted (see this migration header). Amounts are text to keep two decimal places out of a float. Read-only.';

revoke all on function public.admin_overview_money(timestamptz, timestamptz) from public;
revoke all on function public.admin_overview_money(timestamptz, timestamptz) from anon;
revoke all on function public.admin_overview_money(timestamptz, timestamptz) from authenticated;
grant execute on function public.admin_overview_money(timestamptz, timestamptz) to service_role;
