# Authentication security checklist

Controls that live outside this repository — in the Supabase, Resend,
Railway and Vercel dashboards — and therefore cannot be enforced or tested
by code. Each one is load-bearing: the application assumes it is set.

Last reviewed: 2026-09-25.

## How the auth model works

Understanding two things makes the rest of this list make sense.

**Roles are never read from the token.** A Supabase JWT proves only *who*
the caller is. Every authorization decision re-reads `platform_admins` or
`merchant_users` from the database through the service-role client
(`apps/api/app/auth/dependencies.py`). Claims like `role: super_admin`
stuffed into a token are ignored, and a test asserts this
(`test_admin_route_guards.py`).

**Super Admin cannot be granted through the product.** No endpoint, signup
path or form writes to `platform_admins`. It is populated by hand in SQL.
Keep it that way — an "invite an admin" feature would turn a merchant
account takeover into a platform takeover.

## Supabase dashboard

| Check | Expected | Why it matters |
|---|---|---|
| Email confirmation | **Enabled** | Signup creates the user server-side via service role. With confirmation off, anyone could register any address and log in unverified. |
| Site URL | `https://infinitypay.me` | Base for every auth email link. |
| Redirect allow-list | `https://infinitypay.me/auth/callback`, `https://infinitypay.me/dashboard/reset-password`, `https://infinitypay.me/admin-login/reset-password` | Supabase's own check on where a recovery link may land. |
| Wildcard redirects | **None** (no `*`) | A wildcard makes every reset link a token-delivery mechanism for any host that matches. |
| Password reset expiry | 1 hour or less | Recovery links sit in inboxes indefinitely otherwise. |
| Minimum password length | 8+, leaked-password protection on | Backend never sees the password; this is the only place strength is enforced. |
| JWT expiry | 1 hour (default) | Sessions are Supabase-managed; there is no separate app session to expire. |
| MFA for Super Admin | **Not yet enabled — see below** | |

The redirect allow-list only needs those three paths. `redirect_path` on
`POST /v1/auth/forgot-password` is a closed `Literal` of two values
(`apps/api/app/schemas/auth.py`), so the API cannot be induced to point a
recovery link anywhere else. The allow-list is the second layer.

### Super Admin MFA

Not implemented. A Super Admin can approve withdrawals and change pricing,
so a single stolen password is currently enough to reach real money
movement. Client-library support is confirmed on both halves of the stack
(supabase-js 2.112.3, supabase-py 2.22.4) — no dependency upgrade needed.

The rollout plan, preconditions, recovery path and smoke checklist are in
**docs/SUPER_ADMIN_MFA_RUNBOOK.md**. The two hard preconditions are a
verified `TRUSTED_PROXY_HOPS` in production and **at least two** Super
Admin accounts, since one admin plus mandatory MFA is one lost phone away
from nobody being able to approve a withdrawal.

## Resend

- Sending domain verified for `infinitypay.me` (governs the `from` address;
  it does not restrict who mail can be sent *to*).
- SPF and DMARC published. **DKIM is still not enabled** — worth finishing,
  as verification and reset mail landing in spam is an auth availability
  problem, not just a deliverability one.
- `CEO_EMAIL` set in Railway, or withdrawal and signup notifications
  silently no-op.

## Railway (API)

- `SUPABASE_SERVICE_ROLE_KEY` set here and **nowhere in `apps/web`**.
  Enforced by `apps/web/src/security-secret-scan.test.ts`.
- `SUPABASE_JWT_SECRET` and/or `SUPABASE_JWKS_URL` set. Both are accepted;
  JWKS is tried first.
- `TRUSTED_PROXY_HOPS` — number of proxies in front of the API. **1** for
  Railway's edge alone. This decides how `X-Forwarded-For` is read, and
  therefore whether a caller can choose their own IP and bypass every rate
  limit and the API-key IP allowlist. Raise to `2` if Cloudflare or another
  proxy is ever put in front; set `0` if nothing is.
- `REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS=true` and
  `AUTO_WITHDRAWALS_ENABLED=false` for manual approval of every withdrawal.
  Both are needed; either one alone leaves automation off.
- No `.env` file is deployed — only `.env.example` is tracked in git.

## Vercel (web)

- Only `NEXT_PUBLIC_*` variables. Everything under that prefix is public
  and ships in the browser bundle; the Supabase anon key belongs there, and
  nothing else secret does.
- `NODE_ENV=production`, which is what disables the mock auth fallback
  (`apps/web/src/lib/auth/mock-auth-enabled.ts`).
- **`__PORTAL_UI_PREVIEW__` must not be set.** Where it is honoured it
  skips `requireSuperAdmin()` and `requireUser()` outright, so setting it
  would leave the Super Admin console and merchant portal open to anyone.
  It is now ignored whenever `NODE_ENV=production`
  (`apps/web/src/lib/auth/ui-preview.ts`), but it should still be absent
  from the deployment's variables — a flag that only fails safe because of
  a second check is one bad refactor from failing open.

## Rate limiting

In-memory and per-process (`apps/api/app/core/rate_limit.py`), correct only
while the API runs a **single replica**. Scaling Railway horizontally
without a shared store gives each replica its own independent limit —
multiply every limit by the replica count to see the real one. Move to
Redis or an edge limiter before scaling out.

Login itself is not rate limited by this app, because it happens directly
against Supabase Auth from the browser; Supabase's own limits apply. The
API rate limits what it does own: signup, forgot-password, withdrawal OTP
request/verify/resend, payment attempts, API key creation, staff invites.

## Admin account recovery

If every `platform_admins` account is lost, recovery is: create or identify
the user in Supabase Auth, then insert their `user_id` into
`platform_admins` via the SQL editor. There is deliberately no in-product
path. Keep at least two Super Admin accounts so routine loss of one does
not require database access.
