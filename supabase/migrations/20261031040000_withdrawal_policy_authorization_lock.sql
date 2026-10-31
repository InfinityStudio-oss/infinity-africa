-- Close the off-switch race, and make a policy change and its audit row
-- one transaction instead of two.
--
-- =====================================================================
-- A. THE RACE
-- =====================================================================
--
-- As shipped, app/services/disbursements.py read the automation policy
-- over PostgREST and then passed the answers *into* finalize_withdrawal_
-- limits, which trusted them:
--
--     policy = resolve_effective_policy(client)        -- transaction 1
--     client.rpc('finalize_withdrawal_limits',         -- transaction 2
--                {'p_automation_enabled': policy.automation_active, ...})
--
-- Two transactions, so a Super Admin committing OFF between them was
-- invisible: the second transaction authorised a payout against a policy
-- that no longer existed. The module docstring admitted the window and
-- called it one single-row read wide. That is still a window, and it sits
-- on the one control whose entire purpose is to be trusted in a hurry.
--
-- The fix is that the function now reads the policy ITSELF, inside the
-- transaction that authorises the payout, holding `for share` on the row
-- while it decides. A concurrent UPDATE of that row blocks until the
-- decision commits, and a decision starting after an OFF has committed
-- sees the OFF. There is no longer any instant at which the two can
-- disagree.
--
-- **The honest boundary.** This makes OFF authoritative for every payout
-- authorisation that has not yet been taken. It cannot recall one that
-- has: once this function commits 'auto', the API submits to Selcom, and
-- an instruction already with a provider is not ours to take back. OFF
-- therefore means "no new automatic authorisations", never "stop
-- everything in flight". Payouts already submitted keep settling through
-- reconciliation exactly as before, and nothing here changes that.
--
-- **Deployment restrictions still win.** The three env controls
-- (REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS, AUTO_WITHDRAWALS_ENABLED
-- and the two amount ceilings) continue to arrive as arguments, because
-- they are process configuration and not database state. What changed is
-- that they are now treated strictly as an upper bound: the function
-- combines them with the live policy using AND and LEAST, so runtime can
-- only ever be more restrictive than deployment. A policy row cannot
-- raise a ceiling or re-enable automation that the deployment forbids.
--
-- **Older callers fail closed, by construction.** An API build that
-- predates this migration passes values it has already resolved against
-- the policy. The function ANDs those with the policy again, which is
-- idempotent when they agree and more restrictive when they do not. So an
-- old build cannot bypass a current OFF; at worst it declines a payout it
-- could have taken. The 5-argument compatibility wrapper inherits the
-- same guarantee because it delegates here. No coordinated rollout is
-- required, and there is no ordering in which automation runs against a
-- policy that says it should not.
--
-- =====================================================================
-- B. THE POLICY WRITE AND ITS AUDIT ROW
-- =====================================================================
--
-- app/routers/admin_withdrawal_policy.py updated the policy in one
-- request and wrote the audit row in another. The update could commit and
-- the audit insert then fail, leaving the control over unattended payouts
-- changed, no record that anybody changed it, and an error returned to
-- the administrator who had in fact succeeded. Every one of those three
-- is bad on its own.
--
-- update_withdrawal_automation_policy below does both in one transaction
-- under `for update`, so they commit together or not at all, and the
-- before/after values in the audit row are read from the locked row
-- rather than from a separate earlier read that might already be stale.
-- The version check happens under the same lock, which is what makes the
-- optimistic concurrency actually hold between two administrators.
--
-- Notifications stay outside: an SMS or email provider must never be able
-- to roll back a committed financial control, nor to make a committed one
-- look like it failed.
--
-- =====================================================================
-- LOCK ORDER, AND WHY THIS CANNOT DEADLOCK
-- =====================================================================
--
--   authorising a payout:  policy row `for share`  ->  per-merchant
--                          advisory lock
--   changing the policy:   policy row `for update`  (and nothing else)
--
-- Every payout takes the two in the same order, so they cannot cycle
-- among themselves. The writer takes exactly one lock and never waits on
-- a merchant, so it cannot complete a cycle either. A policy change waits
-- only for decisions already in progress, each of which is a few
-- milliseconds.
--
-- ROLLBACK: restore both functions from
-- 20261031010000_withdrawal_automation_policy.sql (and the API from a
-- build of that era). Automation keeps working either way; reverting only
-- reopens the race. The policy row, the audit history and every
-- disbursement are untouched by this migration - it replaces two function
-- bodies and adds one, and creates, drops and rewrites no data.

-- ---------------------------------------------------------------------
-- 1. Authorising a payout, against the policy as it is right now
-- ---------------------------------------------------------------------

create or replace function public.finalize_withdrawal_limits(
  p_disbursement_id uuid,
  p_daily_limit numeric,
  -- From here down these are DEPLOYMENT values: a hard ceiling and a
  -- permission, never the live policy. The function reads that itself.
  p_auto_max numeric,
  p_auto_daily_limit numeric,
  p_automation_enabled boolean,
  -- Accepted for signature compatibility and deliberately ignored: the
  -- version that matters is the one on the row this transaction locked,
  -- not one a caller read earlier.
  p_policy_version integer
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row public.disbursements;
  v_policy public.withdrawal_automation_policy;
  v_automation_enabled boolean;
  v_auto_max numeric(14, 2);
  v_auto_daily_limit numeric(14, 2);
  v_policy_version integer;
  v_requested_today numeric(14, 2);
  v_auto_today numeric(14, 2);
  v_reason text;
  v_code text;
begin
  select * into v_row from public.disbursements where id = p_disbursement_id;
  if not found then
    raise exception 'DISBURSEMENT_NOT_FOUND: %', p_disbursement_id;
  end if;

  -- The policy, read here and held for the rest of this transaction. A
  -- concurrent update of this row waits behind us; an update that already
  -- committed is what we see. This is the whole fix.
  select * into v_policy
  from public.withdrawal_automation_policy
  where id = true
  for share;

  if not found then
    -- No policy at all. Automation is not merely off, it is unknown, and
    -- unknown must never mean yes.
    v_automation_enabled := false;
    v_auto_max := 0;
    v_auto_daily_limit := 0;
    v_policy_version := null;
  else
    -- AND with the deployment permission, LEAST against the deployment
    -- ceilings: runtime can tighten, never loosen.
    v_automation_enabled := coalesce(p_automation_enabled, false) and coalesce(v_policy.enabled, false);
    v_auto_max := least(coalesce(p_auto_max, 0), coalesce(v_policy.max_amount_tzs, 0));
    v_auto_daily_limit := least(coalesce(p_auto_daily_limit, 0), coalesce(v_policy.merchant_rolling_24h_limit_tzs, 0));
    v_policy_version := v_policy.version;
  end if;

  -- A limit of zero would match nothing anyway; saying so here keeps the
  -- reason code honest rather than reporting a limit breach.
  if v_auto_max <= 0 or v_auto_daily_limit <= 0 then
    v_automation_enabled := false;
  end if;

  -- Serializes every concurrent withdrawal for this one merchant. Taken
  -- after the policy lock, and in that order by every caller, so these
  -- two can never cycle. Advisory rather than a row lock on merchants so
  -- it never contends with unrelated writes, and xact-scoped so it is
  -- always released when this transaction ends, including on the raise
  -- above.
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
          auto_policy_version = v_policy_version,
          auto_decided_at = now()
      where id = p_disbursement_id;
    return jsonb_build_object(
      'outcome', 'rejected',
      'reason', v_reason,
      'code', 'DAILY_LIMIT_EXCEEDED',
      'policy_version', v_policy_version,
      'already_requested_today', v_requested_today
    );
  end if;

  if not v_automation_enabled then
    if v_policy_version is null then
      v_reason := 'Manual approval required: the automation policy could not be read.';
      v_code := 'AUTO_POLICY_UNAVAILABLE';
    else
      v_reason := 'Manual approval required: withdrawal automation is not enabled.';
      v_code := 'AUTO_POLICY_DISABLED';
    end if;
  elsif v_row.amount > v_auto_max then
    -- The inclusive boundary. `>` and not `>=`: a withdrawal for exactly
    -- the configured maximum is eligible, which is what the portal's
    -- "TZS X or less may process automatically" promises.
    v_reason := format(
      'Manual approval required: exceeds the %s TZS per-transaction limit for automatic processing.',
      v_auto_max
    );
    v_code := 'AUTO_AMOUNT_LIMIT_EXCEEDED';
  else
    select coalesce(sum(amount), 0) into v_auto_today
    from public.disbursements
    where merchant_id = v_row.merchant_id
      -- Already auto-approved, OR still undecided. The second half
      -- matters: these calls are serialized by the advisory lock, but NOT
      -- necessarily in (initiated_at, id) order - a later row's call can
      -- acquire the lock first, while the earlier row has been inserted
      -- but has not yet had auto_approved written. Counting only
      -- auto_approved there would let each of the two miss the other and
      -- both auto-process, exceeding this cap. An undecided earlier row
      -- is therefore counted conservatively: worst case the later one
      -- falls back to PENDING_ADMIN_APPROVAL, which is the safe
      -- direction.
      --
      -- Keyed on auto_decision_reason rather than auto_decision_code on
      -- purpose: every row decided before 20261031010000 has a reason and
      -- no code, and treating those as undecided would make this cap
      -- count weeks of settled history as in-flight.
      and (auto_approved or auto_decision_reason is null)
      and status not in ('REJECTED', 'FAILED')
      and initiated_at >= now() - interval '24 hours'
      and (initiated_at, id) < (v_row.initiated_at, v_row.id);

    if v_auto_today + v_row.amount > v_auto_daily_limit then
      v_reason := format(
        'Manual approval required: would exceed the %s TZS daily limit for automatic processing (already auto-processed today: %s TZS).',
        v_auto_daily_limit, v_auto_today
      );
      v_code := 'AUTO_ROLLING_LIMIT_EXCEEDED';
    else
      v_reason := 'Eligible: verified merchant, no open high-risk alerts, within auto-withdrawal limits.';
      update public.disbursements
        set auto_approved = true,
            auto_decision_reason = v_reason,
            auto_decision_code = 'AUTO_ELIGIBLE',
            auto_policy_version = v_policy_version,
            auto_decided_at = now()
        where id = p_disbursement_id;
      return jsonb_build_object(
        'outcome', 'auto',
        'reason', v_reason,
        'code', 'AUTO_ELIGIBLE',
        'policy_version', v_policy_version
      );
    end if;
  end if;

  update public.disbursements
    set auto_decision_reason = v_reason,
        auto_decision_code = v_code,
        auto_policy_version = v_policy_version,
        auto_decided_at = now()
    where id = p_disbursement_id;
  return jsonb_build_object(
    'outcome', 'manual', 'reason', v_reason, 'code', v_code, 'policy_version', v_policy_version
  );
end;
$$;

comment on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean, integer) is
  'Authorises or declines automatic processing for a just-inserted disbursement, and enforces the rolling 24h limits, in ONE transaction holding `for share` on the automation policy and an advisory lock on the merchant. p_auto_max, p_auto_daily_limit and p_automation_enabled are DEPLOYMENT ceilings and permission; the live policy is read here and combined with AND/LEAST so runtime can only tighten. p_policy_version is ignored. Returns {outcome: rejected|auto|manual, reason, code, policy_version}.';

-- ---------------------------------------------------------------------
-- 2. Changing the policy, with its audit row, atomically
-- ---------------------------------------------------------------------

create or replace function public.update_withdrawal_automation_policy(
  p_enabled boolean,
  p_max_amount numeric,
  p_rolling_limit numeric,
  p_expected_version integer,
  p_actor_id uuid,
  p_correlation_id text,
  p_confirmed boolean,
  -- The deployment ceilings and permission, so the audit row can record
  -- what they made of this policy. A policy raised above a ceiling it can
  -- never exceed is a real source of confusion later, and the record
  -- should say what actually took effect rather than only what was asked
  -- for. They are recorded, never enforced here - enforcement lives in
  -- finalize_withdrawal_limits, at the moment a payout is authorised.
  p_deployment_allows boolean default false,
  p_deployment_max numeric default 0,
  p_deployment_rolling numeric default 0,
  p_ip text default null,
  p_user_agent text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_before public.withdrawal_automation_policy;
  v_after public.withdrawal_automation_policy;
begin
  -- `for update`, so the version check below and the write that follows
  -- it are one decision. Without this, two administrators can both read
  -- version 7, both pass the check, and the second silently replaces the
  -- first.
  select * into v_before
  from public.withdrawal_automation_policy
  where id = true
  for update;

  if not found then
    return jsonb_build_object('outcome', 'unavailable');
  end if;

  if v_before.version is distinct from p_expected_version then
    return jsonb_build_object(
      'outcome', 'conflict',
      'current_version', v_before.version,
      'current_enabled', v_before.enabled,
      'current_max_amount_tzs', v_before.max_amount_tzs::text,
      'current_rolling_24h_limit_tzs', v_before.merchant_rolling_24h_limit_tzs::text
    );
  end if;

  update public.withdrawal_automation_policy
    set enabled = p_enabled,
        max_amount_tzs = p_max_amount,
        merchant_rolling_24h_limit_tzs = p_rolling_limit,
        version = v_before.version + 1,
        updated_at = now(),
        -- Server-derived. The caller passes the id it authenticated, and
        -- the API never takes it from a request body.
        updated_by = p_actor_id
    where id = true
    returning * into v_after;

  -- Same transaction as the update above. If this insert fails - a
  -- constraint, a foreign key, a disk error - the policy change goes with
  -- it, and the administrator is told it did not happen, which will be
  -- true. Before and after are read from the row this transaction locked,
  -- so they cannot describe some other change.
  insert into public.audit_logs (
    actor_id, actor_type, action, resource_type, resource_id, ip_address, user_agent, metadata
  ) values (
    p_actor_id,
    'user',
    'withdrawal_automation_policy.updated',
    'withdrawal_automation_policy',
    null,
    p_ip,
    p_user_agent,
    jsonb_build_object(
      'correlation_id', p_correlation_id,
      'confirmed', p_confirmed,
      'previous', jsonb_build_object(
        'version', v_before.version,
        'enabled', v_before.enabled,
        'max_amount_tzs', v_before.max_amount_tzs::text,
        'merchant_rolling_24h_limit_tzs', v_before.merchant_rolling_24h_limit_tzs::text,
        'automation_active', (p_deployment_allows and v_before.enabled)
      ),
      'new', jsonb_build_object(
        'version', v_after.version,
        'enabled', v_after.enabled,
        'max_amount_tzs', v_after.max_amount_tzs::text,
        'merchant_rolling_24h_limit_tzs', v_after.merchant_rolling_24h_limit_tzs::text,
        'automation_active', (p_deployment_allows and v_after.enabled)
      ),
      'effective', jsonb_build_object(
        'max_amount_tzs', least(p_deployment_max, v_after.max_amount_tzs)::text,
        'rolling_24h_limit_tzs', least(p_deployment_rolling, v_after.merchant_rolling_24h_limit_tzs)::text
      )
    )
  );

  return jsonb_build_object(
    'outcome', 'ok',
    'version', v_after.version,
    'enabled', v_after.enabled,
    'max_amount_tzs', v_after.max_amount_tzs::text,
    'merchant_rolling_24h_limit_tzs', v_after.merchant_rolling_24h_limit_tzs::text,
    'updated_at', v_after.updated_at,
    'previous_version', v_before.version,
    'previous_enabled', v_before.enabled
  );
end;
$$;

comment on function public.update_withdrawal_automation_policy is
  'Changes the withdrawal automation policy and writes its audit row in ONE transaction, under `for update` on the single policy row. Returns {outcome: ok|conflict|unavailable}. The actor is supplied by the authenticated API and never by a request body. Validation of amounts lives in app/services/withdrawal_policy.py, which can explain a rejection to a person.';

-- ---------------------------------------------------------------------
-- 3. Grants: service_role only, for both
-- ---------------------------------------------------------------------

revoke all on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean, integer) from public;
revoke all on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean, integer) from anon;
revoke all on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean, integer) from authenticated;
grant execute on function public.finalize_withdrawal_limits(uuid, numeric, numeric, numeric, boolean, integer) to service_role;

revoke all on function public.update_withdrawal_automation_policy(boolean, numeric, numeric, integer, uuid, text, boolean, boolean, numeric, numeric, text, text) from public;
revoke all on function public.update_withdrawal_automation_policy(boolean, numeric, numeric, integer, uuid, text, boolean, boolean, numeric, numeric, text, text) from anon;
revoke all on function public.update_withdrawal_automation_policy(boolean, numeric, numeric, integer, uuid, text, boolean, boolean, numeric, numeric, text, text) from authenticated;
grant execute on function public.update_withdrawal_automation_policy(boolean, numeric, numeric, integer, uuid, text, boolean, boolean, numeric, numeric, text, text) to service_role;
