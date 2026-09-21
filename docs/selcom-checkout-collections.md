# Selcom Checkout Collections — Wallet Push, Webhook & Reconciliation

The full Push STK/USSD ("Mobile Money Push") flow for a customer paying
a payment link: create an order shell, trigger a real push, then
resolve the outcome via webhook or manual refresh — and only then credit
the merchant. For the general pricing/withdrawal-side approval flow see
[`docs/withdrawal-pricing-and-approval.md`](./withdrawal-pricing-and-approval.md);
for the Selcom Checkout signing scheme itself see the module docstrings
in `apps/api/app/services/selcom_checkout/`.

## Active customer payment methods (2026-08-24)

Three, and only three, are active. Neither the merchant (creating a
Payment Link or a "Request Collection") nor the frontend ever picks a
channel up front anymore — the customer chooses on Infinity's own
payment page, via `POST /public/payment-links/{slug}/pay`
(`app/services/collection_payment.py::initiate_collection_payment`):

| Public method name | Stored `collections.method` | Backing service | Selcom endpoint |
|---|---|---|---|
| `WALLET_PUSH` | `STK_PUSH` | `app/services/wallet_push.py` | `POST /v1/checkout/wallet-payment` |
| `SELCOM_PESA` | `SELCOM_PESA_PUSH` | `app/services/selcompesa_push.py` | `POST /v1/checkout/selcompesa-payment` |
| `TANQR` | `DYNAMIC_QR` | `app/services/dynamic_qr.py` | (create-order-minimal only — no push step) |

All three method names map onto `collections.method` values that
already existed in the CHECK constraint before this change — no
migration was needed. "Request Collection" in the Merchant Portal now
creates a `payment_links` row (no channel, no expiry) instead of pushing
immediately, and hands the merchant a shareable URL — the customer opens
it and picks a method themselves, same page as a real Payment Link.

**Hosted checkout is inactive** — `POST /public/payment-links/{slug}/pay/checkout`
refuses to run unless `settings.hosted_checkout_enabled` is explicitly
`true` (default `false`; see "Known issue" below for why). No frontend
calls this endpoint. The code path is untouched, not deleted, ready to
re-enable once Selcom confirms hosted checkout is fixed.

**TanQR never generates its own QR.** `qr`/`payment_token` are Selcom's
own `create-order-minimal` response fields, stored on `checkout_orders`
exactly as returned (`app/services/checkout_orders.py`) and passed
through the API/frontend unaltered
(`apps/web/src/components/payment-link/selcom-qr-display.tsx` renders
whatever format Selcom returned — EMVCo/text is encoded into a QR image
client-side via the existing `qrcode` package; a URL/base64-image value
is shown as an `<img>` directly, never re-encoded).

## The Mobile Money Push flow (detail)

```
customer submits phone
        │
        ▼
POST /public/payment-links/{slug}/pay/wallet-push
        │
        ├─ create-order-minimal  (order shell — never charges anyone)
        │
        └─ wallet-payment        (the real push — the one call that can move money)
        │
        ▼
collection created, status = "processing"  (never "successful" here)
        │
   ┌────┴────┐
   ▼         ▼
webhook   manual refresh (merchant/admin "Refresh status")
   │         │
   └────┬────┘
        ▼
complete_checkout_collection_once()
        │
        ▼
resolve_collection()  ← the credit rule is enforced here, once
```

Both resolution paths (webhook and manual refresh) go through the exact
same function — see "Shared completion / idempotency" below. Neither
`create_order_minimal()` nor `process_wallet_payment()` ever credits a
merchant directly; `app/services/wallet_push.py`'s own module docstring
explains why the collection created there is capped at `"processing"`,
never `"successful"`.

## Webhook endpoint

```
POST /v1/webhooks/selcom/checkout
GET  /v1/webhooks/selcom/checkout   (reachability probe only — Selcom's
                                     portal "Test URL" check; carries no
                                     data, verifies nothing)
```

Distinct from the older `/v1/webhooks/selcom` (a different, unconfirmed
placeholder product — see `docs/selcom-live-go-live.md`). Every delivery
is logged to `selcom_webhook_events` (`provider = "selcom_checkout"`)
before signature verification even runs, so the very first real delivery
can be inspected regardless of whether verification passed. As of
2026-08-23 a safe, secret-free log line (`order_id`/`transid`/`reference`/
`payment_status` only — never `Timestamp`/`Digest`/`Digest-Method`, since
those are the signature material itself) is also emitted before
verification, for the same reason.

### Exact URL to register with Selcom

```
https://web-production-3fdc4a.up.railway.app/v1/webhooks/selcom/checkout
```

This is the **verified-live, currently-reachable** URL (confirmed via a
real `GET` reachability check returning `{"status": "ok"}`). Do **not**
register `https://api.infinitypay.me/...` — as of 2026-08-22/23 that
subdomain does **not resolve at all** (confirmed NXDOMAIN via `nslookup`
and curl), despite being referenced as the "production" domain in both
`apps/api/.env.example` and `apps/web/.env.example`. That stale
documentation is the leading suspect for why no real webhook delivery
has ever arrived (see "Known gaps" below) — if Selcom's account was ever
configured with that URL, delivery would silently fail on their end
regardless of anything this codebase does. If/when a stable custom
domain is set up and DNS-verified, update this doc, both `.env.example`
files, and re-register the new URL with Selcom.

### Selcom account configuration required

Two independent things must both be true for a real delivery to ever
arrive — confirming one does not imply the other:

1. **Our side sends the callback URL on order creation.** Every
   `create-order-minimal` call now includes a `webhook` field (base64
   encoded per Selcom's docs) whenever `SELCOM_CHECKOUT_WEBHOOK_URL` is
   set — see `app/services/checkout_orders.py::create_checkout_order_minimal()`.
   **This was NOT happening before 2026-08-23** — the client method
   (`SelcomCheckoutHTTPClient.create_order_minimal()`) always supported a
   `webhook` parameter, but the one real production call site never
   passed it, so Selcom was never told where to deliver a callback for
   any order, ever, independent of the DNS issue above. This is now
   fixed.
2. **Selcom's own Merchant Portal callback setting**, if their platform
   also requires (or additionally uses) a portal-level, account-wide
   callback URL rather than trusting the per-order `webhook` field —
   confirm with Selcom support which applies to this account. Set it to
   the exact same URL above.

### Railway env var

```
SELCOM_CHECKOUT_WEBHOOK_URL=https://web-production-3fdc4a.up.railway.app/v1/webhooks/selcom/checkout
```

Backend/Railway only — never set in `apps/web`/Vercel (it's not a
secret, but it's a backend implementation detail with no frontend use).
Left blank, no `webhook` field is sent to Selcom at all — a deliberate,
safe default: reconciliation still works via the manual refresh
endpoints below, it just relies on nobody ever calling this app back.

Expected payload fields (per the reconciliation task brief — field
names not yet independently re-verified against a live delivery the way
`create-order-minimal` was):

| Field | Notes |
|---|---|
| `transid` | The value this backend generated at wallet-payment time — the precise match key |
| `order_id` | Fallback match key if `transid` isn't found |
| `reference` | Selcom's own reference |
| `result` | e.g. `"SUCCESS"` |
| `resultcode` | e.g. `"000"` |
| `payment_status` | The authoritative completion signal — see below |
| `channel` | Optional — which telco/PSP handled it |
| `amount`, `phone` | Optional, not persisted from the webhook itself |

## Signature verification

**Confirmed against 5 independent real deliveries (2026-08-27): Selcom
sends no signature on this callback at all.** No `Digest`/`Digest-Method`/
`Timestamp`/`Signed-Fields` header, or anything else signature-shaped —
just standard HTTP headers (`accept`, `content-type`, `host`), Selcom's
own `user-agent: SelcomPay 1.0`, and whatever Railway's proxy adds
(`x-forwarded-*`, `x-railway-*`, `x-real-ip`). The scheme
`verify_webhook_signature()` (`apps/api/app/services/selcom_checkout/signer.py`)
was built against — mirroring the outbound request-signing scheme
(`build_auth_headers`) in the opposite direction — was a reasonable
inference at the time but is now confirmed wrong.

**Deliberate policy (2026-08-27, revised same day): the webhook fails
closed on signature, unconditionally, with no exception for "the scheme
might be wrong."** An unsigned/invalid/expired delivery is rejected
(401) before touching anything — no collection status change, no wallet
credit, nothing. `signature_valid` is still computed and stored on every
`selcom_webhook_events` row for audit (it reads `false` for every
genuine Selcom delivery, by design) but a failing/absent signature is
never treated as "probably fine anyway." This means **every real Selcom
delivery is, and is meant to be, rejected** — that's an accepted,
deliberate tradeoff, not a bug: an early version of this fix instead let
an unsigned delivery trigger a live Selcom lookup and credit only from
that; this was reverted in favor of unconditional rejection because
*processing* an unsigned delivery at all — even without trusting its
claims — was judged an unacceptable attack surface for something that
moves money. **This endpoint must never be changed to accept an unsigned
delivery in production.** If Selcom's account team ever confirms a real
signing scheme, wire it into `verify_webhook_signature()` and the
rejection stays exactly as strict.

The only bypass is local development: a request carrying header
`X-Internal-Test-Secret` matching `SELCOM_CHECKOUT_WEBHOOK_TEST_SECRET`
is accepted **only when `ENVIRONMENT=development` too** — both
conditions are required, and a real Railway deployment's `ENVIRONMENT`
is never `development`, so this can't be enabled in production by
misconfiguring the test secret alone. See `Settings.selcom_checkout_webhook_test_secret`'s
docstring (`apps/api/app/config/settings.py`).

**Given the above, real Selcom Checkout traffic never credits via this
endpoint at all.** What actually keeps merchant wallets credited:

- `app/services/checkout_reconciliation.py::reconcile_pending_checkout_collections`
  — a backend-initiated sweep on a timer (see "Scheduled reconciliation"
  below), never triggered by anything inbound.
- The manual `POST /v1/merchant/collections/{id}/refresh-status` /
  `POST /v1/admin/collections/{id}/refresh-status` endpoints.

Both call Selcom's order-status API directly with our own authenticated
credentials — the same underlying call
(`_query_and_complete_checkout_collection` in checkout_reconciliation.py)
— and, even then, only credit once the amount Selcom reports back is
cross-checked against what the collection actually expects
(`_amount_and_currency_agree`). Even a delivery that *does* pass
signature verification (the dev-only bypass path, or a future real
Selcom signature) still goes through this same live, cross-checked
lookup rather than trusting its own claimed fields directly — see
`resolve_checkout_collection_from_webhook_hint`'s docstring.

## Scheduled reconciliation

`Settings.selcom_checkout_reconcile_interval_seconds` (env
`SELCOM_CHECKOUT_RECONCILE_INTERVAL_SECONDS`, default `0` = disabled) —
when set to a positive number, `app/main.py`'s `lifespan` starts an
in-process `asyncio` loop that calls `reconcile_pending_checkout_collections`
on that interval for the lifetime of the process. No separate
cron/worker service required; safe to run on multiple API replicas
concurrently (crediting is idempotent — only the first call to observe
"successful" for a given collection ever posts a ledger entry). A single
failed sweep (e.g. Selcom or the DB briefly unreachable) is logged and
never kills the loop — the next tick tries again. **Set a real value
(e.g. `120`) in Railway** to actually enable auto-crediting; leave at `0`
for local dev/tests, where no background task should run unexpectedly.

**Confirming it's actually running, from Railway logs**: search for
`checkout_reconciliation_scheduler_started` (logged once at boot, with
the configured interval) and `checkout_reconciliation_sweep_starting`
(logged on *every* tick, even when there's nothing pending — deliberately,
so "is this running at all" doesn't require waiting for a real pending
collection to show up). If neither ever appears despite
`SELCOM_CHECKOUT_RECONCILE_INTERVAL_SECONDS` being set correctly on the
right service, check `LOG_LEVEL` next (see below) before assuming the
scheduler itself is broken — an unconfigured logging level silently
drops these exact log calls without the scheduler being at fault at all.

**Logging (`LOG_LEVEL`, 2026-08-28 finding)**: before this was added,
nothing anywhere in this codebase ever configured Python's logging
system — every `logger.info()` call in the entire app (not just the
scheduler's) was silently dropped, because the root logger defaults to
`WARNING` with no handler attached. Only `.warning()`/`.error()`/
`.exception()` calls were ever visible in Railway logs. This is exactly
why the scheduler's own startup/sweep confirmation logs never appeared,
even on a deploy confirmed to be running the correct code — the
scheduler itself was very likely fine the whole time. `app/main.py::
_configure_logging` fixes this by configuring the shared `"infinity"`
parent logger (every logger in this app is named `"infinity.X"`) rather
than the root logger, specifically to avoid interfering with pytest's
own root-logger-based log capture in tests. `LOG_LEVEL` (env var,
default `INFO`) controls the level.

## Order status query

```
GET /v1/checkout/order-status?order_id={order_id}
Signed-Fields: order_id
```

`get_order_status()` on `SelcomCheckoutHTTPClient` — read-only, never
changes anything on Selcom's side. Used by both manual refresh
endpoints. Response `data[0].payment_status` is the same authoritative
field the webhook carries; `data[0].transid`/`channel`/`reference` are
folded into the collection the same way a webhook delivery would be.

## Known issue: Selcom's own payment_gateway_url returns "Page Not Found"

**As of 2026-08-23, every hosted-checkout redirect is broken on Selcom's
side, not ours.** `create-order-minimal` succeeds every time
(`resultcode=000`, `result=SUCCESS`), and the returned
`payment_gateway_url` decodes to a well-formed
`https://tza.selcom.online/paymentgw/checkout/<token>` URL — but opening
that exact URL (a plain browser GET, nothing submitted) returns Selcom's
own "Page Not Found" page, served with HTTP 200.

This has now been confirmed **eight separate times**, across two live
customer-facing tests (`S20690637508`, `S20691093139`) and a full
six-variant diagnostic sweep run 2026-08-23
(`scripts/diagnose_selcom_checkout_gateway_url.py`) that isolated every
optional field this client can send:

| Variant | Optional fields sent | Result |
|---|---|---|
| `bare-minimum` | none | Page Not Found |
| `webhook-only` | `webhook` (today's real production behavior) | Page Not Found |
| `redirect-cancel-only` | `redirect_url`, `cancel_url` | Page Not Found |
| `expiry-future-only` | `expiry=3600` | Page Not Found |
| `remarks-only` | `buyer_remarks`, `merchant_remarks` | Page Not Found |
| `all-optional-combined` | all of the above except `expiry` | Page Not Found |

Every single response body was byte-identical (4765 bytes) regardless of
what was sent — the strongest possible evidence that **no field this
client sends or omits changes the outcome**. This rules out:

- Optional URL fields (`redirect_url`/`cancel_url`/`webhook`) causing it
  — confirmed absent in `bare-minimum` and present in three other
  variants, all identical.
- `expiry` causing it — confirmed absent in every other variant and
  present in exactly one, no difference. (Its exact format —
  seconds-from-now vs. Unix epoch — is still unconfirmed by Selcom's
  docs, but moot: even the "safe" omitted case fails identically.)
- Our own base64 decode pipeline — independently confirmed correct:
  `parse_create_order_minimal_response()` calls `base64_decode_url()`
  exactly once (see `test_base64_decode_url_decodes_exactly_once_never_double_decoded`
  in `tests/test_selcom_checkout_parsing.py`), the decoded value in the
  database matches byte-for-byte what a fresh `curl` fetch of the same
  URL receives, and the frontend does a single, unmodified
  `window.location.href = payment_gateway_url` — no
  `encodeURIComponent`/`decodeURIComponent`, no Next.js route
  interception (a raw `window.location` assignment bypasses the Next.js
  router entirely), no relative-URL conversion.
- Signed-Fields/signing mismatch — every variant's Signed-Fields header
  is asserted (in `test_signed_fields_header_contains_only_fields_actually_in_the_body`)
  to contain exactly the fields present in the body, in the same order;
  and every variant still got a genuine `resultcode=000` SUCCESS from
  Selcom, meaning signing was accepted every time — the failure happens
  strictly *after* order creation, on Selcom's own hosted checkout web
  app, not at the API layer.

**One real, unconfirmed lead**: `SELCOM_CHECKOUT_VENDOR`'s configured
value starts with `SB` (confirmed via the diagnostic script's masked
output, `SB******93`) — worth checking directly with Selcom whether this
vendor code was ever actually provisioned for a live hosted-checkout web
deployment, versus being a business/API-only or sandbox-flavored vendor
code that the API layer accepts but the separate hosted checkout web app
doesn't recognize. This is a real, non-guessed observation, not a fix —
nothing in this codebase was changed based on it, per the instruction not
to make production changes without evidence a fix actually works.

**No code changes were made as a result of this investigation** — the
live evidence conclusively points away from our implementation, so per
the explicit instruction not to change production logic without evidence
a fix works, none was attempted. The next step is external: confirm with
Selcom support (using the order references above as evidence) whether
hosted checkout is actually deployed and reachable for this account's
vendor code.

**Update 2026-08-23**: the account's vendor code was confirmed by the
user to be linked to a live checkout deployment — ruling out the one
lead above. A further check strengthened the evidence rather than
resolving it: the `qr` field's embedded `https://selcom.link/<id>` short
link (Selcom's own official redirector, not something we constructed)
was fetched directly and confirmed to `302`-redirect to the *exact same*
`payment_gateway_url` token stored for that order — two independent
paths Selcom itself generates agree on the destination, and that
destination still returns "Page Not Found". This is now escalated to
Selcom support directly; the specific ask is for them to generate a test
order themselves (this vendor code) and confirm whether they can open
the resulting checkout page on their end.

**Interim measure while this is blocked (2026-08-23, TEMPORARY)**: both
customer-facing payment (the public payment-link page) and the Merchant
Portal's "Request Collection" now use wallet-push again
(`app/services/wallet_push.py::execute_wallet_push_for_payment_link` /
`execute_wallet_push_collection`, `POST /public/payment-links/{slug}/pay/wallet-push`,
`POST /v1/merchant/collections/wallet-push`) instead of hosted checkout —
fully working, proven with two real successful payments earlier this
session. The hosted-checkout backend endpoints
(`POST /public/payment-links/{slug}/pay/checkout`,
`POST /v1/merchant/collections/hosted-checkout`) are untouched and ready
to swap back into the frontend the moment Selcom confirms a fix — see
the module docstrings on the wallet-push functions above for exactly
what to revert.

## Dynamic QR

`POST /public/payment-links/{slug}/collect` with `{"method": "DYNAMIC_QR"}`
now routes through this same confirmed Checkout product
(`app/services/dynamic_qr.py`), not the older, explicitly-unconfirmed
placeholder client (`app/services/selcom/`) it used before 2026-08-22.
There is no wallet-payment push step for this method — the order's own
`payment_gateway_url` (Selcom's hosted payment page) is what the customer
scans or opens directly; the frontend QR-encodes that URL client-side
(`components/payment-link/qr-code.tsx`) and also offers it as a plain
link for desktop users with no camera. Resolution, idempotency, and
merchant crediting all go through the exact same
`checkout_reconciliation.py` pipeline as wallet-push — a Dynamic QR
collection is indistinguishable from a wallet-push one once it reaches
`complete_checkout_collection_once()`.

Selcom's `create-order-minimal` requires a `buyer_phone` even for this
method, despite the customer never being asked for one on this page
(the whole point of QR is scanning without typing anything) — resolved
by using the payment link's own `customer_phone` if the merchant set
one, else a well-formed placeholder (`255700000000`, never dialed —
nothing in this flow pushes to it) — mirrors the existing placeholder
`buyer_email` convention. `collections.customer_phone` itself only ever
stores the real phone or `null`, never the placeholder.

The Merchant Portal's own self-service "Create Collection" form
(`POST /v1/merchant/collections/dynamic-qr`) is a **separate feature**
(an authenticated merchant requesting a collection on demand, not a
customer paying a public link) and still uses the old placeholder client
— out of scope here, unchanged.

## Manual refresh (independent of the webhook)

```
POST /v1/merchant/collections/{id}/refresh-status   (merchant-scoped)
POST /v1/admin/collections/{id}/refresh-status       (Super Admin, any merchant)
```

Both call `get_order_status()` then apply the exact same completion
logic the webhook uses. This is a fully independent path — even if the
webhook signature inference above turns out wrong and every real
delivery gets rejected, a merchant or admin can still reconcile a
payment by clicking refresh. Never double-credits (see idempotency
below).

## Completion rule — when a merchant actually gets credited

A collection is only ever resolved `"successful"` — and therefore only
ever credited — when **all three** agree:

```
result      == "SUCCESS"
resultcode  == "000"
payment_status == "COMPLETED"
```

`payment_status == "COMPLETED"` alone, without `result`/`resultcode`
agreeing, is **not** credited and **not** marked failed — that
combination is treated as corrupted/suspicious input, not a normal
outcome, and the safe response is to leave the collection `"processing"`
(unresolved, still refreshable) rather than guess. This mapping lives in
one place: `app/services/checkout_reconciliation.py::map_checkout_status_to_provider_status`.

### Status mappings

| Selcom `payment_status` | Internal status | Credited? |
|---|---|---|
| `COMPLETED` (+ result/resultcode agree) | `successful` | **Yes**, unless the self-payment/own-till rule holds it — see below |
| `COMPLETED` (result/resultcode disagree) | `processing` | No — stays open |
| `PENDING` | `processing` | No |
| `INPROGRESS` | `processing` | No |
| `CANCELLED` | `failed` | No |
| `USERCANCELLED` | `failed` | No |
| `REJECTED` | `failed` | No |
| `REVERSED` | `failed` (or triggers a real reversal if already credited — see below) | No |
| *(no payment_status yet — bare wallet-payment result)* | falls back to `resultcode`: `000`→successful, `111`/`927`→processing, `999`→processing (ambiguous, never a silent failure), else→failed | per mapping |

Free-text `message`/`result` content is also checked for reversal
wording (`"own till"`, `"unsuccessful"`, `"reversed"`, `"reversal"`) —
see "Reversal after credit" below. This exists because the live incident
that motivated it carried its true outcome only in that free-text field
("Payment unsuccessful. You are trying to pay into your own till"), not
in a clean coded status.

## Reversal after credit (2026-08-23 incident and fix)

**What happened**: a wallet-push collection resolved `COMPLETED` and was
credited to the merchant wallet — Merchant Portal and Super Admin both
showed it `successful`. Selcom then actually reversed the underlying
M-Pesa payment ("Payment unsuccessful. You are trying to pay into your
own till"), but nothing in this codebase could act on that later signal:
`resolve_collection()` treats any collection that's no longer
`"processing"` as already resolved and silently no-ops, so a second
delivery/refresh reporting the true outcome changed nothing. The merchant
stayed credited for money that was never actually settled.

**A wallet-push (or hosted-checkout) API success is never final payment
success** — Selcom's own rule: a success response from wallet-payment
only means the push request was *accepted*, not that the customer's
wallet was finally debited or that funds are settled. This codebase
already never credited on the push response itself (see the flow diagram
above — `"processing"` until `complete_checkout_collection_once()`
resolves it); the gap was specifically a *second, later* signal for an
already-`"successful"` collection.

**The fix**: `complete_checkout_collection_once()` now checks, before
calling `resolve_collection()`, whether the collection is already
`"successful"` and the new signal indicates failure/reversal
(`payment_status == REVERSED`, any terminal-failure `payment_status`, or
a reversal-worded `message`). If so, it routes to
`app/services/collections.py::reverse_successful_collection()` instead —
a separate function, not a tweak to `resolve_collection()`, since
`resolve_collection()`'s own idempotency guard is exactly what made this
unreachable.

`reverse_successful_collection()`:

1. Posts **reversing ledger entries** via the new
   `app/services/ledger.py::reverse_collection_entries()` — the exact
   opposite of `post_collection_entries()`, against the *same*
   `transaction_id` (mirrors the existing
   `reverse_disbursement_entries()` pattern for withdrawals). **Never
   deletes or edits the original entries** — only ever adds reversing
   ones, so the full history stays auditable.
2. If the merchant no longer has the funds available (already withdrawn),
   the database's own atomic guard rejects the reversal
   (`InsufficientBalanceError`) rather than driving the wallet negative.
   This is caught, not propagated: the collection still moves to
   `"reversed"` (so no UI keeps claiming success), and a **CRITICAL**
   admin notification is raised naming the shortfall for manual recovery.
3. Marks the collection `"reversed"` and the linked `transaction`
   `"reversed"` (when the ledger reversal actually succeeded).
4. Reopens a linked `payment_link` (`PAID` → `ACTIVE`) and/or `invoice`
   (reduces `amount_paid`, recomputes `SENT`/`PARTIALLY_PAID`/`PAID`) so
   the merchant can request payment again.
5. Notifies **both** the merchant (`collection_reversed`, "Payment
   reversed") and Super Admin (`collection_reversed`, plus the manual-
   recovery detail when relevant).
6. Enqueues a `collection.reversed` outbound webhook event.

Idempotent by construction: guarded on `status == "successful"`, so a
retried/duplicate reversal signal for an already-`"reversed"` collection
is a safe no-op — it can't double-reverse or drive the wallet further
negative.

## Self-payment / own-till risk (pre-credit hold)

The live incident's own root cause on Selcom's side was a **self-payment
into the merchant's own till** — Selcom's own message said exactly that.
As defense in depth (Selcom is still the authoritative decision-maker
here), `resolve_collection()` now checks — **before** crediting, not
after — whether the payer's phone matches the merchant's own
`contact_phone` (via the new `SELF_PAYMENT_OWN_TILL` fraud rule,
`app/services/fraud_monitoring_service.py::check_self_payment_risk()`,
last-9-digit normalized comparison so `255…`/`0…`/bare formats all
match).

If it matches, the collection is held: status becomes `pending_review`
(a new value added to `collections.status`'s CHECK constraint — see
`supabase/migrations/20260823030000_collection_reversal_and_self_payment_review.sql`),
no ledger entries are posted, no `payment_link`/`invoice` is marked
`PAID`, and a `CRITICAL` fraud alert is raised (visible in Super Admin's
existing risk-alerts screen, same review/clear flow as every other fraud
rule). The merchant sees "Payment pending review" — never `"successful"`
— until a Super Admin clears the alert.

Clearing a `SELF_PAYMENT_OWN_TILL` alert (`PATCH
/v1/admin/risk-alerts/{id}/status` with `status: "CLEARED"`) is the one
place that actually credits it — `app/routers/admin_risk.py` calls
`app/services/collections.py::finalize_pending_review_collection()`,
which posts the ledger entries, marks the collection `"successful"`, and
notifies the merchant, exactly as if it had resolved normally. This rule
never blocks a payment forever — it only requires one review step before
funds become available, and clearing/finalizing is idempotent (only acts
on a collection still `pending_review`).

## Delayed clearance (reserved, not yet enforced)

`COLLECTION_AUTO_SETTLE_ENABLED` and `COLLECTION_CLEARANCE_DELAY_MINUTES`
(`app/config/settings.py`) exist as reserved configuration for a future
"hold every collection briefly before crediting, then recheck" gate.
**Not wired to anything yet** — this codebase has no background
worker/cron infrastructure, and half-wiring a delay with nothing to act
on it would be worse than not having one. The two safety nets that are
actually active today are the reversal handling and the self-payment
hold described above; see `docs/ledger-reconciliation.md` for the full
reasoning and what a real implementation would need.

## Shared completion / idempotency

`app/services/checkout_reconciliation.py::complete_checkout_collection_once()`
is the one function both the webhook and both refresh endpoints call.
For a collection still `"processing"`, it doesn't reimplement crediting —
it reuses `app/services/collections.py::resolve_collection()`, which is
idempotent (a no-op once a collection is no longer `"processing"`),
posts ledger entries exactly once, and marks a linked `payment_link`
`PAID` and a linked `invoice` `PAID`/`PARTIALLY_PAID` (unless the
self-payment/own-till rule holds it in `pending_review` instead — see
above). For a collection that's already `"successful"` and receives a
new failure/reversal signal, it routes to `reverse_successful_collection()`
instead — see "Reversal after credit" above.

What `complete_checkout_collection_once()` adds on top:

1. Always refreshes audit fields (`provider_reference`, `provider_transid`,
   `provider_result`, `provider_resultcode`, `provider_payment_status`,
   `channel`, `raw_response`) — even on a repeat call, so a later
   delivery's data is never lost even once the outcome can't change
   anymore.
2. Captures whether the collection was still `"processing"` **before**
   calling `resolve_collection()` — this is what stops a duplicate
   webhook/refresh from re-notifying the merchant or re-marking the
   linked `checkout_orders` row `"completed"`, even though the ledger
   itself was already safe via `resolve_collection()`'s own guard.
3. On a genuine (not duplicate) success: marks the linked
   `checkout_orders` row `"completed"` and sends a `payment_received`
   notification to the merchant.

Both `provider_transid`-based matching (the precise key — unique per
wallet-payment attempt) and a `checkout_orders.order_id` fallback exist
(`find_collection_by_transid` / `find_collection_by_order_id`), so a
delivery missing one still resolves via the other.

## Merchant/admin/customer visibility

- **Merchant portal** — `GET /v1/merchant/collections` now includes
  `checkout_order_id`, `provider_transid`, `provider_resultcode`,
  `provider_result`, `provider_payment_status`, `channel`,
  `failure_reason`.
- **Super Admin** — `GET /v1/admin/collections` additionally surfaces
  `order_id` (joined from the linked `checkout_orders` row).
- **Customer payment page** — polls
  `GET /public/payment-links/{slug}/collections/{collection_id}/status`,
  which maps the collection's status to one of: `pending`, `completed`,
  `failed`, `cancelled`, `user_cancelled`, `rejected` — never the
  payment link's own status (which only ever reflects `PAID` once, with
  no per-attempt detail).

## How to confirm a webhook actually arrives

1. Check `selcom_webhook_events` for a row where `provider =
   'selcom_checkout'` — its existence alone confirms delivery reached
   this backend. `signature_valid` reads `false` on every row (Selcom
   never signs this callback — see "Signature verification" above), and
   `status='failed'` with `processing_error='invalid or missing
   signature'` is the **expected, permanent** outcome for real Selcom
   traffic — it does not mean anything is broken; it means the fail-closed
   policy is working as designed.
2. Check the collection's `status` — `successful` means it was credited,
   via either the scheduled sweep or a manual refresh (never via this
   webhook, for real Selcom traffic); `processing` means neither has
   resolved it yet.
3. Check the merchant's ledger/wallet balance actually moved by the net
   amount (gross minus platform fee) — the definitive confirmation that
   crediting happened, not just that a row changed status.
4. The safe log line (`selcom_checkout webhook received: order_id=...
   transid=... reference=... payment_status=...`, `app/routers/
   webhooks.py`) is visible in Railway's logs the instant a delivery
   lands, before signature verification even runs — useful to confirm
   Selcom is still delivering at all, even though it always gets 401'd.

**How a real payment actually gets credited today**: the scheduled sweep
(`SELCOM_CHECKOUT_RECONCILE_INTERVAL_SECONDS` set to a positive value —
see "Scheduled reconciliation" above) or a manual refresh —
`POST /v1/merchant/collections/{id}/refresh-status` or
`POST /v1/admin/collections/{id}/refresh-status` — both query Selcom
directly via `get_order_status()` and apply the identical completion
logic, entirely independent of whether a webhook ever arrived at all. If
refresh also never resolves a collection past `PENDING` after a customer
has genuinely paid, that's a signal to contact Selcom/support directly to
confirm their systems actually processed the payment (ask for their own
transaction logs for a specific `order_id`/`transid`).

## Known gaps / what to verify once real traffic exists

- **A real webhook delivery finally arrived on 2026-08-22** (order
  `ORD-20260822-ED25554E`, transid `DHNAZ2ATGL`) — the first ever,
  after both root causes above were fixed and `SELCOM_CHECKOUT_WEBHOOK_URL`
  was set in Railway. Good news: every payload field matched exactly
  what this codebase already expected — `result`, `resultcode`,
  `order_id`, `transid`, `reference`, `channel`, `amount`, `phone`,
  `payment_status` all present and correctly shaped. **Bad news: it was
  rejected** — `signature_valid=False`, and the stored `signature`
  column came back completely empty, meaning the `Digest` header (and,
  it's presumed, `Timestamp`/`Digest-Method`/`Signed-Fields` too) were
  **not present at all** in Selcom's actual request. The inferred
  scheme — mirroring this product's confirmed *outbound* signing
  headers onto the inbound direction — is confirmed wrong: either
  Selcom uses different header names for this callback, or doesn't sign
  it at all. Resolved via manual refresh instead (worked immediately,
  no issue).
- **Fixed the same day**: `selcom_webhook_events` now has a
  `raw_headers` column (every header *name* the delivery carried, plus
  the non-secret `Timestamp`/`Digest`/`Digest-Method`/`Signed-Fields`
  values when present — never `Authorization`/`Cookie`), and a safe log
  line captures the same at delivery time. The first delivery predates
  this fix, so its actual header set is lost.
- **RESOLVED (root cause) 2026-08-27, confirmed against 5 more real
  deliveries** (`raw_headers` inspected directly): Selcom's Checkout
  webhook carries **no signature at all** — the full header set on every
  one of the 5 was just `accept`, `accept-encoding`, `content-length`,
  `content-type`, `host`, `user-agent: SelcomPay 1.0`, plus Railway's own
  proxy headers (`x-forwarded-*`, `x-railway-*`, `x-real-ip`,
  `x-request-start`). No `Digest`/`Digest-Method`/`Timestamp`/
  `Signed-Fields` in any casing. This wasn't a header-name guessing
  problem to keep iterating on — Selcom simply doesn't sign this
  callback.
- **Policy decision, same day**: a first fix let an unsigned delivery
  still trigger a live, authenticated Selcom lookup and credit only from
  that answer (never the payload's own claims) — closing the spoofing
  risk while keeping auto-crediting working. This was explicitly
  reconsidered and reverted in favor of stricter policy: production now
  rejects (401) any delivery that isn't signature-verified,
  unconditionally, with no exception — see "Signature verification"
  above. Real auto-crediting now comes exclusively from
  `reconcile_pending_checkout_collections`'s scheduled sweep (backend-
  initiated, never triggered by anything inbound) and manual refresh.
  `verify_webhook_signature()` and its `_SUPPORTED_DIGEST_METHODS`
  machinery are left in place (harmless, still computes/stores
  `signature_valid=false` for audit) rather than deleted, in case Selcom
  ever does start signing this callback in the future — see the module's
  own docstring for what to change if that happens.
- `get-order-status`'s exact response field names came from the task
  brief, not an independently re-verified live call the way
  `create-order-minimal` was — see
  `apps/api/app/services/selcom_checkout/parsing.py`'s module docstring.
  (The live test on 2026-08-22 did confirm `payment_status`, `transid`,
  `channel` — `MPESA-TZ` — and `reference` all come back exactly as
  expected.)
- `collections.method` stores `"STK_PUSH"` for every wallet-push
  collection regardless of which real channel Selcom actually used —
  a labeling simplification (Selcom's wallet-payment call takes no
  channel parameter at all), not a claim about the real channel. The
  real channel Selcom reports is kept separately in `collections.channel`.
