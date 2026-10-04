-- InfinityPay — pending production migrations, in order.
--
-- These four post-date the last confirmed "applied to production" check.
-- Every one is additive and idempotent (create table if not exists, add
-- column if not exists, create or replace function), so running this file
-- against a database that already has some or all of them is a no-op for
-- those parts. There is nothing destructive here: no drop, no truncate,
-- no delete, no type change on an existing column.
--
-- HOW TO RUN
--   Supabase dashboard -> SQL Editor -> New query -> paste this whole
--   file -> Run. It is wrapped in a single transaction, so it either all
--   applies or none of it does.
--
-- WHAT EACH ONE UNBLOCKS, if it is the missing one:
--   finalize_withdrawal_limits      withdrawal approval (limits function)
--   withdrawal_otp_challenges       the withdrawal OTP step — merchants
--                                   cannot withdraw at all without it
--   api_keys_public_key             API key creation — BillNasi cannot be
--                                   issued credentials without it
--   collection_failure_reason_codes resolving a FAILED collection, and the
--                                   failure_reason_code partners switch on
--
-- AFTER RUNNING, verify with the check at the bottom of this file.

begin;


-- ===========================================================
-- 20260922030000_finalize_withdrawal_limits.sql
-- ===========================================================

-- Concurrency guard for withdrawal daily/rolling limits and auto-withdrawal
-- eligibility — the same role 20260814140001_post_ledger_entries_balance_check.sql
-- plays for available balance.
--
-- The problem this solves: app/services/disbursements.py checks the rolling
-- 24h limits by reading disbursements, summing in Python, and only then
-- inserting the new row. Read-then-write across two PostgREST calls is not
-- atomic, so two withdrawals submitted at the same instant could each read a
-- total that didn't include the other and both pass a limit only one of them
-- should have. Available balance was already safe (post_ledger_entries locks
-- the wallet row and rejects a negative balance); the *limits* were not.
--
-- Shape: the row is still inserted by the application exactly as before — this
-- function runs immediately after, inside one transaction holding a
-- per-merchant advisory lock, and decides that row's fate:
--   'rejected' -> would breach the hard daily limit; the row is marked
--                 REJECTED here (so it stops counting toward everyone
--                 else's totals) and the caller raises.
--   'auto'     -> within every limit and automation is on; auto_approved is
--                 set and the caller proceeds to the provider.
--   'manual'   -> ineligible for automation for the recorded reason; stays
--                 PENDING_ADMIN_APPROVAL for a Super Admin, same as always.
--
-- Ordering matters: totals count only rows that were initiated strictly
-- BEFORE this one, ordered by (initiated_at, id) for a total order. Counting
-- every other in-flight row instead would make two simultaneous requests
-- block *each other* and reject both; this way the earlier one proceeds and
-- only the later one falls back, which is the intended behavior.
--
-- REJECTED/FAILED are excluded from both sums for the same reason the
-- application code excludes them: money that never moved doesn't count
-- against a cap about money moving.

create or replace function public.finalize_withdrawal_limits(
  p_disbursement_id uuid,
  p_daily_limit numeric,
  p_auto_max numeric,
  p_auto_daily_limit numeric,
  p_automation_enabled boolean
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row public.disbursements;
  v_requested_today numeric(14, 2);
  v_auto_today numeric(14, 2);
  v_reason text;
begin
  select * into v_row from public.disbursements where id = p_disbursement_id;
  if not found then
    raise exception 'DISBURSEMENT_NOT_FOUND: %', p_disbursement_id;
  end if;

  -- Serializes every concurrent withdrawal for this one merchant. Advisory
  -- (not a row lock on merchants) so it never contends with unrelated writes
  -- to the merchant row, and xact-scoped so it is always released when this
  -- function's transaction ends, including on the raise above.
  perform pg_advisory_xact_lock(hashtext('withdrawal:' || v_row.merchant_id::text));

  select coalesce(sum(amount), 0) into v_requested_today
  from public.disbursements
  where merchant_id = v_row.merchant_id
    and status not in ('REJECTED', 'FAILED')
    and initiated_at >= now() - interval '24 hours'
    and (initiated_at, id) < (v_row.initiated_at, v_row.id);

  if v_requested_today + v_row.amount > p_daily_limit then
    v_reason := format(
      'Rejected: would exceed the daily withdrawal limit of %s TZS (already requested in the last 24 hours: %s TZS).',
      p_daily_limit, v_requested_today
    );
    update public.disbursements
      set status = 'REJECTED',
          auto_decision_reason = v_reason
      where id = p_disbursement_id;
    return jsonb_build_object(
      'outcome', 'rejected',
      'reason', v_reason,
      'already_requested_today', v_requested_today
    );
  end if;

  if not p_automation_enabled then
    v_reason := 'Manual approval required: withdrawal automation is not enabled.';
  elsif v_row.amount > p_auto_max then
    v_reason := format(
      'Manual approval required: exceeds the %s TZS per-transaction limit for automatic processing.',
      p_auto_max
    );
  else
    select coalesce(sum(amount), 0) into v_auto_today
    from public.disbursements
    where merchant_id = v_row.merchant_id
      -- Already auto-approved, OR still undecided. The second half matters:
      -- these calls are serialized by the advisory lock, but NOT necessarily
      -- in (initiated_at, id) order — a later row's call can acquire the lock
      -- first, while the earlier row has been inserted but has not yet had
      -- auto_approved written. Counting only auto_approved there would let
      -- each of the two miss the other and both auto-process, exceeding this
      -- cap. An undecided earlier row is therefore counted conservatively:
      -- worst case the later one falls back to PENDING_ADMIN_APPROVAL, which
      -- is the safe direction. Outside that race every earlier row already
      -- has a reason set, so this changes nothing in the normal case.
      and (auto_approved or auto_decision_reason is null)
      and status not in ('REJECTED', 'FAILED')
      and initiated_at >= now() - interval '24 hours'
      and (initiated_at, id) < (v_row.initiated_at, v_row.id);

    if v_auto_today + v_row.amount > p_auto_daily_limit then
      v_reason := format(
        'Manual approval required: would exceed the %s TZS daily limit for automatic processing (already auto-processed today: %s TZS).',
        p_auto_daily_limit, v_auto_today
      );
    else
      v_reason := 'Eligible: verified merchant, no open high-risk alerts, within auto-withdrawal limits.';
      -- Set inside the lock. Concurrent calls that run after this one see
      -- auto_approved directly; one that runs before it (lock order is not
      -- (initiated_at, id) order) counts this row via the
      -- "auto_decision_reason is null" half of the predicate above.
      update public.disbursements
        set auto_approved = true,
            auto_decision_reason = v_reason
        where id = p_disbursement_id;
      return jsonb_build_object('outcome', 'auto', 'reason', v_reason);
    end if;
  end if;

  update public.disbursements
    set auto_decision_reason = v_reason
    where id = p_disbursement_id;
  return jsonb_build_object('outcome', 'manual', 'reason', v_reason);
end;
$$;

comment on function public.finalize_withdrawal_limits is
  'Atomically enforces the rolling 24h withdrawal limits and decides auto-withdrawal eligibility for a just-inserted disbursement, under a per-merchant advisory lock. Returns {outcome: rejected|auto|manual, reason}. See app/services/disbursements.py::execute_disbursement.';

revoke all on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean) from public;
revoke all on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean) from anon;
revoke all on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean) from authenticated;
grant execute on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean) to service_role;


-- ===========================================================
-- 20260924010000_withdrawal_otp_challenges.sql
-- ===========================================================

-- Email OTP verification for merchant withdrawals.
--
-- A withdrawal is no longer created when the merchant submits the form.
-- Instead a challenge row is written here, an OTP is emailed to the
-- merchant's own contact address, and only a successful verification
-- creates the disbursement (PENDING_ADMIN_APPROVAL, exactly as before).
--
-- Deliberately a separate table rather than an extra disbursements status:
-- an unverified request must not be visible to, approvable by, or payable
-- from any existing code path. A row here is inert — nothing reads it but
-- the verify endpoint — so a stale or abandoned challenge can never become
-- money movement. It also means no existing query, sweep, reconciliation
-- job or Super Admin view needs to learn a new status to stay correct.
--
-- The OTP itself is never stored. Only a SHA-256 hash is kept, the same
-- one-way treatment API keys get (app/auth/hashing.py).

create table if not exists public.merchant_withdrawal_otp_challenges (
  id uuid primary key default gen_random_uuid(),

  merchant_id uuid not null references public.merchants (id) on delete cascade,
  -- Who asked. A challenge is only ever verifiable by the user who created
  -- it, not merely by anyone holding that merchant's session.
  requested_by uuid not null references auth.users (id) on delete cascade,

  -- The withdrawal exactly as requested, replayed verbatim on verify. The
  -- merchant never re-sends it, so the amount and destination that were
  -- emailed are the ones that get created.
  withdrawal_payload jsonb not null,
  -- SHA-256 over the canonical payload. Binds the OTP to this specific
  -- amount/method/destination: editing any field after the code was sent
  -- produces a different hash and a different challenge, so a code issued
  -- for 1,000 TZS can never approve 1,000,000.
  payload_hash text not null,

  otp_hash text not null,

  expires_at timestamptz not null,
  attempts integer not null default 0,
  max_attempts integer not null default 5,
  -- Set once, on success. A second verify of the same challenge is a no-op
  -- rather than a second withdrawal.
  used_at timestamptz,
  -- Set when attempts are exhausted. Distinct from expiry so the failure
  -- can be told apart in an audit, though both look identical to the caller.
  locked_at timestamptz,

  resend_count integer not null default 0,
  last_sent_at timestamptz not null default now(),

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.merchant_withdrawal_otp_challenges is
  'Pending email-OTP verifications for merchant withdrawal requests. A row here is NOT a withdrawal: nothing is created, reserved, or payable until the OTP is verified, at which point a normal PENDING_ADMIN_APPROVAL disbursement is created. Rows are inert and safe to leave or purge.';
comment on column public.merchant_withdrawal_otp_challenges.otp_hash is
  'SHA-256 of the 6-digit code. The code itself is never stored, logged, or returned by any endpoint.';
comment on column public.merchant_withdrawal_otp_challenges.payload_hash is
  'SHA-256 of the canonical withdrawal payload, binding the code to one specific amount and destination.';

create index if not exists mw_otp_merchant_created_idx
  on public.merchant_withdrawal_otp_challenges (merchant_id, created_at desc);

-- Used by the resend-cooldown and active-challenge lookups, which only ever
-- care about rows that are still live.
create index if not exists mw_otp_active_idx
  on public.merchant_withdrawal_otp_challenges (merchant_id, expires_at)
  where used_at is null and locked_at is null;

-- For purging expired rows.
create index if not exists mw_otp_expires_idx
  on public.merchant_withdrawal_otp_challenges (expires_at);

alter table public.merchant_withdrawal_otp_challenges enable row level security;

-- No policies: this table is reached only by the service role through the
-- backend, never by an authenticated browser session. RLS on with zero
-- policies means anon/authenticated get nothing, which is the intent — the
-- OTP hash must not be readable by the very client being challenged.


-- ===========================================================
-- 20260926010000_api_keys_public_key.sql
-- ===========================================================

-- Public half of the API key pair.
--
-- Until now a key was a single secret string (`inf_{env}_...`), of which
-- only the SHA-256 hash was stored. Partners integrating InfinityPay into
-- their own platform need a non-secret identifier they can keep in config,
-- show in a dashboard, or quote in support — hence the pk/sk pair, matching
-- the convention those integrators already expect from other gateways.
--
-- public_key is stored in PLAINTEXT on purpose: it is not a credential.
-- It identifies a key/merchant/environment and must never authenticate a
-- request on its own — app/auth/dependencies.py only ever matches against
-- hashed_key, and rejects a `pk_` outright with a distinct error.
--
-- Nullable, deliberately. Keys issued before this migration have no public
-- half and must keep working exactly as they do now: authentication matches
-- hashed_key, which is unchanged, so every existing `inf_...` key is
-- unaffected. Backfilling one would invent an identifier the merchant has
-- never seen, so those rows simply show no public key until rotated.
--
-- This does NOT touch merchants.merchant_code — the permanent 27-series
-- Merchant ID is the account identity and is not a credential. An API key
-- is per-integration and revocable; the Merchant ID is neither.

alter table public.api_keys
  add column if not exists public_key text;

comment on column public.api_keys.public_key is
  'Plaintext public half of the key pair (pk_test_/pk_live_). Safe to display: identifies the key and its environment, never authorizes a request. Null for keys issued before the pair existed.';

-- Unique where present, so a public key always names exactly one row when
-- it is used as a lookup for display or support. Partial, because the
-- pre-existing keys legitimately share a null.
create unique index if not exists api_keys_public_key_key
  on public.api_keys (public_key)
  where public_key is not null;


-- ===========================================================
-- 20260927010000_collection_failure_reason_codes.sql
-- ===========================================================

-- Normalized failure reasons on collections.
--
-- `failure_reason` has always been free text, and several paths wrote the
-- provider's own `message` into it. That value reaches the merchant
-- ledger, the public payment page and the outbound webhook, which makes it
-- two problems at once: a partner cannot branch on prose that changes
-- whenever the provider rewords it, and provider text is not ours to
-- forward verbatim.
--
-- These columns add a stable code a partner can switch on, and a sentence
-- written for a merchant to read. See app/services/failure_reasons.py for
-- the vocabulary and for which mappings are evidenced rather than assumed.
--
-- Purely additive. `failure_reason` is left exactly as it is, including on
-- every historical row: nothing is rewritten or backfilled, so no existing
-- reader changes behaviour and no past transaction is reinterpreted.

alter table public.collections
  add column if not exists failure_reason_code text,
  add column if not exists failure_reason_message text,
  add column if not exists provider_status_code text,
  add column if not exists failed_at timestamptz,
  add column if not exists cancelled_at timestamptz;

comment on column public.collections.failure_reason_code is
  'Stable, machine-readable failure reason from app/services/failure_reasons.py (insufficient_balance, wrong_pin, user_cancelled, timeout, provider_unavailable, provider_declined, expired, reversed, unknown_provider_error). Safe to switch on; published in the API docs. Null while the collection has not failed.';
comment on column public.collections.failure_reason_message is
  'Merchant-facing sentence for failure_reason_code. Never the provider''s own message text.';
comment on column public.collections.provider_status_code is
  'The provider''s raw resultcode, kept for support and reconciliation. Internal: never returned by the public API and never shown to a merchant.';
comment on column public.collections.failed_at is
  'When the collection reached a terminal failed state.';
comment on column public.collections.cancelled_at is
  'When the customer cancelled, for the cancellation subset of failures.';

-- Partial: failed collections are the small minority, and this index only
-- exists to support "why did these fail" reporting.
create index if not exists collections_failure_reason_code_idx
  on public.collections (merchant_id, failure_reason_code)
  where failure_reason_code is not null;


commit;


-- VERIFY ---------------------------------------------------------------------
-- Run this separately after the commit above. Every row must say present.

select 'merchant_withdrawal_otp_challenges table' as checks,
       case when to_regclass('public.merchant_withdrawal_otp_challenges') is not null
            then 'present' else 'MISSING' end as status
union all
select 'api_keys.public_key column',
       case when exists (select 1 from information_schema.columns
                         where table_schema='public' and table_name='api_keys'
                           and column_name='public_key')
            then 'present' else 'MISSING' end
union all
select 'collections.failure_reason_code column',
       case when exists (select 1 from information_schema.columns
                         where table_schema='public' and table_name='collections'
                           and column_name='failure_reason_code')
            then 'present' else 'MISSING' end
union all
select 'collections.failed_at column',
       case when exists (select 1 from information_schema.columns
                         where table_schema='public' and table_name='collections'
                           and column_name='failed_at')
            then 'present' else 'MISSING' end;
