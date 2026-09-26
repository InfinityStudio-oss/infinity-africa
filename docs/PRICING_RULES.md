# Assigning Collection Pricing to a Business

The Super Admin workflow at `/super-admin/pricing-rules`. For how a rate
is turned into a fee once assigned — the formula, the precedence tiers,
the fallback to `PLATFORM_FEE_PERCENTAGE`, and why withdrawals charge
nothing — see
[`docs/collection-and-withdrawal-pricing.md`](./collection-and-withdrawal-pricing.md),
which remains the reference for the pricing engine itself. This document
covers only the assignment side.

## What a rule is assigned to

A row in `merchant_collection_pricing_rules` is assigned by its
`merchant_id`:

- **`merchant_id` set** — a negotiated rate for exactly that business.
- **`merchant_id` null** — the platform fallback, applied to any
  business with no rule of their own.

Nothing else distinguishes the two. The UI reads each row's own
`merchant_id` to decide what to display, rather than inferring it from
which table the row appears under, so a row cannot show an assignment it
does not have.

## The page

**Selector.** Choose a business to see the rates assigned to it. Options
are split into two groups:

- *Verified businesses* — approved (`account_status = active`) and
  KYC-verified (`kyc_status = verified`). These can be given a
  negotiated rate.
- *Not verified — view only, no new pricing* — everyone else, with their
  blocking status shown in the option.

Each option carries the business name **and** its merchant code
(the 27-series ID), so two similarly-named businesses cannot be
confused.

**Rules table.** Both the business section and the platform fallback
section show:

| Column | Meaning |
|---|---|
| Assigned Merchant | The business name, or *All businesses (platform default)* |
| Merchant ID | The 27-series merchant code, or `—` for the platform default |
| Label | Free text, e.g. the commercial agreement name |
| Channel | The `CollectionMethod` this rate is limited to, or *All channels* |
| Percentage | `percentage_fee` |
| Flat Fee | `flat_fee` |
| Notes | Agreement reference — internal only, never shown to the business |
| Status | Active / Inactive |
| Actions | Edit, Deactivate / Activate |

The section heading also names the selected business, so a rate is never
edited against the wrong one by accident.

## Verification gates creating, not viewing

A negotiated rate can only be **created** for a verified, approved
business. The Add button is replaced by an explanation when the selected
business does not qualify.

Unverified businesses are deliberately **not** filtered out of the
selector. A business that was verified when its rate was agreed and has
since been suspended must still be reachable — otherwise its existing
rule becomes invisible and uneditable, and it keeps being applied with
no way to change it. So existing rules stay listed and editable for any
business, in any state.

This is a workflow guard, not a security control. The endpoint itself is
Super Admin-only, MFA-gated and audit-logged; it is not additionally
restricted server-side, which leaves room for a rate that is genuinely
agreed before KYC completes to be set deliberately via the API.

## Audit trail

Every create, update, deactivate and activate writes an `audit_logs`
entry (`pricing_rule.created` / `.updated` / `.deactivated`) with the
acting admin — see `app/routers/admin_pricing.py`. `audit_logs` is
append-only (`forbid_mutation` trigger), so the history of what was
agreed with whom cannot be rewritten.

## What this does not change

- No rate range is hardcoded. `percentage_fee` accepts 0–100%, a sanity
  bound rather than a policy, so the negotiated number can be entered
  exactly as agreed.
- Withdrawals still charge nothing. This page's collapsed "Withdrawal
  Pricing Rules (Inactive)" section edits a different table that has no
  effect on fees.
- The precedence lookup
  (`app/services/collection_pricing.py::find_collection_pricing_rule`)
  is unchanged: merchant + channel, then merchant default, then platform
  + channel, then platform generic.
