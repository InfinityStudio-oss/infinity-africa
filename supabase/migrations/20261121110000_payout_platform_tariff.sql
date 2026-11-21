-- A platform tariff for payouts, and the ability to tell "free" from
-- "not set".
--
-- --- What was wrong -------------------------------------------------------
--
-- A payout's fee came only from merchant_payout_settings.fee_flat_tzs and
-- fee_percentage, both `not null default 0`. There was no platform rate at
-- all, so every merchant switched on paid nothing, and the only way to
-- charge was to edit each merchant by hand. Collections and withdrawals
-- both have a platform fallback (merchant_id is null in their rules
-- tables); payouts were the odd one out.
--
-- `not null default 0` also makes two different things look identical: a
-- merchant nobody has priced yet, and a merchant deliberately given free
-- payouts. The same shape caused a real outage of judgement elsewhere in
-- this product - a missing merchant_notification_settings row means
-- "enabled", so "never configured" and "deliberately on" were
-- indistinguishable and a merchant kept receiving email nobody had
-- chosen for them.
--
-- So: the per-merchant columns become nullable, where NULL means "no
-- negotiated rate, use the platform tariff" and 0 means "priced at zero,
-- on purpose". One row holds the tariff.

begin;

-- --- the per-merchant override ------------------------------------------

alter table public.merchant_payout_settings
  alter column fee_flat_tzs drop not null,
  alter column fee_percentage drop not null;

-- The existing CHECKs were written against non-null values. Postgres
-- evaluates a CHECK to NULL (and so passes it) when an input is NULL, so
-- they keep working unchanged - but say so explicitly rather than leaving
-- the next reader to work it out.
comment on column public.merchant_payout_settings.fee_percentage is
  'Negotiated percentage for this merchant. NULL means no negotiated rate: the platform tariff in payout_platform_pricing applies. 0 means priced at zero on purpose.';
comment on column public.merchant_payout_settings.fee_flat_tzs is
  'Negotiated flat fee for this merchant. NULL means no negotiated rate: the platform tariff applies. 0 means priced at zero on purpose.';

-- Rows created before a tariff existed carry 0/0 because that was the
-- default, not because anyone chose it. Narrowed to rows no administrator
-- has ever edited (updated_by is null), so a deliberate zero - which can
-- only have been set through the admin API, which stamps updated_by -
-- survives untouched.
update public.merchant_payout_settings
   set fee_flat_tzs = null,
       fee_percentage = null
 where updated_by is null
   and coalesce(fee_flat_tzs, 0) = 0
   and coalesce(fee_percentage, 0) = 0;

-- --- the platform tariff -------------------------------------------------

create table if not exists public.payout_platform_pricing (
  -- One row, forever. Same trick as withdrawal_automation_policy: a
  -- boolean primary key that must be true can hold exactly one value.
  id boolean primary key default true check (id),

  -- Applies to every payout destination - every mobile money network and
  -- every bank. Deliberately NOT per-destination: Selcom's own code list
  -- has already changed once under this product (see collections.channel,
  -- where 070 turned out to be Mixx by Yas and not Vodacom), and a tariff
  -- keyed on their codes would turn their next change into a pricing bug.
  -- A per-destination rate, if it is ever wanted, belongs in its own
  -- table with its own effective dates.
  percentage_fee numeric(6, 4) not null default 1
    check (percentage_fee >= 0 and percentage_fee <= 100),
  flat_fee numeric(14, 2) not null default 0 check (flat_fee >= 0),

  -- Optimistic concurrency, same shape and reason as
  -- merchant_payout_settings.version.
  version integer not null default 1 check (version > 0),

  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users (id) on delete set null
);

comment on table public.payout_platform_pricing is
  'The default payout fee, applied to any merchant with no negotiated rate of their own. One row. Covers every destination - all mobile money networks, Selcom Pesa and all banks alike.';

alter table public.payout_platform_pricing enable row level security;

-- Deny-all: this is read and written by the API with the service role,
-- never by a merchant session. A merchant seeing the platform's margin
-- structure is not a feature.
-- (No policies declared, which is deny-all under RLS.)

insert into public.payout_platform_pricing (id, percentage_fee, flat_fee)
values (true, 1, 0)
on conflict (id) do nothing;

commit;
