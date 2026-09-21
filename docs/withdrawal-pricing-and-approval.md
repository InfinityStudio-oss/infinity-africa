# Withdrawal Pricing & Super Admin Approval

> **MVP pricing policy (2026-08-31): withdrawals no longer charge a
> merchant fee.** InfinityPay earns fees from merchant collections
> only — see [`docs/collection-and-withdrawal-pricing.md`](./collection-and-withdrawal-pricing.md)
> for the current policy. `calculate_withdrawal_fee`
> (`app/services/withdrawals/fee_calculator.py`) always returns zero
> now, regardless of anything configured in `merchant_pricing_rules`.
> The "Pricing model" / "Fee formula" / "Worked example" sections below
> describe the **pre-2026-08-31 behavior** — kept for historical
> reference and because `merchant_pricing_rules` and its precedence
> lookup (`find_pricing_rule`) still exist in the codebase (still used
> as a production-API-eligibility gate, unrelated to fee amounts — see
> `app/services/api_access.py`) — do not use them to answer "what does a
> withdrawal cost a merchant today": nothing, always. Everything below
> **"Fee snapshot (immutability)"** (the approval flow, status glossary,
> Selcom-call sequencing) is still accurate and unaffected by this
> change — a withdrawal's stored fee fields are just always zero now.

How dynamic, per-merchant withdrawal fees **used to be** calculated, how
the fee snapshot is frozen onto a withdrawal, and why every withdrawal —
regardless of amount — sits for Super Admin approval before it ever
reaches Selcom. For the general endpoint/auth/pagination conventions, see
[`docs/api.md`](./api.md). For the underlying reservation/ledger mechanics,
see `apps/api/app/services/ledger.py`.

## Why this exists

Before this feature, every withdrawal charged a flat **zero fee**, and only
withdrawals at or above a single global `disbursement_approval_threshold`
env var were held for review — everything below it reserved funds and
called Selcom synchronously, inline, with no admin ever seeing it. That's
gone: **every withdrawal now requires Super Admin approval**, and each
merchant can have its own negotiated fee structure instead of one
platform-wide rate.

## Pricing model

`merchant_pricing_rules` (`supabase/migrations/20260820090000_merchant_pricing_rules.sql`)
holds one row per rule:

| Column | Meaning |
|---|---|
| `merchant_id` | `null` = platform fallback rule; otherwise scoped to one merchant |
| `channel` | `null` = any channel; otherwise `SELCOM_PESA` / `MOBILE_MONEY` / `BANK_ACCOUNT` |
| `destination_code` | `null` = any destination within `channel`; otherwise one of the 18 supported codes (see below) |
| `percentage_fee` | e.g. `1.000` = 1% of the withdrawal amount |
| `flat_fee` | fixed TZS amount added on top of the percentage fee |
| `minimum_fee` / `maximum_fee` | clamps applied to `percentage_fee + flat_fee` (either or both may be null) |
| `processor_fee_flat` | admin-configured pass-through processor charge — Selcom's integration here never returns a live fee to quote against, so this is negotiated, not fetched |
| `processor_fee_pass_through` | whether `processor_fee_flat` is actually charged to the merchant |
| `effective_from` / `effective_to` | validity window |
| `is_active` | soft-disable without deleting history |

Supported `destination_code` values: `SELCOM`, `MPESA`, `AIRTELMONEY`,
`HALOPESA`, `MIXXBYYAS`, `TTCLPESA` (mobile money / Selcom Pesa) and
`CRDB`, `NMB`, `NBC`, `ABSA`, `BOA`, `DTB`, `EQUITY`, `EXIM`, `KCB`,
`STANBIC`, `SCB`, `TCB` (banks).

### Rule precedence

`app/services/withdrawals/fee_calculator.py::find_pricing_rule` searches,
most specific first:

1. Merchant + destination-specific rule
2. Merchant + channel-specific rule (destination null)
3. Merchant default rule (channel and destination both null)
4. Platform fallback rule (`merchant_id` null) — itself searched
   destination → channel → generic, the same way, so a platform-wide
   per-channel default can still beat a fully generic platform rule

Only `is_active = true` rules whose `effective_from`/`effective_to` window
covers "now" are considered. **If no rule matches at all — not even a
platform fallback — the fee is zero**, matching the pre-feature default
rather than blocking a withdrawal for missing configuration.

### Fee formula

```
percentage_fee = amount * rule.percentage_fee / 100
infinity_fee   = clamp(percentage_fee + rule.flat_fee, rule.minimum_fee, rule.maximum_fee)
processor_charge = rule.processor_fee_flat   if rule.processor_fee_pass_through else 0
total_charges  = infinity_fee + processor_charge
total_reserved_amount = amount + total_charges   # debited from the merchant wallet
recipient_net_amount  = amount                    # what the recipient actually receives
```

**Worked example** (matching the product spec): merchant requests
TZS 100,000, rule is 1% + TZS 500 flat + TZS 300 processor pass-through:

```
percentage_fee = 1,000
infinity_fee   = 1,000 + 500 = 1,500
processor_charge = 300
total_charges  = 1,800
total_reserved_amount = 101,800   <- debited from the wallet
recipient_net_amount  = 100,000   <- what the recipient gets
```

## Fee snapshot (immutability)

The full breakdown (`FeeBreakdown` — `app/schemas/withdrawals.py`) is
calculated once, at `POST /v1/merchant/withdrawals` time, and written onto
the `disbursements` row: `processor_charge`, `infinity_fee`,
`percentage_fee_component`, `flat_fee_component`, `total_charges`,
`total_reserved_amount`, `recipient_net_amount`, `pricing_rule_id`, and the
entire breakdown as `pricing_snapshot_json`. **A later edit to the
`merchant_pricing_rules` row never changes an already-submitted
withdrawal** — approval (`approve_disbursement`) reads the stored snapshot
and never recalculates.

## Request flow

```
Merchant Portal                          apps/api                         Selcom
────────────────                         ────────                        ──────
POST /v1/merchant/withdrawals/quote  ──▶  calculate_withdrawal_fee()
                                           (no DB write, no Selcom call)
     ◀── FeeBreakdown ─────────────────────┘

POST /v1/merchant/withdrawals        ──▶  execute_disbursement()
                                           - recalculates the fee server-side
                                             (never trusts the quote call)
                                           - checks balance >= total_reserved_amount
                                           - inserts disbursements row,
                                             status = PENDING_ADMIN_APPROVAL
     ◀── 202 { status: PENDING_ADMIN_APPROVAL, ...fee snapshot... }

                                           ⋯ nothing else happens until an
                                             admin acts — Selcom is never
                                             called from this path ⋯

Super Admin Console
────────────────────
POST /v1/admin/withdrawals/{id}/approve ──▶ approve_disbursement()
                                              - reserves funds (uses the
                                                STORED snapshot)
                                              - calls Selcom              ──▶ process_transaction()
                                                                          ◀── successful / processing / ambiguous / failed / 403 or 611
                                              - updates status accordingly
     ◀── 200 { status: SUCCESS | PROCESSING | ... }

POST /v1/admin/withdrawals/{id}/reject       ──▶ reject_disbursement()
  { rejection_reason }                            - status = REJECTED
                                                   - nothing to release (never reserved)

POST /v1/admin/withdrawals/{id}/request-info ──▶ request_more_info()
  { message, requested_documents }                - status = INFO_REQUESTED
                                                   - merchant notified

POST /v1/admin/withdrawals/{id}/refresh-status ─▶ refresh_disbursement_status()
  (for a stuck PROCESSING/NEEDS_RECONCILIATION     - re-checks Selcom, resolves
   withdrawal, admin-triggered only)                 if possible

POST /v1/admin/withdrawals/reconcile-pending  ──▶ reconcile_pending_disbursements()
  (batch refresh, admin-triggered only)             - runs refresh_disbursement_status
                                                       over every stuck row
```

**Selcom is only ever called from `approve_disbursement`** (and its
manual-refresh counterparts, `refresh_disbursement_status`/
`reconcile_pending_disbursements` — both post-approval, both admin-triggered
only). No background worker exists in this codebase and none was added —
nothing sends a merchant's withdrawal request to Selcom before a Super
Admin explicitly approves it.

## Status glossary

| Status | Meaning |
|---|---|
| `PENDING_ADMIN_APPROVAL` | Every withdrawal starts here. Nothing reserved, Selcom not called. |
| `INFO_REQUESTED` | A Super Admin asked the merchant for more information before deciding. |
| `PROCESSING` | Approved; funds reserved; Selcom acknowledged but hasn't resolved synchronously yet. |
| `SUCCESS` | Payout confirmed by Selcom. |
| `FAILED` | Selcom declined the payout (or the call failed outright) — reservation reversed. |
| `REJECTED` | A Super Admin declined the request. Nothing was ever reserved, so nothing to release. |
| `NEEDS_ADMIN_ATTENTION` | Reserved for cases that need a human look outside the automatic branches. |
| `NEEDS_RECONCILIATION` | Selcom's response was ambiguous — funds stay reserved pending manual resolution. |
| `BLOCKED_IP_WHITELIST` | Selcom returned HTTP 403 and/or its own error code 611 (this backend's outbound IP isn't whitelisted) — funds stay reserved; this is an operator problem, not a payout failure. See `docs/selcom-live-go-live.md`. |
| `REVERSED` | An already-`SUCCESS` payout was reversed after the fact (e.g. Selcom reports it bounced post-settlement). |

## Configuring a merchant's pricing

All endpoints are `require_super_admin`-gated (`app/routers/admin_pricing.py`):

```bash
# Create a negotiated rate for one merchant
curl -X POST https://api.infinitypay.me/v1/admin/merchants/{merchant_id}/pricing-rules \
  -H "Authorization: Bearer <super-admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "MOBILE_MONEY",
    "percentage_fee": "1",
    "flat_fee": "500",
    "minimum_fee": "200",
    "maximum_fee": "5000",
    "processor_fee_flat": "300",
    "processor_fee_pass_through": true,
    "label": "Negotiated enterprise rate"
  }'

# List a merchant's rules
curl https://api.infinitypay.me/v1/admin/merchants/{merchant_id}/pricing-rules \
  -H "Authorization: Bearer <super-admin-jwt>"

# Edit a rule
curl -X PATCH https://api.infinitypay.me/v1/admin/pricing-rules/{pricing_rule_id} \
  -H "Authorization: Bearer <super-admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"flat_fee": "750"}'

# Deactivate a rule (soft-disable, keeps history)
curl -X POST https://api.infinitypay.me/v1/admin/pricing-rules/{pricing_rule_id}/deactivate \
  -H "Authorization: Bearer <super-admin-jwt>"

# Platform fallback rule (merchant_id null) — applies when a merchant has none of their own
curl -X POST https://api.infinitypay.me/v1/admin/pricing-rules/platform-fallback \
  -H "Authorization: Bearer <super-admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"flat_fee": "1000", "label": "Platform default"}'
```

In the Super Admin console: **Pricing Rules** (`/super-admin/pricing-rules`)
— select a merchant to manage their negotiated rules, or manage the
platform fallback rules shown below regardless of merchant selection.

## Naming: "Withdrawals" vs. "Disbursements"

The merchant and Super Admin dashboards say "Withdrawal" everywhere — this
was already true before this feature and remains unchanged. Only
`/developers/*` (the public API reference) still says "Disbursements API",
deliberately, because that page documents the literal wire format
(`/v1/disbursements/*` paths, `disbursement.*` webhook event names) — see
that page's own callout explaining the distinction. This document, and
every merchant/admin-facing string introduced by this feature, uses
"Withdrawal".

## Real end-to-end pipeline verification (2026-08-21)

Everything above was implemented and unit-tested against fakes/mocks
before this date. On 2026-08-21, once Selcom sandbox signing was fixed
(see [`docs/selcom-sandbox-test-accounts.md`](./selcom-sandbox-test-accounts.md)),
the pipeline was exercised for real — real production database, real
Selcom sandbox, via direct backend service-function calls (not the browser
UI, and not through the merchant-facing HTTP schema, since `DestinationCode`
deliberately excludes the sandbox-only `TESTBANK`/`TESTWALLET` codes — see
"Sandbox-only" below):

- **No platform fallback rule existed at all** before this date — created
  via `POST /v1/admin/pricing-rules/platform-fallback`
  (`channel: null, destination_code: null, percentage_fee: 1.0, flat_fee:
  500, processor_fee_pass_through: true`).
- **Quote** (`quote_withdrawal_fee`) correctly applied the new fallback
  rule (`is_platform_fallback: true`, correct fee math: 1000 → 510 total
  charges → 1510 reserved).
- **Submission** (`execute_disbursement`) correctly landed
  `PENDING_ADMIN_APPROVAL` with the fee snapshot frozen, and did not touch
  Selcom.
- **Approval** (`approve_disbursement`) correctly reserved the ledger,
  called the real Selcom sandbox (using a real `DestinationCode` —
  `CRDB` — with a fabricated account number, since the sandbox-only codes
  aren't reachable through this real, validated path), got a real
  business-logic rejection from Selcom, and correctly reversed the ledger
  reservation and marked the withdrawal `FAILED`. Ledger symmetry was
  independently verified: wallet balance before submission exactly equals
  balance after the failed-and-reversed cycle.

**Two real bugs found and fixed** in `_fail_and_reverse()`
(`app/services/disbursements.py`), both regression-tested in
`apps/api/tests/test_admin_withdrawals.py`:

1. The failure reason was computed and passed around (audit log, merchant
   notification) but never actually written onto
   `disbursements.admin_status_reason` — so a failed withdrawal's reason
   was invisible on the record itself, only in the audit trail.
2. On the `SelcomAPIError` exception path specifically (as opposed to a
   clean `result.status == "failed"`), `_fail_and_reverse` was called
   without `raw_response` at all, so `exc.provider_response_body` (Selcom's
   real error body, added in an earlier session specifically to make this
   debuggable) was silently dropped instead of reaching
   `disbursements.selcom_raw_response`.

**Not yet verified**: a real terminal `SUCCESS` or `NEEDS_RECONCILIATION`
result through this pipeline (only `FAILED` has been exercised for real —
getting `SUCCESS` would require a real destination_code Selcom's sandbox
actually accepts, which none of the 18 production codes are), and the
actual browser UI end-to-end (Merchant Portal → Super Admin Console) —
everything above was verified via direct backend calls, not clicking
through the deployed frontend.
