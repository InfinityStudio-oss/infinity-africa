-- Webhook events for payouts.
--
-- The Disbursement API emitted nothing at all. Collections notify by
-- webhook; a payout reached a terminal status in silence, so every
-- partner had to poll, and anyone arriving from the Collections API
-- would wait for a callback that was never coming.
--
-- webhook_events.event_name carries a CHECK constraint, so a new name is
-- a migration and not just code. That constraint has bitten this project
-- before: the in-memory test fake does not enforce CHECK, so emitting an
-- unlisted name passes every test and raises an unhandled exception the
-- first time it runs against Postgres. 20260824010000 was written to fix
-- exactly that, for exactly that reason.
--
-- Three names, following the dominant convention in the list
-- (collection.success, disbursement.success) rather than
-- refund.succeeded, which is the odd one out and not worth copying:
--
--   payout.success   confirmed paid by the provider
--   payout.failed    confirmed not paid; the reserve went back
--   payout.reversed  reversed after succeeding
--
-- Nothing is emitted for queued, processing or needs_reconciliation. A
-- payout in flight has no outcome to report, and needs_reconciliation in
-- particular means "we do not know yet" - telling a partner about it
-- would invite exactly the retry that pays twice.

begin;

alter table public.webhook_events
  drop constraint if exists webhook_events_event_name_check;

alter table public.webhook_events
  add constraint webhook_events_event_name_check check (event_name in (
    'collection.pending', 'collection.processing', 'collection.success', 'collection.failed',
    'collection.cancelled', 'collection.reversed', 'collection.pending_review',
    'disbursement.success', 'disbursement.failed', 'disbursement.reversed',
    'invoice.paid', 'invoice.overdue',
    'payment_link.created', 'payment_link.paid', 'payment_link.expired', 'payment_link.payment_reversed',
    'refund.succeeded', 'refund.failed',
    'chargeback.opened', 'chargeback.resolved',
    'payout.success', 'payout.failed', 'payout.reversed'
  ));

-- Prove the new names are insertable rather than assuming the drop found
-- the right constraint. The probe never survives.
do $$
declare
  v_merchant uuid;
begin
  select id into v_merchant from public.merchants limit 1;
  if v_merchant is null then
    return;  -- empty database; nothing to probe against
  end if;
  begin
    insert into public.webhook_events (merchant_id, event_name, payload, target_url, status)
    values (v_merchant, 'payout.success', '{}'::jsonb, 'https://example.invalid/probe', 'pending');
    raise exception 'PROBE_OK';
  exception
    when others then
      if sqlerrm = 'PROBE_OK' then
        null;  -- insertable, and the row is gone
      else
        raise exception 'payout.success is not an accepted event_name: %', sqlerrm;
      end if;
  end;
end
$$;

commit;
