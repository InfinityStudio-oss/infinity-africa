# Direct Wallet Push — Partner Integration

For a billing platform collecting payments on behalf of InfinityPay
merchants. Written to be handed to the integrating engineer as-is.

Public reference pages: `/developers/collections`, `/developers/webhooks`,
`/developers/authentication`, `/developers/transaction-status`.

## How the pieces fit

```
Billing system ──API key──▶ InfinityPay ──▶ Selcom ──▶ Customer's wallet
       ▲                          │
       └────── webhook ───────────┘
```

The merchant integrates with **InfinityPay only**. InfinityPay holds the
Selcom relationship and calls Selcom from its own whitelisted backend
addresses. A merchant never holds, sees, or configures Selcom credentials,
and none appear in any API response, webhook payload, log line or doc.

A merchant's own IP allowlist governs access **to the InfinityPay API**.
It has nothing to do with Selcom's IP whitelist, which covers InfinityPay's
servers and is not a merchant concern.

## Merchant onboarding sequence

1. Merchant creates an InfinityPay account.
2. Super Admin verifies and approves the merchant. **Live keys do not work
   before approval.**
3. Merchant generates API credentials at `/portal/api-credentials`.
4. Merchant pastes the **secret key** into the billing system.
5. Merchant sets a webhook URL and generates a signing secret.
6. Billing system initiates Direct Wallet Push.

## Authentication

Send the secret key as a bearer token:

```
Authorization: Bearer sk_live_YOUR_SECRET_KEY_HERE
```

- `sk_live_…` — live money. `sk_test_…` — sandbox, no provider call, no
  real money.
- `pk_…` is a **public identifier, not a credential**. It cannot
  authenticate and is rejected outright if sent as a bearer token.
- The secret is shown **once**, at creation, and stored only as a
  SHA-256 hash. It cannot be recovered — rotate if lost.
- Server-side only. Never ship a secret key in a browser, mobile app, or
  anything a customer can open.
- Revoke at any time in the portal; a revoked key stops working
  immediately.

### There is no request signing today

Requests are authenticated by the bearer key over HTTPS, optionally
narrowed by an IP allowlist. **InfinityPay does not currently verify an
HMAC signature on inbound API requests** — do not build one expecting it
to be checked.

This is stated plainly rather than glossed: the protections in place are a
192-bit secret, TLS, per-key scopes, an optional IP allowlist, rate
limiting, and idempotency. Request signing is tracked as a follow-up and
would be additive — adding it will not break a key-only integration.

**Outbound** webhooks *are* signed. That is a separate mechanism, covered
below.

## Direct Wallet Push

```
POST https://api.infinitypay.me/v1/collections/wallet-push
Authorization: Bearer sk_live_YOUR_SECRET_KEY_HERE
Idempotency-Key: 8f1c2d3e-4b5a-6c7d-8e9f-0a1b2c3d4e5f
Content-Type: application/json
```

```json
{
  "merchant_id": "8c1f...",
  "amount": "5000.00",
  "currency": "TZS",
  "phone": "+255712345678",
  "customer_name": "Asha Mushi",
  "reference": "INV-2026-000412",
  "description": "March broadband subscription"
}
```

| Field | Required | Notes |
|---|---|---|
| `merchant_id` | yes | Must match the key's own merchant |
| `amount` | yes | Decimal string |
| `currency` | no | Defaults to `TZS` |
| `phone` | yes | Customer's wallet number |
| `customer_name` | no | |
| `reference` | no | Your order/invoice id, echoed back everywhere |
| `description` | no | |

`Idempotency-Key` is a **required header**, not a body field.

### Response — 202 Accepted

```json
{
  "success": true,
  "data": {
    "collection_id": "3f2a...",
    "reference": "INV-2026-000412",
    "status": "processing",
    "message": "Payment prompt sent. Please approve on your phone."
  }
}
```

> **`202` means the prompt was sent, not that payment succeeded.** Never
> mark an order paid from this response. Wait for the
> `collection.success` webhook, or poll
> `GET /v1/collections/{collection_id}`.

## Idempotency

Retry with the **same `Idempotency-Key`** and you get the original result
back — no second prompt to the customer, no second Selcom attempt. Reusing
a key with a *different* body is rejected rather than silently returning
the wrong result.

Generate one key per payment attempt (a UUID is fine) and reuse it for
every retry of that attempt. Do not reuse it for a genuinely new payment.

## Webhooks

Configure the URL and generate a signing secret in the portal, or via
`PATCH /v1/merchant/webhook-config`.

Delivery is automatic. Events relevant here:

| Event | When |
|---|---|
| `collection.success` | Payment confirmed and the wallet credited |
| `collection.failed` | Terminal failure — see reason codes |
| `collection.pending_review` | Held for review; not yet credited |

### Payload

```json
{
  "event": "collection.failed",
  "merchant_code": "27048391",
  "collection_id": "3f2a...",
  "reference": "INV-2026-000412",
  "merchant_reference": "INV-2026-000412",
  "amount": "5000.00",
  "currency": "TZS",
  "status": "failed",
  "failure_reason_code": "user_cancelled",
  "failure_reason_message": "The customer cancelled the payment.",
  "failed_at": "2026-09-27T09:14:22Z",
  "cancelled_at": "2026-09-27T09:14:22Z",
  "timestamp": "2026-09-27T09:14:22Z"
}
```

`transaction_id`, `fee` and `net_amount` appear once a transaction exists
(i.e. on success). Never present: API keys, signing secrets, Selcom
credentials, or the provider's raw response.

### Verifying

`X-Infinity-Signature` is an HMAC-SHA256 hex digest of the **exact raw
body**, keyed with your webhook secret. Sign the bytes you received —
parsing and re-serialising changes them.

```python
import hmac, hashlib
expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
if not hmac.compare_digest(expected, request.headers["X-Infinity-Signature"]):
    return 401
```

Also sent: `X-Infinity-Event`, `X-Infinity-Delivery` (dedupe on this), and
`X-Infinity-Timestamp` (Unix seconds; **not** signed — verify over the body
alone).

### Test deliveries look like real ones — on purpose

**Send Test Webhook** posts a payload whose body reads
`"event": "collection.success"` with `"status": "successful"`. That is
deliberate: it means your real success handler is the thing being
exercised, not a special-cased branch you would never run in production.

It also means a handler that keys only on the body's `event` field will
treat a test as a real payment. **Reject test deliveries explicitly**,
using either signal:

```python
if payload.get("test") is True:
    return 200          # acknowledge, do not fulfil
if request.headers.get("X-Infinity-Event") == "webhook.test":
    return 200
```

A test delivery also carries all-zero UUIDs for `collection_id` and
`transaction_id`, and the reference `TXN-TEST0000`, so any of those is a
reliable tell. Real events never set `test`.

### Retries

Any `2xx` is success. Anything else retries up to **5 attempts** —
immediately, then after 1, 5, 15 and 30 minutes — then the event is marked
`failed` and dropped. Timeout is 8 seconds, so return `200` as soon as
you have stored the event and process afterwards.

Treat deliveries as **at-least-once** and make handling idempotent.

Inspect attempts at `GET /v1/merchant/webhook-events`.

## Statuses

| Status | Meaning | What to do |
|---|---|---|
| `processing` | Prompt sent, customer has not acted | Wait |
| `successful` | Paid and credited | Fulfil |
| `failed` | Terminal failure | Read `failure_reason_code` |
| `pending_review` | Held for review | Wait; do not fulfil |
| `reversed` | Reversed after completing | Reverse fulfilment |

## Failure reason codes

`failure_reason_code` is a closed set, safe to `switch` on.
`failure_reason_message` is a sentence you may show a user.

| Code | Meaning |
|---|---|
| `user_cancelled` | Customer cancelled |
| `provider_declined` | Declined by the provider |
| `reversed` | Reversed after completing |
| `expired` | Expired before approval |
| `provider_unavailable` | Provider unreachable; retryable |
| `insufficient_balance` | Not enough balance |
| `wrong_pin` | Wrong PIN / authorization failed |
| `timeout` | Authorization timed out |
| `unknown_provider_error` | Cause not identifiable |

**Be precise about what is live.** Today the provider reliably
distinguishes cancellation, decline, reversal and expiry. Anything it does
not identify arrives as `provider_declined` or `unknown_provider_error` —
including, currently, insufficient balance and wrong PIN. Those codes are
published so you can write the handler now; they will start arriving when
the provider's responses let us tell them apart, with no API change on
your side.

Handle unknown codes gracefully — the set can grow.

## IP allowlist (optional)

Off by default: a valid key from any address works.

Enabled per key in the portal, it restricts that key to your billing
servers' addresses. A request from anywhere else is rejected with a
generic error that reveals nothing about the allowlist, and the rejection
is written to the audit log.

If you use it, add every egress address your servers can present, and
remember to update it when your infrastructure changes — a silent IP
change looks exactly like a compromised key.

## Go-live checklist

1. Merchant account created and **approved** by Super Admin.
2. Live API key generated; secret stored server-side only.
3. Webhook URL set and signing secret generated.
4. **Send Test Webhook** from the portal; confirm your verifier accepts it.
5. Optional: enable the IP allowlist and confirm a request still succeeds.
6. Sandbox run with `sk_test_…` — no real money, no provider call.
7. One live push at the smallest workable amount, to a phone you control.
8. Confirm: `202` received → webhook delivered → collection `successful`
   → merchant wallet ledger credited, showing the customer's phone.
9. Confirm a deliberate failure (customer declines the prompt) arrives as
   `collection.failed` with `failure_reason_code: "user_cancelled"`.

## Live testing caution

Every live push moves real money and consumes the shared outbound Selcom
budget. Use the smallest workable amount, keep the number of live tests
low, and get explicit owner approval first. Prefer `sk_test_…` for
anything repeatable.

---

# Operator notes (not for the partner)

## Deploy order

1. **Apply the migration first**, before the API deploy:
   `supabase/migrations/20260927010000_collection_failure_reason_codes.sql`.
   It is purely additive (`add column if not exists`), rewrites nothing,
   and backfills nothing — historical rows keep their existing
   `failure_reason` untouched. Deploying the API first is safe too: the new
   columns are only written on a failure, so the worst case is a brief
   window where a failed collection has no normalized code.

2. **Then set `WEBHOOK_DELIVERY_INTERVAL_SECONDS=30`** in Railway.

   Until that variable is set, **nothing is delivered** — the default is 0,
   which disables the scheduler exactly like the two reconciliation loops.
   The queue keeps filling and will drain once it is switched on. This is
   the single most important step: without it the partner's integration
   silently falls back to polling.

## What actually changed behind the docs

`enqueue_webhook_event` has written `webhook_events` rows since the
beginning and **nothing ever read them** — its own docstring called
delivery "future work for a background worker". So the Collections API
told partners to wait for `collection.success` while that event was never
sent. `app/services/webhook_delivery.py` is that worker.

Because delivery was never live, no merchant has a receiver that has ever
been hit by real traffic. Expect first-delivery failures from endpoints
that were configured optimistically months ago and never tested; they will
retry five times and then stop, which is the intended behaviour.

## Known gaps, stated plainly

- **No inbound request signing.** API key + TLS + optional IP allowlist
  only. The partner doc says so explicitly rather than implying HMAC. This
  is the main follow-up before a second large partner.
- **`insufficient_balance`, `wrong_pin` and `timeout` never fire yet.** The
  codes exist and are documented, but no confirmed Selcom response
  distinguishes those cases, so they resolve to `provider_declined` or
  `unknown_provider_error`. Add the mapping in
  `app/services/failure_reasons.py` once a real response proves the code —
  nothing else needs to change.
- **Delivery is single-replica.** The sweep has no cross-process lock, so
  two API replicas would each deliver the same event. Same constraint as
  the in-memory rate limiter, and fine at one replica.

## Before the partner's first live run

- Confirm `SELCOM_OUTBOUND_MAX_PER_MINUTE` against Selcom's real limit.
  It is currently a guess (60), and a billing run across hundreds of
  subscribers is exactly the burst it was set for.
- Bound the reconciliation sweep, which polls Selcom once per pending
  collection and shares that same budget.
