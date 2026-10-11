# Security checklist

Things to verify, not things to read. The design reasoning behind each item
is in [SECURITY.md](../SECURITY.md), [AUTH_SECURITY.md](AUTH_SECURITY.md),
[DATA_SECURITY.md](DATA_SECURITY.md) and [THREAT_MODEL.md](THREAT_MODEL.md).

Related checklists that cover narrower ground and are still current:
[PRE_TRAFFIC_SECURITY_CHECK.md](PRE_TRAFFIC_SECURITY_CHECK.md),
[AUTH_SECURITY_CHECKLIST.md](AUTH_SECURITY_CHECKLIST.md),
[deployment-checklist.md](deployment-checklist.md).

---

## Every pull request

- [ ] `git status --short` shows no `.env`, no keystore, no `.json`
      service-account file.
- [ ] No new `merchant_id` read from a request body without
      `authorize_merchant_action` after it.
- [ ] No client component imports `@/lib/admin/live-api` or
      `@/lib/portal/api`. Those reach the API with the caller's session
      through `server-only` code — use a `"use server"` action.
- [ ] `cd apps/api && python -m pytest -q` passes.
- [ ] `cd apps/web && npx tsc --noEmit && npx next build` passes.
      **`next build` is not optional** — it is the only check that catches
      a server-only import crossing into the client bundle. `tsc`, eslint
      and vitest all pass on code it rejects.
- [ ] If a migration was added, it has been applied to production *before*
      the API is deployed.

> Run the API and web suites **one at a time**. Running both together on a
> developer machine starves the web suite of CPU and produces ~20 spurious
> failures that look like real breakage. Alone: 529/529 web, ~3160 API.

## Before a deploy

- [ ] Migrations applied to production. The API must never be deployed
      ahead of its schema.
- [ ] `CORS_ORIGINS` on Railway lists explicit origins. A wildcard is
      refused at startup outside development, so a mistake here is a
      failed boot, not a silent hole.
- [ ] `ENVIRONMENT=production` on Railway — this is what disables
      `/docs`, `/redoc` and `/openapi.json`.
- [ ] `REQUIRE_SUPER_ADMIN_MFA=true` on both Railway and Vercel.
- [ ] `SECURITY_ALERT_EMAIL` is set and points at a **monitored** inbox.
      It defaults to empty, and empty means security alerts go nowhere.
- [ ] `TRUSTED_PROXY_HOPS=1` on Railway. Not 0 — Railway's own proxy is
      `100.64.0.0/10`, and getting this wrong breaks API-key IP allowlists
      by recording a private IP as the caller.

## After a deploy

- [ ] `curl -sI https://infinitypay.me/ | grep -iE "strict-transport|x-frame|x-content-type|referrer-policy|permissions-policy|content-security-policy"`
      returns all six headers.
- [ ] `curl -s -o /dev/null -w "%{http_code}" https://api.infinitypay.me/openapi.json`
      returns **404**. A 200 means `ENVIRONMENT` is wrong and the whole API
      surface is published.
- [ ] `curl -s https://api.infinitypay.me/health` returns
      `{"status":"ok","environment":"production"}`.
- [ ] The deployed commit matches what you pushed:
      `railway status --json` → `activeDeployments[0].meta.commitHash`.

## Before a mobile release

- [ ] `npx expo export --platform android` then scan the `.hbc` bundle.
      The full procedure, with the control strings that prove the scan is
      not silently finding nothing, is in
      [../apps/mobile/PLAY_STORE_INTERNAL_TESTING.md](../apps/mobile/PLAY_STORE_INTERNAL_TESTING.md).
- [ ] Controls (`InfinityPay`, `v1/merchant/overview`) return **> 0**. If
      they are 0 the scan proved nothing — `strings` is not installed in
      this environment, so `grep -a` is required.
- [ ] Forbidden patterns all **0**: `sk_live`, `sk_test`, `service_role`,
      `RESEND_API`, `DATABASE_URL`, `JWT_SECRET`, `whsec_`,
      `client_secret`, `private_key`, `v1/admin`.
- [ ] Any JWT in the bundle decodes to `"role": "anon"`. Do **not** just
      count `eyJ` occurrences and expect zero — a production build
      legitimately contains the anon key, which is a JWT. The role claim
      is the thing that matters.
- [ ] Run installs from `apps/mobile`, never the repo root. It is
      deliberately not a workspace; a root install resolves the wrong
      React Native version.

## Quarterly

- [ ] Rotate the Supabase service role key, Selcom credentials and Resend
      API key.
- [ ] Review `platform_admins` — remove anyone who no longer needs it.
- [ ] Review merchant API keys for ones that have not been used in 90 days
      (`api_keys.last_used_at`) and revoke them.
- [ ] Re-run the RLS coverage check: every `create table` in
      `supabase/migrations/` has a matching
      `enable row level security`. Last verified 2026-10-11 — 42 tables,
      42 with RLS, zero gaps.
- [ ] Confirm a database restore actually works, rather than that backups
      exist.

## Backups and restore

- **Database:** Supabase automated backups, verified working.
- **Storage: not covered.** KYC documents and dispute evidence in
  `merchant-documents`, `document-requests` and `dispute-evidence` are
  **not** in the database backup. This is a known, deliberately accepted
  gap, not an oversight — raise it as a decision to revisit, not as a bug.
- **Restore drill:** restoring to a new Supabase project and pointing a
  staging API at it is the only way to know the backup is usable. Doing
  this is on the quarterly list above and has not yet been done.

## Incident response

1. **Contain.**
   - Compromised merchant → Super Admin → Businesses → Suspend. This is
     immediate and total: portal, API keys, login, all four write paths.
   - Compromised API key → revoke it in Super Admin → API Keys. Revoked
     keys fail auth on the next request.
   - Compromised Super Admin → remove the `platform_admins` row and ban
     the Supabase auth user. Suspension is for merchants; an admin needs
     both.
2. **Rotate.** Treat any credential that *may* have been exposed as
   exposed. Rotating costs minutes; being wrong costs the float.
3. **Preserve.** Read `audit_logs`, `api_request_logs` and
   `ledger_entries` before changing anything. All three are append-only at
   the database level and cannot be rewritten to fit a theory — including
   by the service role.
4. **Reconcile.** If money is involved, compare the ledger against Selcom
   before concluding anything. A missing credit and a double debit look
   identical from the dashboard. See
   [ledger-reconciliation.md](ledger-reconciliation.md).
5. **Write it down.** What was reachable, for how long, and which
   merchants were affected. Tanzanian merchants are owed an accurate
   answer, not a reassuring one.

## Open action items from the 2026-10-11 audit

### 1. Drop the dead plaintext `merchants.webhook_secret` column

**The one finding from that audit that needs a change to production.**

`20260826040000_webhook_secret_encrypted.sql` replaced this column with
`webhook_secret_encrypted` (Fernet, `app/core/secret_box.py`) and
deliberately left the old one in place to avoid a destructive drop at the
time. No application code reads it any more — outbound signing goes
through `decrypt_secret(webhook_secret_encrypted)` in
`app/routers/merchant_webhooks.py`, verified by grep. So anything still in
that column is a **webhook signing secret stored as plaintext**, unused,
readable by anything that can reach the `merchants` row.

A credential that is unused is still a credential. The only thing keeping
it safe is a property of today's code, not of the schema.

**Checked against production on 2026-10-11: 0 rows.**

```sql
select count(*) from public.merchants where webhook_secret is not null;
-- 0
```

So there is **no live exposure** — the column is empty, and this is
housekeeping rather than an incident. Every merchant with webhooks
configured regenerated after 2026-08-26 and their secret is in
`webhook_secret_encrypted`. Drop it whenever convenient:

```sql
alter table public.merchants drop column if exists webhook_secret;
```

Re-run the count before dropping if significant time has passed — the
column is still writable by anything holding the service role, so "empty
in October" is not a permanent property.

**Nothing breaks either way.** A merchant whose secret only ever existed
in this column already cannot sign webhooks with it — they have to
regenerate (`POST /v1/merchant/webhook-config` with
`regenerate_secret=true`), which was already true before. Anyone who
regenerated after 2026-08-26 has their secret in
`webhook_secret_encrypted` and is untouched.

This was not written as a migration file on purpose: a destructive schema
change on a live payments database is a decision for a human, and the
count above should be read first.

### 2. `SECURITY_ALERT_EMAIL` — done 2026-10-11

Set to `ceo@infinitypay.me,masanja.paul3107@gmail.com`: both Super
Admins, both confirmed real mailboxes.

Three things were wrong here and all three are fixed, recorded because
each is easy to reintroduce:

- **It was unset.** Not the hole it first looked like — `_recipients()`
  falls back to `CEO_EMAIL`, which is set, so alerts were reaching
  `ceo@infinitypay.me` all along. The claim that they went "nowhere" was
  wrong.
- **It could not hold two addresses.** It was handed to `send_email` as
  one string, so `a@x,b@x` produced a single malformed recipient and
  Resend rejected the send. Now comma-parsed with dedup, like
  `CEO_EMAIL`.
- **The fallback used only `ceo_emails[0]`**, so the second Super Admin
  received every other notification but not the security ones. Now all of
  them.

**`security@infinitypay.me` does not exist.** It was briefly set as a
recipient and removed. Do not use it anywhere until the mailbox is
created — an alert sent to a mailbox nobody owns is worse than a known
gap, because the configuration looks right.

**Changing this variable needs a restart, not just a `--set`.** Settings
are read once at startup through an `lru_cache`, so a value set with
`railway variables --set --skip-deploys` sits in Railway looking
configured while the live process keeps using the old one. Omit
`--skip-deploys`, or `railway redeploy` afterwards.

For reference, the rest of the production config was verified correct at
the same time: `ENVIRONMENT=production`, `REQUIRE_SUPER_ADMIN_MFA=true`,
`TRUSTED_PROXY_HOPS=1`, `SECURITY_ALERTS_ENABLED` unset but defaulting to
`true`.

### 3. Do a restore drill

Backups are verified to exist and to run. Nobody has restored one. Until
that happens, "we have backups" is a belief rather than a fact.

### Known residual risks

These are accepted, not unnoticed. Do not treat finding them again as a
new discovery.

| Risk | Why it stands |
|---|---|
| Login is not rate-limited by us | Login never reaches our API; Supabase's limits are the only control |
| `script-src 'unsafe-inline'` | Next.js requires it for its inline bootstrap |
| BillNasi webhooks unverified | That partner holds no signing secret |
| Storage not backed up | Accepted decision |
| No WAF / edge rate limiting | Not configured; the in-process limiter is per-replica |
| A suspended merchant's refresh token stays valid until expiry | The API refuses it; banning the auth user is the stronger action |
