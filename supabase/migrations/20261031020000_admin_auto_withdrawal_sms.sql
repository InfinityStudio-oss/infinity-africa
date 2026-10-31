-- Tell an operator when money left without them.
--
-- Withdrawal automation went live on 2026-10-31 and the first automatic
-- payout went through at 19:30 EAT. The merchant was notified, as always.
-- The operator was not, and that is not an oversight anywhere - it is two
-- correct decisions meeting badly:
--
--   * admin_withdrawal_request is sent only when a withdrawal comes to
--     rest at PENDING_ADMIN_APPROVAL, because its text says "linasubiri
--     idhini yako" - awaiting your approval - and saying that about a
--     payout already on its way is worse than saying nothing.
--   * The approval email is sent for every request and links to the
--     approval queue, so for an automatic payout it asks a human to go
--     and approve money that has already gone.
--
-- Both were right while every withdrawal needed a human. Together, with
-- automation on, they mean an operator gets silence from SMS and a
-- misleading instruction by email for roughly five payouts a day.
--
-- So: a separate purpose with its own text, for the one event the
-- existing alerts cannot describe. It is an alert ABOUT a merchant,
-- addressed to recipient_role = 'super_admin', and is never shown to that
-- merchant - same shape as the two purposes added on 2026-10-28.
--
-- Nothing here sends anything. The application will not write a row of
-- this purpose until SUPER_ADMIN_SMS_ENABLED is on, and the purpose check
-- constraint would reject it until this migration is applied - which is
-- why the migration goes first.
--
-- ROLLBACK: set SUPER_ADMIN_SMS_WITHDRAWAL_AUTO_ENABLED=false, which stops
-- the messages without touching the schema. Reverting the constraint
-- itself would invalidate any row already written with this purpose, so it
-- is not part of a rollback; the list below is additive and every value
-- that was valid before is still valid.

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
    'admin_withdrawal_request',
    -- Added 2026-10-31, also recipient_role = 'super_admin'. The exact
    -- complement of the row above: once per withdrawal that the
    -- automation policy sent to the provider without a human, and only
    -- once it has actually reached the provider. The two are mutually
    -- exclusive by construction - a withdrawal is either waiting for an
    -- operator or it is not - so no payout can produce both and none can
    -- produce neither.
    'admin_withdrawal_auto'
  ));

comment on constraint sms_messages_purpose_check on public.sms_messages is
  'The closed set of message kinds. admin_* rows are operator alerts about a merchant and are never shown to that merchant; see recipient_role.';
