-- One email a day instead of one per payment.
--
-- The merchant collection notification has only ever had two states:
-- every successful payment, or nothing. Measured on 2026-11-01, that
-- meant 30,135 emails in thirty days across 70 businesses — and for the
-- largest one, 16,215 of them, which is 540 a day, one every two and a
-- half minutes around the clock. Merchants started asking for it to
-- stop, and five had already switched themselves off before the setting
-- became a Super Admin control.
--
-- Switching off is a poor answer: a merchant who does it loses every
-- email view of money arriving. They do not want silence, they want to
-- not be pinged 540 times. So the choice stops being binary.
--
-- Two other reasons this is worth doing, neither of them about
-- annoyance:
--   * Cost. Thirty thousand emails a month is a real line item.
--   * Deliverability. Hundreds of near-identical messages a day to one
--     Gmail address is how a sending domain gets spam-foldered, and it
--     would take the verification and password-reset emails down with
--     it. That is the one that actually bites.
--
-- NOT a second copy of the on/off state. collection_notifications_enabled
-- stays the master switch and keeps its meaning exactly: false is still
-- off, and this column is not consulted. The new column only says, when
-- notifications ARE on, how often they arrive. Writing "off" into a
-- frequency as well would give two fields a say over the same question
-- and let them disagree.
--
-- Defaults to 'per_payment', so every existing merchant keeps the
-- behaviour they have today and this migration changes nothing for
-- anyone until a Super Admin chooses otherwise.
--
-- ROLLBACK: set every row back to 'per_payment' (or drop the column —
-- the API treats an unreadable/absent value as per_payment, which is the
-- behaviour that existed before this). No merchant preference, delivery
-- record or financial row is touched by any of that.

alter table public.merchant_notification_settings
  add column if not exists collection_notification_frequency text not null default 'per_payment';

alter table public.merchant_notification_settings
  drop constraint if exists merchant_notification_settings_frequency_check;

alter table public.merchant_notification_settings
  add constraint merchant_notification_settings_frequency_check
  check (collection_notification_frequency in ('per_payment', 'daily_summary'));

comment on column public.merchant_notification_settings.collection_notification_frequency is
  'How often collection notification emails arrive while collection_notifications_enabled is true: per_payment (one per successful collection, the default and the historical behaviour) or daily_summary (one message a day covering the previous Dar es Salaam day). Ignored entirely when notifications are disabled — that remains collection_notifications_enabled''s job alone.';

-- One summary per merchant per day, enforced by the database rather than
-- by the sender remembering.
--
-- The sweep runs on a timer across replicas, so "have we already sent
-- today's?" cannot be a question answered in application memory: two
-- replicas waking together would both read "no" and both send. A unique
-- row is the only answer that holds, and inserting it is what claims the
-- day.
create table if not exists public.merchant_daily_notification_summaries (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references public.merchants (id) on delete cascade,

  -- The Dar es Salaam calendar day being reported, not the day the email
  -- was sent. Those differ: the summary for Monday goes out on Tuesday
  -- morning, and keying on the send date would let a retry after
  -- midnight send Monday's figures twice.
  summary_date date not null,

  collection_count integer not null default 0,
  gross_amount numeric(14, 2) not null default 0,
  currency text not null default 'TZS',

  recipient_email text,
  -- 'sent' | 'failed' | 'skipped'. The row exists either way: a failed
  -- send that left no record would be retried forever, and a skipped one
  -- that left no record would be re-evaluated every tick.
  status text not null default 'sent',
  detail text,

  created_at timestamptz not null default now(),

  constraint merchant_daily_notification_summaries_once_per_day
    unique (merchant_id, summary_date)
);

comment on table public.merchant_daily_notification_summaries is
  'One row per merchant per reported day. The unique constraint is the deduplication: the sweep claims a day by inserting, so two replicas cannot both send it. Not a financial record — it reports figures read from transactions and is never read back by anything that moves money.';

create index if not exists merchant_daily_notification_summaries_date_idx
  on public.merchant_daily_notification_summaries (summary_date desc);

-- Same default-deny shape as every other table the backend owns: RLS on
-- with no policies, so anon and authenticated reach nothing and only the
-- service role (which bypasses RLS) can read or write.
alter table public.merchant_daily_notification_summaries enable row level security;

revoke all on table public.merchant_daily_notification_summaries from anon;
revoke all on table public.merchant_daily_notification_summaries from authenticated;
grant select, insert on table public.merchant_daily_notification_summaries to service_role;

-- The sweep that sends them, claimed one replica at a time like every
-- other scheduled job here. Seeded already expired so the first tick
-- after deploy can take it.
insert into public.scheduler_leases (name, expires_at)
values ('daily_notification_summary', now())
on conflict (name) do nothing;
