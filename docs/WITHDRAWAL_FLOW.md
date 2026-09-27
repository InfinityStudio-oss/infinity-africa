# Merchant Withdrawal Flow

What a merchant does at `/portal/withdrawals`, and what the backend does
behind it. For pricing see
[`docs/collection-and-withdrawal-pricing.md`](./collection-and-withdrawal-pricing.md)
(withdrawals charge nothing during MVP); for the approval/status mechanics
and Selcom sequencing see
[`docs/withdrawal-pricing-and-approval.md`](./withdrawal-pricing-and-approval.md).

## The merchant's steps

1. Choose a withdrawal method and destination provider.
2. Enter the destination phone number or bank account number, the amount,
   and optionally notes. That is the whole form.
3. **Check Balance** — a read-only quote. Nothing is created.
4. **Request Withdrawal** — opens a review step. Still nothing created, and
   no request has left the browser.
5. **Review** — the destination, number and amount exactly as they will be
   submitted, plus available balance. Confirm with **Send Verification
   Code**.
6. A 6-digit code is emailed to the merchant's account address.
7. Enter the code. **Only now** is the withdrawal created.
8. "Your withdrawal request has been submitted for processing."

## The merchant does not enter a recipient name

The "Destination Name" field was removed (2026-09-27). It asked the
merchant to type a name that nothing checked, then displayed it back to
them as though it had been verified — which is worse than showing no name
at all, because it reads like the destination was confirmed.

The review step now shows the name **Selcom** resolves for the
destination, via `GET /account/lookup` — see below. When the provider
cannot answer, it shows "Name not available" rather than anything the
merchant typed.

### What is stored instead

`disbursements.destination_name` is still `not null`, and still populated,
by `WithdrawalCreate.resolved_destination_name`: the bank account name if
one was given, otherwise the destination number itself.

**No migration was made to drop that constraint deliberately.** The stored
name is passed to Selcom as `recipient_name` on every real payout
(`app/services/disbursements.py`). Whether Selcom accepts an empty
recipient name is not verified, and finding out in production means failed
payouts. Making the column nullable buys nothing the merchant can see and
risks the one thing that must not break. The request schema keeps
`destination_name` optional, so the `/v1/disbursements/*` routes and any
integrator still sending one are unaffected.

Consequence for Super Admin: for phone-based withdrawals the `destination`
column now mirrors `destination_identifier`. Both are still shown.

## Where the recipient name comes from (2026-09-27)

`POST /v1/merchant/withdrawals/resolve-recipient` asks Selcom who owns the
destination, and the review step displays the answer. The lookup endpoint
(`GET /account/lookup`) already existed on
`SelcomBusinessClient` — implemented, documented as "available for a
future pre-payout recipient-verification step", and never called. This
wires it up.

**Confirmed working against live Selcom, 2026-09-27.** Real resolved
names came back on the first production attempt, for both channels
tested:

| Destination | Resolved |
|---|---|
| Selcom Pesa (`SELCOM`) | `MASANJA MAZURI` |
| Mobile Money / M-Pesa (`MPESA`) | `MASANJA PAUL MAZURI` |

Two things that were open questions before that call, now answered:
`parse_account_name`'s candidate keys matched on the first try, and the
lookup is **not** bank-only — despite taking a `bank` parameter it
resolves mobile-money destinations too. Bank destinations are the one
channel still unconfirmed by a live call.

Selcom's docs still show no example response body, so the parser keeps
trying the shapes Selcom uses elsewhere (`accountName`, `recipientName`,
`name`, …, inside `data` first, since every verified Selcom response
nests its payload there). If none match, the answer is `None` and the
merchant sees "Name not available". It never falls back to another field,
because a wrong name on a payout confirmation reads as though the
destination was verified.

When a lookup *succeeds* but carries no recognised name field, the
response's **keys** are logged — keys only, never values, so an account
holder's name is never written to a log. That is how the real field name
gets read off the first live call, the same way the Selcom Checkout
webhook's real header casing was learned.

### It cannot make a payout worse

- **It never raises.** Provider down, parameters rejected, unsupported
  channel, account does not exist — all of them are "Name not available".
  A withdrawal is never blocked because a name could not be fetched.
- **It never trips the payout circuit breaker.** This is the important
  one. `selcom_outbound`'s breaker opens after consecutive failures and an
  open breaker blocks real payouts. An endpoint that has never been
  exercised live is exactly the kind that might fail consistently for its
  own reasons, so failures are swallowed *inside* the guard and the guard
  sees a clean exit. The concurrency and rate limits still apply, and an
  already-open breaker still skips the call — both of those protect
  Selcom rather than us. There is a test that fails if this is undone.
- **It is rate limited and audited.** A name lookup is an account-name
  oracle: without a limit, anyone with a merchant login could walk a range
  of phone numbers and harvest the name behind each. Ten per merchant per
  minute, merchant-admin only, and every lookup writes an audit row with a
  **masked** destination. The resolved name is never written to the audit
  trail.

### What it costs

One extra Selcom call per withdrawal review, against the same outbound
budget documented in
[`docs/PRODUCTION_TRAFFIC_MANAGEMENT.md`](./PRODUCTION_TRAFFIC_MANAGEMENT.md).
Withdrawal reviews are low-frequency next to collections, so this is
small — but it is not free, and it shares the ceiling.

In `SELCOM_BUSINESS_MODE=mock` the mock client returns a deliberately
obvious `MOCK ACCOUNT HOLDER (1234)`. Mock mode is never production, and
a plausible invented name is precisely what must not be mistaken for a
verified one.

## The merchant does not enter a bank name or a network either

Removed 2026-09-27, for the same reason and with the same approach. Both
are already decided by the **Destination Provider** the merchant picks:
choosing "CRDB Bank" names the bank, and choosing "M-Pesa" names the
network. Asking again was asking them to retype a value the form already
held.

The Network box was actively misleading in practice — with the recipient
name field gone from above it, merchants started typing a person's name
into it.

Both are now derived server-side from `destination_code`, by
`WithdrawalCreate.resolved_bank_name` and `resolved_network`, using
`DESTINATION_CODE_LABELS` in `app/schemas/enums.py`. A value explicitly
sent still wins, so the `/v1/disbursements/*` routes and any integrator
posting one are unaffected.

`disbursements` has a CHECK constraint requiring a `bank_name` for
`BANK_ACCOUNT`, and it is still satisfied — the derived value is never
blank. The account number is still required: nothing derives that.

### The two label maps must not drift

The stored bank name on a real payout now comes from
`DESTINATION_CODE_LABELS`, and the web app renders its own copy in
`packages/shared/src/destination-code.ts`. If the two disagreed, a
merchant would see one bank on screen while a different name was recorded
and sent to the provider — and nothing else would notice, because each
side is internally consistent.

`apps/api/tests/test_destination_code_labels.py` parses the TypeScript
file and compares it entry by entry, rather than keeping a third hardcoded
mirror that could also fall out of date.

## Email verification (OTP)

Unchanged by this work and already in place — see
`supabase/migrations/20260924010000_withdrawal_otp_challenges.sql` and
`app/services/withdrawal_otp.py`. What it guarantees:

- The code is **never stored** — only a SHA-256 hash — never logged, and
  never returned by any endpoint.
- It is bound to a **hash of the exact payload**. Changing the amount or
  the destination after the code is sent produces a different hash, so a
  code issued for 1,000 TZS cannot submit 1,000,000.
- It expires, attempts are capped, resends are cooled down, and `used_at`
  makes it single-use.
- A challenge is verifiable only by the **user who created it**, not by
  anyone holding the merchant's session.
- The withdrawal is built from the payload stored on the challenge, never
  from anything re-sent at verify time.
- An unverified challenge is **inert**: no disbursement row, no
  reservation, no provider call, no notification. Nothing reads it but the
  verify endpoint.

## Backend security is unchanged

Everything that gated a withdrawal before still gates it:

- authentication, merchant ownership, and merchant-admin role
- approved/active merchant (`require_approved_merchant`)
- server-side balance, amount min/max and daily limits, fraud and standing
  checks — run at request time so the merchant is not sent a code for
  something that could never succeed, and **run again** inside
  `execute_disbursement`, and **again** on approval
- withdrawals are created `PENDING_ADMIN_APPROVAL`; the provider is still
  reached only from a Super Admin's approval
- idempotency: the original request's key is carried on the challenge, so
  a repeated verify returns the first withdrawal rather than creating a
  second

Removing the word "approval" from merchant copy changed **no status, no
gate and no workflow** — only what the merchant reads.

## Merchant-facing wording

The merchant portal no longer shows "approval", "pending approval",
"charges" or "fee" anywhere on the withdrawals page. Backend statuses are
untouched; the merchant view maps the ones that name an internal actor to
"Processing" via `MERCHANT_DISBURSEMENT_STATUS_LABELS`
(`apps/web/src/lib/portal/status-tones.ts`):

| Backend status | Super Admin sees | Merchant sees |
|---|---|---|
| `PENDING_ADMIN_APPROVAL` | Pending Approval | Processing |
| `NEEDS_ADMIN_ATTENTION` | Needs Admin Attention | Processing |
| `NEEDS_RECONCILIATION` | Needs Reconciliation | Processing |
| `BLOCKED_IP_WHITELIST` | Blocked (IP Whitelist) | Processing |

`Failed`, `Rejected`, `Reversed`, `Information Requested` and `Completed`
are the merchant's own business and read the same to both.

The shared `DISBURSEMENT_STATUS_LABELS` is **not** changed — Super Admin
is waiting on an approval and should be told so.

Success copy is the same whether or not the withdrawal was auto-approved.
The merchant-visible difference is only how long it takes, the history row
carries the real status, and two different messages would leak an internal
distinction they cannot act on.

## Super Admin is unchanged

Still sees the merchant, method, destination provider, destination number,
amount, resolved name (where one exists), available balance, status, and
the approve/reject controls. Approval wording stays in the internal UI.

## Audit trail

| Action | When |
|---|---|
| `withdrawal.reviewed` | the balance/quote call behind the review step |
| `withdrawal.recipient_lookup` | a destination name was looked up (masked destination; never the resolved name) |
| `withdrawal.validation_failed` | a gate refused the request before any code was sent |
| `withdrawal.otp_requested` | a code was emailed |
| `withdrawal.otp_verify_failed` | a wrong or expired code |
| `withdrawal.otp_verified` | a correct code |
| `withdrawal.duplicate_submission_blocked` | a challenge that already produced a withdrawal was replayed |
| `withdrawal.submitted_after_otp` | the withdrawal was created |

Metadata carries merchant_id, user_id, the challenge or withdrawal id, the
amount, the method, and a **masked** destination (`mask_destination`, e.g.
`********0000`). Never the code, never the full destination, never a
secret. A test asserts the code appears in no audit row anywhere in the
flow.

Two of these names differ from the obvious ones
(`withdrawal.otp_verify_failed` rather than `otp_failed`,
`withdrawal.submitted_after_otp` rather than `submitted`). They were
already deployed and already exist in production logs, so they were kept
rather than renamed — renaming would silently split the history of the
same event across two names.
