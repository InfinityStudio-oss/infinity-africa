# Production launch smoke test

Run against production, in order, with real money at the smallest usable
amount. Each step says what to check and where the answer lives, so a
failure is diagnosable without reading code.

For what to set before any of this, and what to watch during live
traffic, see `LAUNCH_DAY_RUNBOOK.md`. This page is the one-off walk
through the product.

## Before you start

- [ ] A phone you control with mobile money, holding more than the test amount
- [ ] A mailbox you can read for the test merchant (**not** iCloud — it has
      hard-bounced for this platform before and Resend suppresses the
      address silently)
- [ ] Super Admin access, signed in, in a separate browser profile
- [ ] Railway logs open

## 1. Merchant onboarding

| | Step | Passes when |
|---|---|---|
| ☐ | Create an account at `/create-account` | Lands on "check your email", not an error |
| ☐ | Verification email arrives | In the inbox, not spam. Sender is `notification@infinitypay.me` |
| ☐ | Click the link | Reaches the portal, not the homepage. Landing on the homepage means a missing Supabase redirect allow-list entry |
| ☐ | Pending screen | Overview shows "Account status: Pending Verification" |
| ☐ | Locked pages | Pay by Link, Withdrawals and Invoices are dimmed with a lock, and do not navigate |
| ☐ | Super Admin sees the submission | Super Admin → Onboarding |
| ☐ | Approve it | Merchant's Overview loses the pending banner; the three locked items become links |

**If the verification email never arrives:** check Resend → Sending
first. A `Suppressed` row means the address is blocked and removing it
is a manual step in Resend → Suppressions.

## 2. API credentials

| | Step | Passes when |
|---|---|---|
| ☐ | Generate a live key at `/portal/api-credentials` | Secret shown once, in full |
| ☐ | Reload the page | Only the prefix and last 4 are shown. The secret is **not** retrievable |
| ☐ | Set a webhook URL | Saved. A signing secret is optional — see the partner doc |

## 3. Direct Wallet Push — the success path

Use the smallest workable amount. Every live test spends real money and
consumes the shared Selcom budget.

| | Step | Passes when |
|---|---|---|
| ☐ | `POST /v1/collections/wallet-push` with the live key | `202`, status `processing` |
| ☐ | Phone prompt | Arrives within seconds |
| ☐ | Approve it | — |
| ☐ | Collection resolves | `successful` within ~2 minutes. Reconciliation does this; Selcom's own callback fails signature by design and is **not** a fault |
| ☐ | Wallet credited | Balance rises by amount minus fee. Check the fee matches the merchant's rate, not the platform fallback |
| ☐ | Transaction row | Shows opening/closing balance and the customer phone |
| ☐ | Webhook delivered | Portal → API Credentials → Webhooks shows `200 Delivered` |
| ☐ | Payload is right | Carries your `reference`, and **no** `test` or `sandbox` field |

## 4. Failure paths

The ones that matter, because they are what a real subscriber does.

| | Step | Passes when |
|---|---|---|
| ☐ | Dismiss the prompt and wait ~30 min | Collection becomes `failed` with `failure_reason_code: expired`, and `collection.failed` is delivered |
| ☐ | Enter a wrong PIN | Same as above. Selcom reports both as an indefinite `PENDING`, so `expired` is the normal outcome, not a rare one |
| ☐ | Pay from the merchant's own registered phone | Under 50,000 TZS credits immediately and still raises a `SELF_PAYMENT_OWN_TILL` alert in Risk Monitoring. Above it, held at `pending_review` until cleared |
| ☐ | Point a webhook at a dead URL | Portal shows retries, then stops after 5 attempts (~50 min). The payment is unaffected |

## 5. Withdrawal

| | Step | Passes when |
|---|---|---|
| ☐ | Request a withdrawal | OTP email reaches the merchant |
| ☐ | Enter the OTP | Request created, status `PENDING_ADMIN_APPROVAL` |
| ☐ | CEO alert | Reaches every address in `CEO_EMAIL` |
| ☐ | Super Admin approves | Payout released; a security alert email follows |
| ☐ | Success email | Goes to the merchant's **notification** address, falling back to their account email |
| ☐ | Wallet debited | Balance drops; ledger shows the entry |

## 6. Super Admin

| | Step | Passes when |
|---|---|---|
| ☐ | Sign in at `/admin-login` | Straight to the MFA prompt if enrolled, then the dashboard |
| ☐ | Admin Team | Shows the real roster with Last Signed In. Never "No platform admins found" — that means the read failed |
| ☐ | Pricing Rules | A business's negotiated rate shows "overrides the platform fallback" |
| ☐ | Transactions / Withdrawals / Risk Monitoring | All load with real data |

## 7. Public pages, hard-refreshed

Hard refresh each (Ctrl+Shift+R), on desktop and at 375px:

- [ ] `/`
- [ ] `/create-account`
- [ ] `/dashboard/login`
- [ ] `/dashboard/forgot-password`
- [ ] `/admin-login`
- [ ] `/developers/direct-wallet-push`
- [ ] A live payment page, `/pay/{slug}`

Each passes when no raw icon name (`smartphone`, `qr_code_scanner`,
`account_balance_wallet`) appears even for a frame, nothing overflows
horizontally, and nothing is clipped.

## If something fails

Do not retry blindly. Each of these has a different first place to look:

| Symptom | Look here first |
|---|---|
| Payment stuck `processing` | Railway: `scheduled_checkout_reconciliation` |
| No webhook at the merchant | Portal → Webhooks delivery log, before touching code |
| No email anywhere | Resend → Sending, then Suppressions |
| Wrong fee charged | Super Admin → Pricing Rules; negotiated beats fallback |
| Payments stopped entirely | Railway: `selcom_circuit_opened` |
| 401 on every admin call | The session is aal1 — MFA was not completed |
