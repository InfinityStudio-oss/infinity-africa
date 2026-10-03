# Launch day runbook

What to set before traffic, what to watch during it, and what to do when
something breaks. The deep detail lives in the documents linked at the
bottom — this is the page to have open on the day.

## Before traffic: things code cannot enforce

Each of these is a dashboard setting. The application cannot check them
for you, which is exactly why they are the ones that get missed.

### Supabase — the one that matters most

**Authentication → Rate Limits.** Sign-in happens browser-to-Supabase
(`signInWithPassword`), so it never passes through our API and **our rate
limiter cannot see it**. Every other sensitive endpoint on this platform
is limited in code; login brute-force protection is Supabase's alone.
Confirm sign-in attempts per hour is set to something deliberate.

**Authentication → URL Configuration.** Site URL `https://infinitypay.me`,
and the redirect allow-list must contain every entry in
`docs/supabase-auth-settings.md` exactly, no trailing slashes. A missing
entry sends reset and invite links to the homepage with no error.

**Authentication → Providers → Email.** OTP expiry and length as
configured. Confirm email confirmations are required.

### Railway (API)

Startup now refuses to boot a production deploy missing `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, a token verification method, or
`CORS_ORIGINS` — the deploy fails and the previous release keeps serving.
Check the deploy logs for `production_config_warning` lines, which do not
block startup but each name something switched off:

| Variable | Consequence if unset |
|---|---|
| `WEBHOOK_DELIVERY_INTERVAL_SECONDS` | Merchant webhooks queue and are never sent |
| `CEO_EMAIL` | Nobody is told a withdrawal needs approval |
| `RESEND_API_KEY` | No email at all, including withdrawal alerts |
| `SELCOM_CHECKOUT_API_SECRET` | Collections enabled but cannot reach the provider |

Also confirm `TRUSTED_PROXY_HOPS=1`. Railway fronts the app with
`100.64.0.0/10`; at `0` the client IP resolves to a private address and
every per-IP rate limit and API-key IP allowlist misbehaves.

### Cloudflare

SSL mode **Full (Strict)** · Always Use HTTPS **on** · Universal SSL
active · Minimum TLS **1.2** · TLS 1.3 **on** · WAF enabled · Bot
protection on the auth and payment paths.

### Super Admin MFA

Do not set `REQUIRE_SUPER_ADMIN_MFA=true` until **both** admins have an
authenticator enrolled and have signed in. With one enrolled and one not,
a lost authenticator leaves nobody able to recover the other — recovery
requires a second working admin. See
`docs/super-admin-mfa-recovery-runbook.md`.

## The paid plans, and what each one actually buys

Verified 2026-10-03, after the upgrade to Pro on all four.

| Service | What it carries | What to confirm in its dashboard |
|---|---|---|
| **Resend Pro** | Every outbound email: verification, password reset, merchant approval, withdrawal OTP and approval alerts, CEO notifications, security alerts | Domain `infinitypay.me` verified (SPF + DKIM). **Suppressions list empty** — a hard-bounced address is blocked silently and our logs still say "sent" |
| **Supabase Pro** | Auth, database, the audit trail | Backups enabled and a restore point visible. Auth URL allow-list matches `supabase-auth-settings.md` exactly. **Remove any `infinityafrica.net` entries** still in it |
| **Railway Pro** | The API, and the three background workers | One replica. The rate limiter and webhook sweep are in-memory and per-process, so a second replica silently doubles every limit and double-sends every webhook |
| **Vercel Pro** | The portal, admin console, public site, payment pages | `infinitypay.me` and `www` both resolve; no `infinityafrica.net` alias still serving |

**Email volume is not a constraint on Pro** (50,000/month, no daily cap),
but three flags still suppress categories if a send loop ever appears —
`SEND_CUSTOMER_RECEIPT_EMAILS`, `SEND_WITHDRAWAL_REQUEST_EMAILS`,
`SEND_MERCHANT_WITHDRAWAL_EMAILS`. All default off. The first is
deliberately off in production: subscribers get Selcom's SMS, so a
receipt email would be duplicate cost and duplicate noise.

**No email can break a payment.** Every send function in
`app/services/email.py` is documented and implemented as best-effort and
never raises; wallet crediting and settlement do not depend on one.

## The three background workers

All driven by the scheduler in `app/main.py`, all on one replica:

| Worker | Interval | Silent if |
|---|---|---|
| Checkout reconciliation | `SELCOM_CHECKOUT_RECONCILE_INTERVAL_SECONDS` | Interval is 0, or `ENABLE_AUTO_RECONCILIATION` is false |
| Disbursement reconciliation | `SELCOM_DISBURSEMENT_RECONCILE_INTERVAL_SECONDS` | Same |
| Webhook delivery | `WEBHOOK_DELIVERY_INTERVAL_SECONDS` | Interval is 0 — the queue fills and never sends |

Collection expiry rides the checkout reconciliation tick, so the same
flag stops both.

## During traffic: what to watch

Railway logs, in rough order of how much they would cost you.

| Log line | Means | Act if |
|---|---|---|
| `scheduled_collection_expiry` | Abandoned pushes being closed | `errors` is non-zero |
| `scheduled_checkout_reconciliation` | Payments being credited | `still_pending` keeps climbing |
| `scheduled_webhook_delivery` | Merchant webhooks going out | `failed` is non-zero and rising |
| `selcom_circuit_opened` | Provider failing repeatedly | Always — payments are stopping |
| `webhook.selcom_checkout_rejected` | Unsigned provider callback | Never — this is expected, reconciliation covers it |
| `production_config_warning` | A feature is silently off | Always, at startup |

Two screens worth having open: **Super Admin → Withdrawals** (money
waiting on a human) and **Super Admin → Risk Monitoring** (collections
held before credit).

Known-noisy and safe to ignore: `webhook.selcom_checkout_rejected`.
Selcom does not sign its callbacks and never has; crediting comes from
the reconciliation sweep.

## When something breaks

**A merchant says a payment did not arrive.** Check the collection's
status first, not the code. `processing` means the customer has not
approved yet — it closes itself within about 30 minutes. `pending_review`
means a fraud rule held it and a Super Admin must clear it in Risk
Monitoring. `successful` with an unhappy merchant means the wallet was
credited and the question is their own reconciliation.

**A partner says they got no webhook.** Check Super Admin → Webhooks for
the delivery attempt before touching anything. A `Failed` row with a
non-2xx is their endpoint, not ours. No row at all means no webhook URL
is configured, which fails silently by design.

**Payments stop entirely.** Look for `selcom_circuit_opened`. The breaker
trips after repeated provider failures and closes itself after the
cooldown. If it is flapping, the provider is the problem; do not restart
the API in a loop.

**A merchant API key leaks.** Revoke it in their portal under API
Credentials — it stops working immediately, no deploy needed. Issue a new
one; the old key's transactions remain attributed to it in the logs.

**Email stops arriving.** Check Resend → Suppressions before anything
else. A hard-bounced address is blocked for all future sends and our logs
still record those as "sent".

## Accepted risks going in

Stated plainly so nobody discovers them during an incident.

- **Rate limiting is in-memory and per-process.** Correct at one Railway
  replica, which is the current deployment. Scaling horizontally without
  a shared store silently multiplies every limit by the replica count.
- **No inbound request signing.** Merchant API calls are authenticated by
  bearer key over TLS plus an optional IP allowlist. Documented honestly
  to partners rather than implied.
- **Webhook deliveries are dropped after 5 attempts** over ~50 minutes,
  with no replay. A partner offline longer than that loses those events
  permanently and must reconcile by polling.
- **BillNasi receives unsigned webhooks** by their choice; they hold no
  signing secret. Mitigation offered and not yet adopted — see
  `docs/DIRECT_WALLET_PUSH_PARTNER_INTEGRATION.md`.
- **Login rate limiting is Supabase's**, not ours, as above.

## Where the detail is

| Area | Document |
|---|---|
| Authentication | `AUTH_SECURITY_CHECKLIST.md` |
| Merchant isolation / IDOR | `TENANT_ISOLATION_SECURITY_REVIEW.md` |
| Secrets and API keys | `SECRETS_AND_API_KEY_SECURITY.md` |
| Input validation | `INPUT_VALIDATION_SECURITY.md` |
| Abuse and rate limits | `ABUSE_PROTECTION.md` |
| Deployment and monitoring | `SECURE_DEPLOYMENT_AND_MONITORING.md` |
| Pre-traffic sweep | `PRE_TRAFFIC_SECURITY_CHECK.md` |
| Super Admin MFA recovery | `super-admin-mfa-recovery-runbook.md` |
| Partner integration | `DIRECT_WALLET_PUSH_PARTNER_INTEGRATION.md` |
| Launch smoke test | `PRODUCTION_LAUNCH_SMOKE_TEST.md` |
