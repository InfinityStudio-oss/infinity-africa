# Data security

What data InfinityPay holds, where it lives, and what keeps one merchant's
data away from another's. The cross-merchant review that produced much of
this is [TENANT_ISOLATION_SECURITY_REVIEW.md](TENANT_ISOLATION_SECURITY_REVIEW.md).

> InfinityPay has no tenants. The term throughout the codebase and these
> docs is **merchant** / `merchant_id`.

## What we hold

| Data | Where | Sensitivity |
|---|---|---|
| Merchant wallet balances | `wallets`, derived from `ledger_entries` | Money |
| Double-entry postings | `ledger_entries` | Money, immutable |
| Collections and withdrawals | `collections`, `disbursements`, `transactions` | Money |
| Merchant API keys | `api_keys.hashed_key` (hash only) | Credential |
| Outbound webhook signing secrets | `merchants.webhook_secret_encrypted`, Fernet (migration `20260826040000`) | Credential |
| Customer phone numbers | `customers`, `collections` | Personal data |
| KYC documents | private Supabase Storage bucket | Personal data |
| Dispute evidence | private Supabase Storage bucket | Personal data |
| Admin actions | `audit_logs` | Immutable |

Provider credentials (Selcom) and the Supabase service role key are **not**
in the database. They are environment variables on Railway, read only by
the API.

## Row Level Security

**All 42 tables created by `supabase/migrations/` have RLS enabled.** That
was verified by extracting every `create table` against every
`enable row level security` and diffing the two sets — the difference is
empty.

Most of those tables have **no policies at all**, which is deliberate and
is the stronger position: RLS enabled with no policy denies every `anon`
and `authenticated` request. Those tables are reached only by the API using
the service role, which bypasses RLS by design and applies the ownership
checks itself in code (see [AUTH_SECURITY.md](AUTH_SECURITY.md)). The
browser never queries them.

Where policies do exist (83 of them), every one is scoped either to the
caller's own `merchant_users` membership or to a `platform_admins` row.
There is no policy that grants a merchant read access to another merchant's
row.

`payment_links` is worth noting because it looks like an exception and is
not: an early migration sketched an `anyone can view an active payment
link` policy in a comment, and it was never applied. Public checkout goes
through the API, not through a public read policy.

## The ledger is immutable at the database level

`ledger_entries` has no `updated_at` column and an immutability trigger
(`ledger_entries_immutable`). A second constraint trigger
(`ledger_entries_balanced`) enforces that debits equal credits per
`transaction_id`. So:

- A posting cannot be edited or deleted, including by the service role.
- An unbalanced transaction cannot be committed.
- A correction is a new, opposite posting — which is why a reversed
  collection nets its own fee out without any special case.

`audit_logs` is append-only the same way. This matters during an incident:
the record of what happened cannot be tidied up afterwards, by anyone.

Design detail in [WALLET_LEDGER.md](WALLET_LEDGER.md), reconciliation in
[ledger-reconciliation.md](ledger-reconciliation.md).

### One stale plaintext credential, pending a decision

The pre-2026-08-26 plaintext `merchants.webhook_secret` column still
exists. No code reads it, so it is harmless to today's requests — but any
legacy value in it is a webhook signing secret stored in plaintext, and
"nothing queries it" is a property of the current code rather than of the
schema. The count query and the one-line drop are in
[SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md#1-drop-the-dead-plaintext-merchantswebhook_secret-column).

## Withdrawals are auditable end to end

Every status change on a withdrawal is written to `audit_logs` with the
actor. A payout cannot be retried without evidence that Selcom did not
already pay — see [withdrawal-pricing-and-approval.md](withdrawal-pricing-and-approval.md)
and [WITHDRAWAL_FLOW.md](WITHDRAWAL_FLOW.md). There is no automatic payout
path from "approved" to "money left the float".

## File uploads

Two upload surfaces: KYC documents during onboarding, and dispute
evidence.

- **Buckets are private.** `merchant-documents`, `document-requests` and
  `dispute-evidence` are all created with `public = false`. Nothing is
  reachable by URL guessing.
- **Access is via signed URLs that expire in 300 seconds**, generated on
  demand for a caller who has already passed the ownership check.
- **10 MB cap**, enforced by a bounded read of one byte past the limit —
  an oversized file is rejected without being pulled into memory.
- **MIME allowlist: PDF, JPEG, PNG only.** No executable type is
  accepted.
- **The file's own leading bytes decide.** `content_type` is a
  client-supplied header and is not trusted; the magic bytes are checked
  against the declared type.
- An empty file is rejected explicitly rather than stored as a zero-byte
  record.

## Personal data in logs and monitoring

The Sentry scrubber (`apps/api/app/core/monitoring.py`) is the control
here, and it is deliberately aggressive:

- Request bodies for payment endpoints are **dropped whole**. There is no
  useful redaction of a payment payload — the amount, the phone and the
  reference *are* the payload.
- Environment variables are never sent.
- What survives is walked recursively, with `authorization`, `phone` and
  similar keys replaced, and bearer tokens pattern-matched out of free
  text.
- Recursion is depth-bounded, because an unbounded recursive scrubber over
  attacker-influenced data is itself a denial of service.
- The scrubber is wrapped so that a scrubber failure drops the event
  rather than sending it unscrubbed.

PostHog autocapture, session replay and automatic pageviews are **off in
code and not configurable by env var**. Autocapture would record the text
of whatever was clicked — a customer's phone number on a checkout page, a
revealed API secret in the portal — and replay would record the screen
during a payment.

`api_request_logs` stores method, path, status, duration, IP and the API
key id. No headers, no bodies, no key material.

## Backups

Supabase provides the database backups and they have been verified
working. **They do not cover Supabase Storage**, so KYC documents and
dispute evidence are not backed up. This gap is known and was accepted
deliberately rather than overlooked. Restore procedure and the current
state of this are in [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md#backups-and-restore).
