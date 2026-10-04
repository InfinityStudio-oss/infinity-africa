-- Find merchant wallet credits that came from a simulated collection.
--
-- Why this exists: production ran with SELCOM_MODE=mock, which hands out
-- MockSelcomClient. That client resolves a collection to "successful"
-- about nine times in ten, and execute_collection() resolves one the
-- moment it is created — so any collection that went through the legacy
-- push paths during that window credited a real merchant wallet for money
-- no customer ever paid.
--
-- The fingerprint is exact, not a guess. Every client stamps its own name
-- onto collections.provider:
--
--     mock_selcom  -> simulated          (app/services/selcom/mock_client.py)
--     selcom       -> real               (live client, and both Checkout paths)
--
-- So there is no date-range guessing and no risk of catching a genuine
-- payment: a real collection is never labelled 'mock_selcom'.
--
-- Everything here is READ ONLY. Run it in the Supabase SQL editor.
-- Nothing is corrected automatically — see the note at the bottom for why.


-- 1. THE HEADLINE ------------------------------------------------------------
-- How much fake money reached merchant wallets, if any. If this returns
-- zero rows, nothing was simulated and you are done.

select
    count(*)                                   as simulated_credits,
    coalesce(sum(t.net_amount), 0)             as total_credited_to_wallets,
    coalesce(sum(t.fee_amount), 0)             as total_fees_booked,
    min(c.created_at)                          as first_seen,
    max(c.created_at)                          as last_seen
from collections c
join transactions t on t.collection_id = c.id
where c.provider = 'mock_selcom'
  and c.status = 'successful';


-- 2. PER MERCHANT ------------------------------------------------------------
-- Who is affected and by how much. This is the figure to correct against.

select
    m.business_name,
    c.merchant_id,
    count(*)                        as simulated_credits,
    sum(t.net_amount)               as wallet_credited,
    c.currency
from collections c
join transactions t on t.collection_id = c.id
join merchants m     on m.id = c.merchant_id
where c.provider = 'mock_selcom'
  and c.status = 'successful'
group by m.business_name, c.merchant_id, c.currency
order by wallet_credited desc;


-- 3. THE INDIVIDUAL COLLECTIONS ----------------------------------------------
-- The rows themselves, for the audit trail and for reversing.

select
    c.created_at,
    c.id                as collection_id,
    m.business_name,
    c.method,
    c.amount,
    c.currency,
    c.status,
    c.customer_phone,
    c.provider_reference,
    c.source,
    t.id                as transaction_id,
    t.reference         as transaction_reference,
    t.net_amount        as credited_to_wallet,
    t.status            as transaction_status
from collections c
join transactions t on t.collection_id = c.id
join merchants m     on m.id = c.merchant_id
where c.provider = 'mock_selcom'
order by c.created_at desc;


-- 4. EVERYTHING SIMULATED, INCLUDING THE FAILURES ----------------------------
-- The mock fails roughly one time in ten. Those credited nothing, but they
-- still reached a merchant's dashboard as a failed payment and may have
-- been reported to you as a bug that was never real.

select
    c.status,
    count(*)        as collections,
    sum(c.amount)   as total_amount
from collections c
where c.provider = 'mock_selcom'
group by c.status
order by collections desc;


-- 5. CROSS-CHECK AGAINST THE AUDIT LOG ---------------------------------------
-- resolve_collection() writes an append-only audit row for every wallet
-- credit, carrying the provider in its metadata. This should agree with
-- query 1. If it does not, trust this one: audit_logs cannot be updated.

select
    count(*)                                          as credited_events,
    sum((a.metadata ->> 'amount')::numeric)           as total_amount
from audit_logs a
where a.action = 'collection.credited'
  and a.metadata ->> 'provider' = 'mock_selcom';


-- 6. CONFIRM IT IS OVER ------------------------------------------------------
-- After SELCOM_MODE=live is set, no new row should appear here. Run this
-- again the day after and confirm max(created_at) has not moved.

select
    c.provider,
    count(*)            as collections,
    max(c.created_at)   as most_recent
from collections c
group by c.provider
order by collections desc;


-- IF YOU FIND ROWS -----------------------------------------------------------
--
-- Stop and read this before changing anything.
--
-- **There is no supported way to reverse these today.**
-- reverse_successful_collection() exists in app/services/collections.py and
-- does the right thing — posts the opposite ledger entries, marks the
-- transaction reversed, leaves the audit trail intact — but its only
-- caller is the Checkout reconciliation sweep, and that sweep acts on
-- Selcom Checkout collections. A simulated legacy collection has no
-- checkout order, so nothing will ever pick it up on its own. No admin
-- route calls it either.
--
-- So if these queries return rows, the reversal needs a small Super Admin
-- action built for it. That is a deliberate decision to take with the
-- numbers in front of you, not a thing to improvise during a launch.
--
-- Do NOT correct it by hand in SQL. The ledger is double-entry: a
-- simulated credit posted matching entries against the settlement clearing
-- account, so adjusting ledger_accounts.balance leaves the books
-- unbalanced and every later reconciliation disagrees with itself. Deleting
-- the collection row is worse — the ledger entries survive it.
--
-- First check whether the merchant has already withdrawn against the
-- inflated balance (query 2 gives you the merchant ids):
--
--   select d.created_at, d.amount, d.status
--   from disbursements d
--   where d.merchant_id = '<merchant_id>'
--     and d.created_at >= '<first_seen from query 1>'
--   order by d.created_at;
--
-- If they have, real money has already left on the back of a fake credit,
-- and that is a conversation with the merchant before it is a database
-- change. If they have not, the wallet can be put right cleanly.
