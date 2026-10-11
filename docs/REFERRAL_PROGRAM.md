# Merchant referral commissions

A merchant invites another business. If that business is approved and then
actually trades, the referrer earns a share of what InfinityPay earned
from them during their first 30 days.

**Off by default.** `REFERRAL_PROGRAM_ENABLED=false` ships inert: no codes
are issued, no referral is captured at signup, and the recalculation sweep
never starts. Turning it on is not retroactive — a referral has to be
captured while it is on.

---

## The rule everything else follows

> **A signup earns nothing.**

This is not a detail of the policy, it is the reason the policy has the
shape it does. Paying for signups creates an incentive to manufacture
them, and a payments platform that pays per account is a platform that
will be given accounts. Commission is owed only when a referred business:

1. is **approved** by a Super Admin (so a human has looked at it), and
2. processes at least **TZS 100,000** in successful collections, and
3. does both **inside 30 days** of its approval, and
4. produces a commission of at least **TZS 5,000**, and
5. passes a **Super Admin review** of the commission itself.

Fail any of those and nothing is paid.

---

## Commission is a share of revenue, not of volume

The commission base is **InfinityPay's net revenue** from the referred
merchant — not the amount that merchant collected. The difference is
roughly two orders of magnitude, so this is the single most important
line in this document.

```
commission_amount = infinitypay_net_revenue × commission_rate_bps / 10000
```

### Worked example

A referred merchant collects **TZS 200,000** in their first month, on a
2.5% platform fee.

| | |
|---|---:|
| Collected by the merchant | TZS 200,000 |
| **InfinityPay's net revenue** | **TZS 5,000** |
| Commission at 1500 bps (15%) | **TZS 750** |

Fifteen percent of the *collected* amount would be TZS 30,000 — six times
what the platform earned on the whole relationship. There is a test named
`test_commission_is_a_share_of_net_revenue_not_of_what_was_collected`
whose only job is to fail if anyone ever "simplifies" this.

In that example the merchant has also passed the TZS 100,000 volume floor
but the commission is below the TZS 5,000 payout floor, so it is held as
`below_threshold` rather than sent for review.

### Where the revenue figure comes from

It is **not** re-derived from pricing rules. It is read from the existing
double-entry ledger:

- every collection fee is posted as a **credit** to the single
  `platform_revenue` ledger account
  (`app/services/ledger.py::post_collection_entries`)
- a reversal posts the matching **debit**
  (`::reverse_collection_entries`)

So the base is `sum(credits) − sum(debits)` for the referred merchant's
collection transactions inside the window. A reversed collection removes
its own fee with no special case, and the number agrees by construction
with what the platform reports as its own revenue. Duplicating the fee
logic would have produced a second, competing answer.

**Known limitation, deliberate:** a *refunded* collection keeps its fee,
because `post_refund_entry` moves the wallet and settlement legs and
leaves platform revenue alone. The commission follows the revenue, so it
follows that existing product decision rather than inventing a different
one here. If refunds should claw back the fee, that is a change to the
refund posting, and the commission will follow it automatically.

---

## Status flow

A referral:

```
pending_approval → active → qualified → commission_pending
                                      → commission_approved → commission_paid
        ↘ expired        ↘ fraud_hold          ↘ commission_rejected
        ↘ ineligible
```

Its commission:

```
accruing → below_threshold
         → pending_review → approved → paid
                          → rejected
         → cancelled   (a blocker appeared: suspension, fraud hold)
```

`accruing` means the window is still open and the figure can still grow —
reviewing it then would mean reviewing it again tomorrow.

---

## Super Admin review

Super Admin → **Referrals**. The queue opens on what needs a decision.

| Action | What it does |
|---|---|
| **Approve** | Marks a commission payable. **Moves no money.** |
| **Reject** | Refuses it, with a reason that is kept. |
| **Mark paid** | Records that a payout happened *elsewhere*. |
| **Hold / Clear hold** | Freezes or releases a suspicious referral. |
| **Disable code** | Stops one merchant's code working at signup. |

**There is no automated referral payout, by choice.** Pay an approved
commission through the normal withdrawal process, then mark it paid here
so the record matches reality. The platform has no safe automatic path
from "a commission was approved" to "money left the float", and this
feature does not invent one.

Every action is audit logged with the admin who took it.

---

## Fraud controls

Enforced in code, not just documented:

| Control | Where |
|---|---|
| No self-referral | DB `check` constraint + service check |
| One referrer per referred merchant, ever | Unique index on `referred_merchant_id` |
| Referrer must be active | Code lookup filters on `status = 'active'` |
| Referred merchant must be approved | Window only opens at approval |
| Suspended either end → no commission | Recalculation marks it `cancelled` |
| Failed/cancelled transactions excluded | Only `status = 'successful'` counts |
| Reversed collections excluded | Ledger debit nets the fee out |
| No duplicate commission records | Unique index on `referral_id` |
| Human approval before payout | No automated payout path exists |
| Terms frozen at capture | Rate/thresholds copied onto the referral row |

That last one matters: changing `REFERRAL_COMMISSION_RATE_BPS` later does
not re-price referrals already captured. Each row carries the terms it was
created under.

**Not implemented, worth knowing:** there is no automatic duplicate-owner
detection (same email, phone, device or IP across referrer and referred).
The manual review step is what catches those today. If referral volume
grows enough to make that impractical, that check is the first thing to
add.

---

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `REFERRAL_PROGRAM_ENABLED` | `false` | Master switch |
| `REFERRAL_COMMISSION_RATE_BPS` | `1500` | 15% of net revenue |
| `REFERRAL_MIN_SUCCESSFUL_VOLUME` | `100000` | Qualification floor, TZS |
| `REFERRAL_MIN_PAYOUT_AMOUNT` | `5000` | Payout floor, TZS |
| `REFERRAL_PERIOD_DAYS` | `30` | Measured from approval |
| `REFERRAL_RECALCULATION_INTERVAL_SECONDS` | `3600` | `0` disables the sweep |

Env vars rather than database settings, because this platform has no
database-backed settings table and inventing one for this feature would
have been a larger change than the feature.

---

## How it runs

A sweep revalues every open referral on a timer, and Super Admin can
trigger it from the UI. It is **idempotent**: one commission row per
referral, updated in place, and anything a human has ruled on is skipped.
A missed tick costs nothing and a double tick changes nothing — which is
why there is no retry logic.

---

## Deployment

1. Apply `supabase/migrations/20261011010000_merchant_referrals.sql`.
2. Deploy the API and web app. Everything stays inert.
3. Set `REFERRAL_PROGRAM_ENABLED=true` when you want it live.

Steps 1–2 are safe at any time: with the flag off, the only change to
existing behaviour is three unused columns on `merchants`.

---

## Public wording

> Invite a serious business to InfinityPay and earn commission from their
> first month of successful transactions. Commission applies only after
> the referred merchant is approved and starts processing successful
> payments.

Say the second sentence wherever the first appears. A referrer who thinks
they are paid per signup will be disappointed once, loudly, and in public.
