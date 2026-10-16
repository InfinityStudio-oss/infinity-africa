-- Merchant SMS becomes two lifecycle messages instead of one per payment.
--
-- The collection alert shipped on 2026-10-16 and was proven working the
-- same evening. It is being withdrawn for cost: the platform took 3,748
-- payments in the first sixteen days of October, so alerting on every one
-- is roughly 230 messages a day and climbing with volume. Two messages
-- per merchant lifecycle - welcome on approval, confirmation on a
-- completed payout - carry most of the reassurance at a tiny fraction of
-- that.
--
-- Collection *emails* are untouched and keep working exactly as they do.
--
-- Nothing here touches money. No ledger table, no transactions column, no
-- balance. sms_messages still only ever *copies* financial values for
-- display and is never read back by any financial path.

-- 1. The two new kinds of message ---------------------------------------
--
-- 'collection_alert' stays in the check constraint on purpose. Rows
-- already sent are history and must keep validating; dropping the value
-- would make an existing row unrepresentable the moment anything updated
-- it.

alter table public.sms_messages
  drop constraint if exists sms_messages_purpose_check;

alter table public.sms_messages
  add constraint sms_messages_purpose_check check (purpose in (
    -- Retired 2026-10-17, retained so historical rows stay valid.
    'collection_alert',
    -- Once per merchant, after their first approval.
    'welcome',
    -- Once per withdrawal, after the provider confirms the payout.
    'withdrawal_complete',
    'announcement'
  ));

-- 2. Which payout a message belongs to ----------------------------------

alter table public.sms_messages
  add column if not exists disbursement_id uuid references public.disbursements (id) on delete set null;

comment on column public.sms_messages.disbursement_id is
  'The payout a withdrawal_complete message confirms. Null for every other purpose.';

-- 3. Cancelling, as distinct from failing -------------------------------
--
-- A queued collection alert that we have decided not to send is neither
-- failed nor skipped: nothing went wrong and nothing was refused. It
-- needs its own terminal state so the Super Admin screen can say what
-- actually happened, and so the worker's claim query ignores it.

alter table public.sms_messages
  drop constraint if exists sms_messages_status_check;

alter table public.sms_messages
  add constraint sms_messages_status_check check (status in (
    'queued', 'sending', 'sent', 'pending', 'failed', 'skipped', 'unknown',
    -- Deliberately not sent, with a reason. Terminal.
    'cancelled'
  ));

-- 4. The uniqueness the brief asks for, in the database -----------------
--
-- Both are partial indexes so they constrain only the purpose they name,
-- and both sit in Postgres rather than in whichever code path happens to
-- run first - the same argument as the existing one-alert-per-collection
-- index, and for the same reason: approval can be retried and a payout
-- can be confirmed by both a callback and the reconciliation sweep at
-- once.

-- One welcome per merchant, for all time. A merchant suspended and later
-- reactivated has already been welcomed.
create unique index if not exists sms_messages_one_welcome_per_merchant
  on public.sms_messages (merchant_id)
  where purpose = 'welcome';

-- One confirmation per payout.
create unique index if not exists sms_messages_one_completion_per_withdrawal
  on public.sms_messages (disbursement_id)
  where purpose = 'withdrawal_complete' and disbursement_id is not null;

create index if not exists sms_messages_disbursement_id_idx
  on public.sms_messages (disbursement_id);

-- 5. Stop the queued collection alerts ----------------------------------
--
-- Only rows that have not been offered to the provider. 'sending' is
-- deliberately excluded: that row is in a worker's hands right now, its
-- provider call may already be in flight, and a message the gateway has
-- accepted cannot be recalled - pretending otherwise would be worse than
-- letting one extra text arrive. The worker's own claim is what settles
-- those; they reach a terminal state on their own within one lease.
--
-- 'sent', 'pending' and 'unknown' are likewise untouched: all three mean
-- the provider may already hold the message, and all three are history.
--
-- Run this AFTER deploying the code that stops enqueueing new ones, or
-- the gap between the two refills the queue.
update public.sms_messages
set status = 'cancelled',
    skipped_reason = 'Collection SMS was retired on 2026-10-17; this message was never sent'
where purpose = 'collection_alert'
  and status in ('queued', 'failed');
