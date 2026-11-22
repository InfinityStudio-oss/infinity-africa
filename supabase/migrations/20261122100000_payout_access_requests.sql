-- Let a merchant ask for payout access, and let Super Admin see who asked.
--
-- Until now the merchant's Payouts page was a dead end: "contact
-- InfinityPay support to start in the sandbox", with nothing to click
-- and no address. Nothing reached anyone, and there was no record of who
-- had asked, so the first step of the pilot depended on the merchant
-- already knowing somebody.
--
-- No new table. merchant_payout_settings already carries exactly the
-- right meaning - a row means "this merchant is manageable", not "this
-- merchant is allowed", which is why create_payout_access writes one
-- with every flag off. A request is that same row, stamped. The merchant
-- then appears in the Super Admin queue they would have to appear in
-- anyway, and granting stays one deliberate click.
--
-- Nothing here grants anything. Both columns are nullable and default
-- null, and no existing row is touched.

begin;

alter table public.merchant_payout_settings
  add column if not exists access_requested_at timestamptz,
  add column if not exists access_requested_by uuid references auth.users (id) on delete set null;

comment on column public.merchant_payout_settings.access_requested_at is
  'When the merchant asked for payout access. Null means they never asked - which is different from being refused, and different again from being granted.';
comment on column public.merchant_payout_settings.access_requested_by is
  'The merchant user who asked. Kept so an operator can see who to reply to, and set null if that user is ever removed.';

-- Partial, because the question this index answers is always "who is
-- waiting" - a request that has been granted is history, and the queue
-- should not get slower as the granted list grows.
create index if not exists merchant_payout_settings_awaiting_idx
  on public.merchant_payout_settings (access_requested_at desc)
  where access_requested_at is not null
    and sandbox_enabled = false
    and live_enabled = false;

commit;
