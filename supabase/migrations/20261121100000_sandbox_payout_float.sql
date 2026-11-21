-- A source of play money, so the sandbox stops spending real money.
--
-- --- What was wrong -------------------------------------------------------
--
-- Funding a sandbox payout wallet credited payout_available in `sandbox`
-- and debited merchant_wallet in `live`, because the debit leg never
-- passed the environment through. Real settled shillings left a
-- merchant's Collections balance and landed in a wallet whose payouts are
-- make-believe, with no route to move them back. Commit 175adf7 made both
-- legs take the same environment, which stopped the bleeding - and made
-- sandbox funding impossible, because a sandbox merchant_wallet starts at
-- zero and nothing credits it.
--
-- This is the other half: something for a sandbox transfer to balance
-- against.
--
-- --- The account ----------------------------------------------------------
--
-- One platform-level account (merchant_id is null) per currency, in the
-- sandbox environment only. Funding a sandbox payout wallet debits it and
-- credits the merchant's sandbox payout_available, so the entry balances
-- without any real money being involved.
--
-- It is DELIBERATELY ABSENT from the no-negative guard in
-- post_ledger_entries. The guard covers merchant_wallet, payout_available
-- and payout_reserved, which hold money somebody is owed. This holds the
-- opposite: it goes more negative with every shilling of play money
-- minted, and that balance read back is exactly "how much sandbox money
-- exists". Capping it would cap how much testing a merchant can do, which
-- is the one thing a sandbox should never do.
--
-- An 'equity' account_type rather than a liability, because nobody is owed
-- it. It is the counter-entry for money conjured for testing, and calling
-- it a liability would mean the platform owes someone play shillings.
--
-- --- Why this does not pollute the real numbers ---------------------------
--
-- ledger_accounts.environment already separates sandbox from live, and
-- every merchant-side payout account is scoped by it. The gap was on the
-- PLATFORM side: post_payout_settlement credited settlement_clearing and
-- platform_revenue with no environment at all, so a settled sandbox payout
-- booked a fake fee into live platform revenue. The accompanying code
-- change passes the environment to both, so sandbox settlement lands in
-- sandbox copies of those accounts and real reporting never sees it.
--
-- Note for whoever reads revenue next: admin_overview_money does not
-- filter on environment. It does not need to today, because every sandbox
-- account created from here carries environment = 'sandbox' and the
-- existing live rows are untouched - but a report that sums
-- ledger_accounts without a filter WILL include play money once sandbox
-- accounts exist. Filter environment = 'live' in anything new.

begin;

alter table public.ledger_accounts
  drop constraint if exists ledger_accounts_purpose_check;

alter table public.ledger_accounts
  add constraint ledger_accounts_purpose_check check (purpose in (
    'merchant_wallet', 'platform_revenue', 'settlement_clearing',
    'fee_receivable', 'disbursement_payable',
    'payout_available', 'payout_reserved',
    'sandbox_float'
  ));

comment on constraint ledger_accounts_purpose_check on public.ledger_accounts is
  'sandbox_float is the counter-entry for play money minted into a sandbox payout wallet. It is not in the no-negative guard: it is meant to go negative, and that balance is how much sandbox money exists.';

-- Prove the new purpose is insertable rather than assuming the drop found
-- the right constraint. The probe never survives: the exception rolls the
-- block back to its implicit savepoint whichever branch is taken.
do $$
declare
  v_id uuid;
begin
  begin
    insert into public.ledger_accounts
      (merchant_id, name, account_type, purpose, currency, environment, balance)
    values
      (null, 'PROBE', 'equity', 'sandbox_float', 'TZS', 'sandbox', 0)
    returning id into v_id;
    raise exception 'PROBE_OK';
  exception
    when sql_routine_exception then
      raise;
    when others then
      if sqlerrm = 'PROBE_OK' then
        null;  -- insertable, and the row is gone
      else
        raise exception 'sandbox_float is not insertable: %', sqlerrm;
      end if;
  end;
end
$$;

commit;
