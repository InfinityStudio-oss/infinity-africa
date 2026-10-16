-- Merchant SMS: transactional collection alerts, and Super Admin announcements.
--
-- Recipients are MERCHANTS ONLY. Nothing here can address a payer: every
-- recipient is resolved from merchant_notification_settings.sms_notification_phone
-- or merchants.contact_phone, and collections.customer_phone is never read
-- by any of it. That is a property of the schema, not only of the code -
-- sms_messages has no column that could hold a customer number.
--
-- **Nothing in this file touches money.** No ledger table, no transactions
-- column, no balance. sms_messages *copies* financial values for display
-- in a message and is never read back by any financial path. An SMS that
-- fails, duplicates or never sends cannot change what a merchant is owed.
--
-- Deployment order: apply this migration BEFORE deploying the API that
-- reads it. The dispatch worker is additionally gated behind
-- OASIS_SMS_ENABLED (default false), so the API is safe to deploy with
-- the migration applied and the flag off - which is the intended rollout.

-- 1. Where a merchant wants transactional SMS ---------------------------
--
-- On merchant_notification_settings rather than a new table: that row
-- already exists per merchant, already has a collection_notifications_enabled
-- flag for the email equivalent, and is already rendered by both the
-- Merchant Portal notification card and the Super Admin notification view.
-- A parallel table would mean a second join and a second place to forget.

alter table public.merchant_notification_settings
  add column if not exists collection_sms_enabled boolean not null default false,
  add column if not exists sms_notification_phone text,
  add column if not exists announcement_sms_enabled boolean not null default true,
  add column if not exists sms_phone_updated_by uuid references auth.users (id) on delete set null,
  add column if not exists sms_phone_updated_at timestamptz;

comment on column public.merchant_notification_settings.collection_sms_enabled is
  'Transactional collection alerts. Defaults FALSE: enabling SMS for 60 live merchants at once is a cost and consent decision, not a deployment side effect.';
comment on column public.merchant_notification_settings.sms_notification_phone is
  'E.164 destination for this merchant''s own alerts. NULL falls back to merchants.contact_phone. Never a payer number.';
comment on column public.merchant_notification_settings.announcement_sms_enabled is
  'Super Admin announcements. Separate from collection_sms_enabled on purpose: a merchant opting out of marketing must not thereby stop their own payment alerts, and vice versa.';
comment on column public.merchant_notification_settings.sms_phone_updated_by is
  'Who last changed the destination number. A number change redirects a merchant''s payment alerts, so it is attributable - the audit_logs entry carries the masked before/after.';

-- 2. The messages themselves --------------------------------------------
--
-- One table for the queue, the delivery state and the history. Same shape
-- as webhook_events (20260814090014), which has carried outbound delivery
-- for this platform since launch, plus the two things that table lacks and
-- an SMS needs: a frozen financial snapshot and a provider idempotency key.

create table if not exists public.sms_messages (
  id uuid primary key default gen_random_uuid(),

  merchant_id uuid not null references public.merchants (id) on delete cascade,

  -- 'collection_alert' is transactional and always wins a worker slot;
  -- 'announcement' is bulk and yields to it. See the worker.
  purpose text not null check (purpose in ('collection_alert', 'announcement')),

  collection_id uuid references public.collections (id) on delete set null,
  transaction_id uuid references public.transactions (id) on delete set null,
  campaign_id uuid,

  -- Frozen before the first attempt and never rewritten. A retry must
  -- resend the identical bytes under the identical key, or the provider
  -- cannot tell a retry from a second message.
  recipient_phone text not null,
  sender_id text not null,
  body text not null,

  -- The financial snapshot this message quotes, copied at enqueue time
  -- from the committed ledger_entries row for this transaction's merchant
  -- wallet leg. Display-only, never read back by a financial path.
  --
  -- closing_balance comes from ledger_entries.balance_after, which is
  -- written once by post_ledger_entries() under the same row lock as the
  -- balance check (20260828020000) and is immutable afterwards. It is
  -- deliberately NOT transactions.balance_after: that column is documented
  -- (20260828030000) as tracking the MOST RECENT posting, so a later
  -- reversal rewrites it - which would silently change the number in a
  -- message already queued or already sent.
  currency text not null default 'TZS' check (currency ~ '^[A-Z]{3}$'),
  gross_amount numeric(14, 2),
  fee_amount numeric(14, 2),
  net_amount numeric(14, 2),
  closing_balance numeric(18, 2),
  reference text,

  status text not null default 'queued' check (status in (
    -- queued      : waiting for a worker
    -- sending     : claimed by a worker, provider call in flight
    -- sent        : gateway ACCEPTED it (200). NOT a handset receipt.
    -- pending     : 202 - provider could not confirm in time. Most likely
    --               sent and charged; never resend.
    -- failed      : provider refused it. Not charged.
    -- skipped     : never offered to the provider, with a reason.
    -- unknown     : we called the provider and never learned the outcome.
    --               Distinct from 'failed' on purpose - a failure is safe
    --               to retry, an unknown is not, because the message may
    --               already be on its way.
    'queued', 'sending', 'sent', 'pending', 'failed', 'skipped', 'unknown'
  )),

  -- Why nothing was sent, in words an operator can act on: no number on
  -- file, number failed validation, merchant has alerts off, no closing
  -- balance snapshot available. Shown in the Super Admin SMS screen.
  skipped_reason text,

  attempts int not null default 0 check (attempts >= 0),
  last_error text,
  -- Defaults to now() rather than NULL so "due" is always a plain
  -- comparison. A nullable due-time forces every reader into
  -- "null OR <= now", which is easy to get wrong and easy to forget.
  next_attempt_at timestamptz not null default now(),

  -- Worker claim. A crashed worker's claim expires and the row returns to
  -- the pool; see the partial index below.
  locked_by text,
  locked_until timestamptz,

  -- Provider's own identifiers, kept for reconciliation against GET /v1/logs.
  idempotency_key text not null,
  provider_sms_log_id text,
  provider_ref text,
  provider_status text,
  credits_used numeric(10, 2),
  segments int,
  encoding text,

  -- Set when a provider callback (sms.delivered / sms.pending / sms.failed)
  -- arrives. Callbacks can overtake the send response, so the worker must
  -- not clobber a newer callback state with an older send result.
  provider_event_at timestamptz,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  sent_at timestamptz
);

comment on table public.sms_messages is
  'Outbound SMS to MERCHANTS - transactional collection alerts and Super Admin announcements. Never addressed to a payer. Financial columns are a display snapshot and are never read back by a financial path.';

-- The duplicate-protection the brief asks for, enforced by the database
-- rather than by whichever code path happens to run first.
--
-- Two signals routinely resolve the same collection at once: the Selcom
-- callback and the reconciliation sweep. Both funnel through
-- resolve_collection(), whose own guard already prevents a double ledger
-- credit - this is the equivalent guarantee for the message, so that a
-- race which does slip past produces one alert, not two.
--
-- Partial, so it constrains collection alerts only: announcements legitimately
-- send many messages to one merchant over time.
create unique index if not exists sms_messages_one_alert_per_collection
  on public.sms_messages (collection_id, merchant_id, purpose)
  where purpose = 'collection_alert' and collection_id is not null;

-- The provider's key must be unique on our side too, or a bug that reused
-- one would be reported by the provider as an idempotent replay and look
-- to us like a success for a message we never composed.
create unique index if not exists sms_messages_idempotency_key_key
  on public.sms_messages (idempotency_key);

-- The worker's claim query: oldest unclaimed work first, alerts before
-- announcements.
create index if not exists sms_messages_claimable_idx
  on public.sms_messages (purpose, created_at)
  where status in ('queued', 'failed');

create index if not exists sms_messages_merchant_id_idx on public.sms_messages (merchant_id);
create index if not exists sms_messages_campaign_id_idx on public.sms_messages (campaign_id);
create index if not exists sms_messages_status_idx on public.sms_messages (status);
create index if not exists sms_messages_provider_log_idx on public.sms_messages (provider_sms_log_id);

-- drop-then-create rather than a bare create: the rest of this file is
-- idempotent, and a trigger that errors on a second run would make a
-- partial failure impossible to simply re-run.
drop trigger if exists sms_messages_set_updated_at on public.sms_messages;
create trigger sms_messages_set_updated_at
  before update on public.sms_messages
  for each row execute function public.set_updated_at();

alter table public.sms_messages enable row level security;

-- Default deny, same as every other table the backend owns: reached only
-- by the service role. Deliberately NO merchant-facing select policy -
-- nothing in the Merchant Portal reads this table today, and a policy
-- added speculatively is a policy nobody has thought about.

-- 3. Announcements ------------------------------------------------------

create table if not exists public.sms_campaigns (
  id uuid primary key default gen_random_uuid(),

  title text not null,
  body text not null,

  -- draft     : editable, never dispatches. The brief's hard rule.
  -- sending   : recipients frozen, worker dispatching.
  -- sent      : every message reached a terminal state.
  -- cancelled : stopped before dispatch.
  --
  -- There is no transition back to 'draft'. A sent campaign that stayed
  -- editable as an unsent draft is exactly how a second send happens.
  status text not null default 'draft'
    check (status in ('draft', 'sending', 'sent', 'cancelled')),

  -- What was asked for, kept for the history view. The recipients that
  -- actually matter are the sms_messages rows, frozen at dispatch.
  filters jsonb not null default '{}'::jsonb,

  recipient_count int not null default 0 check (recipient_count >= 0),
  excluded_count int not null default 0 check (excluded_count >= 0),
  estimated_segments int,
  estimated_credits numeric(10, 2),

  created_by uuid references auth.users (id) on delete set null,
  dispatched_by uuid references auth.users (id) on delete set null,
  dispatched_at timestamptz,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.sms_campaigns is
  'Super Admin SMS announcements to merchants. A draft never dispatches; dispatch freezes recipients into sms_messages and the campaign can never return to draft.';
comment on column public.sms_campaigns.estimated_credits is
  'Our own estimate from the rendered text, not a provider-confirmed quote. The provider dry-run is what confirms cost.';

create index if not exists sms_campaigns_status_idx on public.sms_campaigns (status, created_at desc);

-- drop-then-create rather than a bare create: the rest of this file is
-- idempotent, and a trigger that errors on a second run would make a
-- partial failure impossible to simply re-run.
drop trigger if exists sms_campaigns_set_updated_at on public.sms_campaigns;
create trigger sms_campaigns_set_updated_at
  before update on public.sms_campaigns
  for each row execute function public.set_updated_at();

alter table public.sms_campaigns enable row level security;

-- Added after sms_campaigns exists, rather than inline above, because
-- sms_messages is created first. Guarded so re-running this file is a
-- no-op instead of an error.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'sms_messages_campaign_fk'
  ) then
    alter table public.sms_messages
      add constraint sms_messages_campaign_fk
      foreign key (campaign_id) references public.sms_campaigns (id) on delete set null;
  end if;
end $$;

-- 4. Provider callbacks -------------------------------------------------
--
-- The provider retries a failed callback at 1min, 5min, 30min, 2h and 12h,
-- so the same event id arrives repeatedly and must be idempotent. The
-- unique event_id is what makes acknowledging safe.

create table if not exists public.sms_provider_events (
  id uuid primary key default gen_random_uuid(),
  event_id text not null unique,
  event_name text not null,
  sms_message_id uuid references public.sms_messages (id) on delete set null,
  provider_sms_log_id text,
  payload jsonb not null default '{}'::jsonb,
  received_at timestamptz not null default now()
);

comment on table public.sms_provider_events is
  'Raw provider callbacks, deduplicated by the provider event id. Kept so a callback that arrives before its send result is saved can be replayed against the message once it exists.';

create index if not exists sms_provider_events_log_idx on public.sms_provider_events (provider_sms_log_id);

alter table public.sms_provider_events enable row level security;

-- 5. The worker's lease -------------------------------------------------
--
-- Same mechanism as every other sweep (20261016120000). This is what makes
-- the in-process rate limiter correct: only one replica dispatches SMS at
-- a time, so a per-process limiter IS the account-wide limiter. If this
-- row were ever removed, the 300/min account limit would be enforced per
-- replica instead of in total.
insert into public.scheduler_leases (name, expires_at)
values ('sms_dispatch', now())
on conflict (name) do nothing;
