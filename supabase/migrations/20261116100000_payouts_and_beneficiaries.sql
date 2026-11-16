-- The Disbursement API's own tables: approved beneficiaries, and the
-- payouts sent to them from the prefunded Payout Wallet.
--
-- --- Why not reuse public.disbursements -----------------------------------
--
-- A `disbursements` row is a WITHDRAWAL: a merchant moving their own
-- settled money to their own registered account, out of the Collections
-- balance, with a Super Admin or the automation policy deciding it. A
-- payout is a merchant sending money to a THIRD PARTY out of a separately
-- funded wallet, decided by an API key within limits set per merchant.
--
-- Same verb, different money, different authority, different lifecycle.
-- Sharing a table would mean every existing query over disbursements
-- silently started returning payouts - including the Super Admin
-- withdrawal queues, the rolling 24h limit sum in finalize_withdrawal_
-- limits, and the merchant's own Withdrawals page. Each of those would
-- then need a filter it does not have today, and the one that got
-- forgotten would be a real bug over real money. A separate table makes
-- the separation structural instead of a WHERE clause nobody can omit.
--
-- The route is /v1/payouts for the same reason: /v1/disbursements is
-- occupied by the withdrawal API and conflating the two in a URL is how
-- an integrator ends up spending the wrong balance.

-- --- beneficiaries --------------------------------------------------------
--
-- A payout can only go to an id that was approved beforehand. The pilot
-- does not let an API call name an arbitrary phone number: that turns a
-- leaked key into an open money tap, where approving destinations first
-- caps the damage at "money went to someone already on the list".

create table if not exists public.payout_beneficiaries (
  id uuid primary key default gen_random_uuid(),

  merchant_id uuid not null references public.merchants (id) on delete cascade,
  environment text not null check (environment in ('sandbox', 'live')),

  name text not null,

  -- The payout rail. Only mobile money is in the pilot; a bank route goes
  -- in when a verified provider contract exists for it, not before.
  method text not null check (method in ('MOBILE_MONEY')),
  -- Operator code as Selcom names it (MPESA, TIGOPESA, AIRTELMONEY, ...).
  -- Deliberately not an enum: the authoritative list is the provider's and
  -- has already changed once (see collections.channel), so a CHECK here
  -- would turn their change into our outage.
  destination_code text not null,
  destination_identifier text not null,

  status text not null default 'active' check (status in ('active', 'disabled')),

  approved_by uuid references auth.users (id) on delete set null,
  approved_at timestamptz,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  -- One live beneficiary per destination per merchant per environment, so
  -- an integrator cannot accumulate duplicates and then wonder which id
  -- they just paid.
  constraint payout_beneficiaries_identifier_not_blank
    check (length(trim(destination_identifier)) > 0)
);

create unique index if not exists payout_beneficiaries_unique_destination
  on public.payout_beneficiaries (merchant_id, environment, method, destination_code, destination_identifier)
  where status = 'active';

create index if not exists payout_beneficiaries_merchant_idx
  on public.payout_beneficiaries (merchant_id, environment, status);

comment on table public.payout_beneficiaries is
  'Destinations a merchant may send payouts to. A payout names a beneficiary id, never a raw phone number, so a leaked payout key cannot invent a destination.';

alter table public.payout_beneficiaries enable row level security;

create trigger payout_beneficiaries_set_updated_at
  before update on public.payout_beneficiaries
  for each row execute function public.set_updated_at();

-- --- payouts --------------------------------------------------------------

create table if not exists public.payouts (
  id uuid primary key default gen_random_uuid(),

  merchant_id uuid not null references public.merchants (id) on delete cascade,
  environment text not null check (environment in ('sandbox', 'live')),

  -- Which credential asked. Kept for the audit trail and so revoking a key
  -- can be followed by "what did it send": set null on delete rather than
  -- cascade, because deleting the key must never delete the money record.
  api_key_id uuid references public.api_keys (id) on delete set null,

  beneficiary_id uuid not null references public.payout_beneficiaries (id) on delete restrict,

  amount numeric(14, 2) not null check (amount > 0),
  fee_amount numeric(14, 2) not null default 0 check (fee_amount >= 0),
  -- amount + fee: what left payout_available and sits in payout_reserved.
  -- Stored rather than derived so a later fee-schedule change cannot
  -- retroactively alter what was reserved for a payout already sent.
  total_debit numeric(14, 2) not null check (total_debit > 0),
  currency text not null default 'TZS' check (currency ~ '^[A-Z]{3}$'),

  -- The lifecycle, named for what is true about the MONEY at each point.
  --
  --   queued               accepted and funded; reserve held; not yet sent
  --   processing           dispatched; awaiting the provider's answer
  --   needs_reconciliation outcome unknown; reserve STILL HELD. A timeout
  --                        lands here, never in failed - releasing funds
  --                        because a response was slow is how a payout
  --                        gets paid twice
  --   successful           confirmed paid; reserve posted to clearing+fees
  --   failed               confirmed not paid; reserve released
  --   cancelled            confirmed never dispatched; reserve released
  --   reversed             confirmed reversed after success; compensating
  --                        entry, the original stays as it was
  status text not null default 'queued'
    check (status in (
      'queued', 'processing', 'needs_reconciliation',
      'successful', 'failed', 'cancelled', 'reversed'
    )),

  failure_reason text,
  failure_code text,

  -- Ours, and stable: generated once at creation and sent to the provider
  -- as their idempotency handle, so a retry after an ambiguous dispatch
  -- asks about the SAME payout instead of starting another.
  provider_reference text not null,
  provider_transid text,
  provider_raw_response jsonb,

  -- Delivery attempts by the worker, not provider retries.
  dispatch_attempts integer not null default 0 check (dispatch_attempts >= 0),
  last_dispatched_at timestamptz,
  next_check_at timestamptz,

  reversed_from_payout_id uuid references public.payouts (id) on delete restrict,

  metadata jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,

  constraint payouts_total_debit_matches
    check (total_debit = amount + fee_amount),
  constraint payouts_completed_only_when_terminal
    check (
      completed_at is null
      or status in ('successful', 'failed', 'cancelled', 'reversed')
    )
);

-- Scoped to merchant AND environment, which is what makes the reference
-- genuinely unique where it matters: a sandbox payout and a live payout
-- must never collide, and two merchants' references must never collide
-- even if a client generates the suffix itself.
create unique index if not exists payouts_provider_reference_key
  on public.payouts (merchant_id, environment, provider_reference);

create index if not exists payouts_merchant_created_idx
  on public.payouts (merchant_id, environment, created_at desc);

-- The worker's queue. Partial, so it stays small however many payouts
-- have settled: only unfinished work is ever scanned.
create index if not exists payouts_pending_work_idx
  on public.payouts (next_check_at)
  where status in ('queued', 'processing', 'needs_reconciliation');

comment on table public.payouts is
  'Payouts sent from a merchant''s prefunded Payout Wallet via the Disbursement API. Separate from public.disbursements, which are withdrawals from the Collections balance - different money, different authority, different lifecycle.';
comment on column public.payouts.status is
  'needs_reconciliation means the outcome is unknown and the reserve is STILL HELD. Nothing releases funds on a timeout.';
comment on column public.payouts.provider_reference is
  'Our stable handle, generated once at creation and used as the provider idempotency key, so a retry after an ambiguous dispatch asks about the same payout rather than starting another.';

alter table public.payouts enable row level security;

create trigger payouts_set_updated_at
  before update on public.payouts
  for each row execute function public.set_updated_at();

-- A reversal must point at a payout that actually succeeded, and must not
-- point at itself. Cheap to enforce here, and the alternative is a bug
-- that credits a merchant for a payout that never happened.
create or replace function public.assert_payout_reversal_valid()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_original public.payouts;
begin
  if new.reversed_from_payout_id is null then
    return new;
  end if;

  if new.reversed_from_payout_id = new.id then
    raise exception 'INVALID_REVERSAL: a payout cannot reverse itself';
  end if;

  select * into v_original from public.payouts where id = new.reversed_from_payout_id;

  if not found then
    raise exception 'INVALID_REVERSAL: payout % does not exist', new.reversed_from_payout_id;
  end if;

  if v_original.merchant_id <> new.merchant_id or v_original.environment <> new.environment then
    raise exception 'INVALID_REVERSAL: cannot reverse another merchant or environment''s payout';
  end if;

  if v_original.status <> 'successful' then
    raise exception 'INVALID_REVERSAL: payout % is %, only a successful payout can be reversed',
      v_original.id, v_original.status;
  end if;

  return new;
end;
$$;

create trigger payouts_reversal_valid
  before insert or update of reversed_from_payout_id on public.payouts
  for each row execute function public.assert_payout_reversal_valid();

-- --- authorize_payout -----------------------------------------------------
--
-- The rolling 24h limit check and the fund reservation, as ONE decision
-- under one per-merchant advisory lock.
--
-- Both halves are read-then-write and both are wrong if two payouts
-- interleave. Two calls can each see the same remaining daily allowance
-- and both proceed; two calls can each see the same available balance
-- and both proceed. Doing the check in the API and the reservation in a
-- second round trip leaves exactly that gap, so the whole decision lives
-- here instead.
--
-- Modelled on finalize_withdrawal_limits (20260922030000), including the
-- (created_at, id) tie-break so two payouts created in the same
-- microsecond still have a deterministic order and cannot both count
-- themselves as "earlier".
--
-- Advisory, not a row lock on merchants, so it never contends with
-- unrelated writes to the merchant row. Transaction-scoped so it is
-- always released when this function ends, including on a raise.
--
-- Reservation is delegated to post_ledger_entries rather than reimplemented,
-- so the no-negative guard and the balance_before/after snapshot apply to
-- payouts exactly as they do to everything else. Calling it from inside
-- this function keeps the advisory lock held across the posting.
--
-- Returns jsonb {outcome, reason}. Outcomes:
--   authorized          reserved and ready to dispatch
--   daily_limit         would exceed the rolling 24h limit; nothing reserved
--   insufficient_funds  payout wallet cannot cover it; nothing reserved
--   not_queued          the payout was not in `queued` (double call)

-- --- transactions carries payouts too -----------------------------------
--
-- ledger_entries.transaction_id is a FOREIGN KEY to transactions. Every
-- ledger posting therefore needs a real transactions row behind it - a
-- payout id is not one, and passing it would fail on the foreign key the
-- moment this ran against Postgres rather than the in-memory fake, which
-- does not enforce foreign keys.
--
-- So payouts get the same treatment collections and disbursements have:
-- a transactions row, linked back, with its own type. `payout` rather
-- than reusing `disbursement`, so platform reporting can tell money sent
-- by a machine from a merchant's prefunded wallet apart from a
-- withdrawal a person approved out of Collections.

alter table public.transactions
  add column if not exists payout_id uuid references public.payouts (id) on delete set null;

create index if not exists transactions_payout_id_idx
  on public.transactions (payout_id)
  where payout_id is not null;

do $$
declare
  v_name text;
begin
  for v_name in
    select con.conname
    from pg_constraint con
    join pg_class rel on rel.oid = con.conrelid
    join pg_namespace nsp on nsp.oid = rel.relnamespace
    where nsp.nspname = 'public'
      and rel.relname = 'transactions'
      and con.contype = 'c'
      and pg_get_constraintdef(con.oid) ilike '%collection%'
      and pg_get_constraintdef(con.oid) ilike '%disbursement%'
  loop
    execute format('alter table public.transactions drop constraint %I', v_name);
  end loop;
end
$$;

alter table public.transactions
  add constraint transactions_type_check check (type in (
    'collection', 'disbursement', 'fee', 'refund', 'reversal', 'adjustment', 'payout'
  ));

comment on column public.transactions.payout_id is
  'Set for transactions created by the Disbursement API. Distinct from disbursement_id, which is a withdrawal from the Collections balance.';

create or replace function public.authorize_payout(
  p_payout_id uuid,
  p_daily_limit numeric default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row public.payouts;
  v_today numeric(18, 2);
  v_available_id uuid;
  v_reserved_id uuid;
  v_transaction_id uuid;
begin
  select * into v_row from public.payouts where id = p_payout_id;
  if not found then
    return jsonb_build_object('outcome', 'not_queued', 'reason', 'payout not found');
  end if;

  if v_row.status <> 'queued' then
    return jsonb_build_object(
      'outcome', 'not_queued',
      'reason', format('payout is %s, not queued', v_row.status)
    );
  end if;

  perform pg_advisory_xact_lock(hashtext('payout:' || v_row.merchant_id::text));

  -- Re-read inside the lock. The status may have changed between the
  -- read above and the lock being granted, and acting on the stale read
  -- would reserve funds twice for one payout.
  select * into v_row from public.payouts where id = p_payout_id for update;
  if v_row.status <> 'queued' then
    return jsonb_build_object(
      'outcome', 'not_queued',
      'reason', format('payout is %s, not queued', v_row.status)
    );
  end if;

  if p_daily_limit is not null then
    -- Everything not definitively refunded counts against the allowance:
    -- in-flight money is spent until proven otherwise. failed, cancelled
    -- and reversed are excluded because their funds went back.
    select coalesce(sum(total_debit), 0) into v_today
    from public.payouts
    where merchant_id = v_row.merchant_id
      and environment = v_row.environment
      and status in ('queued', 'processing', 'needs_reconciliation', 'successful')
      and created_at >= now() - interval '24 hours'
      and (created_at, id) < (v_row.created_at, v_row.id);

    if v_today + v_row.total_debit > p_daily_limit then
      update public.payouts
      set status = 'cancelled',
          failure_code = 'daily_limit_exceeded',
          failure_reason = format(
            'Would exceed the rolling 24-hour payout limit of %s (already sent: %s).',
            p_daily_limit, v_today
          ),
          completed_at = now()
      where id = v_row.id;

      return jsonb_build_object(
        'outcome', 'daily_limit',
        'reason', format('limit %s, already %s, this %s', p_daily_limit, v_today, v_row.total_debit),
        'already_today', v_today::text
      );
    end if;
  end if;

  select id into v_available_id from public.ledger_accounts
  where merchant_id = v_row.merchant_id and purpose = 'payout_available'
    and currency = v_row.currency and environment = v_row.environment;

  select id into v_reserved_id from public.ledger_accounts
  where merchant_id = v_row.merchant_id and purpose = 'payout_reserved'
    and currency = v_row.currency and environment = v_row.environment;

  if v_available_id is null or v_reserved_id is null then
    update public.payouts
    set status = 'cancelled',
        failure_code = 'insufficient_funds',
        failure_reason = 'The payout wallet has never been funded.',
        completed_at = now()
    where id = v_row.id;
    return jsonb_build_object('outcome', 'insufficient_funds', 'reason', 'no payout wallet');
  end if;

  -- The transactions row the ledger entries hang off. Created here, in
  -- the same transaction as the reservation, so a payout can never have
  -- entries without a parent or a parent without entries.
  insert into public.transactions (
    merchant_id, reference, type, method, payout_id,
    gross_amount, fee_amount, net_amount, currency, status
  ) values (
    v_row.merchant_id,
    v_row.provider_reference,
    'payout',
    'MOBILE_MONEY',
    v_row.id,
    v_row.amount,
    v_row.fee_amount,
    v_row.amount,
    v_row.currency,
    'processing'
  )
  returning id into v_transaction_id;

  begin
    perform public.post_ledger_entries(jsonb_build_array(
      jsonb_build_object(
        'transaction_id', v_transaction_id,
        'ledger_account_id', v_available_id,
        'direction', 'debit',
        'amount', v_row.total_debit,
        'currency', v_row.currency,
        'description', 'Reserved for payout'
      ),
      jsonb_build_object(
        'transaction_id', v_transaction_id,
        'ledger_account_id', v_reserved_id,
        'direction', 'credit',
        'amount', v_row.total_debit,
        'currency', v_row.currency,
        'description', 'Payout reservation held'
      )
    ));
  exception
    when others then
      if sqlerrm like 'INSUFFICIENT_BALANCE%' then
        -- The authoritative answer, taken under the same lock. The
        -- friendly check in the API can be stale; this one cannot.
        update public.payouts
        set status = 'cancelled',
            failure_code = 'insufficient_funds',
            failure_reason = 'Payout wallet balance could not cover this payout.',
            completed_at = now()
        where id = v_row.id;
        return jsonb_build_object('outcome', 'insufficient_funds', 'reason', 'balance check failed');
      end if;
      raise;
  end;

  update public.payouts
  set next_check_at = now()
  where id = v_row.id;

  return jsonb_build_object(
    'outcome', 'authorized',
    'transaction_id', v_transaction_id,
    'reserved', v_row.total_debit::text,
    'already_today', coalesce(v_today, 0)::text
  );
end;
$$;

comment on function public.authorize_payout(uuid, numeric) is
  'Checks the rolling 24h payout limit and reserves the funds for one queued payout, as a single decision under a per-merchant advisory lock. Returns {outcome: authorized|daily_limit|insufficient_funds|not_queued}.';

revoke execute on function public.authorize_payout(uuid, numeric) from public, anon, authenticated;
grant execute on function public.authorize_payout(uuid, numeric) to service_role;
