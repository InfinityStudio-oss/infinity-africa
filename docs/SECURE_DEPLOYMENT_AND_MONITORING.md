# Secure deployment and monitoring

Reviewed 2026-09-26.

**Most of what a hardening pass would add is already here.** This documents
what is enforced and how to verify it, rather than claiming new work. The
one genuine gap is error monitoring, called out honestly at the end.

## Already enforced (verified, not assumed)

| Control | Where | Evidence |
|---|---|---|
| Security headers (HSTS, CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy, COOP) | `app/middleware/security_headers.py`, `apps/web/next.config.ts` | `test_security_headers.py` |
| Swagger / ReDoc / OpenAPI off in production | `app/main.py` via `Settings.docs_enabled` | `test_production_docs_disabled.py` |
| No wildcard CORS outside development | `Settings._reject_wildcard_cors_outside_development` | `test_settings.py` |
| No stack traces to clients | `unhandled_exception_handler` returns a generic 500 | `core/errors.py` |
| Service-role key never in the frontend | — | `apps/web/src/security-secret-scan.test.ts` |
| Roles read from the database, never token claims | `app/auth/dependencies.py` | `test_admin_route_guards.py` |
| Super Admin MFA (aal2) | `require_super_admin` | `test_super_admin_mfa.py` |
| Merchant isolation | every by-id route | `test_cross_merchant_idor.py`, `test_tenant_isolation_route_guards.py` |
| Rate limiting incl. per-email and per-API-key | `app/core/rate_limit.py` | `test_rate_limit_dimensions.py` |
| Real client IP behind Railway's proxy | `app/core/request_ip.py` | `test_client_ip_trust.py` |
| Audit + alerts on sensitive admin actions | `app/services/security_alerts.py` | `test_admin_audit_alerts.py` |

The health endpoint returns `{"status", "environment"}` and nothing else —
asserted, including that it mentions no key, token, URL or provider name.

## Required production environment

Names only. Never paste values into a ticket, a screenshot or a chat.

**Railway (API):** `ENVIRONMENT=production`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` and/or
`SUPABASE_JWKS_URL`, `CORS_ORIGINS`, `APP_URL`, `PUBLIC_APP_URL`,
`TRUSTED_PROXY_HOPS=1`, `RESEND_API_KEY`, `EMAIL_FROM`, `EMAIL_REPLY_TO`,
`CEO_EMAIL`, `REQUIRE_SUPER_ADMIN_MFA`,
`REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS=true`,
`AUTO_WITHDRAWALS_ENABLED=false`, `ENABLE_AUTO_RECONCILIATION`, the
`SELCOM_*` set, and the reconcile interval variables.

**Vercel (web):** `NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL`,
`NEXT_PUBLIC_SITE_URL`, `REQUIRE_SUPER_ADMIN_MFA`, `NODE_ENV=production`.

Two that must stay absent: `__PORTAL_UI_PREVIEW__` (an authentication
bypass, now also blocked by `NODE_ENV=production`) and any
`NEXT_PUBLIC_`-prefixed secret — that prefix ships the value to the browser.

`TRUSTED_PROXY_HOPS` is **1**, not 0. Railway fronts the app on
`100.64.0.0/10`, so `0` returns the proxy address and both the API-key IP
allowlist and every rate limit break. See
`docs/api-logs-and-ip-allowlist-drift-fixed` history for why.

## Verifying a deploy

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://api.infinitypay.me/openapi.json   # 404
curl -s https://api.infinitypay.me/health                                          # {"status":"ok",...}
curl -sI https://infinitypay.me | grep -i "strict-transport\|content-security"     # both present
```

Then one authenticated check that exercises the real path: sign in as Super
Admin (expect the MFA challenge), and make one API-key request and confirm
`api_keys.last_used_ip` is a **public** address, not `100.64.x.x`.

## Monitoring — the honest gap

**There is no Sentry, no PostHog, no APM.** Nothing was installed here,
because adding an error tracker is a decision with cost, data-residency and
PII consequences that belongs to you, not to a hardening pass.

What exists instead: structured logging under the `infinity.*` logger
namespace, an append-only `audit_logs` table, and security alert emails for
the events worth interrupting someone over.

Until a tracker is added, these are the things worth watching in Railway
logs, and what each would mean:

| Signal | Likely meaning |
|---|---|
| `Unhandled exception on` | a real 500 — always worth reading |
| `api_key.auth_failed` bursts | key guessing, or a partner with a stale key |
| `super_admin.access_denied` | a non-admin probing the platform surface |
| `super_admin.mfa.required_block` | an admin locked out, or a stolen password |
| `checkout_reconciliation_row_failed` | collections silently not settling |
| `security_alert_send_failed` | alerts are failing, so the others go unseen |
| A rise in 429s | abuse, or a limit set too tight for real traffic |

The last one matters both ways: a limit that fires on legitimate traffic is
as much an incident as one that never fires.

## Incident quick steps

1. **Suspected key compromise** — revoke it in the portal; rotation issues a
   new pair and revokes the old one in the same step.
2. **Suspected admin compromise** — remove the row from `platform_admins`
   via SQL. There is no product path, by design.
3. **Unexplained withdrawals** — `ENABLE_WITHDRAWALS=false` stops new
   requests immediately; approval is already required for every one.
4. **Locked out by MFA** — `REQUIRE_SUPER_ADMIN_MFA=false` and redeploy.
   Enrollments survive.
5. **Reconciliation wrong** — `ENABLE_AUTO_RECONCILIATION=false` pauses both
   sweeps without touching settled records.

Every one of those is an environment variable or a SQL statement, not a
code change, so none needs a deploy to take effect beyond a restart.

## Manual platform settings

- **Supabase**: email confirmation on, redirect allow-list with no
  wildcards, MFA/TOTP enrollment permitted.
- **Cloudflare** (if adopted): rate-limiting rules on `/v1/auth/*` and
  `/public/*` would be shared across replicas, which the in-process limiter
  is not. **Allowlist `/v1/webhooks/*`** — a managed challenge served to the
  payment provider silently breaks settlement.
- **Railway**: single replica today. Scaling out multiplies every rate limit
  by the replica count; see `docs/ABUSE_PROTECTION.md`.

## Residual risks

1. **No error tracker.** A 500 is visible only if someone reads the logs.
2. **In-process rate limiting.** Correct at one replica, wrong the moment
   there are two.
3. **DMARC is `p=none`.** Monitoring only; nothing is rejected on failure
   yet.
4. **No automated dependency scanning.** Enabling Dependabot on the repo is
   free and would cover it.
