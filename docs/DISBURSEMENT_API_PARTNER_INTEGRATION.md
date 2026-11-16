# Disbursement API — Partner Integration

For a partner whose own server needs to send money out to recipients
automatically, with no person approving each payment. Written to be handed
to the integrating engineer as-is.

Everything below describes behaviour exercised against the sandbox. Where
a thing is not built yet, it says so rather than describing an intention.

---

## The one idea you need first

**A payout key spends a prefunded wallet, and nothing else.**

```
                   dashboard, 2FA              payout API key
  Collections ──────────────────────▶ Payout wallet ──────────────▶ Recipient
   balance                              (available)
                                              │
                                              ▼
                                         (reserved)  ← held while in flight
```

The payout wallet is topped up from the merchant's Collections balance by
a person signed into the dashboard, behind two-factor authentication. **An
API key cannot do it**, and that is the point: the wallet balance is the
ceiling on what a leaked key can cost. A key that could refill the pot it
spends from would have no ceiling at all.

The same reasoning closes the other routes. A payout key cannot:

- fund the payout wallet (`403`)
- reach the merchant's Collections balance
- request a withdrawal on `/v1/disbursements/*` (`403`)
- read the dashboard surface at `/v1/merchant/*` (`403`)

A payout key can create payouts, and read them back. Nothing else.

---

## Onboarding sequence

1. Merchant has an InfinityPay account, verified and approved.
2. InfinityPay enables the **sandbox** for that merchant. This is a Super
   Admin action, audited, and granted one environment at a time.
3. Merchant creates a **payout key** in the dashboard:
   **API Credentials → Payout Keys → New payout key**.
4. Merchant adds at least one **beneficiary** (the destination money goes
   to). Payouts are only ever sent to an already-approved beneficiary —
   you cannot pass a raw phone number to `POST /v1/payouts`.
5. Merchant funds the payout wallet.
6. Your server starts calling `POST /v1/payouts`.

Live access is a separate grant with a commercial agreement behind it. It
is **not** a switch on the same screen, and a request to enable it through
the sandbox control is refused rather than ignored.

---

## Authentication

```
X-API-Key: sk_test_…        (sandbox)
X-API-Key: sk_live_…        (live)
```

The key implies its merchant **and** its environment. There is no
`merchant_id` in any request body — sending one is a `422`, not a silently
ignored field. A sandbox key cannot read a live payout, and vice versa:
the answer is `404`, because that id is not one of theirs.

Scopes are fixed for this key type: `payouts:create` and `payouts:read`.
A payout key cannot hold any other scope, and a scope that does not belong
to the key's type is dropped at authentication even if it is somehow
present on the stored record.

---

## Creating a payout

```http
POST /v1/payouts
X-API-Key: sk_test_…
Idempotency-Key: 8f2c1b90-5d4e-4a7b-9c31-2e6f8a1d4b02
Content-Type: application/json

{
  "beneficiary_id": "a0ee27ea-51a1-4da5-a31a-671896b42de1",
  "amount": "50000.00",
  "currency": "TZS",
  "metadata": { "invoice": "INV-2026-114" }
}
```

```http
201 Created

{
  "success": true,
  "data": {
    "id": "9ab5902e-c38e-4a07-ad03-dbd71f6ff13f",
    "status": "processing",
    "amount": "50000.00",
    "fee_amount": "0.00",
    "total_debit": "50000.00",
    "currency": "TZS",
    "environment": "sandbox",
    "beneficiary_id": "a0ee27ea-51a1-4da5-a31a-671896b42de1",
    "reference": "PO-6F9223F5A1E44605B036",
    "failure_code": null,
    "failure_reason": null,
    "created_at": "2026-11-16T13:02:01.510Z",
    "completed_at": null
  }
}
```

### `Idempotency-Key` is required, not optional

A `422` if you omit it. This is deliberate. Your retry after a timeout is
the normal case, not the exception — and without a key, a network failure
on a call that actually succeeded is indistinguishable from one that
failed, so the safe-looking action (retry) sends the money twice.

- **Same key, same body** → the stored response is replayed. One payout.
- **Same key, different body** → `409`. Re-running would send a different
  amount; replaying the stored response would answer for a payout that was
  never created. Neither is acceptable, so it is refused.

### What `201` means

**The money is reserved, not sent.** `status: "processing"` means the funds
have moved from `available` to `reserved` in the same database transaction
that created the payout. There is no window in which a payout exists with
nothing behind it.

The provider is contacted afterwards, by a worker. Poll
`GET /v1/payouts/{id}` for the outcome.

### Refusals

| Status | `error.code` / meaning | What to do |
|---|---|---|
| `422` | validation — bad amount, unknown field, missing `Idempotency-Key` | fix the request |
| `404` | the beneficiary is unknown, belongs to someone else, is disabled, or is in the other environment | check the beneficiary |
| `409` | `insufficient_funds` — the payout wallet cannot cover `amount + fee` | the merchant funds the wallet |
| `409` | the rolling 24-hour payout limit would be exceeded | wait, or ask for a higher limit |
| `409` | payouts are paused on this account | contact support; the reason is in the message |
| `403` | the key is not a payout key, or has the wrong scope | check the credential |

A refusal moves no money and leaves nothing behind — no ledger entry and
no orphaned transaction record.

---

## Statuses, and the one that matters

| Status | Funds | Meaning |
|---|---|---|
| `queued` | nothing held | created, not yet authorised. You will rarely see this. |
| `processing` | **reserved** | authorised and funded; sent or being sent to the provider |
| `needs_reconciliation` | **STILL RESERVED** | the provider has not told us the outcome |
| `successful` | spent | the provider confirmed payment |
| `failed` | returned to `available` | the provider confirmed it did **not** pay |
| `cancelled` | never held, or returned | a limit or the balance stopped it |
| `reversed` | returned | reversed after settling |

### `needs_reconciliation` is not a failure

This is the single most important row in that table, so it gets its own
section.

If the provider times out, drops the connection, or answers with anything
other than a definite yes or no, the payout goes to
`needs_reconciliation` **and the funds stay reserved**. Nothing releases a
reserve on a timeout.

The reason is simple: a payout whose outcome is unknown **may have been
paid**. Releasing its funds would let the merchant spend money that has
already left, and the shortfall would be real. So an unknown outcome parks
the payout with the money still committed, and we keep asking the provider
until it answers.

For you, that means:

- **Do not treat `needs_reconciliation` as failed.** Do not re-send.
- **Do not re-create the payout.** Re-sending a payout whose outcome is
  unknown is the one action that can genuinely pay a recipient twice.
- Keep polling. It will become `successful` or `failed`.

Our own reconciliation only ever *queries* the provider; it never re-sends.
Please do the same.

---

## Reading payouts

```http
GET /v1/payouts/{id}
GET /v1/payouts?page=1&page_size=50
```

Both are scoped to your key's merchant and environment. The list is
newest-first.

The response deliberately excludes the provider's raw payload and the id
of the key that created the payout. The first is ours to debug with; the
second is a credential reference.

---

## Fees and limits

- `amount` is what the recipient receives.
- `fee_amount` is InfinityPay's fee, quoted at creation.
- `total_debit` is `amount + fee_amount` — **this** is what leaves the
  payout wallet, and **this** is what counts against the rolling limit.

Two limits may apply, both set per account:

- **per payout** — a ceiling on one payment
- **rolling 24 hours** — the sum of `total_debit` over the last 24 hours,
  measured from the moment of the request, not a calendar day

Everything not definitively refunded counts against the rolling limit:
`queued`, `processing`, `needs_reconciliation` and `successful`. In-flight
money is treated as spent until proven otherwise. `failed`, `cancelled`
and `reversed` do not count, because those funds went back.

---

## Sandbox

A sandbox payout is simulated end to end. No real money moves and no real
recipient is paid. Sandbox has **no path to a live provider**: the mock is
refused outright outside a development environment rather than being
allowed to fall back.

Sandbox and live are separate in every direction — separate keys, separate
beneficiaries, separate wallets, separate payout history. A sandbox key
reading a live payout gets `404`.

---

## Not built yet

Stated plainly so you do not design around them:

- **No outbound webhooks for payouts.** There is no `payout.succeeded`
  event yet. Poll `GET /v1/payouts/{id}`.
- **No reversal endpoint.** The data model supports a reversal and the
  database enforces its rules, but no API route exposes it.
- **No beneficiary API.** Beneficiaries are created by InfinityPay on the
  merchant's behalf during onboarding; there is no
  `POST /v1/payout-beneficiaries` yet.
- **No bulk payout endpoint.** One payout per request.

---

## Support

When reporting a problem, send the payout `reference` (the
`PO-…` value). It is our stable handle for that payout and is also the
idempotency key we present to the provider, so a retry after an ambiguous
dispatch asks about the same payout rather than starting another.
