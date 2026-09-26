# Secrets and API key security

Reviewed 2026-09-26. **No exposed secret was found.** Nothing requires
rotation as a result of this review.

## Public vs server-only

Public means *deliberately shipped to browsers*. Anything else must never
appear in `apps/web/src`, a client component, a bundle, a log, a docs
example or an API response.

| Public | Server-only |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `SUPABASE_SERVICE_ROLE_KEY` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `SUPABASE_JWT_SECRET` |
| `NEXT_PUBLIC_API_URL` | `RESEND_API_KEY` |
| `NEXT_PUBLIC_SITE_URL` | every `SELCOM_*` credential |
| `pk_test_…` / `pk_live_…` | `WEBHOOK_SECRET_ENCRYPTION_KEY` |
| a key's prefix and last 4 | `sk_test_…` / `sk_live_…` |

The anon key is public by design — it is the identity RLS evaluates
against, not a bypass of it. The service-role key is the opposite: it
bypasses RLS entirely, so it exists only in the Railway API service.

⚠️ **The `NEXT_PUBLIC_` prefix is not a label, it is an instruction.** Next
inlines those values into the browser bundle at build time. Prefixing a
secret with it publishes the secret.

## Merchant API keys

A key is a pair. The **public** half (`pk_…`) is stored in plaintext
because it is an identifier, not a credential — it cannot authenticate, and
presenting it as one is refused with a message saying exactly that. The
**secret** half (`sk_…`) is returned once, at creation, and only its
SHA-256 hash is stored. Nobody can retrieve it afterwards: not support, not
Super Admin, not us.

Authentication looks the key up by indexed equality on the hash, so no
secret is ever compared byte-by-byte in application code and there is no
timing side channel to close. `hash_api_key` documents why SHA-256 is right
here and what would make Argon2id necessary instead.

Rotation issues a whole new pair and revokes the old one in the same step,
so a rotated-away secret and its replacement never share an identifier.

## Webhook secrets

Generated server-side, **encrypted at rest** in
`merchants.webhook_secret_encrypted` under `WEBHOOK_SECRET_ENCRYPTION_KEY`,
and returned exactly once — on creation or regeneration. Every read returns
`has_secret: true` and nothing more. Delivery logs record status, never the
signature input.

## Supabase, Selcom, Resend

Two Supabase clients exist and are kept apart: the browser client
(`lib/supabase/client.ts`) uses the anon key, the server client
(`lib/supabase/server.ts`) uses cookies and still runs under RLS. The
service-role client exists only in `apps/api`. The frontend performs no
privileged database work.

Selcom credentials and the Resend key live only in the Railway service.
Provider errors are logged server-side and returned to callers as generic
messages — a raw provider response can carry request signatures and account
identifiers, so it is never passed through.

## How this is enforced, not just intended

| Check | Test |
|---|---|
| No backend secret env-var name in the frontend tree | `apps/web/src/security-secret-scan.test.ts` |
| No committed credential anywhere in tracked files | `apps/api/tests/test_no_committed_secrets.py` |
| No secret in a security alert email | `test_security_alerts.py` |
| Secret key never in a list response; only its hash stored | `test_api_key_pairs.py` |
| No secret in the audit trail | `test_api_key_pairs.py` |

`test_no_committed_secrets.py` scans `git ls-files` for Stripe-shaped keys,
Resend keys, JWTs, PEM blocks, AWS/Slack/Google tokens, tracked `.env` or
key files, and literal `Authorization: Bearer` values. Placeholders
containing `xxxx`, `YOUR_`, `<…>` or bullets are allowed; real entropy is
not. Verified by planting a fake key and confirming it fails, naming the
file and line and never the value.

That test exists because the gap was demonstrated: a docs placeholder
shaped like a real Stripe key reached a push and was caught by GitHub's
scanner rather than by anything in this repo.

## If a key is exposed

1. **Merchant API key** — revoke it in the portal. Rotation issues a new
   pair and kills the old one atomically.
2. **Webhook secret** — regenerate from the webhook settings; the old one
   stops validating immediately.
3. **Supabase service-role key** — rotate in the Supabase dashboard, update
   Railway, redeploy. This one bypasses RLS entirely; treat it as the most
   serious.
4. **Resend key** — rotate in Resend, update Railway.
5. **Selcom credentials** — rotate in the Selcom portal, update Railway,
   and re-check the IP allowlist afterwards.

In every case: rotate **first**, then remove the value from the file, then
rewrite git history if it was committed. Removing it from the current
commit alone leaves it in history and still exposed.

## Verifying before a release

```bash
cd apps/api && python -m pytest tests/test_no_committed_secrets.py -q
cd apps/web && npx vitest run src/security-secret-scan.test.ts
git ls-files | grep -E "\.env$|\.pem$|\.key$|\.pfx$"     # expect nothing
```

After a frontend build, grep `.next/static` for `SERVICE_ROLE`,
`RESEND_API_KEY` and `sk_live_`. Expect no matches.

## Deployment checklist

- **Railway**: every server-only value above. `ENVIRONMENT=production`.
- **Vercel**: only `NEXT_PUBLIC_*`, plus `NODE_ENV` and
  `REQUIRE_SUPER_ADMIN_MFA`. Nothing from the server-only column.
- **Supabase**: service-role key never leaves the dashboard and Railway.
- **Resend / Selcom**: keys only in Railway.
- Enable GitHub secret scanning and push protection on the repository. It
  caught something this repo's own tests did not; keep it on.
