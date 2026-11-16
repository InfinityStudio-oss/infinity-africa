-- Prefunded Payout Wallet: the ledger accounts, and the guard that makes
-- them safe to spend from.
--
-- The product shape: a merchant moves settled funds from their Collections
-- balance into a separate Payout Wallet, and a payout API key spends only
-- from that wallet. Collections money and payout money must therefore be
-- different accounts - not a flag on one account - so that a withdrawal and
-- an API payout can never reach the same shilling.
--
-- Three things are added here and nothing is changed for existing money:
--
-- 1. `environment` on ledger_accounts. The ledger has had no environment
--    concept at all. That has been harmless so far because a sandbox
--    collection never reaches the ledger - production holds 115 successful
--    sandbox collections and not one of them has a transactions row, while
--    live collections have one each. Payouts cannot rely on that: a sandbox
--    payout wallet has to hold a balance to be worth testing against, so it
--    needs an account, and that account must not be the live one.
--
--    Every existing row is backfilled to 'live', which is what they all
--    are. The merchant unique index gains `environment`, which is exactly
--    as restrictive as before while every row is 'live' - no existing pair
--    can collide, and no row changes.
--
-- 2. Two new purposes. Both are liabilities: the money belongs to the
--    merchant whichever pocket it sits in, same as merchant_wallet.
--
--      payout_available - prefunded and spendable
--      payout_reserved  - committed to a payout that has not settled
--
-- 3. The negative-balance guard inside post_ledger_entries extended to
--    cover them. That guard is the whole reason concurrent withdrawals
--    cannot overdraw a wallet today (see 20260814140001), and it is
--    hardcoded to purpose = 'merchant_wallet'. Adding accounts without
--    extending it would create two pots of money where only one is
--    protected, and the unprotected one is the one a machine spends from
--    without a human in the loop.
--
-- Additive throughout. No existing row, balance or entry is rewritten.

-- --- 1. environment -------------------------------------------------------

alter table public.ledger_accounts
  add column if not exists environment text not null default 'live'
    check (environment in ('sandbox', 'live'));

comment on column public.ledger_accounts.environment is
  'Which environment this account holds funds for. Every account predating the Payout Wallet is live: sandbox collections have never posted to the ledger. Sandbox payout accounts hold simulated funds and are never dispatched to a real provider.';

-- Same uniqueness as before for every account that exists today (all of
-- them live), and room for one sandbox payout account alongside the live
-- one. Created before the old indexes are dropped so the table is never
-- briefly unprotected.
create unique index if not exists ledger_accounts_merchant_purpose_env_key
  on public.ledger_accounts (merchant_id, purpose, currency, environment)
  where merchant_id is not null;

create unique index if not exists ledger_accounts_platform_purpose_env_key
  on public.ledger_accounts (purpose, currency, environment)
  where merchant_id is null;

drop index if exists public.ledger_accounts_merchant_purpose_key;
drop index if exists public.ledger_accounts_platform_purpose_key;

-- --- 2. the two new purposes ---------------------------------------------

-- Dropped by lookup rather than by name. The original was written inline
-- (`purpose text not null check (...)`), so its name is whatever Postgres
-- generated - almost certainly ledger_accounts_purpose_check, but
-- `drop constraint if exists <guess>` fails SILENTLY when the guess is
-- wrong. The new constraint would then be added BESIDE the old one, the
-- old one would go on rejecting 'payout_available', and the migration
-- would report success while leaving the feature unable to create an
-- account. Finding it instead makes a wrong guess impossible, and the
-- assertion below makes a silent miss impossible too.
do $$
declare
  v_name text;
begin
  for v_name in
    select con.conname
    from pg_constraint con
    join pg_class rel on rel.oid = con.conrelid
    join pg_namespace nsp on nsp.oid = rel.relnamespace
    where nsp.nspname = 'public'
      and rel.relname = 'ledger_accounts'
      and con.contype = 'c'
      and pg_get_constraintdef(con.oid) ilike '%purpose%'
  loop
    execute format('alter table public.ledger_accounts drop constraint %I', v_name);
  end loop;
end
$$;

alter table public.ledger_accounts
  add constraint ledger_accounts_purpose_check check (purpose in (
    'merchant_wallet', 'platform_revenue', 'settlement_clearing',
    'fee_receivable', 'disbursement_payable',
    'payout_available', 'payout_reserved'
  ));

-- Prove the new purposes are actually insertable, rather than assuming the
-- drop above found everything. The probe row never survives: raising
-- inside the inner block rolls the block back to its implicit savepoint,
-- so the insert is undone whichever branch is taken, and PROBE_OK is
-- simply how success exits.
do $$
begin
  begin
    insert into public.ledger_accounts (merchant_id, name, account_type, purpose, currency, environment)
    values (null, 'constraint probe', 'liability', 'payout_available', 'TZS', 'sandbox');
    raise exception 'PROBE_OK';
  exception
    when check_violation then
      raise exception
        'MIGRATION FAILED: a CHECK constraint still rejects payout_available. An older constraint survived the drop above.';
    when others then
      if sqlerrm <> 'PROBE_OK' then
        raise;
      end if;
  end;
end
$$;

-- --- 3. the guard ---------------------------------------------------------

-- Based on 20260828020000, the CURRENT definition - NOT on 20260814140001,
-- which is where the balance check itself was introduced. Copying the
-- older body would have silently dropped the balance_before/balance_after
-- snapshot that 20260828020000 writes onto every entry, and that snapshot
-- is what wallet_balance_after() and _record_wallet_snapshot() read to
-- denormalize a wallet balance onto the transactions row. Nothing would
-- have failed loudly; the snapshots would just have stopped.
--
-- Exactly one line differs from 20260828020000: the list of purposes that
-- may not go negative.
create or replace function public.post_ledger_entries(p_entries jsonb)
returns setof public.ledger_entries
language plpgsql
security definer
set search_path = public
as $$
declare
  v_entry jsonb;
  v_row public.ledger_entries;
  v_account_id uuid;
  v_direction text;
  v_amount numeric(14, 2);
  v_account_type text;
  v_purpose text;
  v_balance numeric(18, 2);
  v_delta numeric(18, 2);
  v_new_balance numeric(18, 2);
begin
  for v_entry in select * from jsonb_array_elements(p_entries)
  loop
    v_account_id := (v_entry ->> 'ledger_account_id')::uuid;
    v_direction := v_entry ->> 'direction';
    v_amount := (v_entry ->> 'amount')::numeric;

    select account_type, purpose, balance into v_account_type, v_purpose, v_balance
    from public.ledger_accounts
    where id = v_account_id
    for update;

    -- Asset/expense accounts increase on debit, decrease on credit;
    -- liability/equity/revenue accounts increase on credit, decrease on debit.
    if v_account_type in ('asset', 'expense') then
      v_delta := case when v_direction = 'debit' then v_amount else -v_amount end;
    else
      v_delta := case when v_direction = 'credit' then v_amount else -v_amount end;
    end if;

    v_new_balance := v_balance + v_delta;

    -- THE ONE CHANGED LINE. payout_available joins merchant_wallet because
    -- it is spendable, and is the pot an API key draws down with no human
    -- approving each call. payout_reserved joins them because a release
    -- that outran its own reservation would invent money: negative there
    -- means more has been released than was ever committed.
    if v_purpose in ('merchant_wallet', 'payout_available', 'payout_reserved')
       and v_new_balance < 0 then
      raise exception 'INSUFFICIENT_BALANCE: account % (%) balance % cannot cover a % of % (would be %)',
        v_account_id, v_purpose, v_balance, v_direction, v_amount, v_new_balance;
    end if;

    insert into public.ledger_entries (
      transaction_id, ledger_account_id, direction, amount, currency, description,
      balance_before, balance_after
    ) values (
      (v_entry ->> 'transaction_id')::uuid,
      v_account_id,
      v_direction,
      v_amount,
      coalesce(v_entry ->> 'currency', 'TZS'),
      v_entry ->> 'description',
      v_balance,
      v_new_balance
    )
    returning * into v_row;

    update public.ledger_accounts
    set balance = v_new_balance
    where id = v_account_id;

    return next v_row;
  end loop;

  return;
end;
$$;

comment on function public.post_ledger_entries(jsonb) is
  'Atomically inserts a batch of ledger_entries (with a balance_before/after snapshot on each) and updates each ledger_accounts.balance in one transaction; rejects the whole batch if it would take a merchant_wallet, payout_available or payout_reserved balance negative.';

revoke execute on function public.post_ledger_entries(jsonb) from public, anon, authenticated;
grant execute on function public.post_ledger_entries(jsonb) to service_role;
