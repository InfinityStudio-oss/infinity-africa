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
