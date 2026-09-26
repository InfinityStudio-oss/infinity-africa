# API Documentation

FastAPI auto-generates interactive docs while `apps/api` is running:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI schema: `http://localhost:8000/openapi.json`

A role-gated summary of the same information is also served at
`GET /v1/merchants/{merchant_id}/developer-docs` (see "Developer docs" below).

## Response envelope

Every `/v1` response — success or error — has the same shape:

```json
// success
{ "success": true, "data": { ... }, "meta": null }

// paginated list
{ "success": true, "data": [ ... ], "meta": { "page": 1, "page_size": 20, "total": 42, "total_pages": 3 } }

// error
{ "success": false, "error": { "code": "not_found", "message": "...", "details": null } }
```

`GET` list endpoints accept `?page=1&page_size=20` (`page_size` max 100).

## Authentication

Two independent schemes, enforced per-endpoint by `apps/api/app/auth`:

- **Dashboard (Supabase Auth JWT)** — `Authorization: Bearer <access_token>`.
  Used by `apps/web`. Role comes from `merchant_users`/`platform_admins`,
  never from the token's own claims/metadata.
- **API key** — `X-API-Key: <secret key>` or
  `Authorization: Bearer <secret key>`. For a merchant's own backend calling
  InfinityPay directly. Accepted alongside a JWT on the handful of endpoints
  marked "dashboard or API key" below (creating a payment link, invoice,
  collection, or disbursement); everything else is dashboard-only.

### Key pairs: public and secret

Each key is a **pair**, created together in the Merchant Portal under API
Credentials:

| | Sandbox | Live |
|---|---|---|
| Public key | `pk_test_…` | `pk_live_…` |
| Secret key | `sk_test_…` | `sk_live_…` |

**The secret key authenticates requests. The public key never does.** The
public half identifies a key and its environment — safe to keep in
configuration, show in a dashboard, or quote to support. Sending it as a
credential is refused with a message saying so, rather than a generic
"invalid key", because the usual cause is wiring up the wrong half.

**The secret is shown exactly once**, in the response that creates it. Only
its SHA-256 hash is stored, so nobody can retrieve it later — not support,
not Super Admin, not us. Lose it and you rotate.

Keys issued before pairs existed (`inf_…`) keep working unchanged and have
no public half. Rotating one issues a full pair.

### This is not your Merchant ID

The permanent **27-series Merchant ID** identifies your business inside
InfinityPay — for support, receipts, invoices and reconciliation. It is not
a credential, it never expires, and it must never be used as an API secret.
An API key is per-integration and revocable; the Merchant ID is neither.

### Security rules

- Secret keys belong on a **server** you control. Never in browser
  JavaScript, a mobile app binary, a git repository, a screenshot, or a
  support ticket.
- Keep sandbox and live configuration separate.
- Revoke immediately if a key is exposed — rotation issues a new pair and
  revokes the old one in the same step.
- Enable the IP allowlist on live keys if your backend has stable
  addresses.

A few endpoints require neither — the public checkout endpoints, and the
provider webhook — see the tables below. The provider webhook instead
verifies an HMAC signature (`X-Selcom-Signature`, see "Mock payment
provider" below).

Most resources are nested under `/v1/merchants/{merchant_id}/...`, which
resolves the caller's access from that path segment. **Payment links,
invoices, disbursements, and collection initiation are flat**
(`/v1/payment-links`, `/v1/invoices`, `/v1/disbursements/{method}`,
`/v1/collections/{method}` — no merchant_id in the path) — `merchant_id` is
a field in the request body instead (a required query parameter for the
flat `GET` list endpoints), checked against the caller (API key's own
merchant, or the JWT user's membership) once it's known. See
`get_authenticated_caller`/`authorize_merchant_action` in `app/auth` vs.
`get_merchant_actor`/`require_role` used everywhere else. Reading
collections back stays nested (`/v1/merchants/{id}/collections`) —
unaffected, and unrelated to this split. Disbursement approval/rejection
(`/v1/disbursements/{id}/approve`, `.../reject`) is flat too, but
super-admin-only and unrelated to the merchant-auth split above.

## Idempotency

`POST /v1/payment-links`, `/v1/collections/{method}`, `/v1/disbursements/{method}`,
and the two public `.../collect` endpoints all require an `Idempotency-Key`
header. Retrying the same key + endpoint + request body replays the
original response instead of double-processing (double-charging, or — for
payment links — creating a second link); reusing the key with a
*different* body is rejected with `409 idempotency_key_reused`.

## Mock payment provider

No live Selcom integration exists yet (see `docs/selcom-live-go-live.md`
for the go-live procedure once the backend is deployed and IP-whitelisted).
Every collection/disbursement runs through `MockSelcomClient`
(`apps/api/app/services/selcom/mock_client.py`), behind the same
`PaymentProvider` interface (`app/services/selcom/client.py`) the live
client (`app/services/selcom/live_client.py`) implements —
`initiate_collection`/`generate_dynamic_qr` (fast ack), `check_collection_status`
(simulates the customer-approval delay + a configurable failure rate:
`MOCK_PROVIDER_FAILURE_RATE`, `MOCK_PROVIDER_LATENCY_SECONDS`, see
`.env.example`), and `initiate_disbursement`.

Two different call patterns sit on top of that interface:

- **`/v1/collections/{method}`** (this doc's "Implement mock collection
  APIs" endpoints) call `initiate_collection`/`generate_dynamic_qr` only,
  and return immediately with the collection `status: "processing"` — a
  real push/QR payment doesn't resolve within the same request; the
  customer still has to approve it. Resolution happens later via
  `POST /v1/webhooks/selcom` (`resolve_collection_from_callback`), which is
  where a real Selcom callback would land.
- **`POST /public/payment-links/{public_slug}/collect`** (payment-link
  checkout, where a customer is watching the page — including an invoice's
  generated "Pay Now" link, see below) calls `check_collection_status`
  immediately afterward and resolves synchronously in the same response —
  see `execute_collection` in `app/services/collections.py`.

Either way, resolution always goes through the same `resolve_collection()`:
update the collection + its transaction in place (never a second
transaction row), post ledger entries (and update account balances) on
success, apply the result to a linked payment_link/invoice, and enqueue a
webhook event.

## Webhook processing (`POST /v1/webhooks/selcom`)

Where a real Selcom callback would land, resolving a `collection` or
`disbursement` left `processing`. Request handling, in order:

1. **Raw body capture** — the exact bytes are read via `Request.body()`
   (not FastAPI's automatic Pydantic parsing), so signature verification
   runs against precisely what was sent.
2. **Signature verification** — `X-Selcom-Signature` is checked against an
   HMAC-SHA256 of the raw body using `SELCOM_WEBHOOK_SECRET`
   (`app/services/selcom/webhooks.py`; no live Selcom scheme exists yet, so
   this is a mock in the same shape a real one would take).
3. **Storage + idempotency** — every delivery is logged to
   `selcom_webhook_events` before anything else happens, keyed by
   `(provider, event_id)`. A duplicate delivery (same `event_id`) short-
   circuits with `{"status": "duplicate"}` instead of reprocessing; an
   invalid signature is stored `status: 'failed'` and rejected `401`.
4. **Dispatch** — `event_type` is one of `collection.success`,
   `collection.failed`, `disbursement.success`, `disbursement.failed`
   (Selcom only ever reports on its own domain events); routed by
   `provider_reference` to `resolve_collection_from_callback` or
   `resolve_disbursement_from_callback`, same as before.

`payment_link.paid` and `invoice.paid` are *not* things Selcom sends — they're
outbound events InfinityPay enqueues (to `webhook_events`) as a consequence of
resolving a collection linked to a payment_link/invoice.

## Invoices

An invoice (`invoice_number` generated automatically, `INV-YYYYMMDD-XXXXXXXX`)
carries its own line items (`invoice_items`, `subtotal` = sum of
`quantity * unit_price`) and is `DRAFT` until sent. It has no public
checkout page of its own — `POST /v1/invoices/{id}/payment-link` generates
(or, while the previous one is still `ACTIVE`, reuses) an ordinary
`payment_links` row for the remaining balance (`total_amount - amount_paid`),
which the merchant shares with the customer; the customer pays it exactly
like any other payment link, at `/public/payment-links/{public_slug}`. Only
a `SENT`/`PARTIALLY_PAID`/`OVERDUE` invoice can generate one — a `DRAFT`
hasn't been sent yet, and `PAID`/`CANCELLED` have nothing left to collect.

Invoice status is linked to payment status through that same link: when the
generated payment link's collection resolves successfully,
`services/collections.py`'s `_apply_collection_success` looks up whether
any invoice references that `payment_links.id` (via `invoices.payment_link_id`)
and, if so, credits `amount_paid` and moves the invoice to `PARTIALLY_PAID`
or `PAID` — the same function that already does this for a collection
carrying `invoice_id` directly.

## Disbursements

A payout from a merchant's InfinityPay balance to `SELCOM_PESA`/`MOBILE_MONEY`
(a phone number) or `BANK_ACCOUNT` (destination_identifier is the account
number, `bank_name` required). `POST /v1/disbursements/{method}` validates
available balance up front — `409 insufficient_balance` if `amount` exceeds
the merchant's current `merchant_wallet` ledger balance — before creating
anything. Status is one of `PENDING` (created; `PROCESSING`/`SUCCESS`/
`FAILED` if at or above `disbursement_approval_threshold`, held here for a
super admin to approve/reject instead), `PROCESSING` (balance reserved,
provider call in flight), `SUCCESS`, `FAILED` (provider declined — its
reservation was reversed), or `REVERSED` (defined for reversing an
already-`SUCCESS` payout later; no endpoint triggers it yet).

Reservation happens *before* the provider is called, not just on success:
the same amount that was validated is immediately debited from the wallet
(`services/ledger.py`'s `post_disbursement_entries`, via the
`post_ledger_entries` RPC — see "Webhook processing" above), so a second,
concurrent disbursement can't also spend it. If the provider then declines,
`reverse_disbursement_entries` posts the offsetting entries against the
*same* transaction, netting it to zero. The RPC's own balance check (not
just the up-front one) is what makes this race-proof under concurrent
requests.

## Endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/health` | none | Service health check |
| GET | `/v1/system/selcom-config-status` | super admin | Safe booleans only (which Selcom vars are set, feature flags, mock mode) — never secret values. See `docs/backend-setup.md`'s "Selcom integration on Railway" section |
| POST | `/v1/merchants` | super admin | Onboard a merchant |
| GET | `/v1/merchants` | super admin | List merchants |
| GET | `/v1/merchants/{id}` | member or super admin | Get a merchant |
| PATCH | `/v1/merchants/{id}` | MERCHANT_ADMIN | Update profile fields |
| PATCH | `/v1/merchants/{id}/status` | super admin | Update status/kyc_status |
| POST | `/v1/merchants/{id}/api-keys` | MERCHANT_ADMIN, DEVELOPER | Create an API key (plaintext shown once) |
| GET | `/v1/merchants/{id}/api-keys` | MERCHANT_ADMIN, DEVELOPER | List API keys |
| DELETE | `/v1/merchants/{id}/api-keys/{key_id}` | MERCHANT_ADMIN, DEVELOPER | Revoke an API key |
| POST | `/v1/payment-links` | dashboard or API key | Create a payment link (`merchant_id` in the body; Idempotency-Key required) |
| GET | `/v1/payment-links/{link_id}` | MERCHANT_ADMIN, MERCHANT_STAFF | Get a payment link (reports `EXPIRED` if `expires_at` has passed) |
| PATCH | `/v1/payment-links/{link_id}/cancel` | MERCHANT_ADMIN, MERCHANT_STAFF | Cancel a payment link (idempotent; rejects an already-`PAID` link) |
| GET | `/public/payment-links/{public_slug}` | **none (public)** | View a link by its public slug — always 200 for a slug that exists, `status` reflects ACTIVE/EXPIRED/CANCELLED/PAID |
| POST | `/public/payment-links/{public_slug}/collect` | **none (public)** | Pay it — `409` if not ACTIVE (Idempotency-Key required) |
| POST | `/v1/invoices` | dashboard or API key | Create an itemized invoice (`merchant_id` in the body; `invoice_number` generated automatically) |
| GET | `/v1/invoices` | dashboard or API key | List invoices (`merchant_id` required as a query param) |
| GET | `/v1/invoices/{invoice_id}` | dashboard or API key | Get an invoice |
| PATCH | `/v1/invoices/{invoice_id}` | dashboard or API key | Edit an invoice — only while `DRAFT`; recomputes totals if `items`/`tax_amount`/`discount_amount` change |
| POST | `/v1/invoices/{invoice_id}/send` | dashboard or API key | `DRAFT` → `SENT` |
| POST | `/v1/invoices/{invoice_id}/payment-link` | dashboard or API key | Generate (or reuse an already-`ACTIVE`) "Pay Now" payment link for the remaining balance |
| PATCH | `/v1/invoices/{invoice_id}/cancel` | dashboard or API key | Cancel an invoice (idempotent; rejects an already-`PAID` invoice) |
| POST | `/v1/collections/ussd-push` | dashboard or API key | Initiate a USSD push collection — always returns `status: "processing"` (Idempotency-Key required) |
| POST | `/v1/collections/stk-push` | dashboard or API key | Same, via an STK push (Idempotency-Key required) |
| POST | `/v1/collections/selcom-pesa-push` | dashboard or API key | Same, pushed to Selcom Pesa (Idempotency-Key required) |
| POST | `/v1/collections/dynamic-qr` | dashboard or API key | Generates a scannable QR (`qr_payload`, `qr_expires_at`) — no phone required (Idempotency-Key required) |
| GET | `/v1/merchants/{id}/collections` | MERCHANT_ADMIN, MERCHANT_STAFF | List collections (read-only) |
| GET | `/v1/merchants/{id}/collections/{collection_id}` | MERCHANT_ADMIN, MERCHANT_STAFF | Get a collection |
| POST | `/v1/disbursements/selcom-pesa` | dashboard or API key | Request a payout via Selcom Pesa — validates available balance first (Idempotency-Key required) |
| POST | `/v1/disbursements/mobile-money` | dashboard or API key | Same, to a mobile money number (Idempotency-Key required) |
| POST | `/v1/disbursements/bank-account` | dashboard or API key | Same, to a bank account (`bank_name` required) (Idempotency-Key required) |
| GET | `/v1/disbursements` | dashboard or API key | List disbursements (`merchant_id` required as a query param) |
| GET | `/v1/disbursements/{id}` | dashboard or API key | Get a disbursement |
| POST | `/v1/disbursements/{id}/approve` | super admin | Approve a held high-value payout |
| POST | `/v1/disbursements/{id}/reject` | super admin | Reject it |
| GET | `/v1/merchants/{id}/transactions` | MERCHANT_ADMIN, MERCHANT_STAFF | List the unified ledger (read-only) |
| GET | `/v1/merchants/{id}/transactions/{tx_id}` | MERCHANT_ADMIN, MERCHANT_STAFF | Get a transaction |
| GET | `/v1/merchants/{id}/webhooks` | MERCHANT_ADMIN, MERCHANT_STAFF | List webhook delivery events |
| GET | `/v1/merchants/{id}/webhooks/{event_id}` | MERCHANT_ADMIN, MERCHANT_STAFF | Get a webhook event |
| POST | `/v1/webhooks/selcom` | **none (provider, HMAC-signed)** | Resolve a collection/disbursement left `processing` |
| GET | `/v1/merchants/{id}/developer-docs` | MERCHANT_ADMIN, DEVELOPER | This page's endpoint summary, as JSON |

### Merchant Portal self-service surface (`/v1/merchant/*`)

Everything above resolves `merchant_id` from a path segment, query param, or
request body. `/v1/merchant/*` is different: the caller's own merchant is
resolved purely from their JWT (`merchant_users`, first active membership —
see `app.auth.get_own_merchant`), so the client never sends a merchant_id at
all. This is what `apps/web`'s Merchant Portal (`lib/portal/api.ts`) calls.
No super-admin bypass — a super admin with no `merchant_users` row of their
own gets `404 not_found`, the same as anyone without a membership.

Every handler delegates to the same services as the routes above (thin
wrappers, no reimplemented logic) — see `app/routers/merchant_portal.py`.

| Method | Path | Roles | Notes |
| --- | --- | --- | --- |
| GET | `/v1/merchant/me` | any member | Own merchant profile |
| GET | `/v1/merchant/overview` | any member | Aggregated dashboard: merchant profile, `total_collections`, `available_balance`, `pending_transactions`, `successful_withdrawals`, `active_payment_links`, `unpaid_invoices`, `total_fees_charged` |
| GET/POST | `/v1/merchant/payment-links` | MERCHANT_ADMIN, MERCHANT_STAFF | Create requires `Idempotency-Key` |
| GET | `/v1/merchant/payment-links/{id}` | MERCHANT_ADMIN, MERCHANT_STAFF | |
| PATCH | `/v1/merchant/payment-links/{id}/cancel` | MERCHANT_ADMIN, MERCHANT_STAFF | |
| GET/POST | `/v1/merchant/invoices` | MERCHANT_ADMIN, MERCHANT_STAFF | |
| GET | `/v1/merchant/invoices/{id}` | MERCHANT_ADMIN, MERCHANT_STAFF | |
| PATCH | `/v1/merchant/invoices/{id}` | MERCHANT_ADMIN, MERCHANT_STAFF | DRAFT-only, same as `/v1/invoices/{id}` |
| POST | `/v1/merchant/invoices/{id}/send` | MERCHANT_ADMIN, MERCHANT_STAFF | Not in the original spec — added so the portal's create-invoice "send now" flow works; DRAFT → SENT |
| POST | `/v1/merchant/invoices/{id}/payment-link` | MERCHANT_ADMIN, MERCHANT_STAFF | |
| GET | `/v1/merchant/collections` | MERCHANT_ADMIN, MERCHANT_STAFF | |
| POST | `/v1/merchant/collections/{ussd-push,stk-push,selcom-pesa-push,dynamic-qr}` | MERCHANT_ADMIN, MERCHANT_STAFF | `Idempotency-Key` required |
| GET | `/v1/merchant/withdrawals` | MERCHANT_ADMIN, MERCHANT_STAFF | "Withdrawal" is the same thing as "disbursement" everywhere else — user-facing naming only |
| POST | `/v1/merchant/withdrawals` | **MERCHANT_ADMIN only** | Deliberately stricter than `/v1/disbursements/{method}` (which also allows MERCHANT_STAFF) — single endpoint, `method` in the body, `Idempotency-Key` required |
| GET | `/v1/merchant/transactions` | MERCHANT_ADMIN, MERCHANT_STAFF | |
| GET | `/v1/merchant/transactions/{reference}` | MERCHANT_ADMIN, MERCHANT_STAFF | By the human-readable reference (`TXN-...`), not the internal UUID — new, doesn't exist on the `/v1/merchants/{id}/transactions/*` routes |
| GET/POST | `/v1/merchant/api-keys` | MERCHANT_ADMIN, DEVELOPER | |
| PATCH | `/v1/merchant/api-keys/{id}/revoke` | MERCHANT_ADMIN, DEVELOPER | Same effect as the existing `DELETE`, new verb/path |
| GET | `/v1/merchant/users/me` | any member | Own `merchant_users` row + `full_name`/`email` joined from Supabase Auth — what the portal topbar reads |
| GET/POST | `/v1/merchant/users` | **MERCHANT_ADMIN only** | POST invites a brand new Supabase Auth user (`auth.admin.invite_user_by_email`, `full_name` required) and links them to the merchant as `invited`; `409` if the email is already registered |
| PATCH | `/v1/merchant/users/{id}` | **MERCHANT_ADMIN only** | `role`/`status` only; `409` if targeting your own membership |
| POST | `/v1/merchant/users/{id}/deactivate` | **MERCHANT_ADMIN only** | Sets `status: suspended`; `409` if targeting yourself |

Collections/disbursements/transactions/webhook events are read-only via the
API — every row is written by `apps/api`'s own services (the provider
result, ledger posting, webhook enqueueing), never directly by a client.

The four `/v1/collections/{method}` bodies share `merchant_id`, `amount`
(> 0), `currency`, `customer_id`, `merchant_reference` (the *merchant's*
own order/reference, max 100 chars — distinct from `transactions.reference`,
which is InfinityPay's own), `payment_link_id`, and `description`; the three
push endpoints additionally require `customer_phone` (validated format),
which `dynamic-qr` omits entirely. `method` itself isn't a body field — the
endpoint you call is the method. When `payment_link_id` is given, it's
cross-validated: it must belong to the same `merchant_id`, be currently
`ACTIVE`, and accept the method you're calling (`409`/`422` otherwise).

## Integrating InfinityPay into another platform

For a partner adding InfinityPay as a payment option inside their own
product — an ISP billing system, a school fees portal, a booking platform.

### Where the keys live

Your backend holds `sk_live_…`. Nothing else does. The customer's browser
never sees it, your mobile app never ships it, your repository never
contains it. If your platform has a per-tenant settings screen, store it
encrypted and never render it back — show `pk_live_…` instead, which is
what it is for.

### Sequence

1. **Sandbox first.** Create a sandbox pair and integrate against
   `sk_test_…`. Sandbox never moves real money. Collections accept an
   optional `simulate_status` so you can drive success, failure and
   pending-clearance paths deliberately instead of waiting for them.
2. **Create a collection** per bill or invoice, passing your own account or
   subscriber reference as `merchant_reference`. That reference comes back
   on every status read and webhook, and is how you match a payment to the
   right customer without keeping your own mapping table.
3. **Send an idempotency key** on every create (`Idempotency-Key` header).
   A retried request with the same key returns the original collection
   rather than charging twice — this is the single most important header
   for a billing system that retries.
4. **Read status** from the documented status endpoint, or receive it by
   webhook if you have merchant webhooks configured. Verify the signature
   on any webhook before acting on it.
5. **Go live**: swap `sk_test_…` for `sk_live_…`. Nothing else changes.

### Operating at volume

- **Rate limits** are per-endpoint and per-IP. Collection creation is 20
  requests per minute. A bulk run of thousands of bills should be paced or
  queued rather than fired in parallel; a `429` means back off and retry,
  not that the request failed permanently.
- **Retries** are safe when they carry the same `Idempotency-Key`. Without
  one, a retry is a second payment request.
- **Reconciliation**: treat the status endpoint as the source of truth, not
  your own optimistic state. A payment is settled when InfinityPay says it
  is.
- **IP allowlisting** is recommended for live keys. Add your backend's
  egress addresses under API Credentials; they take effect once approved.

### What this does not include

InfinityPay collects payments and pays out to merchant-controlled
destinations. There is **no bill-payment, LUKU, airtime or utility-purchase
API** — if your platform needs those, they are not available here.

Payouts to your own settlement account follow InfinityPay's withdrawal
rules, including Super Admin approval, and are not part of the collection
integration.

### Before going live

- [ ] Sandbox covers success, failure and pending-clearance
- [ ] Every create sends an `Idempotency-Key`
- [ ] `merchant_reference` carries your customer/account reference
- [ ] Status is read back rather than assumed
- [ ] Webhook signatures verified, if used
- [ ] `sk_live_…` exists only in server-side configuration
- [ ] IP allowlist populated and approved, if your IPs are stable
- [ ] A revocation path exists for a leaked key

## What's not built yet

Payment/disbursement writes go through `MockSelcomClient`, not a real
payment network — see `docs/selcom-live-go-live.md` for going live.
Outbound webhook *delivery* (an HTTP POST to a merchant's
`webhook_url` with retries) isn't implemented — `webhook_events` rows are
enqueued as `status: 'pending'` for a future background worker to pick up.

A collection initiated via `/v1/collections/{method}` stays `PROCESSING`
indefinitely in this environment unless something calls
`POST /v1/webhooks/selcom` (correctly signed) with its `provider_reference`
— there's no background timer that auto-resolves it the way a real
provider eventually would. That endpoint is the manual way to simulate one
during local development/testing.
