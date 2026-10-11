# Security

InfinityPay moves real money for real businesses in Tanzania. Merchant
wallets, a double-entry ledger, API keys, webhook secrets, customer phone
numbers and withdrawal approvals all live in this repository's blast
radius. This file is the entry point; the detail is in the documents it
links to.

## Reporting a vulnerability

Email **security@infinitypay.me** with what you found, how to reproduce it,
and what you could reach with it. Do not open a public GitHub issue for
anything that affects money, merchant data or authentication.

> **Set this up before relying on it.** That address is the one the
> platform's own `SECURITY_ALERT_EMAIL` is expected to point at, but
> `security_alert_email` defaults to empty — with nothing configured on
> Railway, automated security alerts are not sent anywhere and the inbox
> above may not be monitored. Confirm both before publishing this file
> anywhere public. See [docs/SECURITY_CHECKLIST.md](docs/SECURITY_CHECKLIST.md).

If you believe a credential has leaked, say so in the first line — that
changes the response from "triage" to "rotate now".

## The rules that are not negotiable

1. **No secret ever reaches the browser or a phone.** Only
   `NEXT_PUBLIC_*` (web) and `EXPO_PUBLIC_*` (mobile) variables are
   bundled, and every one of them is public by design. The Supabase
   service role key is backend-only. See [docs/SECRETS_AND_API_KEY_SECURITY.md](docs/SECRETS_AND_API_KEY_SECURITY.md).
2. **No real `.env` is ever committed.** Only `.env.example` templates are
   tracked. Two independent scanners enforce this —
   `apps/api/tests/test_no_committed_secrets.py` scans every file in
   `git ls-files` for credential-shaped values, and
   `apps/web/src/security-secret-scan.test.ts` scans the web source for
   backend variable names.
3. **The merchant is never taken from the request.** A merchant's identity
   comes from their session or their API key, never from a `merchant_id`
   a client supplies unchecked. This is enforced structurally by
   `apps/api/tests/test_tenant_isolation_route_guards.py`, which walks the
   whole route table and fails on any route that is not deliberately
   classified.
4. **Nothing moves money without a human.** Withdrawals require Super
   Admin approval and merchant OTP. There is no automatic payout path, and
   referral commissions deliberately have none either.
5. **Suspension means suspended everywhere.** A suspended merchant loses
   the portal, their API keys, and login. See [docs/AUTH_SECURITY.md](docs/AUTH_SECURITY.md).

## Where to look

| Topic | Document |
|---|---|
| Sessions, roles, Super Admin MFA, suspension | [docs/AUTH_SECURITY.md](docs/AUTH_SECURITY.md) |
| Merchant isolation, RLS, ledger immutability, uploads | [docs/DATA_SECURITY.md](docs/DATA_SECURITY.md) |
| Assets, entry points, risks, what stops each one | [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) |
| What to verify before and after a deploy | [docs/SECURITY_CHECKLIST.md](docs/SECURITY_CHECKLIST.md) |
| Secrets and API key handling in depth | [docs/SECRETS_AND_API_KEY_SECURITY.md](docs/SECRETS_AND_API_KEY_SECURITY.md) |
| Rate limiting and abuse | [docs/ABUSE_PROTECTION.md](docs/ABUSE_PROTECTION.md) |
| Input validation | [docs/INPUT_VALIDATION_SECURITY.md](docs/INPUT_VALIDATION_SECURITY.md) |
| Cross-merchant isolation review | [docs/TENANT_ISOLATION_SECURITY_REVIEW.md](docs/TENANT_ISOLATION_SECURITY_REVIEW.md) |
| Super Admin MFA enrolment and recovery | [docs/SUPER_ADMIN_MFA_RUNBOOK.md](docs/SUPER_ADMIN_MFA_RUNBOOK.md) |
| Monitoring, and what is scrubbed from it | [docs/MONITORING_AND_OBSERVABILITY.md](docs/MONITORING_AND_OBSERVABILITY.md) |

## Supported versions

There is one deployed version: `main`. The API runs on Railway, the web app
on Vercel, both deploying automatically from `main`. There are no
maintained release branches, so a security fix means a commit to `main`.

## Incident response, in short

The full sequence is in [docs/SECURITY_CHECKLIST.md](docs/SECURITY_CHECKLIST.md#incident-response).
The first four steps never change:

1. **Contain.** Suspend the affected merchant (Super Admin → Businesses) or
   revoke the affected API key. Both take effect immediately.
2. **Rotate.** Any credential that may have been exposed is treated as
   exposed. Rotating is cheap; assuming is not.
3. **Preserve.** `audit_logs`, `api_request_logs` and `ledger_entries` are
   append-only at the database level and cannot be edited to tidy up a
   story. Read them before changing anything else.
4. **Reconcile.** If money is involved, compare the ledger against Selcom
   before concluding what happened. See [docs/ledger-reconciliation.md](docs/ledger-reconciliation.md).
