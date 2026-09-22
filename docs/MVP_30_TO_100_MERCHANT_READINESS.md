# MVP Readiness: 30–100 Selected Merchants

Readiness review and hardening pass for opening InfinityPay to a
controlled cohort of 30–100 real merchants using collections, payment
links, Pay by Link permanent checkout pages, invoices, withdrawals,
merchant API keys, and email notifications daily. This supersedes
nothing in [`MVP_LAUNCH_CHECKLIST.md`](./MVP_LAUNCH_CHECKLIST.md)
— that doc's env vars, kill-switch mechanics, and incident steps are still
current and linked throughout below rather than repeated. This doc adds
what changed and what to verify specifically for sustained multi-merchant
daily volume, plus the rollout plan.

## Executive summary

**Ready**, with the rollout gated by week as in §9 below. Every money-
movement path (collection credit, withdrawal debit) was already,
independently of this pass, funneled through a single idempotent
chokepoint per direction (`resolve_collection()` / the disbursement
approval RPC), backed by database-level append-only + no-negative-balance
constraints — not just application-level discipline. This pass found and
closed real gaps (below), none of which were money-movement bugs: all
were either missing audit trail, missing rate limiting, or missing
database indexes that would have started to matter at this cohort's
volume, not at today's.

## What changed this pass

- **Database indexes** — added `(merchant_id, created_at desc)` on
  `collections`, `transactions`, and `ledger_entries` (the three
  highest-row-count tables, previously indexed only on `merchant_id`
  alone), plus single-column indexes on `email_deliveries.email_type` and
  `api_keys.key_prefix`. See §2.
- **Rate limiting gaps closed** — four endpoints had no limiter at all:
  merchant payment-link creation, staff invite, invoice creation, invoice
  send. See §5.
- **Audit-log gaps closed** — three real gaps found and fixed:
  - A successful withdrawal payout (`disbursement.completed`) was never
    written to `audit_logs` at all — only `disbursement.failed` and
    `disbursement.reversed` were. The far more common successful path had
    no audit trail for "whose money actually moved, when."
  - The merchant-portal and API-key manual collection "Refresh status"
    endpoints recorded the money-movement outcome (via
    `resolve_collection()`) but never recorded *who clicked refresh* —
    the Super Admin equivalent already did.
  - All three are fixed the same way: `write_audit_log(...)` added at the
    exact point money moves (`app/services/disbursements.py`,
    `app/services/collections.py::resolve_collection`) or the action is
    attempted (`app/routers/merchant_portal.py`,
    `app/routers/collections_api.py`).
- **Everything else in this doc's checklist was verified, not rebuilt** —
  the previous MVP launch pass (see `MVP_LAUNCH_CHECKLIST.md`) already put
  the core safety invariants in place. This pass's job was confirming
  they hold at 30–100-merchant daily volume, not redesigning them.

## 1. Architecture — confirmed on this pass

- Backend lifespan (`app/main.py`) starts both reconciliation schedulers
  only when their interval env var is `>0` **and** `ENABLE_AUTO_RECONCILIATION`
  is true; each sweep iteration is wrapped so one bad row can't abort it
  (fixed 2026-08-28, confirmed still in place).
- Every collection entry point (request-collection, payment link, invoice,
  merchant API) and the withdrawal request endpoint resolve `merchant_id`
  from the authenticated caller (JWT membership or API key), never from
  the request body's own `merchant_id` field for authorization purposes.
- Public payment pages (`/pay/{slug}`) render only what
  `app/routers/public_payment_links.py` explicitly selects — no service
  role key, no internal IDs beyond the public slug, no provider secrets.
- Frontend (`apps/web`) reads only `NEXT_PUBLIC_*` Supabase/API/site URLs
  from `process.env` — confirmed again this pass, see §6.

## 2. Database indexes

New migration: `supabase/migrations/20260830010000_mvp_scale_indexes.sql`,
**applied to the live production project** (not just committed — applied
via Supabase directly and verified live against `pg_indexes`).

| Table | New index | Why |
|---|---|---|
| `collections` | `(merchant_id, created_at desc)` | Every "recent activity" merchant dashboard view sorts by date; previously only indexed on bare `merchant_id`, forcing a sort at query time once a merchant accumulates a few thousand rows. |
| `transactions` | `(merchant_id, created_at desc)` | Same reasoning — the ledger/activity views join through this table. |
| `ledger_entries` | `(ledger_account_id, created_at desc)` | Balance/history views for one account, newest first. |
| `email_deliveries` | `(email_type)` | Lower-volume but cheap; supports "all signup-notification emails" style queries. |
| `api_keys` | `(key_prefix)` | Near-static table; cheap to add now. |

Existing indexes already covered every table/column this brief asked to
confirm (`merchants.id`/`.status`, `collections.merchant_id`/`.status`/
`.provider_reference`, `payment_links.merchant_id`/`.slug`,
`invoices.merchant_id`/`.status`, `disbursements.merchant_id`/`.status`,
`ledger_entries`/`ledger_accounts` balance columns, `api_keys.merchant_id`/
`.hash`, `audit_logs.merchant_id`/`.created_at`) from their original
migrations — nothing there was missing. This migration only adds indexes,
never drops or modifies one; no risk to existing data or queries.

## 3. Reconciliation worker readiness

Both schedulers (`checkout_reconciliation` for collections,
`disbursement_reconciliation` for withdrawals) — confirmed:

- Start only when interval `>0` and `ENABLE_AUTO_RECONCILIATION=true`;
  log a startup line with the configured interval, and a per-sweep
  summary line.
- Per-row exception isolation — one malformed/duplicate row logs and is
  skipped, never aborts the sweep for every other merchant's pending rows
  (the real bug found and fixed 2026-08-28 during Selcom sandbox testing).
- Only ever call Selcom's authenticated order/transaction-status query
  API — never trust an unsigned webhook, never credit/debit off a bare
  status string without that authenticated confirmation.
- Wrong amount/currency/reference cannot resolve a collection — the
  match is by `provider_reference` lookup against the row already created
  server-side at initiation, not by trusting fields from the provider
  response.
- Manual "Refresh status" (merchant, Super Admin, and API-key callers)
  remains available as a backup at all times, independent of scheduler
  state, and now individually audit-logged per §"What changed."

**Required interval config, both set to 120s in production** (confirmed
current Railway value, unchanged this pass):
```
SELCOM_CHECKOUT_RECONCILE_INTERVAL_SECONDS=120
SELCOM_DISBURSEMENT_RECONCILE_INTERVAL_SECONDS=120
```
Both default to `0` (scheduler disabled) if unset — this is a real
config dependency, not just documentation; verify it's actually set in
Railway, not just assumed.

## 4. Collections and wallet credit safety

Confirmed across all five collection entry points (Request Collection,
Payment Link, **Pay by Link**, Invoice, Merchant API). Pay by Link
([`docs/PAY_BY_LINK.md`](./PAY_BY_LINK.md)) is a merchant's permanent
public checkout page (`/pay/{merchant_slug}`) — its checkout endpoint
only ever creates an ordinary `payment_links` row
(`created_via="pay_by_link"`, tagged `source="PAY_BY_LINK"` for
Super Admin/reporting) and hands off to the exact same "Choose how you
want to pay" flow, so it's a fifth entry point into the guarantees
below, not a sixth set of guarantees to separately verify:

- `merchant_id` for authorization always comes from the authenticated
  caller, never trusted from the request body.
- Amount/currency validated server-side before any row is written.
- `provider_reference` is unique per attempt; `Idempotency-Key` header
  required on money-moving POSTs, preventing accidental double-submission
  from a retried client request before any provider call even happens.
- Status transitions (`processing` → `successful`/`failed`) are written
  only by backend code — never accepted from the frontend.
- **Wallet credit happens in exactly one place**: `resolve_collection()`,
  guarded by `if collection["status"] != "processing": return collection`
  — an idempotent no-op once a collection is resolved. Every crediting
  path (webhook, 3 separate manual-refresh entry points, both scheduled
  reconciliation sweeps) funnels through this one function, so "unsigned
  webhook can't credit," "duplicate reconciliation/webhook/refresh can't
  double-credit," and "failed/cancelled/pending never credit" are the
  same guarantee proven once, not four separate ones to keep in sync.
- Unsigned Selcom Checkout webhook deliveries are rejected with 401 in
  production before any collection is even looked up (fail-closed policy,
  confirmed unchanged).
- Fees/net computed once at the `transactions` row level, consistently
  read by every downstream view; `post_collection_entries` (Postgres RPC)
  enforces a balanced debit/credit posting and non-negative balances at
  the database level, not just in application code.
- **Merchant charges apply to collections only** (2026-08-31 pricing
  policy) — this is the one and only place a merchant fee is ever
  charged, and it's flexible per merchant/channel now
  (`merchant_collection_pricing_rules`, Super Admin-managed at
  `/super-admin/pricing-rules` → "Collection Pricing Rules"), falling
  back to the original flat `PLATFORM_FEE_PERCENTAGE` for any merchant
  nobody has explicitly priced. See
  [`docs/collection-and-withdrawal-pricing.md`](./collection-and-withdrawal-pricing.md)
  and §5's own pricing note below for the withdrawal side of this split.

## 5. Withdrawals and wallet debit safety

Confirmed unconditional flow, no bypass exists in code:

`POST /v1/disbursements/*` (merchant request) → validated against
min/max/daily limits → `PENDING_ADMIN_APPROVAL` → CEO email → Super Admin
`approve`/`reject` (`require_super_admin`-gated) → approval **re-checks**
merchant standing, open high-risk fraud alerts, and live balance
atomically → only then does a real Selcom payout call happen → wallet
debited exactly once, at that point.

- Hardcoded `TZS 1,000` cap removed; `MIN_WITHDRAWAL_AMOUNT_TZS` /
  `MAX_WITHDRAWAL_AMOUNT_TZS` / `DAILY_WITHDRAWAL_LIMIT_TZS` are
  configurable (see `MVP_LAUNCH_CHECKLIST.md` §4 for the exact enforcement
  point).
- Rejection stores a required `rejection_reason`; rejected/failed
  withdrawals never debit (nothing is reserved until the approval-time
  RPC runs); a provider-side failure after approval reverses the
  reservation (`_fail_and_reverse`), leaving the wallet whole.
- Duplicate approval/callback/reconciliation cannot double-disburse — the
  disbursement row's own status is the guard (`PROCESSING`/`SUCCESS`/
  `FAILED` are terminal-ish states each resolution path checks before
  acting).
- Approval and rejection both record the acting Super Admin's user ID;
  account/mobile numbers are masked in every merchant-facing and audit
  surface that doesn't need the full value.
- **New this pass**: a successful payout now writes
  `audit_logs.action="disbursement.completed"` (previously only failure/
  reversal were audited — see §"What changed").
- **Pricing policy (2026-08-31): merchant charges apply to collections
  only. Withdrawals do not charge merchant fees during MVP. Any provider
  disbursement cost is treated as an internal platform cost unless a
  future policy changes this.** `calculate_withdrawal_fee`
  (`app/services/withdrawals/fee_calculator.py`) always returns zero now
  — no percentage fee, no flat fee, no processor charge passed through —
  regardless of any `merchant_pricing_rules` row configured; a
  withdrawal reserves and debits exactly the requested amount. See
  [`docs/collection-and-withdrawal-pricing.md`](./collection-and-withdrawal-pricing.md).
  Historical withdrawals from before this date keep whatever fee they
  already stored — nothing was rewritten.

## 6. Merchant signup and email flow readiness

Two structurally separate flows, confirmed not to cross:

- **CEO internal notification** — trigger: merchant submits onboarding;
  recipient: `CEO_EMAIL` (`ceo@infinitypay.me`); function:
  `send_merchant_signup_notification_email`. Never sent to the merchant.
  Never gated by any of the §17 email-volume flags (Part 5's "keep" list
  explicitly excludes it).
- **Merchant welcome email** — trigger: merchant verified/approved;
  recipient: the merchant's own `contact_email`; separate function, never
  reused for the CEO notification and never sent to the CEO. Also never
  gated by an email-volume flag.
- A merchant record with no usable email logs a delivery failure — it
  does not silently redirect to the CEO's inbox.
- Email failures are always best-effort around the underlying business
  action (signup submission, approval) — a Resend outage never blocks or
  reverts a successful signup/approval.

**Get Started (combined signup) flow** — `POST /v1/onboarding/signup`
(public, unauthenticated), backing the public site's "Get Started" →
`/create-account` page. Creates the Supabase Auth user itself
(service_role) with `email_confirm: false`, then the merchant record
(`status: "pending"`, `kyc_status: "unverified"`) and onboarding
submission (`review_status: PENDING_VERIFICATION`) in the same call as
the older two-step `/onboarding` flow (`create_merchant_onboarding`,
shared). Sends the email-verification link (InfinityPay's own branded
email, never Supabase's default) only when the account isn't already
confirmed. **Email verification and Super Admin approval are two
independent gates** — verifying only proves the merchant controls that
inbox; a verified-but-not-yet-approved merchant can log in
(`merchant_gate.require_approved_merchant` and
`disbursements._check_merchant_is_verified` both still block every
financial action — see §5, "Merchant onboarding checklist"). Never
auto-approved by any code path.

## 17a. Email-volume reduction flags (2026-09-22)

Three independent flags, each defaulting `false` (the reduced-volume
state), each gating exactly one email category and nothing else:

| Flag | Gates | Never affects |
|---|---|---|
| `SEND_CUSTOMER_RECEIPT_EMAILS` | `send_payment_receipt_email` (customer receipt after a successful collection) | Payment success, wallet credit, in-portal receipt page, merchant collection-notification email (§17, separately gated) |
| `SEND_WITHDRAWAL_REQUEST_EMAILS` | `send_withdrawal_request_notification_email` (CEO "please review" email per withdrawal request) | The request itself, its audit log, Super Admin queue visibility |
| `SEND_MERCHANT_WITHDRAWAL_EMAILS` | `send_withdrawal_success_email` (merchant "your withdrawal succeeded" email) | The in-app notification (`notify_merchant`) and outbound webhook, both unconditional |

None of the three ever gates: email verification, password reset, staff
invite, merchant approval/welcome email, the CEO merchant-signup
notification, or any security-alert email.

## 7. Resend and notification readiness

- `RESEND_API_KEY` is backend/Railway-only; confirmed no
  `NEXT_PUBLIC_RESEND_API_KEY` or any Resend key anywhere under
  `apps/web` (§6/§10 secret scan).
- Sender: `EMAIL_FROM` (`InfinityPay <notification@infinitypay.me>`),
  invoices use their own visually-distinct `INVOICE_EMAIL_FROM` (falls
  back to `EMAIL_FROM` if unset). Reply-to: `EMAIL_REPLY_TO`
  (`info@infinitypay.me`). CEO recipient: `CEO_EMAIL`.
- Confirmed present: CEO signup notification, merchant welcome, CEO
  withdrawal-request notification, merchant withdrawal-success email,
  invoice payment-request email (customer), payment-link customer email
  (only sent when `customer_email` is present — **Request Collection does
  not send a customer link email at all**, since it has no real public
  payment URL to send, matching required policy #14), forgot-password,
  staff invite.
- No raw reset/invite token or link is ever logged — `app/services/email.py`
  and the auth action logging around `generate_link` log only metadata
  (recipient, type, success/failure), never the link/token itself.
- **Merchant collection notification email** (added 2026-09-01, full
  detail in `docs/merchant-collection-notifications.md`): up to 2
  merchant-configured email addresses (`merchant_notification_settings`),
  sent from `_apply_collection_success` — the single chokepoint every
  collection source (Request Collection, Payment Link, Pay by Link,
  Invoice, API Collection, Wallet Push, Push to Selcom Pesa, TanQR)
  funnels through — right after the customer's own receipt email, in its
  own separate `try/except` so a failure sending it never blocks the
  wallet credit or the receipt email. Idempotent per
  `(collection_id, recipient_email)` via an `email_deliveries` lookup
  before every send (`email_deliveries.status` now also accepts
  `'skipped'`), so a webhook redelivery/manual refresh/reconciliation
  sweep can never double-send. Uses the same `EMAIL_FROM`/`EMAIL_REPLY_TO`
  as everything else — no new Railway env var. Never exposes
  `RESEND_API_KEY` or any provider secret, in the email itself or in
  Super Admin's Notification Details view.

## 8. Password reset and invite link readiness

Fixed this session (see `05cea8c`): `@supabase/ssr`'s browser client
hardcodes PKCE flow, which can never consume an implicit-style link from
`auth.admin.generate_link()` — both reset and invite links now establish
their session explicitly (`establishRecoveryLinkSession`) instead of
relying on auth-js's automatic (and, for this link shape, silently
broken) URL detection. Confirmed:

- Reset page and invite-accept page both show a "Verifying your link…"
  state before rendering the form or an error — no more instant false
  "expired" on a fresh, valid link.
- A token is consumed once — `establishRecoveryLinkSession` scrubs the
  URL immediately after use.
- Mobile browser flow uses the same code path as desktop, no separate
  handling to drift out of sync.

**Supabase-dashboard-only settings, not readable via any tool — verify
directly in the Supabase dashboard, not assumed from this doc:**
- Auth → URL Configuration → Site URL and Redirect URLs must include the
  production frontend origin and its `/reset-password` and `/accept-invite`
  paths (and Super Admin's own reset path, if it differs).
- Auth → Email → OTP/link expiry: recommended 30–60 min for password
  reset, up to 24h for staff invite if the app-level flow supports that
  window (currently governed by Supabase's own link expiry, not an
  app-level override).

## 9. Merchant API key readiness — confirmed, not newly built

Generated server-side (`secrets.token_urlsafe(24)`), stored as a SHA-256
hash (never plaintext), shown once at creation/rotation, scoped per-
merchant on every lookup, revocable and rotatable individually, rate-
limited (`app/core/rate_limit.py`), never appear in logs or audit-log
metadata, never present in the frontend bundle (§10).

## 10. Frontend secret exposure — scan result

```
rg -n "RESEND_API_KEY|SUPABASE_SERVICE_ROLE_KEY|PRIVATE_KEY|JWT_SECRET|SELCOM|CLIENT_SECRET|SECRET|PASSWORD|TOKEN" apps/web
```
Re-run this pass: **clean**. Every real hit is either an enum/mock-data
label containing "SELCOM" (payment method display names), client-side
password-strength UI copy (`PASSWORD_RULES`, not a credential), or
literal sample code on the public `/developers` docs pages showing what a
*merchant's own server* should do with their own API key/webhook secret —
each already carries an explicit "keep this on your server" warning. No
`process.env.` read in `apps/web/src` resolves to a backend-only
variable — only `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SITE_URL`,
`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, and two
internal build/preview flags are read.

## 11. Rate limiting and abuse protection

**Gaps found and closed this pass** (all in-memory, per-process,
`app/core/rate_limit.py` — see its own limitation note on multi-replica
deployments, unchanged from the previous pass and still correct for
today's confirmed single-replica Railway service):

| Endpoint | Scope | Limit |
|---|---|---|
| `POST /v1/merchant/payment-links` | `payment_link_create` | 30/min/IP |
| `POST /v1/merchant/users` (staff invite) | `staff_invite` | 10/min/IP |
| `POST /v1/invoices` | `invoice_create` | 30/min/IP |
| `POST /v1/invoices/{id}/send` | `invoice_send` | 30/min/IP |

Already covered from the previous pass, confirmed still wired: forgot-
password, both Selcom webhook callback endpoints, withdrawal request
creation, withdrawal approve/reject, merchant API key create/rotate,
every collection-creation endpoint, public payment-link pay endpoints.

**Added with the Pay by Link feature**: `POST /public/pay-by-link/{slug}/checkout`
(`pay_by_link_checkout`, 20/min/IP, public), `POST /v1/merchant/pay-by-link`
and `PATCH /v1/merchant/pay-by-link/me` (`pay_by_link_manage`, 10/min/IP,
merchant-authenticated), `GET /v1/merchant/pay-by-link/slug-availability`
(`pay_by_link_slug_check`, 30/min/IP, merchant-authenticated).

**Not covered, by design**: real login goes directly to Supabase Auth
from the browser — this backend never sees the request, so it can't be
limited here (Supabase has its own Auth rate limiting). Plain GET/list
endpoints are unlimited — a documented TODO if enumeration/scraping ever
becomes a real concern, not a gap specific to this cohort size.

## 12. Operational kill switches — confirmed, not newly built

`ENABLE_COLLECTIONS` / `ENABLE_WITHDRAWALS` / `ENABLE_MERCHANT_API_KEYS` /
`ENABLE_AUTO_RECONCILIATION` — see `MVP_LAUNCH_CHECKLIST.md` §12 for the
full behavior table (unchanged, still accurate). Summary: each blocks
only *new* writes/requests of its kind; existing records remain fully
viewable and, where relevant (withdrawals), still actionable by Super
Admin. All four default `true` and require a Railway restart/redeploy to
take effect (no hot-reload).

## 13. Audit logs and monitoring

Confirmed coverage (✅ = existing before this pass, 🆕 = added this pass):

| Event | Status |
|---|---|
| Merchant signup submission | ✅ |
| Merchant approval/rejection | ✅ |
| Withdrawal request | ✅ |
| Withdrawal approval/rejection | ✅ |
| **Payout success** | 🆕 `disbursement.completed` |
| Payout failure/reversal | ✅ `disbursement.failed` / `.reversed` |
| **Collection credited (money-movement)** | 🆕 `collection.credited` |
| **Collection failed (money-movement)** | 🆕 `collection.failed` |
| **Manual "Refresh status" attempted (merchant + API-key callers)** | 🆕 `collection.status_refreshed` (Super Admin's own already existed) |
| API key create/revoke/rotate/rename/IP-allowlist update | ✅ |
| Webhook accepted/rejected (Selcom Checkout) | ✅ |
| Reconciliation success/failure | ✅ (per-row skip logging) |

Every audit entry uses `actor_type="system"` for automated/reconciliation
events and the real user/API-key ID otherwise; metadata never includes
secrets, raw API keys, or full account numbers — phone/account values are
masked at the point they'd otherwise appear.

## 14. This document

You're reading it. See §16 below for what still needs a human decision
before scaling past the numbers in the rollout plan.

## 15. Tests added this pass

- `disbursement.completed` audit log — asserted in
  `tests/test_admin_withdrawals.py::test_approve_reserves_funds_and_calls_selcom`.
- `collection.credited` / `collection.failed` audit logs — asserted in
  `tests/test_collections.py::test_resolve_via_callback_marks_successful_and_posts_ledger`
  and `::test_resolve_via_callback_marks_failed_without_ledger_entries`.
- `collection.status_refreshed` (merchant-portal caller) — asserted in
  `tests/test_collection_refresh_status.py::test_merchant_refresh_status_completes_and_credits`.
- `collection.status_refreshed` (API-key caller, logged on every call
  including an already-resolved no-op — matching the existing Super Admin
  endpoint's behavior) — asserted in
  `tests/test_collections_api.py::test_refresh_status_is_idempotent`.
- New rate-limit wiring tests, one per newly-limited endpoint (pre-fill
  the shared in-memory bucket directly rather than firing dozens of real
  requests, then confirm one more real request is rejected):
  `test_merchant_portal.py::test_create_payment_link_is_rate_limited`,
  `test_merchant_users.py::test_invite_is_rate_limited`,
  `test_invoices.py::test_create_invoice_is_rate_limited` and
  `::test_send_invoice_is_rate_limited`.
- Everything else this brief asked for (duplicate-credit/debit
  prevention, one-bad-row sweep isolation, hardcoded-cap removal,
  approval re-checks, CEO/merchant email routing) already had test
  coverage from earlier hardening passes this session — confirmed via the
  full suite run in §16, not re-written.

## 16. Checks run

- `python -m pytest` (full backend suite, including every test above) —
  all passing.
- `python -m ruff check .` — clean on every file touched this pass.
- `npm run lint --workspace=apps/web`, `npx tsc --noEmit`,
  `npm run build --workspace=apps/web` — no frontend code changed this
  pass; run to confirm the build is still clean.
- Full-repo secret scan:
  ```
  rg -n "RESEND_API_KEY|SUPABASE_SERVICE_ROLE_KEY|PRIVATE_KEY|JWT_SECRET|API_KEY|SELCOM|CLIENT_SECRET|SECRET|PASSWORD|TOKEN|\.env" .
  ```
- Frontend-only secret scan (§10) — clean.
- `git status` reviewed before commit: no `.env` file staged, no secret
  values staged, no backend-only key referenced from `apps/web`.

## 17. Remaining operational risks

- Rate limiter is per-process/in-memory — correct for today's confirmed
  single-replica Railway deployment, but silently multiplies the
  effective limit if ever scaled horizontally without a shared (Redis)
  backend. Revisit before adding a second replica.
- API key hash is fast SHA-256, not a slow KDF — acceptable given the key
  itself is a 24-byte random token, but worth a deliberate look before
  scaling meaningfully past this cohort.
- No formal balance *reservation* exists for a still-pending withdrawal
  request (by design — the atomic approval-time RPC is the only place
  that actually needs to be race-safe, and it is) — two pending requests
  that together exceed balance simply means whichever is approved second
  fails cleanly, nothing to reconcile.
- No `send_withdrawal_rejection_email` exists yet — a rejected withdrawal
  reaches the merchant via in-app notification only, not email (request
  and success emails both exist).
- Supabase Auth email-link expiry/Site-URL/Redirect-URL settings live
  only in the Supabase dashboard — not verifiable from this repo; confirm
  directly before the first real invite/reset goes out to a new cohort.

## 18. Rollout plan

| Week | Cohort | Focus |
|---|---|---|
| 1 | 3–5 trusted merchants | Watch every collection/withdrawal manually; confirm reconciliation sweep logs and email delivery for real traffic, not just tests. |
| 2 | 10–20 merchants | Same monitoring, less manual per-transaction attention; confirm rate limits aren't tripping on legitimate usage. |
| 3 | 30–50 merchants | Full daily-operations checklist below in regular use. |
| After stable monitoring | 100 merchants | Full cohort — revisit §17's risks before going materially past this. |

### Daily operations checklist
- Check Railway logs for `checkout_reconciliation_sweep_starting` /
  `disbursement_reconciliation_sweep_starting` recurring on schedule.
- Check for any `checkout_reconciliation_row_failed` entries — investigate
  the underlying row, don't just note it resolved on its own.
- Spot-check a handful of `collections`/`disbursements` against their
  `ledger_entries` for balance sanity.

### Transaction monitoring checklist
- Any `NEEDS_RECONCILIATION` disbursement — resolve manually via
  `POST /v1/admin/withdrawals/{id}/refresh-status` before end of day.
- Any fraud-alert-flagged merchant with a pending withdrawal — review
  before it reaches approval.
- Spot-check the Collections view filtered to `source = PAY_BY_LINK` —
  confirm amounts/customer emails look sane for merchants using a
  permanent Pay by Link page, same as any other source.

### Withdrawal approval checklist
- Confirm requested amount is within the merchant's normal pattern.
- Confirm merchant standing (`status=active`, `kyc_status=verified`) at
  approval time — the system re-checks this automatically, but a human
  reviewing the same signal catches context automation can't.

### Merchant onboarding checklist
- Verify submitted documents against `docs/` KYC requirements before
  approving.
- Confirm the CEO notification email actually arrived at `CEO_EMAIL` for
  every submission — this is the trigger for the human review step.

### Support process
- First response: check `audit_logs` and `email_deliveries` for the
  merchant/resource in question before escalating.
- Escalate anything touching §17's known risks or any ledger-balance
  discrepancy immediately — do not attempt a manual ledger fix (append-
  only, DB-trigger-enforced).

### Incident response
See `MVP_LAUNCH_CHECKLIST.md` §6 — unchanged, still current.

### Quick disable reference
See `MVP_LAUNCH_CHECKLIST.md` §8/§9/§12 — unchanged, still current.

### Verifying wallet ledger consistency
For a given merchant: sum `ledger_entries` debits and credits on their
`ledger_accounts` row and confirm it matches the row's own `balance`
column; `post_ledger_entries`'s balanced-per-transaction and no-negative-
balance checks make a drift here a database-level constraint violation,
not a silent possibility — if one is ever found, it indicates a bug to
investigate, not a value to hand-correct.

## 19. Security & SEO hardening pass (2026-08-30)

Full detail lives in `MVP_LAUNCH_CHECKLIST.md` §18–§19 (security headers,
Google Search Console/robots/sitemap, SEO metadata, social preview image,
Discord cache behavior, production CORS, private-route noindex, security
tools not public — checklist + verification for every item). Summary of
what changed:

- **Confirmed already correct, not changed**: production CORS wildcard
  rejection (§4 above), Selcom webhook signature verification (fails
  closed in production, never bypassed outside `ENVIRONMENT=development`
  — `app/routers/webhooks.py`), collection/withdrawal double-credit/debit
  safety (§§4–5 above, unchanged by this pass), favicon/app icons (already
  the current official brand mark).
- **Newly fixed**: Swagger/ReDoc/OpenAPI docs were reachable,
  unauthenticated, in every environment including production — now
  disabled outright when `ENVIRONMENT=production`
  (`Settings.docs_enabled`). Seven previously-unlimited money-moving/
  submission endpoints gained rate limits (six merchant-portal "Request
  Collection" endpoints + `create-order-minimal`, merchant onboarding
  submission, the public contact-form endpoint). Both apps now send the
  standard defensive HTTP header set (HSTS, CSP, X-Frame-Options,
  Referrer-Policy, Permissions-Policy, ...). Every private/authenticated
  route now carries `robots: { index: false }` plus a matching
  `robots.txt` disallow entry. The Open Graph/Twitter social preview image
  was still the old, never-actually-used-in-the-app logo — replaced with
  a versioned (`-v2`) image generated from the real current brand mark.
- **Tests**: `apps/web/src/security-secret-scan.test.ts` (no backend
  secret env-var name anywhere in `apps/web/src`),
  `apps/web/src/app/seo-and-security.test.ts` (robots/sitemap/headers/
  metadata/noindex), `apps/api/tests/test_security_headers.py`,
  `docs_enabled` cases in `test_settings.py`, and one rate-limit wiring
  test each in `test_merchant_portal.py`/`test_onboarding.py`/
  `test_public_inquiries.py`.
