-- Merchant referral commissions.
--
-- A merchant invites another business. If that business is approved and
-- then actually trades, the referrer earns a share of what InfinityPay
-- itself earned from them during their first 30 days.
--
-- The rule that shapes every table here: **commission is never paid for a
-- signup**. A referral row exists from the moment a code is used, but it
-- is worth nothing until the referred merchant is approved, trades past a
-- volume floor, and a Super Admin approves the payout. Nothing in this
-- migration moves money, and nothing here is reachable from the wallet,
-- withdrawal or settlement paths.
--
-- Commission is computed from **InfinityPay's net revenue**, not from the
-- amount collected. That figure is not re-derived from fee rules: it is
-- read from the existing double-entry ledger, where every collection fee
-- is already posted as a credit to the single platform_revenue account
-- (app/services/ledger.py::post_collection_entries) and a reversal posts
-- the matching debit (::reverse_collection_entries). Summing
-- credits - debits for a merchant's transactions is therefore the same
-- number the platform's own revenue reporting uses, and a reversed
-- collection nets itself out without any special case.

-- --------------------------------------------------------------------
-- A. Referral code on the merchant
-- --------------------------------------------------------------------

alter table public.merchants
  add column if not exists referral_code text,
  add column if not exists referral_code_created_at timestamptz,
  add column if not exists referral_code_status text not null default 'active'
    check (referral_code_status in ('active', 'disabled'));

comment on column public.merchants.referral_code is
  'Human-readable invite code, e.g. INF-8K3P2M. Random, never derived from the merchant id or code, so it reveals nothing and cannot be guessed from another merchant''s. Null until the merchant generates one.';
comment on column public.merchants.referral_code_status is
  'Super Admin kill switch for one merchant''s code. A disabled code stops being usable at signup; referrals already captured under it keep their own status.';

-- Case-insensitive uniqueness: codes are shown upper-case and typed by
-- hand, so "inf-8k3p2m" must not become a second, different code.
create unique index if not exists merchants_referral_code_key
  on public.merchants (upper(referral_code))
  where referral_code is not null;

-- --------------------------------------------------------------------
-- B. Who referred whom
-- --------------------------------------------------------------------

create table if not exists public.merchant_referrals (
  id uuid primary key default gen_random_uuid(),

  referrer_merchant_id uuid not null references public.merchants (id) on delete restrict,
  -- One referral per referred merchant, enforced by the unique constraint
  -- below: a business belongs to whoever invited it first, and can never
  -- be claimed twice or re-attributed.
  referred_merchant_id uuid not null references public.merchants (id) on delete restrict,

  -- The code exactly as used, kept even if the referrer later rotates or
  -- disables theirs — an audit needs to show what was typed.
  referral_code_used text not null,

  signup_at timestamptz not null default now(),
  -- Null until a Super Admin approves the referred merchant. The referral
  -- period is measured from approval, not from signup, so a business that
  -- sits unapproved for weeks does not burn its referrer's window.
  referred_approved_at timestamptz,
  referral_period_start_at timestamptz,
  referral_period_end_at timestamptz,

  status text not null default 'pending_approval'
    check (status in (
      'pending_signup',
      'pending_approval',
      'active',
      'qualified',
      'ineligible',
      'expired',
      'fraud_hold',
      'commission_pending',
      'commission_approved',
      'commission_paid',
      'commission_rejected'
    )),

  -- The terms this referral was captured under, copied in at creation
  -- rather than read from config at payout time. Changing the platform
  -- default later must not silently re-price a referral someone has
  -- already earned.
  qualification_volume_threshold numeric(14, 2) not null default 100000,
  commission_rate_bps integer not null default 1500 check (commission_rate_bps between 0 and 10000),
  minimum_payout_amount numeric(14, 2) not null default 5000,
  currency text not null default 'TZS' check (currency ~ '^[A-Z]{3}$'),

  ineligible_reason text,
  fraud_flag_reason text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  -- Self-referral is not a thing to detect later; it cannot be written.
  constraint merchant_referrals_no_self_referral
    check (referrer_merchant_id <> referred_merchant_id)
);

-- A referred merchant has exactly one referrer, forever.
create unique index if not exists merchant_referrals_referred_key
  on public.merchant_referrals (referred_merchant_id);

create index if not exists merchant_referrals_referrer_idx
  on public.merchant_referrals (referrer_merchant_id, created_at desc);
create index if not exists merchant_referrals_status_idx
  on public.merchant_referrals (status);
-- The daily job asks for referrals whose window is still open.
create index if not exists merchant_referrals_window_idx
  on public.merchant_referrals (referral_period_end_at)
  where referral_period_end_at is not null;

comment on table public.merchant_referrals is
  'Who invited whom. A row here is an attribution, not an entitlement: it pays nothing until the referred merchant is approved, trades past qualification_volume_threshold, and a Super Admin approves the resulting commission.';
comment on column public.merchant_referrals.commission_rate_bps is
  'Basis points, 1500 = 15%. Frozen at capture so a later change to the platform default cannot re-price an existing referral.';

-- --------------------------------------------------------------------
-- C. What was earned
-- --------------------------------------------------------------------

create table if not exists public.referral_commissions (
  id uuid primary key default gen_random_uuid(),

  referral_id uuid not null references public.merchant_referrals (id) on delete restrict,
  -- Denormalised so Super Admin can filter without a join, and so the
  -- record still reads correctly if a referral row is ever corrected.
  referrer_merchant_id uuid not null references public.merchants (id) on delete restrict,
  referred_merchant_id uuid not null references public.merchants (id) on delete restrict,

  period_start_at timestamptz not null,
  period_end_at timestamptz not null,

  -- Gross value of the referred merchant's successful collections in the
  -- window. Used only to test qualification; it is NOT the commission
  -- base.
  successful_volume numeric(14, 2) not null default 0,
  -- What InfinityPay actually kept: credits minus debits on the
  -- platform_revenue ledger account for those transactions. This is the
  -- commission base.
  infinitypay_net_revenue numeric(14, 2) not null default 0,

  commission_rate_bps integer not null check (commission_rate_bps between 0 and 10000),
  commission_amount numeric(14, 2) not null default 0,
  minimum_payout_amount numeric(14, 2) not null,
  currency text not null default 'TZS' check (currency ~ '^[A-Z]{3}$'),

  status text not null default 'accruing'
    check (status in (
      'accruing',
      'below_threshold',
      'pending_review',
      'approved',
      'rejected',
      'paid',
      'cancelled'
    )),

  reviewed_by_admin_id uuid references auth.users (id) on delete set null,
  reviewed_at timestamptz,
  paid_at timestamptz,
  rejection_reason text,

  -- Everything the figure was built from, as it stood when it was built:
  -- transaction counts, the ledger entries summed, the thresholds applied.
  -- A commission that is questioned months later has to be explainable
  -- without replaying the data, which will have moved on.
  calculation_snapshot jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- One commission per referral. The daily job updates this row in place
-- rather than appending, so a recalculation can never create a second
-- payable record for the same referral.
create unique index if not exists referral_commissions_referral_key
  on public.referral_commissions (referral_id);

create index if not exists referral_commissions_referrer_idx
  on public.referral_commissions (referrer_merchant_id, created_at desc);
create index if not exists referral_commissions_status_idx
  on public.referral_commissions (status);

comment on table public.referral_commissions is
  'One row per referral, recalculated in place while still open and frozen once reviewed. Never a payment instruction: marking one paid records that a payout happened elsewhere, it does not move money.';
comment on column public.referral_commissions.infinitypay_net_revenue is
  'Commission base. Sum of credits minus debits on the platform_revenue ledger account for the referred merchant''s collection transactions inside the period, so a reversed collection removes its own fee without a special case.';
comment on column public.referral_commissions.calculation_snapshot is
  'Audit trail of how the figure was reached. Contains no customer PII, no secrets, and no provider payloads.';

-- --------------------------------------------------------------------
-- Row level security
-- --------------------------------------------------------------------
--
-- No policies, matching every other table the backend owns: these are
-- reached only by the service role. A merchant sees their own referral
-- figures through /v1/merchant/referrals, which filters by the session's
-- own merchant_id, never by querying these tables from the browser.

alter table public.merchant_referrals enable row level security;
alter table public.referral_commissions enable row level security;
