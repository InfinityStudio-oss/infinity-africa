# Pre-traffic production security check

> Note: this is a dated historical record of the 2026-09-09 pass, written
> while the product was still branded Infinity Africa at infinityafrica.net.
> It intentionally still refers to that name/domain as configured at the
> time — the platform has since moved to InfinityPay / infinitypay.me.

**Date:** 2026-09-09
**Scope:** urgent pre/early-traffic safety inspection — Infinity Africa (now
InfinityPay) is already serving real merchants; this is a verification +
light-hardening pass.
**Result:** ✅ safe to continue serving traffic. Two low-severity hardening
changes made (below). No critical issues. No secrets exposed.

---

## 1. Git / sensitive files

- Working tree **clean**, on `main`, up to date with `origin/main` at start.
- Tracked `.env*` files: **only** `apps/api/.env.example` and
  `apps/web/.env.example` — both contain placeholders / non-secret defaults
  only (every `*_API_KEY`, `*_SECRET`, `SERVICE_ROLE_KEY`, `WEBHOOK_SECRET`,
  `DATABASE_URL`, `PRIVATE_KEY_BASE64` line is blank).
- Real env files present locally (`apps/api/.env`, `apps/web/.env.local`) —
  confirmed **git-ignored**, not tracked.
- `docs/test-accounts.md` (real throwaway passwords) — git-ignored, **not tracked**.
- `.gitignore` **updated** — added `*.pfx`, `*.csr`, `*-service-account.json`,
  `playwright-report/`, `test-results/`, `supabase/.temp/`.

## 2. Secret scan

| Check | Result |
|---|---|
| Backend-secret env-var names in `apps/web/src` | ❌ none (only the `security-secret-scan.test.ts` allow-list + merchant-facing doc code samples using the merchant's *own* `INFINITY_WEBHOOK_SECRET`) |
| Private keys / JWT literals / `re_…` / `sk_live_…` anywhere tracked | ❌ none |
| `eyJ…` tokens in tracked files | ❌ none |
| Real secrets in `docs/` | ❌ none |
| Real secrets in `.env.example` | ❌ none |
| `apps/web/src/security-secret-scan.test.ts` (CI guard) | ✅ passing |

**No secret rotation required** — nothing was found in tracked history.
Frontend only ever reads `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SITE_URL`,
`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (all public by design).

## 3. API route audit

Every backend route enumerated and classified. **No missing auth, no
trusted-frontend `merchant_id`, no open admin/debug route.**

| Group | Auth | Notes |
|---|---|---|
| `/v1/admin/*`, `/v1/system/*` | `require_super_admin` on **every** route | incl. onboarding approve/reject, risk, pricing, withdrawals, disputes, IP-allowlist |
| `/v1/merchant/*` | `require_own_merchant_role` (merchant resolved from JWT, never path/body) | except `POST /users/me/accept-invite` → `get_current_user` (correct — invitee isn't a member yet) |
| `/v1/merchants/{id}/…` (nested) | `require_role(...)` — membership on path `merchant_id` | |
| `/v1/collections`, `/v1/disbursements`, `/v1/invoices`, `/v1/payment-links`, `/v1/transactions` (flat, API-key or JWT) | `get_authenticated_caller` + **`authorize_merchant_action(caller, payload.merchant_id, …)`** + `require_api_key_scope(...)` in every handler | body `merchant_id` is always checked against the caller |
| `/v1/onboarding/*` | `get_current_user` / `get_own_merchant` | merchant created from verified JWT identity |
| `POST /v1/merchants`, `PATCH /v1/merchants/{id}/status` | `require_super_admin` | merchant cannot self-create or self-approve |
| Public payment pages (`/public/payment-links/*`, `/public/pay-by-link/*`) | none / `rate_limit` | merchant resolved by slug lookup; amount/fee/net computed backend-side; `require_approved_merchant` enforced downstream |
| `POST /v1/webhooks/selcom`, `/v1/webhooks/selcom/checkout` | `rate_limit` + **HMAC signature, fail-closed** | see §5 |
| `GET /v1/webhooks/selcom[/checkout]` | none | reachability probe only, returns `{"status":"ok"}`, no data, no action |
| `POST /v1/auth/forgot-password` | `rate_limit` | account-enumeration-safe generic response |
| `POST /v1/public/inquiries` | `rate_limit` | |
| `POST /v1/public/disputes/report` | **`rate_limit` added this pass** (was unlimited; accepts file uploads + triggers merchant email) |
| `GET /health` | public | returns `{"status":"ok","environment":"…"}` — see remaining risks |
| `GET /docs`, `/redoc`, `/openapi.json` | **disabled in production** (`settings.docs_enabled` → `environment != "production"`) — verified **404** live |

## 4. Broken-route check (frontend ↔ backend)

Extracted every `/v1/*` and `/public/*` path referenced in `apps/web/src` and
matched against backend routers. **No path/method mismatches, no missing
`/v1` prefix.** The only unmatched strings are in **comments / mock-data
placeholders** (`/v1/merchants/{id}/reports`, `/v1/merchant/customers`) and a
comment referencing Supabase's own `/auth/v1/verify` — none are live calls.

## 5. Money-movement safety

**Collections**
- `create_processing_collection` (the single chokepoint for dashboard, API-key,
  and dynamic-QR collections) calls `require_approved_merchant()` — a
  pending/unapproved merchant **cannot** collect.
- Amount/currency validated backend-side; fee/net via `calculate_collection_fee`
  backend-side.
- `resolve_collection` is the single idempotent credit chokepoint — early-returns
  if the collection is missing or already resolved; credits (`post_collection_entries`
  + `_apply_collection_success`) only on `status == "successful"`.
- `finalize_pending_review_collection` and the reversal path are both explicitly
  idempotent (no-op on already-finalized / already-reversed).
- Failed / pending / cancelled / reversed never credit.

**Selcom webhooks**
- `POST /v1/webhooks/selcom` — verifies `X-Selcom-Signature` HMAC over the raw
  body; invalid/missing → logged + **401**. Duplicate `(provider, event_id)` →
  early "duplicate".
- `POST /v1/webhooks/selcom/checkout` — **fails closed on signature, always**;
  the dev test-secret bypass requires `environment == "development"` (impossible
  on Railway). The webhook payload's `payment_status`/`result`/`resultcode` are
  **never trusted** — it's used only to locate the collection, then
  `resolve_checkout_collection_from_webhook_hint` re-queries Selcom with our own
  credentials. Wallet credit only from that trusted confirmation.

**Scheduled reconciliation**
- `_checkout_reconciliation_loop` / `_disbursement_reconciliation_loop` — one
  failed sweep is logged and never crashes the loop; both gated by
  `ENABLE_AUTO_RECONCILIATION` and their interval var (0 = off). They resolve
  through the same idempotent `resolve_*` chokepoints, so a duplicate
  sweep/webhook/manual-refresh cannot double-credit or double-debit.

**Withdrawals**
- `execute_disbursement` → **always** `PENDING_ADMIN_APPROVAL`; **Selcom is never
  called from this path.** `_check_merchant_is_verified` runs before any row is
  created (unapproved/unverified/suspended merchant → `409 withdrawal_restricted`;
  open HIGH/CRITICAL fraud alert also blocks).
- `approve_disbursement` re-checks merchant standing + requires status
  `PENDING_ADMIN_APPROVAL` (duplicate approval → no-op) before the **only**
  provider call path (`_reserve_and_run_disbursement_provider`, atomic reserve).
- Reject requires `PENDING_ADMIN_APPROVAL`, debits nothing. Failed payout
  reverses the reservation. Successful payout debits once.
- Withdrawal merchant fee = 0 for MVP (`calculate_withdrawal_fee` returns
  zero-fee). Amount guardrails (`MIN/MAX/DAILY_WITHDRAWAL_*`) enforced backend-side.
- `REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS` documents an invariant — no code
  path skips approval regardless of its value; `main.py` logs a startup warning
  if it's ever set false.

## 6. Auth & onboarding

- Signup / email-verification / `/auth/callback` — fixed and verified live
  earlier today (`4782dcb`); real merchants completed the flow end-to-end.
- Onboarding accepts **business details only** — KYC document upload removed
  (`a709cd7`, deployed to Railway, verified ACTIVE). `_REQUIRED_APPROVAL_DOCUMENTS`
  is empty; approval no longer 422s on missing documents.
- Submission → `PENDING_VERIFICATION`; **CEO notification** to
  `ceo@infinityafrica.net` on submission (verified Delivered in Resend today).
- Pending merchant blocked from collections / payment links / invoices / API
  keys (production) / withdrawals — UI guard (`requireVerifiedMerchant`) + API
  guard (`require_approved_merchant`, `_check_merchant_is_verified`).
- Super Admin approval required → `status=active`, `kyc_status=verified`, wallet
  created, **welcome email to the merchant** (never CEO — covered by
  `test_welcome_email_never_goes_to_ceo`).
- Login errors are safe + specific: "verify your email" for unconfirmed,
  generic "Incorrect email or password" for bad credentials, no stack traces.

## 7. CORS & security headers (verified live)

**CORS** (`web-production-3fdc4a.up.railway.app`):
- `https://infinityafrica.net` → echoed ✅
- `https://www.infinityafrica.net` → echoed ✅
- `https://evil.example.com` → **not** echoed ✅
- `Vary: Origin` present. `allow_credentials=True`. Settings validator refuses
  to boot with `"*"` outside `ENVIRONMENT=development`.

**API response headers** (verified on `/health`): `Strict-Transport-Security`
(2y, preload), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`
(camera/mic/geo/payment/usb all `()`), `Content-Security-Policy: default-src
'none'; frame-ancestors 'none'`.

**Frontend headers** (verified on `/merchant/login`): full CSP with
`default-src 'self'`, scoped `connect-src` (Supabase + the Railway API only),
`object-src 'none'`, `frame-ancestors 'none'`, `form-action 'self'`,
`upgrade-insecure-requests`; HSTS; `X-Frame-Options: DENY`; nosniff;
Referrer-Policy; Permissions-Policy. Source maps **not served** (`.js.map` → 403).

## 8. Public debug / tooling

- Swagger/OpenAPI (`/docs`, `/redoc`, `/openapi.json`) → **404 in production** ✅
- No debug/test/log-viewer/DB-tool routes exist.
- `/v1/system/selcom-config-status` — `require_super_admin`, returns booleans
  only (`*_configured`), never a secret value.
- Unauthenticated `/v1/merchant/*` and `/v1/admin/*` → **401** (not 500, no
  stack trace); unknown route → **404**.
- Frontend source maps not exposed.

## 9. Fixes made this pass

| # | Change | Severity | File |
|---|---|---|---|
| 1 | Rate-limit `POST /v1/public/disputes/report` (5/60s) — was unlimited despite accepting file uploads + sending merchant email | low | `apps/api/app/routers/public_disputes.py` |
| 2 | `.gitignore` — add `*.pfx`, `*.csr`, `*-service-account.json`, `playwright-report/`, `test-results/`, `supabase/.temp/` | low (hygiene) | `.gitignore` |

## 10. Tests / checks

| Check | Result |
|---|---|
| `python -m pytest` (apps/api) | ✅ 1010 passed |
| `python -m ruff check .` | 1 error — pre-existing `app/routers/health.py:10` B008 (`Depends` in default), present on `main` before this pass; not introduced here |
| `npm run lint --workspace=apps/web` | ✅ 0 errors (1 pre-existing `<img>` warning in `pay-by-link-form.tsx`) |
| `npx tsc --noEmit` (apps/web) | ✅ clean |
| `npm run build --workspace=apps/web` | ✅ compiled successfully |
| `npx vitest run` (apps/web) | ✅ 306/306 (51 files), incl. `security-secret-scan.test.ts` |

## 11. Live smoke (production)

| Target | Result |
|---|---|
| `infinityafrica.net/` , `/create-account`, `/merchant/login`, `/admin-login` | 200 |
| `/onboarding` unauthenticated | 200 → redirects to `/merchant/login` (guard works) |
| `/auth/callback` with no token | 200 → `/merchant/login?notice=…verified…` (fails safe) |
| API `/health` | `{"status":"ok","environment":"production"}` |
| API `/docs` `/redoc` `/openapi.json` | 404 |
| API `/v1/merchant/me`, `/v1/admin/overview` unauthenticated | 401 |
| CORS from disallowed origin | not echoed |

## 12. Remaining risks (non-blocking)

- **`/health` returns `environment`** in addition to `status`. Not a secret
  (the Railway hostname already says "production"), left as-is to avoid
  disturbing any external monitor that reads it. Could be trimmed to
  `{"status":"ok"}` in a later pass.
- **Pre-existing `health.py:10` ruff B008** — cosmetic, `Depends()` in a
  default arg. Not fixed here to keep this pass strictly security-scoped.
- **Withdrawal balance not formally reserved at request time** (only at
  approval) — documented as a `TODO` in `app/services/disbursements.py`. The
  atomic reservation in `_reserve_and_run_disbursement_provider` at approval
  time is the real double-spend guard, so this is a UX gap, not a money-loss
  risk.
- **`NEXT_PUBLIC_SITE_URL` is the apex** while the site canonicalises to
  `www.` — verification links hit apex `/auth/callback` then 308 to `www`,
  which works. Optionally align to `https://www.infinityafrica.net`.

## 13. Manual checks (platform dashboards — cannot be verified from the repo)

- **Railway** `apps/api` env: `ENVIRONMENT=production` (confirmed indirectly via
  `/health`), `CORS_ORIGINS` = the two real domains (confirmed via live
  preflight), `SUPABASE_SERVICE_ROLE_KEY` / `RESEND_API_KEY` / `SELCOM_*` set
  server-side only, `SELCOM_MODE` / `SELCOM_CHECKOUT_MODE` / `SELCOM_BUSINESS_MODE`
  at the intended values, reconciliation interval vars set if the timed sweep is
  wanted.
- **Vercel** `apps/web` env: only `NEXT_PUBLIC_*` vars; no backend secret.
- **Supabase** Auth: custom SMTP → Resend (done today), redirect allow-list
  includes `/auth/callback` for both apex and `www`, Site URL set, email rate
  limit raised.
- **Supabase** advisors (security + performance) — run and review.

## 14. Safe to push / deploy?

**Yes.** No secrets staged, no `.env` staged, only source + docs changes. The
two changes are additive hardening and do not touch collection, wallet,
withdrawal, reconciliation, onboarding, or email flows.
