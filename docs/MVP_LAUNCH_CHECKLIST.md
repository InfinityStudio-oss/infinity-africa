# MVP Launch Checklist

Consolidated go-live checklist for opening InfinityPay to selected real
merchants with real collections and real withdrawals. This is the
platform-wide checklist; it doesn't replace the subsystem-specific docs it
links to — those still have the deeper mechanics and incident history.

Related docs: [`docs/withdrawal-pricing-and-approval.md`](./withdrawal-pricing-and-approval.md),
[`docs/withdrawal-production-pilot-checklist.md`](./withdrawal-production-pilot-checklist.md) (now superseded by §3 below),
[`docs/selcom-checkout-collections.md`](./selcom-checkout-collections.md),
[`docs/selcom-live-go-live.md`](./selcom-live-go-live.md),
[`docs/collections-production-go-live-checklist.md`](./collections-production-go-live-checklist.md),
[`docs/ledger-reconciliation.md`](./ledger-reconciliation.md),
[`docs/email-delivery.md`](./email-delivery.md),
[`docs/merchant-collection-notifications.md`](./merchant-collection-notifications.md).

## 1. Railway backend env vars

**Withdrawal limits (new, replaces the old pilot cap):**
```
MIN_WITHDRAWAL_AMOUNT_TZS=1000
MAX_WITHDRAWAL_AMOUNT_TZS=5000000
DAILY_WITHDRAWAL_LIMIT_TZS=10000000
REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS=true
```
Remove `WITHDRAWAL_PILOT_MODE`/`WITHDRAWAL_PILOT_MAX_AMOUNT_TZS` if still
set — no code reads them anymore (see §3). `REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS`
documents an invariant the code enforces unconditionally; it cannot
actually disable approval, and setting it `false` only produces a startup
warning log, nothing more.

**Production safety switches (new):**
```
ENABLE_COLLECTIONS=true
ENABLE_WITHDRAWALS=true
ENABLE_MERCHANT_API_KEYS=true
ENABLE_AUTO_RECONCILIATION=true
```
All default `true`. See §12 for what flipping each one to `false` actually
does.

**Reconciliation schedulers (already live, confirmed working 2026-08-28):**
```
SELCOM_CHECKOUT_RECONCILE_INTERVAL_SECONDS=120
SELCOM_DISBURSEMENT_RECONCILE_INTERVAL_SECONDS=120
```

**Everything else** (Selcom Checkout/Business credentials, Supabase
service role key, JWT secret, Resend API key, CORS origins, `LOG_LEVEL`)
is unchanged by this pass — see `apps/api/.env.example` for the full,
current list with explanations. None of it belongs in Vercel.

## 2. Vercel/frontend env vars

Only ever:
```
NEXT_PUBLIC_API_URL=<backend URL>
NEXT_PUBLIC_SITE_URL=<frontend URL>
NEXT_PUBLIC_SUPABASE_URL=<Supabase project URL>
NEXT_PUBLIC_SUPABASE_ANON_KEY=<Supabase anon key — public by design>
```
Confirmed clean 2026-08-28 (`rg` across `apps/web/src` and
`apps/web/.env.example` — see §14): no `SELCOM_*`, no
`SUPABASE_SERVICE_ROLE_KEY`, no `JWT_SECRET`, no `RESEND_API_KEY` anywhere
in the frontend. `NEXT_PUBLIC_SUPABASE_ANON_KEY` is meant to be public —
it's constrained entirely by Postgres Row Level Security, not secrecy.

## 3. Withdrawal approval policy (confirmed, not newly built)

Every merchant-submitted withdrawal — any amount, any channel — always
lands `PENDING_ADMIN_APPROVAL`. There is no code path where
`execute_disbursement` (the only way a withdrawal is created) reaches
Selcom directly; only a Super Admin calling `approve_disbursement` via
`POST /v1/admin/withdrawals/{id}/approve` (`require_super_admin`-gated)
ever does. This was already true before this pass — confirmed by reading
`app/services/disbursements.py` end to end, not assumed.

What changed this pass:
- `approve_disbursement` now **re-checks merchant standing and open
  high-risk fraud alerts** at approval time, not just at request time —
  closes a real gap where a merchant suspended (or a new fraud alert
  opened) *after* requesting but *before* a Super Admin got to reviewing
  it would previously have been approved anyway.
- Available balance was already atomically re-checked at approval time
  (via the `post_disbursement_entries` Postgres RPC, which can never take
  a wallet negative) — unchanged, already correct.
- Rejection reason was already required and stored (`rejection_reason`
  column) — unchanged, already correct.
- Rejected/failed withdrawals were already never debited — unchanged,
  already correct (nothing is reserved until approval).

**Known gap, deliberately left as a TODO, not fixed this pass:** no
`send_withdrawal_rejection_email` exists — a rejected withdrawal reaches
the merchant via an in-app notification only, not email (the request and
success emails already exist and are unaffected). See the TODO comment
next to `reject_disbursement` in `app/services/disbursements.py`.

## 4. Withdrawal limits

`Settings.min_withdrawal_amount_tzs` / `max_withdrawal_amount_tzs` /
`daily_withdrawal_limit_tzs` (`app/services/disbursements.py::_check_withdrawal_amount_limits`),
enforced before any withdrawal row is written, backend-only — the frontend
only ever displays whatever error message the backend returns. The daily
limit is a rolling 24-hour cumulative cap per merchant across every
non-REJECTED/non-FAILED request (a pending request already counts, since
it represents money the merchant intends to withdraw today).

No formal balance *reservation* exists for a still-pending request (see
the TODO in `disbursements.py`'s module docstring) — this is safe by
construction, not an oversight: the only place money actually moves is
the atomic approval-time RPC, which independently re-checks live balance
and can never overdraw. Two pending requests that together exceed
available balance simply mean whichever is approved second fails cleanly
(marked `FAILED`, nothing to reverse).

## 4a. Pricing policy (2026-08-31)

**Merchant charges apply to collections only. Withdrawals do not charge
merchant fees during MVP. Any provider disbursement cost is treated as
an internal platform cost unless a future policy changes this.** See
[`docs/collection-and-withdrawal-pricing.md`](./collection-and-withdrawal-pricing.md)
for the full detail — `calculate_withdrawal_fee` always returns zero now,
regardless of any `merchant_pricing_rules` row; a withdrawal reserves
and debits exactly the requested amount. Collection fees are unchanged.

## 5. Merchant onboarding checklist

A merchant must be `status=active` and `kyc_status=verified`
(`_check_merchant_is_verified`) before their first withdrawal request —
this was already enforced, unchanged. No new onboarding step was added
this pass. See `docs/withdrawal-pricing-and-approval.md` for the fee-quote
flow a merchant sees before submitting.

## 6. Incident response steps

1. **Something looks financially wrong** (balance drift, unexpected
   credit/debit, duplicate-looking transaction): stop — do not approve
   any more withdrawals or manually edit `ledger_entries` (it's
   append-only and DB-trigger-enforced; there is no "just fix the row").
   Pull the relevant `transactions`/`ledger_entries`/`disbursements`/
   `collections` rows and the Railway logs for that time window first.
2. **Suspected secret leak** (a key visible in a browser, a log, a commit):
   rotate it immediately (Selcom: regenerate via their Business portal,
   §8 of `docs/withdrawal-production-pilot-checklist.md`; Supabase: roll
   the service role key from the Supabase dashboard; Resend: revoke and
   reissue from the Resend dashboard) — then redeploy.
3. **A specific subsystem is misbehaving** (Selcom outage, a bad
   collection/withdrawal loop, abuse traffic): use §12's kill switches to
   pause new requests without a full redeploy, then investigate calmly.
4. **Reconciliation looks stuck**: see §7's log-search steps before
   assuming it's broken — check whether it's just legitimately idle
   (nothing pending) first.

## 7. Manual reconciliation fallback

Automatic reconciliation (§1's `SELCOM_*_RECONCILE_INTERVAL_SECONDS`) is
the primary mechanism, confirmed working end-to-end 2026-08-28. If it's
ever disabled or looks stuck:

- **Collections**: the merchant/admin-facing "Refresh status" button
  (`POST /v1/.../collections/{id}/refresh-status`) does the exact same
  authenticated Selcom order-status lookup as the scheduler, for one
  collection at a time — always available regardless of scheduler state.
- **Withdrawals**: `POST /v1/admin/withdrawals/reconcile-pending` (Super
  Admin only) does the same batch sweep on demand; `POST
  /v1/admin/withdrawals/{id}/refresh-status` does one at a time.
- **To confirm the scheduler itself is healthy**: search Railway logs for
  `checkout_reconciliation_scheduler_started` /
  `disbursement_reconciliation_scheduler_started` (should appear once at
  boot with the configured interval), then
  `checkout_reconciliation_sweep_starting` /
  `disbursement_reconciliation_sweep_starting` (should recur every
  interval). A single bad row is logged as
  `checkout_reconciliation_row_failed` /
  (disbursements have no equivalent-named row-level log line other than
  the sweep's own per-row `refresh_disbursement_status` exceptions) and
  skipped — it no longer aborts the whole sweep for everyone else (fixed
  2026-08-28, see git history on `checkout_reconciliation.py` and
  `disbursements.py`).

## 8. How to disable withdrawals quickly

Set `ENABLE_WITHDRAWALS=false` in Railway and let it redeploy (or restart
the service if your Railway plan applies env var changes without a full
rebuild). Every `POST /v1/disbursements/*` withdrawal-creation endpoint
returns `503 feature_disabled` immediately. Already-pending withdrawals
remain visible and Super Admins can still approve/reject/reconcile them —
this only blocks brand-new requests. Revert by setting it back to `true`.

## 9. How to disable collections quickly

Set `ENABLE_COLLECTIONS=false` in Railway. Every collection-creating
endpoint (`/v1/collections/*`, the merchant portal's request-collection
endpoints, the public payment-link `/pay` endpoints) returns `503
feature_disabled`. Existing payment links, collections, and their status
remain fully viewable — customers mid-payment on an already-created
collection are unaffected; only *new* collection attempts are blocked.

## 10. How to check logs safely

Railway → API service → **Deploy Logs**. Clear any search filter before
scrolling to a specific timestamp — a filtered search hides the
multi-line context (tracebacks, related log lines) around a match; see
the "Copy logs as… Plain text" option in the search bar's download menu
for pulling an unfiltered window to inspect offline.

Confirmed clean this pass: no secret material (`RESEND_API_KEY`,
`SUPABASE_SERVICE_ROLE_KEY`, Selcom keys/secrets, JWT secret, plaintext
API keys) appears in any logger call anywhere in `apps/api/app` (grepped
for log calls near key-shaped variable names — see §14). Every
`selcom_checkout_request`/`selcom_business_*` log line logs only
path/status/latency, never request/response bodies (established
convention, unchanged).

## 11. How to verify no frontend secrets

```
rg -n "RESEND_API_KEY|SUPABASE_SERVICE_ROLE_KEY|PRIVATE_KEY|JWT_SECRET|SELCOM|CLIENT_SECRET|SECRET|PASSWORD|TOKEN" apps/web/src
```
Every real hit as of 2026-08-28 is one of: an enum/mock-data string
containing "SELCOM" (payment method names), `PASSWORD_RULES` (client-side
password-strength UI copy, not a credential), or literal sample code on
the public `/developers/*` docs pages showing what a *merchant's own
server* should do with their API key/webhook secret — each already
carries an explicit "keep this on your server" warning. No `process.env.`
read in `apps/web/src` resolves to a backend-only variable; the only
`process.env.` names used are `NEXT_PUBLIC_API_URL`,
`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, and two
internal build/preview flags. Re-run this grep after any frontend change
that touches env vars or the `/developers` example pages.

## 12. Production safety switches — what each one does

| Flag | Default | Blocks (when `false`) | Never blocks |
|---|---|---|---|
| `ENABLE_COLLECTIONS` | `true` | New collection creation (all methods, all entry points — dashboard, API key, public pay) | Viewing/listing existing collections; refresh-status |
| `ENABLE_WITHDRAWALS` | `true` | New withdrawal requests (`POST /v1/disbursements/*`) | Super Admin approve/reject/reconcile on already-existing requests |
| `ENABLE_MERCHANT_API_KEYS` | `true` | New API key creation and rotation | Already-issued keys keep authenticating; individual revoke still works |
| `ENABLE_AUTO_RECONCILIATION` | `true` | Both reconciliation schedulers (checkout + disbursement), regardless of their interval env vars | Manual "Refresh status" and the admin batch-reconcile endpoint |

All four are read fresh on next app start — flipping one in Railway
requires the service to actually restart/redeploy to take effect (env var
changes don't hot-reload a running process).

## 13. Rate limiting

Added this pass (`app/core/rate_limit.py`) — an in-memory, per-process,
fixed-window limiter, since no rate-limiting package existed anywhere in
this codebase before. **Known limitation**: state is per-process, not
shared across replicas. This deployment is confirmed single-replica as of
2026-08-28 (Railway "1 Replica"), so this is correct today — revisit with
a Redis-backed or edge/proxy-level limiter before ever scaling
horizontally, or the effective limit silently multiplies by replica
count.

Currently rate-limited: `POST /auth/forgot-password` (5/min/IP), the
public payment-link pay endpoints (20/min/IP), Pay by Link's public
checkout endpoint (20/min/IP), both Selcom webhook callback endpoints
(120/min/IP — generous, just flood protection, real Selcom traffic should
never come close), withdrawal request creation (10/min/IP), withdrawal
approve/reject (60/min/IP — a trusted Super Admin action, limited
generously), merchant API key create/rotate (10/min/IP), invoice
create/send (30/min/IP), staff invite (10/min/IP), every collection-
creation endpoint across both `/v1/collections/*` routers (20/min/IP),
**and, added in the 2026-08-30 security-hardening pass**: every merchant-
portal "Request Collection" endpoint (`/v1/merchant/collections/*` —
ussd-push, stk-push, selcom-pesa-push, dynamic-qr, hosted-checkout,
wallet-push, create-order-minimal; 20/min/IP, same limit as their
API-key equivalents — previously unlimited despite moving real money),
merchant onboarding submission (`POST /v1/onboarding/merchant-account`,
5/min/IP), and the public contact-form endpoint (`POST
/v1/public/inquiries`, 10/min/IP — unauthenticated, triggers a CEO
notification email per submission).

**Not covered, and why**: real user login happens via Supabase Auth
directly from the browser — this backend never sees a login request, so
it can't rate-limit it from here. Supabase has its own auth rate limiting
(check the Supabase dashboard's Auth settings if login abuse is ever a
concern). Plain GET/list endpoints (reading collections, withdrawals,
payment link details) are not rate-limited — add if scraping/enumeration
becomes a real concern; the pattern (`Depends(rate_limit(scope=...,
limit=N, window_seconds=W))`) is copy-paste-ready in
`app/core/rate_limit.py`'s own docstring.

## 14. Secret exposure scan — how to re-run it

Whole repo:
```
rg -n "RESEND_API_KEY|SUPABASE_SERVICE_ROLE_KEY|PRIVATE_KEY|JWT_SECRET|API_KEY|SELCOM|CLIENT_SECRET|SECRET|PASSWORD|TOKEN|\.env" .
```
Frontend only (the one that actually matters for browser exposure):
```
rg -n "RESEND_API_KEY|SUPABASE_SERVICE_ROLE_KEY|PRIVATE_KEY|JWT_SECRET|SELCOM|CLIENT_SECRET|SECRET|PASSWORD|TOKEN" apps/web
```
Confirmed clean 2026-08-28 (see §11 for what the frontend hits actually
are). Also confirmed: no `.env` file (only `.env.example`) is tracked in
git anywhere in the repo (`git ls-files | grep -E "\.env$"`).

## 15. Merchant API credentials — confirmed, not newly built

Already correct before this pass, verified by reading
`app/routers/merchant_portal.py` end to end: keys are generated
server-side (`secrets.token_urlsafe(24)`), stored as a SHA-256 hash (not
plaintext), shown to the merchant exactly once at creation/rotation,
scoped per-merchant (every lookup filters on the caller's own
`merchant_id`), revocable, and never appear in logs or audit-log
metadata. One thing worth knowing, not fixed this pass: the hash is a
fast SHA-256, not a slow/salted KDF like bcrypt/argon2 — acceptable given
the key itself is a 24-byte random token (not a guessable low-entropy
password), but worth a deliberate look before scaling far past MVP.

## 16. Wallet ledger — confirmed, not newly built

`ledger_entries` is genuinely append-only (a DB trigger forbids
update/delete), posted only through one atomic Postgres RPC
(`post_ledger_entries`) that also enforces the no-negative-balance rule
and a balanced-per-transaction check, both at the database level — not
just in application code. Double-credit/double-debit is prevented by
`resolve_collection()`'s own idempotency guard (a collection can only be
resolved once) plus the `Idempotency-Key` header mechanism on every
money-moving endpoint. `merchant_id`/fee/net/provider_reference/status
live on the separate `transactions` table, joined to `ledger_entries` for
display — this is standard double-entry-ledger shape, not a gap.

## 17. Merchant collection notification emails

Full detail: [`docs/merchant-collection-notifications.md`](./merchant-collection-notifications.md).

- Merchant Portal → Settings → Notification Settings: up to 2 email
  addresses, an enable/disable toggle. Backend is the source of truth for
  every rule (valid format, max 2, no duplicates, at least 1 required
  while enabled) — the frontend only guides.
- Sent from `_apply_collection_success` (the single chokepoint every
  collection source funnels through) right after the customer's own
  receipt email — separate `try/except`, so a failure sending one never
  blocks the other or the wallet credit itself.
- Idempotent per `(collection_id, recipient_email)` — a webhook
  redelivery, manual "Refresh status", or reconciliation sweep can never
  double-send. `email_deliveries.status` now also accepts `'skipped'` for
  the case where a retry was correctly suppressed.
- Super Admin → a merchant's detail page → Notification Details: settings,
  last-sent status, failed-delivery count, and recent per-recipient
  delivery history. Editable there too, same validation, own audit-log
  action (`notification_settings.updated_by_admin`).
- Sender/reply-to reuse the existing `EMAIL_FROM`/`EMAIL_REPLY_TO` — no
  new Railway env var needed for this feature.

## 18. Security & SEO hardening pass (2026-08-30)

**Security headers checklist** — both sides now set the full defensive
set on every response:

| Header | Frontend (`apps/web/next.config.ts`) | Backend (`app/middleware/security_headers.py`) |
|---|---|---|
| `Strict-Transport-Security` | ✅ | ✅ |
| `X-Content-Type-Options: nosniff` | ✅ | ✅ |
| `X-Frame-Options: DENY` + `frame-ancestors 'none'` | ✅ | ✅ |
| `Referrer-Policy` | ✅ | ✅ |
| `Permissions-Policy` | ✅ | ✅ |
| `Content-Security-Policy` | ✅ (see below) | ✅ (`default-src 'none'`, skipped on `/docs`/`/redoc`/`/openapi.json`) |
| `Cross-Origin-Opener-Policy: same-origin` | ✅ | ❌ deliberately |
| `Cross-Origin-Resource-Policy: same-origin` | ✅ | ❌ deliberately |

The API deliberately omits COOP/CORP: this app's own frontend calls it
cross-origin over CORS by design (a different origin than
`infinitypay.me`) — `Cross-Origin-Resource-Policy: same-origin` on
the API would silently block those legitimate fetch() calls even though
CORS explicitly permits them. See that middleware's own docstring.

Frontend CSP keeps `'unsafe-inline'` on `script-src`/`style-src` —
Next.js's own ["Without Nonces"](https://nextjs.org/docs/app/guides/content-security-policy)
guidance keeps it too; the alternative (nonce-based CSP) forces every
page to dynamic rendering, undoing the static-optimization/performance
work in this same pass for a codebase with no analytics or third-party
inline scripts to actually defend against. Documented in
`next.config.ts` itself, not just here.

**Google Search Console checklist**:
- [ ] Verify `https://infinitypay.me` as a property (DNS TXT record
      or the HTML file Search Console gives you — nothing in this repo
      needs to change for that step itself).
- [ ] Submit `https://infinitypay.me/sitemap.xml` (see `app/sitemap.ts`).
- [ ] Confirm `https://infinitypay.me/robots.txt` (see `app/robots.ts`)
      shows the expected allow/disallow rules once deployed.
- [ ] Request indexing for `/` after the first deploy of this pass — the
      title/description/canonical all changed.

**SEO metadata checklist** (`app/layout.tsx`):
- [x] Title: "InfinityPay | Payment Infrastructure for African Merchants"
- [x] Description matches the brief's suggested copy
- [x] `alternates.canonical` = `https://infinitypay.me/`
- [x] Open Graph title/description/url/image/type/siteName all set
- [x] Twitter card: `summary_large_image`, title, description, image

**Social preview image checklist**:
- [x] Official brand mark used (`apps/web/public/brand/infinity-mark.png`
      — the same mark already used on the live Pay by Link page and in
      every transactional email's header), not the old glossy stock-art
      logo (`infinity-logo-v2.png`, never actually rendered anywhere in
      the live app — only ever referenced in this one metadata field,
      now removed).
- [x] Generated via `apps/web/scripts/generate-og-image.mjs` (Next's own
      `next/og` `ImageResponse` renderer, run standalone under plain
      Node — re-run this script, don't hand-edit the PNG, whenever the
      brand mark or copy changes) → now `apps/web/public/og/infinitypay-og-v1.png`
      (supersedes `infinity-africa-og-v2.png`), 1200×630.
- [x] Referenced by absolute URL (`https://infinitypay.me/og/infinitypay-og-v1.png`)
      in both `openGraph.images` and `twitter.images`.
- [x] Versioned filename (`-v1` under the new brand, not a re-save of the
      old filename) specifically so social platforms' own link-preview
      caches — keyed by URL — pick up the new image on next crawl instead
      of continuing to serve a cached copy of the same URL indefinitely.
- [x] Favicon (`app/favicon.ico`) and app icons (`app/icon.png`,
      `app/apple-icon.png`) already used the current official mark —
      confirmed, not changed.

**Discord/social cache note**: Discord (and WhatsApp, Slack, etc.) cache
a link's preview per-URL for some time after the first share, independent
of how fast the underlying page/metadata changes. If a preview still
shows old/blank content after this deploy:
- Share a version of the link with a harmless query string appended
  (e.g. `https://infinitypay.me/?v=2`) to force a fresh crawl — the
  page renders identically regardless of the query string.
- Or wait; Discord's cache does expire on its own (observed: hours, not
  days, but not instant).
- Verify the image itself is being served correctly independent of any
  crawler cache by opening `https://infinitypay.me/og/infinitypay-og-v1.png`
  directly in a browser.

**Production CORS checklist** — already correct before this pass, just
confirmed: `app/config/settings.py`'s `_reject_wildcard_cors_outside_development`
validator refuses `CORS_ORIGINS` containing `"*"` whenever
`ENVIRONMENT != "development"` (see `tests/test_settings.py`). No wildcard,
nothing else, in production. Railway's `CORS_ORIGINS` should be
`https://infinitypay.me,https://www.infinitypay.me` — the old
infinityafrica.net domain has been fully removed from Vercel (it 404s
now), so there's no live frontend left that could ever send that Origin.

**Private route noindex checklist** — every private/authenticated/
transaction-specific route now carries `robots: { index: false, follow:
false }` metadata (checked by `apps/web/src/app/seo-and-security.test.ts`)
*and* is disallowed in `robots.txt` (defense in depth — a crawler that
ignores meta tags, or reads robots.txt first, still never gets pointed
there):

| Route group | noindex metadata | robots.txt disallow |
|---|---|---|
| `/merchant/*` (Merchant Portal — new `layout.tsx`) | ✅ | ✅ |
| `/portal/*` (redirect shims onto `/merchant/*`) | ✅ | ✅ |
| `/super-admin/*` | ✅ | ✅ |
| `/admin/*` (legacy duplicate of `/super-admin/*` — same auth guard) | ✅ | ✅ |
| `/admin-login`, `/login` | ✅ | ✅ |
| `/onboarding` | ✅ | ✅ |
| `/pay/*` (public Pay by Link checkout) | ✅ (MVP default — see below) | ✅ |
| `/payment-links/*`, `/invoices/*` (public one-off checkout pages) | ✅ | ✅ |

`/pay/*` (Pay by Link) is the one genuine judgment call the brief flagged:
public by design (anyone with the link should reach it), but noindexed
for MVP since a search engine caching a live checkout page (merchant
name, amount, QR code) adds exposure with no real SEO upside. Revisit by
removing `app/pay/layout.tsx` (or overriding it) if the business later
wants these pages discoverable — a deliberate one-line change, not a
default anyone stumbled into. `/create-account` (public self-signup) and
every `/developers/*` page are deliberately left indexable — real
marketing/SEO surface, not private.

**Security tools not public checklist**:
- [x] Swagger UI (`/docs`), ReDoc (`/redoc`), raw OpenAPI schema
      (`/openapi.json`) — now disabled outright when `ENVIRONMENT=production`
      (`Settings.docs_enabled`, `app/main.py`). Previously open to anyone,
      unauthenticated, in every environment including production — a full
      machine-readable map of every route (admin/withdrawal/wallet
      included). No actual endpoint depends on these being enabled.
- [x] `GET /health` — returns only `{"status": "ok", "environment": "..."}`.
      `environment` (not one of the brief's explicitly forbidden fields —
      no env vars, DB URL, provider config, API keys, or stack traces) is
      left in deliberately: removing it would be a needless breaking
      change to a field with genuinely no exposure value to an attacker.
- [x] `GET /v1/system/selcom-config-status` — already `require_super_admin`-
      gated before this pass; returns only booleans (`*_configured`), never
      a raw credential value. Confirmed, not changed.
- [x] No log viewer, database console, or secret-scan-output endpoint
      exists anywhere in this API.

## 19. Frontend security/SEO regression tests (added 2026-08-30)

- `apps/web/src/app/seo-and-security.test.ts` — `robots.ts`/`sitemap.ts`
  content, `next.config.ts`'s generated security headers, root
  `layout.tsx`'s Open Graph/Twitter image (v2, never the old logo), and
  every private route group's noindex metadata.
- `apps/web/src/security-secret-scan.test.ts` — every real backend secret
  env-var name (`RESEND_API_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, every
  `SELCOM_*` credential, ...) asserted absent from `apps/web/src`, plus no
  `NEXT_PUBLIC_` variant of any of them — a standing regression guard for
  §11/§14's manual scans, not just a one-time check.
- Backend: `apps/api/tests/test_security_headers.py` (headers present,
  CSP skipped on docs paths, CORP deliberately absent), `test_settings.py`'s
  `docs_enabled` tests (production disables docs, everything else keeps
  them), and one rate-limit wiring test each in `test_merchant_portal.py`
  (`merchant_collection_create`), `test_onboarding.py`
  (`merchant_onboarding_submit`), and `test_public_inquiries.py`
  (`public_inquiry_create`).
