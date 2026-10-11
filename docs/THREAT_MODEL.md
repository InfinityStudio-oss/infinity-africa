# Threat model

What an attacker would want from InfinityPay, how they would try to reach
it, and what stops them. Written for engineers and reviewers working on
this codebase.

Scope: the `main` branch as deployed — FastAPI on Railway
(`api.infinitypay.me`), Next.js on Vercel (`infinitypay.me`), the Expo
Android app, and one Supabase project (`vtwnhxwtnllgispjbkaz`).

## Assets, in order of what losing them would cost

| Asset | Why it matters | Where it lives |
|---|---|---|
| **Merchant wallet balances** | Real money owed to real businesses (36 active accounts as of 2026-10-11) | `wallets`, derived from `ledger_entries` |
| **Float balance at Selcom** | The money an unauthorised payout would actually take | Selcom, not us |
| **Provider credentials (Selcom)** | Direct access to move the float | Railway env vars only |
| **Supabase service role key** | Bypasses all RLS; total database access | Railway env vars only |
| **The ledger** | The record of who is owed what | `ledger_entries`, immutable |
| **Merchant API keys** | Collect payments as a merchant | `api_keys.hashed_key` (hash only) |
| **Webhook signing secrets** | Forge a payment notification | Encrypted at rest |
| **Super Admin accounts** | Approve withdrawals, suspend merchants, read everything | Supabase Auth + `platform_admins` |
| **Customer phone numbers** | Personal data, and the identifier payments key on | `customers`, `collections` |
| **KYC documents** | National IDs and business registrations | Private Storage buckets |
| **Transaction records** | Commercially sensitive to each merchant | `collections`, `transactions` |

## Entry points

| Surface | Authentication | Notes |
|---|---|---|
| Marketing site | None | Static, no data access |
| Signup / login | Supabase Auth | Login never touches our API |
| Password reset | Supabase Auth + `/v1/auth/forgot-password` | Rate-limited per IP and per email |
| Public payment page (`/pay/{slug}`) | None, by design | Must accept anonymous traffic |
| Pay by Link checkout | None, by design | Rate-limited |
| Merchant dashboard | Supabase JWT | `/v1/merchant/*`, no `merchant_id` in requests |
| Super Admin console | Supabase JWT + `platform_admins` + TOTP | `/v1/admin/*` |
| Mobile app | Supabase JWT | Merchant surface only; no admin endpoints exist in it |
| Partner API | Secret API key | IP allowlist available on `live` keys |
| Selcom webhooks | HMAC-SHA256 signature | Two providers, two schemes |
| File uploads | Session + ownership check | PDF/JPEG/PNG, 10 MB, private buckets |

## Risks and what stops each one

### Exposed secrets
A credential in git, a bundle, or a log.

**Stops:** only `.env.example` is tracked; `.gitignore` covers `.env*`,
keystores, service-account JSON and private keys at three levels;
`test_no_committed_secrets.py` scans every file in `git ls-files` for
credential-*shaped values* (not just names) and
`security-secret-scan.test.ts` scans web source for backend variable
names; the Sentry scrubber drops env vars and payment payloads; the
Android bundle has been scanned and contains exactly one JWT, whose role
claim is `anon`.

**Residual:** the bundle scan is a manual step, not a CI gate. The
procedure, including the control strings that prove the scan is not
vacuous, is in [../apps/mobile/PLAY_STORE_INTERNAL_TESTING.md](../apps/mobile/PLAY_STORE_INTERNAL_TESTING.md).

### IDOR between merchants
Merchant A reads or moves merchant B's money by changing an id.

**Stops:** `/v1/merchant/*` takes no `merchant_id` at all; path-scoped
routes check the path id against membership; flat routes call
`authorize_merchant_action` as soon as the merchant is known. Enforced
structurally by `test_tenant_isolation_route_guards.py`, which walks the
whole route table — a new endpoint that forgets its check fails the suite.
Plus `test_cross_merchant_idor.py` for the concrete cases.

### Fake webhook crediting
Forging a "payment received" callback to credit a wallet for money that
never arrived.

**Stops:** HMAC-SHA256 over the raw body, compared with
`hmac.compare_digest`. Two provider schemes
(`services/selcom/webhooks.py`, `services/selcom_checkout/signer.py`),
each verified against its own secret. Unsigned or wrongly-signed
deliveries are rejected and recorded.

**Residual, and it is real:** the BillNasi partner integration holds no
webhook signing secret, so their inbound events are unverified. Accepted
deliberately for that one partner.

### Duplicate payment crediting
The same real payment credited twice, by a provider retry or a double
submit.

**Stops:** `Idempotency-Key` required on every collection and withdrawal
creation; a unique constraint on `collections.provider_reference`;
webhook processing keyed on the event so a redelivery is a no-op.
Pinned by `test_duplicate_webhook_delivery_is_not_reprocessed` and
`test_duplicate_webhook_does_not_double_credit`.

### Unauthorised withdrawal
Money leaving to an attacker's number.

**Stops:** four independent gates — the merchant must be active and
KYC-verified; no open HIGH/CRITICAL fraud alert; an amount cap; and a
merchant OTP (`compare_digest`, 5 attempts then locked). Then a Super
Admin must approve. There is no automatic payout path, and automation is
off behind two flags. A failed payout cannot be retried without evidence
Selcom did not already pay.

### Admin account takeover
The highest-value target: approves withdrawals and can read everything.

**Stops:** `platform_admins` membership is not inferable from the JWT;
TOTP MFA enforced server-side on every `/v1/admin/*` call (an `aal1`
session is refused regardless of what the portal does); every action
audit-logged to an append-only table; security alert emails on failed MFA
and rejected IPs.

**Residual:** MFA is enforced only when `REQUIRE_SUPER_ADMIN_MFA=true`.
Verify it on Railway rather than assuming it.

### XSS
Script execution in the portal, reading a session or a revealed API key.

**Stops:** React escapes by default; CSP with `default-src 'self'`,
`object-src 'none'`, `base-uri 'self'`, `form-action 'self'`,
`frame-ancestors 'none'`, and `upgrade-insecure-requests` in production.

**Residual:** `script-src` includes `'unsafe-inline'`, which Next.js
requires for its inline bootstrap. This is the weakest part of the CSP and
is a known, documented trade-off rather than an oversight.

### SQL injection
**Stops:** all database access goes through PostgREST via the Supabase
client with parameterised filters. No string-built SQL exists in
application code. Input is validated by Pydantic models before it reaches
a query — see [INPUT_VALIDATION_SECURITY.md](INPUT_VALIDATION_SECURITY.md).

NoSQL injection is not applicable; there is no document store.

### Brute force
Guessing passwords, API keys or OTPs.

**Stops:** 25 rate-limit scopes covering signup, password reset, API key
creation, OTP request/verify, public payment attempts and webhooks.
Failed API key auth is capped at 20 per 5 minutes per IP, applied only on
the failure path so a working integration never reaches it.

**Residual, and it is structural:** **login is not rate-limited by us.**
Merchant and Super Admin login go straight from the browser to Supabase
Auth; this API never sees them. Supabase's own limits are the only control.
This is documented honestly rather than papered over — see
[ABUSE_PROTECTION.md](ABUSE_PROTECTION.md#login-is-not-limited-here).
The in-process limiter is also per-replica, not shared, so an edge rule
would be the real fix for both.

### Leaked logs
An error report or log line carrying a key, a token or a customer's phone.

**Stops:** payment request bodies dropped whole from Sentry; env vars
never sent; recursive key/pattern redaction on what survives; depth-bounded
to avoid a DoS; a scrubber failure drops the event rather than sending it
raw. `api_request_logs` records metadata only. Client-facing 500s are a
fixed generic message — detail stays in Railway logs.

### Weak CORS / CSP
**Stops:** a wildcard `CORS_ORIGINS` is refused at startup whenever
`ENVIRONMENT != development` — it cannot be misconfigured into production,
it fails to boot. All six security headers verified live on
`infinitypay.me`. Swagger/OpenAPI disabled in production (verified:
`/openapi.json` returns 404).

### Insecure mobile bundle
**Stops:** only three `EXPO_PUBLIC_*` variables exist, all public by
design; the session lives in the device keychain, not AsyncStorage; no
admin endpoint is referenced; access tokens are never logged. The bundle
scan confirms no `sk_live`, `sk_test`, `service_role`, `RESEND_API`,
`DATABASE_URL`, `JWT_SECRET`, `whsec_`, `client_secret`, `private_key` or
`v1/admin`, and the single JWT present decodes to `role: anon`.

## Explicitly out of scope

- **Compromise of Selcom itself**, or of Supabase's own infrastructure.
- **A malicious Super Admin.** The audit log makes their actions
  undeniable; it does not prevent them. Two Super Admins exist, so
  separation of duties is a process control, not a technical one.
- **Physical access to an unlocked phone** with a live merchant session.
- **Denial of service.** No WAF or edge rate limiting is configured;
  Railway and Vercel defaults are what stand. The Cloudflare options are
  sketched in [ABUSE_PROTECTION.md](ABUSE_PROTECTION.md).
