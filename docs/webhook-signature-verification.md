# Verifying InfinityPay webhooks

For developers building or maintaining a system that receives InfinityPay
webhooks — ISP and WiFi billing platforms, voucher systems, and any
integration that acts when a payment arrives.

If your system activates service, issues a voucher, or credits an account
when an InfinityPay event arrives, **this page is the difference between
doing that for real payments and doing it for anyone who learns your
webhook URL.**

A working reference implementation is at
[`docs/examples/webhook_receiver.py`](examples/webhook_receiver.py). It is
dependency-free, framework-agnostic, and covered by tests in
`apps/api/tests/test_webhook_receiver_reference.py`. Those tests cover the
example; they do not cover your integration. Do not consider your receiver
verified until your own code has been run against the same cases.

## What a delivery looks like

```http
POST /your/webhook/path HTTP/1.1
Content-Type: application/json
X-Infinity-Event: collection.successful
X-Infinity-Delivery: 6f1c9a52-0b7e-4f1a-9c3d-2a8e7b4d5c10
X-Infinity-Timestamp: 1792486252
X-Infinity-Signature: 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08

{"merchant_id":"...","reference":"INV-10432","amount":"5000.00","currency":"TZS","status":"successful"}
```

| Header | Meaning |
|---|---|
| `X-Infinity-Event` | The event name, e.g. `collection.successful` |
| `X-Infinity-Delivery` | **Stable identifier for this delivery.** Unchanged across retries. This is your deduplication key |
| `X-Infinity-Timestamp` | Unix seconds when we sent it. **Not covered by the signature** — see below |
| `X-Infinity-Signature` | HMAC-SHA256 of the raw body, keyed with your signing secret, lowercase hex. **Absent if you have not configured a secret** |

## Getting your signing secret

InfinityPay portal → API Credentials → Webhooks → **Generate Secret**.

It is shown once and never retrievable afterwards — we store only an
encrypted copy, used to sign your deliveries. If you lose it, generate a
new one; that immediately replaces the old one, so deploy the new value to
your receiver at the same time.

A new webhook endpoint now requires a secret before it can be saved. If
your endpoint predates that, it keeps working, and you can add a secret at
any time without losing your URL or your event subscriptions.

**Your signing secret is not your API key.** They are separate credentials
with separate lifetimes: rotating one does not affect the other. Never use
an API key to verify a signature.

## Verifying

### 1. Sign the bytes you received, not the JSON you parsed

This is the mistake that costs the most time. Parsing JSON and
re-serialising it changes key order and whitespace, so the HMAC will not
match even though everything else is correct. Capture the raw body
*before* any JSON middleware touches it.

```python
# Flask
raw = request.get_data()          # correct
raw = json.dumps(request.json)    # WRONG - will never verify
```

```javascript
// Express: mount a raw body parser on the webhook route only
app.post("/hooks/infinitypay",
  express.raw({ type: "application/json" }),
  (req, res) => { /* req.body is a Buffer - verify against this */ });
```

### 2. Compare in constant time

```python
import hmac, hashlib

expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
ok = hmac.compare_digest(received_signature.strip().lower(), expected)
```

```javascript
const crypto = require("crypto");

const expected = crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
const received = Buffer.from((header || "").trim().toLowerCase(), "utf8");
const ok =
  received.length === Buffer.byteLength(expected) &&
  crypto.timingSafeEqual(received, Buffer.from(expected, "utf8"));
```

`===` or `==` returns as soon as two characters differ. That timing
difference leaks the expected signature one character at a time to anyone
who can measure it. Use `compare_digest` / `timingSafeEqual`, and compare
lengths first — `timingSafeEqual` throws on a length mismatch.

### 3. Treat a missing signature as a rejection

Once your secret is configured, a delivery with no `X-Infinity-Signature`
did not come from us in any way you can trust. Reject it. Do not accept
unsigned deliveries as a temporary measure — that is the gap this exists
to close.

## Replay protection: deduplicate, do not rely on the timestamp

The signature covers **the body only**. It does not cover
`X-Infinity-Timestamp`, so an attacker replaying a captured delivery can
replay the timestamp unchanged, and a freshness check alone will not stop
them.

Your real protection is deduplication on `X-Infinity-Delivery`, because
that lives in your own records and cannot be forged into looking new.

Make the claim atomic. Checking first and inserting second is a race: two
concurrent retries both read "not seen" and both activate service.

```sql
create table infinitypay_deliveries (
  delivery_id text primary key,
  received_at timestamptz not null default now()
);

-- Claim it. No row returned means we have already handled this delivery.
insert into infinitypay_deliveries (delivery_id) values ($1)
on conflict (delivery_id) do nothing
returning delivery_id;
```

**Claim the delivery id before you activate anything.** If you activate
first and record second, a crash in between leaves service activated and
the delivery unrecorded — so our retry activates it a second time.

A freshness check on the timestamp is still reasonable as a cheap filter.
Keep the window generous (hours, not minutes): our retry schedule backs
off, so a legitimate retry of an event first attempted much earlier is
normal, and a tight window throws away real payments.

## Check the event before you act on it

A signature proves the event came from InfinityPay. It does not prove the
event means what your activation logic assumes. Before activating:

- **`merchant_id`** matches the merchant you expect. An authentic event
  for a different merchant is not yours to act on.
- **`status`** is `successful`. Never treat "an event arrived" as "money
  arrived" — other statuses are real events about payments that have not
  completed.
- **`currency`** is the one you price in (`TZS`).
- **`amount`** is positive, and is what you expected for that reference.
- **`reference`** is present and matches an order on your side.
- **`X-Infinity-Event`** is an event you actually handle. Return 2xx for
  the others rather than erroring, so we stop retrying them.

## Responding, and retries

Return **2xx once the event is durably recorded** — not once your business
logic has finished. Do the slow work afterwards.

We retry on any non-2xx response and on timeouts, with a backing-off
schedule, and a retry repeats the same `X-Infinity-Delivery`. If you fail
*after* recording the delivery, still return 2xx and recover from your own
records: a retry would otherwise arrive and you must then be certain you
will not act twice.

| Your response | What we do |
|---|---|
| 2xx | Mark delivered, stop retrying |
| 4xx / 5xx | Record the failure, retry per the schedule |
| Timeout | Record the failure, retry per the schedule |

## Testing your receiver

Portal → API Credentials → Webhooks → **Send Test Webhook**. The test
delivery carries the same headers as a real one, signed with the same
secret, so verification that passes on the test will pass on live traffic.

Then check, with your own tests:

- A valid delivery is accepted and activates exactly once.
- A delivery whose body has been altered after signing is rejected.
- A delivery with no signature is rejected.
- A delivery signed with a different secret is rejected.
- The same delivery sent twice activates once.
- Five retries of the same delivery activate once.
- Two different payments of the same amount both activate.
- A `pending` status does not activate.
- An event for another merchant does not activate.

`docs/examples/webhook_receiver.py` passes all of these; translate the
cases, not just the code.

## Questions

Contact InfinityPay support with your merchant code and the
`X-Infinity-Delivery` id of any delivery you are asking about. **Never
send us your signing secret**, and never put it in a bug report, a log, or
a screenshot — we cannot read it back and we will never ask for it.
