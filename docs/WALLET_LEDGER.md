# Wallet Ledger

What a merchant sees at `/portal/wallet`, and where each column comes
from. For how ledger entries are *posted* (double-entry, balance
snapshots, immutability) see
[`docs/ledger-reconciliation.md`](./ledger-reconciliation.md); this
document is about the read side.

## Columns

| Column | Source |
|---|---|
| Date | `ledger_entries.created_at`, rendered in Dar es Salaam time |
| Transaction ID | `ledger_entries.transaction_id` (first 8 chars) |
| Type / Reference / Provider Reference / Payment Method / Charge / Net / Status | joined from the entry's `transactions` row |
| Payer Phone | joined through `transactions.collection_id` → `collections.customer_phone` |
| Opening / Closing Balance | `ledger_entries.balance_before/balance_after`, with a replay fallback for rows posted before those columns existed |
| Amount, Direction | `ledger_entries.amount` / `.direction` |

All of it is assembled in
`app/services/ledger.py::_wallet_ledger_entries`, which both the paged
API (`GET /v1/merchant/wallet/ledger`) and the Excel export
(`GET /v1/merchant/wallet/ledger/export`) call — so the two can never
disagree about a row.

## Payer phone (2026-09-27)

A merchant reading their wallet could see money arriving but not who
sent it; matching a credit to a customer meant opening the Collections
page and comparing amounts and timestamps. The ledger row now carries
the paying customer's phone number, in the portal table and as a
**Payer Phone** column in the Excel export.

### It is resolved on read, not stored on the entry

The phone is looked up through the entry's transaction to its
collection, in one batched query per page — not copied onto
`ledger_entries` when the entry is posted. Three reasons:

- **The money path stays untouched.** Writing the phone at posting time
  would mean changing `post_ledger_entries`
  (`supabase/migrations/20260828020000_post_ledger_entries_balance_snapshot.sql`),
  the function that also performs the balance check and captures the
  balance snapshot. That is the single riskiest piece of SQL in the
  system, and this is a presentational field. No migration was needed
  and no money-movement code changed.
- **It cannot drift.** `collections.customer_phone` is already the
  record of who paid. A copy on the ledger could disagree with it after
  a correction; a lookup cannot.
- **History works immediately.** Every entry ever posted shows a phone
  as soon as this deploys. A stored column would have shown null for
  everything older than the deploy until someone wrote a backfill.

The cost is one extra batched query per ledger page, against an indexed
primary key (`collections.id`). `_wallet_ledger_entries` already reads
the full history per request to compute running balances, so this does
not change the shape of that trade-off.

### When it is empty

`—` in the portal, blank in the export, `null` in the API. Never
guessed, never substituted with the merchant's own number:

- **Withdrawals** — a payout goes to the merchant's own destination.
  There is no payer.
- **Dynamic QR** — no phone is captured when a customer scans (see the
  column comment in
  `supabase/migrations/20260814090009_collections.sql`).
- **Entries with no linked collection** — adjustments, refunds and
  reversals posted against a transaction that has no `collection_id`.

### The same number appears on Transactions

The Transactions page (`/portal/transactions`) and its detail drawer show
the same **Payer Phone**, resolved the same way through
`app/services/payer_lookup.py`, and it is a column in that page's CSV
export and in the Transactions Summary report
([`docs/REPORTS.md`](./REPORTS.md)). One helper behind all of them, so
the ledger and the transactions list cannot answer differently about who
paid.

### Who can see it

Only the merchant the wallet belongs to, through the existing
merchant-scoped wallet endpoints — the same merchant who already sees
the number, unmasked, on their own Collections page and in the
collection detail view. This adds no new exposure and no new endpoint.
It is not masked, because it is the merchant's own customer's number and
masking it would defeat the reconciliation purpose.
