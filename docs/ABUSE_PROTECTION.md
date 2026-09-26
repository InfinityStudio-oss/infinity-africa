# Abuse protection and rate limiting

Reviewed and extended 2026-09-26.

## What exists

Rate limiting is a FastAPI dependency (`app/core/rate_limit.py`) applied
per endpoint. Around 25 scopes are already covered — signup, forgot
password, withdrawal OTP request/verify/resend, collection creation,
payment attempts, API key creation, staff invites, public inquiries and
dispute reports, and the provider webhooks.

Each scope has its own bucket, so exhausting one never affects another.

### Dimensions

Per-IP alone leaves two holes: one attacker rotating addresses against a
single account, and one address attacking many accounts. The dependency
closes the second; `enforce_rate_limit()` closes the first by keying on
something only the handler can see.

| Dimension | Where | Example |
|---|---|---|
| IP | `rate_limit()` dependency | every protected endpoint |
| Email | `enforce_rate_limit()` in-handler | password reset, 3 per 15 min |
| API key id | `verify_api_key` | 120 requests per minute per key |
| IP, on failure only | `verify_api_key` | 20 bad keys per 5 min |

Keys are SHA-256 hashed before use, so an email or key id never becomes a
bucket name that could surface in a traceback or heap dump.

### Retry-After

A 429 carries `Retry-After` in seconds, computed from when the oldest hit
falls out of the window. A client that cannot see how long to wait either
gives up or keeps hammering — neither is the point of a limit.

The body is deliberately generic: *"Too many requests. Please try again in
a few minutes."* It never says which limit was hit or what the caller is,
because a limiter that explains itself tells an attacker how to pace
around it.

### Password reset is not an account oracle

`POST /v1/auth/forgot-password` returns one message for every outcome, and
the 429 is byte-identical whether or not the address is registered. The
per-email limit is applied **before** any lookup, so timing does not
distinguish the two either. Tested directly.

## Known limitation: single replica

The limiter is **in-memory and per-process**. On this deployment (one
Railway replica) that is correct. Scale out without a shared store and each
replica enforces its own limit — multiply every number below by the replica
count to see the real one.

This is the one thing to fix before scaling horizontally. The interface is
already the right shape: `_InMemoryRateLimiter` is a single class with one
`check()` method, so a Redis-backed implementation swaps in behind it
without touching a single call site.

## Current limits

| Action | Limit |
|---|---|
| Signup | 5 / 5 min per IP |
| Password reset | 5 / min per IP **and** 3 / 15 min per email |
| Withdrawal OTP request | 5 / 5 min |
| Withdrawal OTP verify | 10 / 5 min (plus 5 attempts per challenge, then locked) |
| Withdrawal OTP resend | 5 / 10 min |
| Collection create | 20 / min |
| Payment attempt | 20 / min |
| API key create | 10 / min |
| Staff invite | 10 / min |
| Public inquiry | 10 / min |
| Public dispute report | 5 / min |
| Withdrawal approval | 60 / min |
| API key requests | 120 / min per key |
| API key auth failures | 20 / 5 min per IP |
| Provider webhooks | 120 / min |

Provider webhooks are limited generously and verified by signature. Do not
tighten them without checking real delivery volume — a dropped webhook is a
payment nobody gets told about.

## Login is not limited here

Merchant and Super Admin login go directly to Supabase Auth from the
browser; this API never sees them, so it cannot limit them. Supabase's own
limits apply. Anything claiming otherwise in this repo would be theatre.

If login limiting becomes a requirement, the honest options are Supabase
Auth rate-limit settings, or an edge rule (below) — not application code
that never runs.

## Manual: Cloudflare / edge

Not configured in code, and worth doing if the platform is ever put behind
Cloudflare:

- **Rate limiting rules** on `/v1/auth/*`, `/v1/onboarding/signup` and
  `/public/*` — an edge limit is shared across replicas, which the
  in-process limiter is not.
- **Bot Fight Mode** on the marketing site and public payment pages.
- **Do not challenge `/v1/webhooks/*`.** A managed challenge served to the
  payment provider silently breaks settlement. Allowlist those paths
  explicitly before enabling anything.

## What was considered and not built

**CAPTCHA / Turnstile.** Not added. It is friction on a payment page, where
abandonment costs a real merchant a real sale, and the abuse it would stop
is already bounded by the limits above. Worth revisiting only if abuse is
actually observed — adding it speculatively trades certain conversion loss
for hypothetical protection.

**Honeypot fields on public forms.** The public forms that matter
(inquiries, dispute reports) are already limited per IP and write no money.
A honeypot would catch naive bots; the limit already caps what they can do.

Both are cheap to add later; neither is worth the friction today.
