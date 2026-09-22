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
      and auto_approved
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
      -- Set inside the lock, so the very next concurrent call's
      -- v_auto_today sum already sees this row.
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
