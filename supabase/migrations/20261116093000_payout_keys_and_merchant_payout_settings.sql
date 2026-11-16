-- Payout keys, and the per-merchant switch that has to be on before one
-- can exist.
--
-- Two separate ideas, in one migration because neither is usable without
-- the other: a key type that may spend the Payout Wallet, and a
-- Super-Admin-controlled record of which merchants are allowed one.
--
-- --- Why a key TYPE and not just a scope ---------------------------------
--
-- Scopes alone would let one key hold collections:write and payouts:create
-- together. That key would then be a single credential that can both take
-- money in and send money out, and the blast radius of leaking it is the
-- whole business rather than one capability. A type makes the two
-- mutually exclusive in the data model, so the separation survives
-- somebody ticking the wrong box in the portal.
--
-- --- Why the legacy scopes stay ungrantable ------------------------------
--
-- /v1/disbursements (the Collections-funded withdrawal route) now requires
-- disbursements:write / disbursements:read. Those are deliberately NOT in
-- either grantable list. A payout key carries payouts:create / payouts:read
-- instead, which do not satisfy them - so a payout key cannot create, list
-- or fetch a legacy withdrawal, and cannot reach Collections funds through
-- that older surface. The legacy route stays available to dashboard
-- sessions, which is the only way it has ever been used.

-- --- 1. the key type ------------------------------------------------------

alter table public.api_keys
  add column if not exists key_type text not null default 'standard'
    check (key_type in ('standard', 'payout'));

comment on column public.api_keys.key_type is
  'standard = the collections/links/invoices credential merchants have always had. payout = may spend the prefunded Payout Wallet and nothing else. Enforced mutually exclusive: a standard key can hold no payouts:* scope and a payout key can hold only payouts:* scopes.';

-- Every key that exists is a standard key. Stated as an index rather than
-- left implicit so a payout key is findable without a sequential scan when
-- the Super Admin console lists them.
create index if not exists api_keys_payout_type_idx
  on public.api_keys (merchant_id, environment)
  where key_type = 'payout' and status = 'active';

-- --- 2. per-merchant payout access ---------------------------------------

create table if not exists public.merchant_payout_settings (
  merchant_id uuid primary key references public.merchants (id) on delete cascade,

  -- Two environments, two switches, deliberately independent: a merchant
  -- testing in sandbox must not thereby be live. Both default off, so
  -- applying this migration enables nothing for anybody.
  sandbox_enabled boolean not null default false,
  live_enabled boolean not null default false,

  -- A brake that is not an off switch. Pausing stops NEW provider
  -- dispatches; payouts already sent stay in flight and reconcile
  -- normally, because cancelling something the provider may already have
  -- paid is how a payout gets paid twice. Queued-but-undispatched payouts
  -- stay queued and resume when the pause lifts - they are funded and
  -- reserved already, and failing them would release funds for work that
  -- was never attempted.
  paused boolean not null default false,
  paused_reason text,

  -- Limits. Null means "no merchant-specific limit", and the platform
  -- deployment ceiling then applies alone - the same precedence the
  -- withdrawal policy uses.
  per_payout_limit_tzs numeric(14, 2) check (per_payout_limit_tzs is null or per_payout_limit_tzs > 0),
  daily_limit_tzs numeric(14, 2) check (daily_limit_tzs is null or daily_limit_tzs > 0),

  -- Fee schedule for payouts, kept here rather than reusing the collection
  -- pricing rules: those are a percentage of money coming IN and are
  -- resolved per collection channel, which has no meaning for a payout.
  fee_flat_tzs numeric(14, 2) not null default 0 check (fee_flat_tzs >= 0),
  fee_percentage numeric(6, 4) not null default 0
    check (fee_percentage >= 0 and fee_percentage <= 100),

  -- Optimistic concurrency, same shape and same reason as
  -- withdrawal_automation_policy.version: two admins editing one
  -- merchant's limits must not silently overwrite each other.
  version integer not null default 1 check (version > 0),

  updated_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.merchant_payout_settings is
  'Per-merchant Disbursement API access, limits and fees. Absent row = no access, which is the default for every merchant: the API is enabled one merchant at a time by a Super Admin, never by the merchant.';
comment on column public.merchant_payout_settings.paused is
  'Stops new provider dispatches. Does not cancel in-flight payouts and does not fail queued ones - they resume on unpause.';

create trigger merchant_payout_settings_set_updated_at
  before update on public.merchant_payout_settings
  for each row execute function public.set_updated_at();

-- Default-deny, same as every other table the backend owns: RLS on with no
-- policies, so anon and authenticated reach nothing and only the service
-- role (which bypasses RLS) can read or write it.
alter table public.merchant_payout_settings enable row level security;

-- --- 3. the key/settings invariant ---------------------------------------

-- A payout key may only exist for a merchant with a settings row, and only
-- in an environment that row has switched on. Enforced in the database as
-- well as the API because this is the boundary between "a merchant can
-- test" and "a machine can move real money", and an API-side check alone
-- would be one refactor away from being skipped.
create or replace function public.assert_payout_key_allowed()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_settings public.merchant_payout_settings;
begin
  if new.key_type <> 'payout' then
    return new;
  end if;

  select * into v_settings
  from public.merchant_payout_settings
  where merchant_id = new.merchant_id;

  if not found then
    raise exception 'PAYOUT_NOT_ENABLED: merchant % has no payout settings', new.merchant_id;
  end if;

  if new.environment = 'live' and not v_settings.live_enabled then
    raise exception 'PAYOUT_NOT_ENABLED: live payouts are not enabled for merchant %', new.merchant_id;
  end if;

  if new.environment = 'sandbox' and not v_settings.sandbox_enabled then
    raise exception 'PAYOUT_NOT_ENABLED: sandbox payouts are not enabled for merchant %', new.merchant_id;
  end if;

  return new;
end;
$$;

create trigger api_keys_payout_requires_enablement
  before insert or update of key_type, environment on public.api_keys
  for each row execute function public.assert_payout_key_allowed();

comment on function public.assert_payout_key_allowed() is
  'Refuses a payout-type api_key unless the merchant has a merchant_payout_settings row with that environment enabled.';
