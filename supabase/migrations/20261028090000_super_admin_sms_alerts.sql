-- Super Admin SMS alerts: a new merchant registering, and a withdrawal
-- entering the approval queue.
--
-- PREPARED, NOT APPLIED. Apply before deploying the code that writes
-- these rows; the purpose check constraint rejects them until then.
--
-- The existing sms_messages table was built for messages *to merchants* -
-- its own comment says so, and merchant_id is NOT NULL because the
-- recipient was always the merchant. These two alerts go to an operator
-- instead, and the brief is explicit that the administrator must not be
-- pretended into the merchant model.
--
-- So merchant_id keeps its meaning for the new rows, but as the SUBJECT
-- rather than the recipient: the merchant who registered, or the merchant
-- whose withdrawal is waiting. recipient_role is what says who the
-- message is actually addressed to, and it is what any merchant-facing
-- reader must filter on. Nothing in the Merchant Portal reads this table
-- today (there is deliberately no merchant select policy), so this is a
-- guard for the reader that does not exist yet.

-- 1. Who the message is addressed to -----------------------------------

alter table public.sms_messages
  add column if not exists recipient_role text not null default 'merchant';

do $$
begin
  alter table public.sms_messages
    add constraint sms_messages_recipient_role_check
    check (recipient_role in ('merchant', 'super_admin'));
exception
  when duplicate_object then null;
end $$;

comment on column public.sms_messages.recipient_role is
  'Who this message is addressed to. merchant: the subject and the recipient are the same business. super_admin: an operator alert ABOUT merchant_id, never shown to that merchant. Any merchant-facing reader must filter recipient_role = ''merchant''.';

-- 2. The two new purposes ----------------------------------------------

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
    'announcement',
    -- Added 2026-10-28, both addressed to recipient_role = 'super_admin'.
    -- Once per merchant, when the account is first persisted. Registered
    -- is NOT approved and NOT KYC-verified; the message says so.
    'admin_new_merchant',
    -- Once per withdrawal, and only when it comes to rest at
    -- PENDING_ADMIN_APPROVAL. A withdrawal that is auto-processed or
    -- rejected never reaches that state, so it never produces this row.
    'admin_withdrawal_request'
  ));

-- 3. Duplicate protection, in the database ------------------------------
--
-- The brief asks for this to be atomic rather than a check-then-insert in
-- application memory, and for the identity to include the recipient so
-- configuring a second operator number does not silently drop their copy.
--
-- sms_messages_idempotency_key_key (unique, already present) is the real
-- guarantee: the key is derived from purpose + anchor + recipient, so a
-- concurrent second attempt loses the insert rather than racing. These
-- partial indexes state the same rule in the table's own terms, so the
-- constraint is legible to someone reading the schema rather than only to
-- someone reading the key-building function.

create unique index if not exists sms_messages_one_admin_alert_per_merchant
  on public.sms_messages (merchant_id, recipient_phone, purpose)
  where purpose = 'admin_new_merchant';

create unique index if not exists sms_messages_one_admin_alert_per_withdrawal
  on public.sms_messages (disbursement_id, recipient_phone, purpose)
  where purpose = 'admin_withdrawal_request' and disbursement_id is not null;

-- 4. The worker's claim query ------------------------------------------
--
-- Unchanged on purpose. The existing claimable index is on
-- (purpose, created_at) where status in ('queued','failed'), which covers
-- the new purposes without modification, and the worker's ordering
-- already prefers transactional purposes over 'announcement'.

-- Rollback
-- --------
-- These alerts stop being produced the moment SUPER_ADMIN_SMS_ENABLED is
-- false; no schema change is needed to switch them off, and that is the
-- rollback to reach for first.
--
-- To undo the schema itself:
--   drop index if exists public.sms_messages_one_admin_alert_per_withdrawal;
--   drop index if exists public.sms_messages_one_admin_alert_per_merchant;
--   -- restore the previous purpose list (without the two 'admin_' values)
--   -- and only then:
--   alter table public.sms_messages drop column if exists recipient_role;
--
-- Dropping the column while rows carrying the new purposes still exist
-- would leave operator alerts indistinguishable from merchant messages,
-- so delete or re-purpose those rows first.
