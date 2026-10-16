# Merchant SMS (OasisTech BulkSMS)

Transactional payment alerts to merchants, and Super Admin announcements.

**Recipients are merchants only.** No code path here can address a paying
customer: every recipient is resolved from
`merchant_notification_settings.sms_notification_phone` or
`merchants.contact_phone`, and `sms_messages` has no column that could
hold a customer number. There was no earlier SMS implementation in this
repository, so there was no payer-notification behaviour to remove — the
only pre-existing mentions of SMS were marketing copy on the public site,
which is untouched.

**Nothing here can change a payment.** The dispatcher reads and writes
`sms_messages` and talks to the provider. It never touches a ledger
account, ledger entry, transaction or collection. An SMS that fails,
duplicates or never sends cannot alter what a merchant is owed, and an
SMS outage cannot delay a merchant webhook — webhook delivery is a
separate sweep with a separate lease.

## The message

```
InfinityPay: Umepokea TZS {amount}. Makato: TZS {fee}. Kiasi halisi: TZS {net}. Salio baada ya muamala: TZS {closing_balance}. Kumbukumbu: {reference}.
```

Every figure is copied from a committed record and none is recomputed.
`gross`/`fee`/`net`/`reference` come from the `transactions` row the
ledger posted against. `net` is read, never derived from `gross - fee` —
a second opinion in a text renderer is how two sources of truth start.

### Where the closing balance comes from, and why

`ledger_entries.balance_after` for that posting's merchant-wallet leg.
`post_ledger_entries()` writes it under the same row lock as the balance
check (`20260828020000`) and never updates it afterwards, so it is the
balance *this payment produced*.

It is deliberately **not** `transactions.balance_after`. That column's own
migration (`20260828030000`) documents it as tracking the *most recent*
posting for a transaction, so a later reversal rewrites it — which would
silently change the number in a message already queued or already sent.

The value is frozen into the `sms_messages` row at enqueue time, along
with the fully rendered body. A withdrawal or a second payment a minute
later cannot reach it.

**Postings with no snapshot are skipped, not estimated.** Rows predating
those columns have `balance_after = NULL`, and the migration is explicit
that there is no sound way to reconstruct one. The merchant gets no SMS
and the Super Admin screen shows the reason. A balance that is merely
plausible is worse than none.

## When an alert is queued

Only after `post_collection_entries` has committed, in the two paths that
credit a merchant:

- `resolve_collection()` — the funnel for the Selcom callback, the manual
  "Refresh status" action and the reconciliation sweep
- `finalize_pending_review_collection()` — a Super Admin clearing a
  self-payment risk alert

Never for initiated, pending, failed or cancelled payments. An accepted
STK prompt is not payment success and does not reach that branch.

### Duplicate protection

A partial unique index on `(collection_id, merchant_id, purpose)` for
`collection_alert` rows. The Selcom callback and the reconciliation sweep
routinely resolve the same collection at once; `resolve_collection`'s own
guard already prevents a double credit, and this is the equivalent
guarantee for the message. The loser of that race gets a constraint
violation, which is the correct outcome.

There is **no transactional outbox in this codebase** — `enqueue_webhook_event`
has always been a separate operation after the ledger posting, and SMS
follows the same shape deliberately. Coupling the enqueue into
`post_ledger_entries` would make an SMS failure capable of rolling back a
payment, which the brief forbids. The cost is a narrow window: a crash
between the ledger commit and the enqueue loses that one alert. It cannot
produce a wrong alert or a double credit.

## Idempotency

The provider key is `ipay-c-{collection_id.hex}` — derived, stable, and
written to the row **before the first attempt**. Within the provider's
documented 1–64 visible-ASCII format.

This is what makes every retry safe. A timeout, a crash mid-send, a
reclaimed lock: all resend the identical bytes under the identical key,
and the provider replays its original response without sending or
charging again. **No code path mints a new key to retry.** That single
rule is what keeps an uncertain outcome from becoming a duplicate SMS.

## Provider outcomes

Verified against `https://bulksms.oasistech.co.tz/llms-full.txt`,
2026-10-17.

| Response | Our status | Behaviour |
|---|---|---|
| 200 `sent` | `sent` | Gateway accepted. **Not** a handset receipt. |
| 200 + `idempotent_replay` | `sent` | Already sent. No charge. |
| 202 `pending`/`processing` | `pending` | Terminal. Never resend. |
| 409 `already_processed` | `sent` | Documented as already sent. |
| 429 | requeued | Honours `Retry-After`. Does not spend an attempt. |
| 402 insufficient credits | `failed`, parked | No retry storm. Logged at error. |
| 400/401/403/415/422 | `failed`, parked | A person must fix it. |
| 502 `failed`/`partial` | `failed` | Not charged. Retried. |
| 503 | `failed` | Retried later, same key. |
| 5xx / timeout | `unknown` | Retried with the same key, never a new one. |

`unknown` is deliberately distinct from `failed`: a failure was not
charged and is safe to retry, an unknown may already be on its way.

One recipient per request. The provider supports batching, but a partial
failure inside a batch is far easier to mishandle than a failure of a
request that only ever carried one message. At 60 merchants the request
count is not the constraint.

## Rate limiting

Provider limit: **300 send requests/minute per account**, plus a per-IP
guard of 600/min. We send at **240/min** by default, leaving a fifth of
the account for anything else sharing those credentials.

This is an **in-process** counter. It is equivalent to an account-wide
limit *only because* the dispatch sweep holds the `sms_dispatch`
scheduler lease and therefore runs in exactly one replica at a time.
Remove that lease and this silently becomes a per-replica limit, letting
two replicas send twice the account's budget.

## Cost

1 credit per part per recipient. GSM-7 is 160 characters (153 when
split); Unicode is 70 (67 when split). One curly quote, long dash or
emoji moves a message to Unicode and roughly doubles its cost — the
Compose screen shows the encoding and part count as you type.

A payment receipt is **not** assumed to fit one part. With four amounts
and a long reference it can exceed 160 characters, and in that case it
costs two parts. References and amounts are never shortened to force a
one-part message.

Campaign credit figures are **our own estimate** from the rendered text
and are labelled as such everywhere. The provider's `dry_run` is the only
thing that confirms a price; it runs every check, returns the encoding,
part count, `credits_required` and `enough_credits`, and consumes no
idempotency key and no credits.

## Migrations

One migration, **not applied**:
`supabase/migrations/20261017090000_merchant_sms_notifications.sql`

1. Five columns on `merchant_notification_settings` — `collection_sms_enabled`
   (default **false**), `sms_notification_phone`, `announcement_sms_enabled`
   (default true), and who/when the number last changed.
2. `sms_messages` — queue, delivery state, history, frozen snapshot,
   idempotency key; two unique indexes.
3. `sms_campaigns` — drafts and sent announcements. No transition back to
   `draft`.
4. `sms_provider_events` — callback deduplication by provider event id.
5. One `scheduler_leases` row for `sms_dispatch`.

Additive only. No existing column is altered or dropped, no data is
backfilled, and no financial table is touched.

### Deployment order

1. **Apply the migration.** The API reads these tables.
2. **Deploy the API** with `OASIS_SMS_ENABLED=false` (the default). Rows
   are not even enqueued while off, so nothing accumulates.
3. Confirm the Super Admin → SMS screen loads and reports "switched off".
4. Set the provider variables and flip `OASIS_SMS_ENABLED=true` plus
   `OASIS_SMS_DISPATCH_INTERVAL_SECONDS=30` when you are ready.

Deploying the API before the migration leaves the SMS screen erroring and
every enqueue failing silently into its own try/except — no payment is
affected, but do not do it.

## Railway environment (API service)

```
OASIS_SMS_ENABLED=false
OASIS_SMS_API_KEY=<provider key, messages:send + balance:read>
OASIS_SMS_SENDER_ID=<approved sender ID>
OASIS_SMS_WEBHOOK_SECRET=<only if callbacks are registered>
OASIS_SMS_DISPATCH_INTERVAL_SECONDS=0
OASIS_SMS_RATE_LIMIT_PER_MINUTE=240
OASIS_SMS_TIMEOUT_SECONDS=180
OASIS_SMS_BATCH_SIZE=50
OASIS_SMS_ANNOUNCEMENT_BATCH_SIZE=20
```

There is one service; the worker runs inside the API process as a
lifespan task, like every other sweep. If a separate worker service is
ever added, it needs the same variables and the lease keeps the two from
both dispatching — but set `OASIS_SMS_DISPATCH_INTERVAL_SECONDS=0` on the
web-facing one so only the worker sweeps.

**None of these may be set in `apps/web` or `apps/mobile`.** No
`NEXT_PUBLIC_` variable exists for any of them.

## Provider prerequisites

- KYC approved on the provider account (required even for trial credits)
- An **approved sender ID**, 3–20 characters. An unapproved sender is a
  403 on every send, not a silent failure.
- Credits on the account
- API key with `messages:send`, plus `balance:read` for the credit figure
  on the overview screen
- For callbacks: register the endpoint at `POST /v1/sms/callbacks/oasis`
  and put the secret the provider returns **once** at creation into
  `OASIS_SMS_WEBHOOK_SECRET`. Until that is set, the endpoint rejects
  everything — fail-closed is right for an endpoint that exists to accept
  unauthenticated POSTs.

## Rollout

1. Apply the migration, deploy with the flag off.
2. Run a dry run to confirm sender, encoding and cost without sending:
   `POST /v1/sms` with `"dry_run": true`. Consumes no credits and no key.
3. Enable `collection_sms_enabled` for **one** merchant you can call, set
   their notification number, flip `OASIS_SMS_ENABLED=true` and
   `OASIS_SMS_DISPATCH_INTERVAL_SECONDS=30`, and take one real payment.
4. Check Super Admin → SMS: one message, `Accepted by gateway`, one part,
   and the balance in the text matching that merchant's wallet after the
   payment.
5. Widen merchant by merchant. `collection_sms_enabled` defaults to
   false, so nothing turns on by itself.

Enabling SMS **never** sends for payments that already happened: nothing
is enqueued while the flag is off, so there is no backlog to drain.

## Monitoring

- Super Admin → SMS → Overview: queue depth, queue age, skip reasons,
  recent errors, provider credits.
- Log lines (`infinity.sms`): `scheduled_sms_dispatch` with a per-sweep
  summary, `sms_reclaimed_abandoned`, `sms_provider_credits_low`,
  `sms_dispatch_not_configured`.
- Worth alerting on: queue age climbing past a few minutes, any
  `unknown` status, and `credits.low` from the provider.

No phone number, message body, secret or API key is ever logged.

## Rollback

Set `OASIS_SMS_ENABLED=false` and redeploy.

Dispatch stops immediately. Queued rows stay queued, history is kept,
provider state is untouched, and **no financial record changes**. New
collections stop enqueuing rows, so nothing accumulates while off. There
is nothing to undo in the database and the migration does not need
reverting.

## What is deliberately not built

- **No merchant-facing view of `sms_messages`.** The table has no
  merchant RLS policy. Nothing in the Merchant Portal reads it, and a
  policy added speculatively is a policy nobody has thought about.
- **No retry button for `sent`, `pending` or `unknown`.** All three are
  states where the provider may already hold the message. The stable key
  would most likely save us; "most likely" is not a reason to offer the
  button.
- **No scheduled sends.** The provider supports `scheduled_at` and
  reserves credits at submission. Not needed yet.
- **No reconciliation sweep against `GET /v1/logs`.** Worth adding if
  `unknown` rows ever appear in practice; the provider log is how a send
  whose response we never received would be resolved.
