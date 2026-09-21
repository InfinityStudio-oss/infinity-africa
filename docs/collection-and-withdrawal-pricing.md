# Collection & Withdrawal Pricing (MVP policy)

**Merchant charges apply to collections only. Withdrawals do not charge
merchant fees during MVP. Any provider disbursement cost is treated as
an internal platform cost unless a future policy changes this.**

Effective 2026-08-31. Applies going forward only — historical
withdrawals that already stored a non-zero fee (before this date) are
untouched; nothing was rewritten. See
[`docs/withdrawal-pricing-and-approval.md`](./withdrawal-pricing-and-approval.md)
for how withdrawal pricing worked before this change, and for the
still-current approval-flow/status-glossary/Selcom-sequencing mechanics,
which this change didn't touch.

## Collections — flexible, per-merchant pricing (2026-08-31, same day)

Every collection flow (Request Collection, Wallet Push, Push to Selcom
Pesa, TanQR, Payment Links, [Pay by Link](./PAY_BY_LINK.md), Invoices,
Merchant API collections) still computes its fee through the single
shared chokepoint `app/services/collections.py::create_processing_transaction`
— unchanged since before this policy — but that function now delegates
the actual rate lookup to
`app/services/collection_pricing.py::calculate_collection_fee`:

```
fee_amount = clamp(amount * rule.percentage_fee / 100 + rule.flat_fee, rule.minimum_fee, rule.maximum_fee)
net_amount = amount - fee_amount
```

`rule` is the most specific active row in `merchant_collection_pricing_rules`
(Super Admin-managed at `/super-admin/pricing-rules`, "Collection Pricing
Rules" — the primary content of that page now; the pre-existing
withdrawal pricing UI is collapsed below it, inactive). Precedence, most
to least specific:

1. merchant + channel (`channel` = `CollectionMethod`: `STK_PUSH`,
   `SELCOM_PESA_PUSH`, `DYNAMIC_QR`, `HOSTED_CHECKOUT`, `USSD_PUSH` — how
   the customer paid, not which product page/API created the
   collection; Payment Links, Pay by Link, Invoices, and API collections
   all funnel through `HOSTED_CHECKOUT` today, so they share one rate
   unless a merchant is given a `HOSTED_CHECKOUT`-specific override)
2. merchant default (channel null)
3. platform fallback + channel (`merchant_id` null)
4. platform fallback, fully generic

**If no row matches at all — not even a platform fallback — this falls
back to `settings.platform_fee_percentage`** (`PLATFORM_FEE_PERCENTAGE`
env var, default `1.5`), the original flat rate every collection used
before this per-merchant engine existed. That preserves exact backward
compatibility: a merchant nobody has explicitly priced yet keeps seeing
the same rate they always did, never a silent 0%.

`merchant_collection_pricing_rules` is a **separate table** from
`merchant_pricing_rules` (the withdrawal-only one, inactive for fee
purposes as of the same date — see below) — not a repurposing of it.
Collections have no "destination" concept and no processor-charge-pass-
through concept; the collection table instead adds a free-text `notes`
column for a commercial-agreement reference, since collection pricing is
explicitly negotiated per merchant/customer.

No business-specific rate range (e.g. "0.4%-2.0%") is hardcoded anywhere
— `percentage_fee` accepts any value from 0-100% (a basic sanity bound,
not a policy), so Super Admin can set exactly what was actually
negotiated.

**Worked examples** (TZS 10,000 collected):

| Merchant | Rate | Fee | Wallet credit |
|---|---|---|---|
| A | 0.4% | TZS 40 | TZS 9,960 |
| B | 0.8% | TZS 80 | TZS 9,920 |
| C | 2.0% | TZS 200 | TZS 9,800 |

## Withdrawals — fees removed

`app/services/withdrawals/fee_calculator.py::calculate_withdrawal_fee`
now unconditionally returns a zero-fee breakdown:

```
percentage_fee = 0
flat_fee = 0
infinity_fee = 0
processor_charge = 0          (processor_fee_pass_through is never applied)
total_charges = 0
total_reserved_amount = amount     (== the requested withdrawal amount)
recipient_net_amount = amount
```

This is unconditional — it does not consult `merchant_pricing_rules` at
all, so a merchant-specific or platform-fallback rule configured there
(even a real, non-zero one, e.g. left over from before this date) has no
effect. A withdrawal always reserves and debits the merchant's wallet
for exactly the amount they requested, subject only to available
balance, min/max/daily withdrawal limits, and Super Admin approval —
none of which this change touched.

`merchant_pricing_rules` and its precedence lookup
(`find_pricing_rule`) are **not dead code** — they're still used as a
production-API-key-eligibility gate
(`app/services/api_access.py::has_resolvable_pricing_rule` — "has this
merchant been assigned pricing at all"), which is unrelated to fee
amounts, and are a fully separate table from `merchant_collection_pricing_rules`
above. `/super-admin/pricing-rules` still edits this table — now a
collapsed "Withdrawal Pricing Rules (Inactive)" section on the same page
as (and below) the primary "Collection Pricing Rules" UI — see its own
on-page notice.

### If a real provider disbursement cost needs tracking later

Selcom (or any future payout provider) may charge InfinityPay a real
cost per payout. That cost is an **internal platform cost** — it must
never be deducted from what a merchant receives unless a deliberate,
separate future policy change says otherwise. Nothing in this codebase
currently records that cost anywhere (no field, no table); building that
tracking is explicitly out of scope for this change and intentionally
not stubbed in, to avoid a half-built, silently-unused mechanism.

## Why this split is safe

- Every collection-crediting path and every withdrawal-debiting path was
  already independently reviewed for wallet-ledger safety (see
  [`docs/MVP_30_TO_100_MERCHANT_READINESS.md`](./MVP_30_TO_100_MERCHANT_READINESS.md)
  §4/§5) — this change only replaces the *number* `calculate_withdrawal_fee`
  returns; it doesn't touch how or when a wallet is credited or debited.
- `total_reserved_amount` (what gets checked against available balance
  and what gets debited on approval) and `recipient_net_amount` (what
  the merchant sees as "you'll receive") both derive from the same
  `FeeBreakdown` — making them equal to `amount` was a one-function
  change, not two changes that could drift out of sync.
- No historical `disbursements` row was rewritten — a withdrawal
  submitted before 2026-08-31 keeps whatever real fee it already
  reserved/debited; only new withdrawals use the zero-fee policy.
