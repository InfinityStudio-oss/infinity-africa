-- Super Admin control over withdrawal automation, stored in the database.
--
-- Until now the three switches that decide whether a merchant's withdrawal
-- can reach Selcom without a human were environment variables only
-- (Settings.require_admin_approval_for_all_withdrawals,
-- auto_withdrawals_enabled, auto_withdrawal_max_amount_tzs,
-- auto_withdrawal_daily_limit_tzs). Changing any of them meant a Railway
-- edit and a restart, which is the wrong shape for a control an operator
-- needs to be able to turn OFF in seconds during an incident.
--
-- This adds one platform-wide policy row the Super Admin portal reads and
-- writes, and makes the payout decision read it. The environment variables
-- do NOT go away and are not duplicated: they become the deployment-level
-- gate and the hard ceilings above the policy. Exact precedence, enforced
-- in app/services/withdrawal_policy.py and nowhere else:
--
--   1. REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS=true (the DEFAULT) is an
--      emergency manual-only override. While it is true, no policy row can
--      enable automation, and the portal says so instead of offering a
--      switch that would do nothing.
--   2. AUTO_WITHDRAWALS_ENABLED=true is the deployment's permission for
--      automation to exist at all. Both env flags must be set before the
--      portal switch has any effect - the existing belt-and-suspenders
--      pair, unchanged.
--   3. This policy row's `enabled` is the routine ON/OFF a Super Admin
--      operates, within that permission.
--   4. AUTO_WITHDRAWAL_MAX_AMOUNT_TZS and AUTO_WITHDRAWAL_DAILY_LIMIT_TZS
--      become HARD CEILINGS: the effective limit is min(policy, env), so a
--      policy row can only ever be more conservative than the deployment
--      allows, never less.
--   5. Every existing check still applies to every withdrawal, automatic
--      or manual: merchant verification and active status, OTP, open
--      high-risk fraud alerts, available balance, the min/max per-request
--      amounts, the hard rolling 24h limit, and destination validation.
--
-- A missing, malformed or unreadable policy row means manual approval.
-- There is no state of this table that can turn automation on by itself.
--
-- ROLLBACK. Nothing here needs to be reverted to restore manual approval,
-- and reverting it must never be the first move during an incident:
--   * Fastest (seconds, no deploy): turn the switch OFF in the portal, or
--     update public.withdrawal_automation_policy set enabled = false.
--   * Deployment-level: set REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS=true
--     (or AUTO_WITHDRAWALS_ENABLED=false) in Railway. Overrides the row.
--   * Schema: the 5-argument finalize_withdrawal_limits below is preserved
--     as a wrapper precisely so an older API build keeps working, so this
--     migration can be applied before the API is deployed and left in
--     place if the API is rolled back. If the function itself must be
--     reverted, restore the body from
--     20260922030000_finalize_withdrawal_limits.sql and drop the
--     6-argument overload. Dropping the table or the new disbursements
--     columns is NOT part of any rollback: they hold the audit record of
--     which policy decided each payout.
-- No financial record, reservation or audit row is deleted by any of this.

-- --------------------------------------------------------------------------
-- 1. The policy row
-- --------------------------------------------------------------------------

create table if not exists public.withdrawal_automation_policy (
  -- One row, forever. `check (id)` with a boolean primary key is the
  -- cheapest way Postgres can refuse a second one: there is exactly one
  -- value that satisfies both the check and the uniqueness, so a stray
  -- insert fails rather than creating a second policy nobody is reading.
  id boolean primary key default true check (id),

  -- The routine Super Admin ON/OFF. False here means every withdrawal
  -- waits for a human, which is the behaviour this platform has always had
  -- and the state this table is created in.
  enabled boolean not null default false,

  -- Per-request ceiling, INCLUSIVE: amount <= max_amount_tzs may process
  -- automatically, amount > max_amount_tzs goes to manual approval. The
  -- inclusive boundary is not new - finalize_withdrawal_limits has always
  -- compared with `>` - it is now stated in the schema because the portal
  -- labels it inclusive and shows a worked example.
  max_amount_tzs numeric(14, 2) not null default 500000.00 check (max_amount_tzs >= 0),

  -- Rolling 24-hour total this platform will auto-process for ONE merchant.
  -- A real rolling window measured from now() at decision time, never a
  -- calendar-day reset - see the sum in finalize_withdrawal_limits.
  merchant_rolling_24h_limit_tzs numeric(14, 2) not null default 1000000.00
    check (merchant_rolling_24h_limit_tzs >= 0),

  -- Optimistic concurrency. A writer sends the version it read; the update
  -- only lands if that is still current, so two admins editing the same
  -- policy cannot silently overwrite one another - the second gets a 409
  -- and reloads.
  version integer not null default 1 check (version > 0),

  updated_at timestamptz not null default now(),
  -- Null for the seeded row: nobody set it, so no administrator is named
  -- for it. Never taken from a client - the backend writes the
  -- authenticated admin's own id.
  updated_by uuid references auth.users (id) on delete set null,

  -- A zero limit while enabled would be an automation policy that can
  -- never match anything: not dangerous, but it reads as "on" in the
  -- portal while behaving as "off", which is the kind of disagreement
  -- this table exists to remove. Enforced again in the API, with a
  -- message, because a constraint violation is not an error a person can
  -- act on.
  constraint withdrawal_automation_policy_enabled_limits_positive check (
    not enabled or (max_amount_tzs > 0 and merchant_rolling_24h_limit_tzs > 0)
  )
);

comment on table public.withdrawal_automation_policy is
  'Platform-wide withdrawal automation policy (one row) read by the payout authorization boundary. Environment variables remain the deployment override and the hard ceilings above it; see the header of this migration for the exact precedence. Absent or unreadable means manual approval.';
comment on column public.withdrawal_automation_policy.max_amount_tzs is
  'Inclusive per-request ceiling for automatic processing: amount <= this may auto-process, amount > this requires manual approval. Applies to the requested payout principal; the balance check still covers the full wallet debit including fees.';
comment on column public.withdrawal_automation_policy.merchant_rolling_24h_limit_tzs is
  'Rolling 24-hour total auto-processed per merchant, measured from the decision instant. Not a calendar day, and not reset by toggling this policy.';
comment on column public.withdrawal_automation_policy.version is
  'Optimistic concurrency token. An update must present the current version or be refused with a conflict.';

-- Seeded disabled, with the same numbers the environment defaults already
-- carry so the portal opens on sensible values rather than zeros. Seeding
-- the numbers changes nothing while enabled is false: no existing
-- installation is switched on by applying this migration, which is the
-- point. `on conflict do nothing` makes re-applying it a no-op rather than
-- something that could quietly reset a live policy back to disabled.
insert into public.withdrawal_automation_policy (id, enabled, max_amount_tzs, merchant_rolling_24h_limit_tzs)
values (true, false, 500000.00, 1000000.00)
on conflict (id) do nothing;

-- Same default-deny shape as every other table the backend owns: RLS on
-- with no policies at all, so anon and authenticated reach nothing, and
-- the service role (which bypasses RLS) is the only way in. All
-- administration goes through the require_super_admin endpoints in
-- app/routers/admin_withdrawal_policy.py.
alter table public.withdrawal_automation_policy enable row level security;

revoke all on table public.withdrawal_automation_policy from anon;
revoke all on table public.withdrawal_automation_policy from authenticated;
grant select, insert, update on table public.withdrawal_automation_policy to service_role;

-- --------------------------------------------------------------------------
-- 2. What decided each payout
-- --------------------------------------------------------------------------

alter table public.disbursements
  add column if not exists auto_decision_code text,
  add column if not exists auto_policy_version integer,
  add column if not exists auto_decided_at timestamptz;

comment on column public.disbursements.auto_decision_code is
  'Stable, merchant-safe code for the automation decision: AUTO_ELIGIBLE, AUTO_POLICY_DISABLED, AUTO_AMOUNT_LIMIT_EXCEEDED, AUTO_ROLLING_LIMIT_EXCEEDED, AUTO_POLICY_UNAVAILABLE, AUTO_RISK_REVIEW_REQUIRED, DAILY_LIMIT_EXCEEDED. Carries no fraud detail.';
comment on column public.disbursements.auto_policy_version is
  'withdrawal_automation_policy.version in force when this row was decided. Null for rows decided before this migration, or when the policy could not be read.';
comment on column public.disbursements.auto_decided_at is
  'When the automation decision was taken, which is not the same instant as initiated_at or approved_at.';

-- --------------------------------------------------------------------------
-- 3. The decision itself
-- --------------------------------------------------------------------------
--
-- One implementation, two entry points. The 6-argument function below is
-- the authoritative one; the original 5-argument signature is replaced by a
-- wrapper that delegates to it with a null policy version, so an API build
-- deployed before or after this migration behaves identically and the
-- migration can safely go first. There is deliberately no second copy of
-- this logic anywhere.
--
-- Everything the original function did is unchanged: the per-merchant
-- advisory lock, the strictly-before (initiated_at, id) ordering that makes
-- two simultaneous requests resolve to one winner rather than rejecting
-- both, the exclusion of REJECTED/FAILED from the sums, and the
-- conservative counting of an inserted-but-undecided earlier row. The
-- additions are the reason codes, the policy version, and the decision
-- timestamp.

create or replace function public.finalize_withdrawal_limits(
  p_disbursement_id uuid,
  p_daily_limit numeric,
  p_auto_max numeric,
  p_auto_daily_limit numeric,
  p_automation_enabled boolean,
  p_policy_version integer
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
  v_code text;
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
          auto_decision_reason = v_reason,
          auto_decision_code = 'DAILY_LIMIT_EXCEEDED',
          auto_policy_version = p_policy_version,
          auto_decided_at = now()
      where id = p_disbursement_id;
    return jsonb_build_object(
      'outcome', 'rejected',
      'reason', v_reason,
      'code', 'DAILY_LIMIT_EXCEEDED',
      'already_requested_today', v_requested_today
    );
  end if;

  if not p_automation_enabled then
    v_reason := 'Manual approval required: withdrawal automation is not enabled.';
    v_code := 'AUTO_POLICY_DISABLED';
  elsif v_row.amount > p_auto_max then
    -- The inclusive boundary. `>` and not `>=`: a withdrawal for exactly
    -- the configured maximum is eligible, which is what the portal's
    -- "TZS X or less may process automatically" promises.
    v_reason := format(
      'Manual approval required: exceeds the %s TZS per-transaction limit for automatic processing.',
      p_auto_max
    );
    v_code := 'AUTO_AMOUNT_LIMIT_EXCEEDED';
  else
    select coalesce(sum(amount), 0) into v_auto_today
    from public.disbursements
    where merchant_id = v_row.merchant_id
      -- Already auto-approved, OR still undecided. The second half matters:
      -- these calls are serialized by the advisory lock, but NOT necessarily
      -- in (initiated_at, id) order - a later row's call can acquire the lock
      -- first, while the earlier row has been inserted but has not yet had
      -- auto_approved written. Counting only auto_approved there would let
      -- each of the two miss the other and both auto-process, exceeding this
      -- cap. An undecided earlier row is therefore counted conservatively:
      -- worst case the later one falls back to PENDING_ADMIN_APPROVAL, which
      -- is the safe direction. Outside that race every earlier row already
      -- has a reason set, so this changes nothing in the normal case.
      --
      -- Keyed on auto_decision_reason rather than the new auto_decision_code
      -- on purpose: every row decided before this migration has a reason and
      -- no code, and treating those as undecided would make this cap count
      -- weeks of settled history as in-flight.
      and (auto_approved or auto_decision_reason is null)
      and status not in ('REJECTED', 'FAILED')
      and initiated_at >= now() - interval '24 hours'
      and (initiated_at, id) < (v_row.initiated_at, v_row.id);

    if v_auto_today + v_row.amount > p_auto_daily_limit then
      v_reason := format(
        'Manual approval required: would exceed the %s TZS daily limit for automatic processing (already auto-processed today: %s TZS).',
        p_auto_daily_limit, v_auto_today
      );
      v_code := 'AUTO_ROLLING_LIMIT_EXCEEDED';
    else
      v_reason := 'Eligible: verified merchant, no open high-risk alerts, within auto-withdrawal limits.';
      -- Set inside the lock. Concurrent calls that run after this one see
      -- auto_approved directly; one that runs before it (lock order is not
      -- (initiated_at, id) order) counts this row via the
      -- "auto_decision_reason is null" half of the predicate above.
      update public.disbursements
        set auto_approved = true,
            auto_decision_reason = v_reason,
            auto_decision_code = 'AUTO_ELIGIBLE',
            auto_policy_version = p_policy_version,
            auto_decided_at = now()
        where id = p_disbursement_id;
      return jsonb_build_object('outcome', 'auto', 'reason', v_reason, 'code', 'AUTO_ELIGIBLE');
    end if;
  end if;

  update public.disbursements
    set auto_decision_reason = v_reason,
        auto_decision_code = v_code,
        auto_policy_version = p_policy_version,
        auto_decided_at = now()
    where id = p_disbursement_id;
  return jsonb_build_object('outcome', 'manual', 'reason', v_reason, 'code', v_code);
end;
$$;

comment on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean, integer) is
  'Atomically enforces the rolling 24h withdrawal limits and decides auto-withdrawal eligibility for a just-inserted disbursement, under a per-merchant advisory lock. Returns {outcome: rejected|auto|manual, reason, code}. The caller supplies the EFFECTIVE limits already resolved against the deployment ceilings - see app/services/withdrawal_policy.py.';

-- The original signature, now a wrapper. Kept so the API can be deployed
-- before or after this migration without a window where withdrawals fail.
create or replace function public.finalize_withdrawal_limits(
  p_disbursement_id uuid,
  p_daily_limit numeric,
  p_auto_max numeric,
  p_auto_daily_limit numeric,
  p_automation_enabled boolean
)
returns jsonb
language sql
security definer
set search_path = public
as $$
  select public.finalize_withdrawal_limits(
    p_disbursement_id, p_daily_limit, p_auto_max, p_auto_daily_limit, p_automation_enabled, null::integer
  );
$$;

comment on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean) is
  'Compatibility wrapper for API builds that predate withdrawal_automation_policy. Delegates to the 6-argument function with a null policy version. Do not add logic here.';

revoke all on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean, integer) from public;
revoke all on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean, integer) from anon;
revoke all on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean, integer) from authenticated;
grant execute on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean, integer) to service_role;

revoke all on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean) from public;
revoke all on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean) from anon;
revoke all on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean) from authenticated;
grant execute on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean) to service_role;
