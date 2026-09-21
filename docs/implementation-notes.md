# Implementation Notes

Placeholder for architecture decisions, open questions, and implementation
notes as InfinityPay is built out.

## Stack

- **Frontend** (`apps/web`): Next.js App Router, TypeScript, Tailwind CSS —
  deployed on Vercel.
- **Backend** (`apps/api`): FastAPI, Python — deployed on Railway.
- **Database & Auth**: Supabase (Postgres + Auth).
- **Shared code** (`packages/shared`): TypeScript constants/enums consumed
  by `apps/web`.

## Surfaces

- Landing page — public marketing site (`apps/web` at `/`).
- Customer payment page — public checkout for a payment link
  (`apps/web` at `/pay/[slug]`, matching `payment_links.public_slug`).
- Merchant portal — authenticated merchant dashboard (`apps/web` at
  `/portal`).
- Super admin dashboard — authenticated platform-operator dashboard
  (`apps/web` at `/admin`).

## Database schema

`supabase/migrations/` — one migration per table, applied in order via the
Supabase CLI (`supabase db push`). Summary:

- **merchants** / **merchant_users** — tenants and their Supabase Auth team members.
- **customers** — a merchant's own customers.
- **api_keys** — hashed merchant API credentials (plaintext shown once, never stored).
- **settlement_accounts** — InfinityPay's own platform-level bank/provider accounts.
- **payment_links** / **invoices** / **invoice_items** — the documents merchants send customers.
- **collections** — attempts to pull money from a customer (`USSD_PUSH`, `STK_PUSH`,
  `SELCOM_PESA_PUSH`, `DYNAMIC_QR`); `merchant_reference` is the merchant's
  own order/reference, kept distinct from InfinityPay's own `transactions.reference`.
- **disbursements** — payouts to a merchant (`SELCOM_PESA`, `MOBILE_MONEY`, `BANK_ACCOUNT`);
  `status` is its own uppercase `PENDING`/`PROCESSING`/`SUCCESS`/`FAILED`/`REVERSED`
  vocabulary, distinct from the lowercase `TransactionStatus` its settling
  `transactions` row uses.
- **transactions** — the unified ledger row for every collection, disbursement, fee,
  refund, reversal, and adjustment.
- **ledger_accounts** / **ledger_entries** — internal double-entry bookkeeping;
  entries are append-only and a deferred trigger enforces debits = credits per
  transaction. `post_ledger_entries` (a `SECURITY DEFINER` Postgres function,
  `service_role`-only) is the only way entries + account balances are ever
  written together — see "Webhook + ledger processing" below.
- **webhook_events** — outbound delivery log, `event_name` mirrors
  `packages/shared/src/webhook-events.ts`.
- **selcom_webhook_events** — raw log of *inbound* Selcom deliveries to
  `POST /v1/webhooks/selcom`; `unique (provider, event_id)` is the
  duplicate-delivery guard. Distinct from `webhook_events` (outbound).
- **audit_logs** — append-only admin/system action history.

Enum-like columns (statuses, methods) use `text` + `CHECK` constraints rather
than Postgres `ENUM` types, so new values can be added later without a
blocking `ALTER TYPE`. Their value sets mirror `packages/shared/src` (TS) and
`apps/api/app/schemas/enums.py` (Python) — kept in sync by hand.

## Auth & RBAC

Four roles (`packages/shared/src/user-roles.ts`, `apps/api/app/schemas/enums.py`):

- **SUPER_ADMIN** — platform staff, all merchant data. Membership lives in
  `platform_admins` (platform-wide, not tied to any merchant).
- **MERCHANT_ADMIN** — full control of their merchant: business data, team
  (`merchant_users`), and API keys.
- **MERCHANT_STAFF** — day-to-day merchant data (customers, payment links,
  invoices), equal to MERCHANT_ADMIN except team/profile management.
- **DEVELOPER** — scoped to exactly one thing: managing the merchant's
  `api_keys` (and viewing API docs, which isn't DB-gated).

Membership in `platform_admins`/`merchant_users` — never Supabase Auth
`user_metadata` or `app_metadata` — is the only source of truth for role
decisions, at every layer:

- **Database** (`supabase/migrations/2026081410*`): every table has RLS
  enabled with real policies. Two SQL helper functions
  (`current_user_is_super_admin()`, `current_user_merchant_role(uuid)`,
  both `SECURITY DEFINER` with a pinned `search_path`) back nearly every
  policy. Money-movement tables written by a trusted backend process
  (`collections`, `disbursements`, `transactions`, `webhook_events`) are
  read-only for merchant users via RLS; all writes to those go through
  `apps/api` using `service_role`, which bypasses RLS entirely.
  `payment_links` and `invoices` additionally have a public (anon) SELECT
  policy scoped to exactly "valid"/"payable" rows, implementing "public
  customers can access only valid payment links and invoice payment pages"
  at the data layer — see `/pay/[slug]/page.tsx` for it in use.
- **Frontend** (`apps/web/src/lib/supabase/`): `client.ts`/`server.ts` are
  thin wrappers around `@supabase/ssr` (anon key only, never `service_role`).
  `session.ts` exposes `getSession()`, which calls `auth.getUser()` (re-
  validates the JWT) rather than the unverified `auth.getSession()` cookie
  read. `protected-route.ts` exposes `requireUser()` / `requireSuperAdmin()`
  / `requireMerchantAccess(merchantId)` for Server Components to gate on;
  `logout.ts` is a Server Action. `src/proxy.ts` (Next.js 16's renamed
  `middleware.ts`) refreshes the session cookie on every request. `/portal`
  and `/admin` layouts call `requireUser()`/`requireSuperAdmin()`; `/login`
  is a structural placeholder — no real sign-in form yet.
- **Backend** (`apps/api/app/auth/`): `jwt.py` verifies a Supabase access
  token via JWKS (`SUPABASE_JWKS_URL`/`SUPABASE_JWT_ISSUER` — asymmetric,
  the current default for a Supabase project's signing keys), falling back
  to a legacy shared HS256 secret (`SUPABASE_JWT_SECRET`) if configured.
  `dependencies.py` exposes `get_current_user`/`get_current_user_id`,
  `get_merchant_membership`, `require_role(*roles)` (super admins always
  pass; otherwise requires active membership with an allowed role — mirrors
  the RLS OR-policy), `require_super_admin`, and `verify_api_key` (a
  *separate* credential from Supabase Auth, for a merchant's own backend
  calling InfinityPay directly — hashed the same way as `api_keys.hashed_key`).
  `get_merchant_actor`/`require_role` expect `merchant_id` as a path
  segment (most routers); `get_authenticated_caller` +
  `authorize_merchant_action` are the same two rules split apart, for flat
  routes with no merchant_id in the path (`/v1/payment-links` and
  `/v1/collections/{method}`) where it's only known from the request body
  or a fetched row. All of it reads `merchant_users`/`platform_admins` via
  `app.database.session.get_supabase_admin()`, a `service_role` client that
  must never be constructed outside `apps/api`.

No login/signup UI or merchant-scoped routing (`/portal/[merchantId]/...`)
in `apps/web` yet — the dependencies above are now consumed by the full
`/v1` API (below), just not by the dashboard UI itself.

## Backend core (`/v1` API)

See `docs/api.md` for the endpoint table, response envelope, auth, and
idempotency rules. Architecture, in `apps/api/app/`:

- **`core/`** — cross-cutting infra: `errors.py` (an `APIError` hierarchy +
  exception handlers giving every response the same
  `{success, data|error}` envelope), `pagination.py`, `references.py`
  (human-readable IDs like `TXN-20260814-9F3A1C2B`), `time.py`.
- **`services/`** — the actual logic, independent of any router:
  `crud.py` (generic list/get/insert/update against supabase-py, since
  there's still no ORM — see `database/session.py`), `idempotency.py`,
  `audit.py`, `ledger.py` (double-entry posting — see below),
  `webhooks.py` (enqueues `webhook_events`; delivery isn't built),
  `payment_links.py` (the lazy-expiry helper, shared with `collections.py`
  for `payment_link_id` cross-validation), `collections.py` (the
  initiate/resolve lifecycle — see below) and `disbursements.py` (the
  disbursement equivalent — reserve/settle-or-reverse, see "Disbursements"
  below — still single-call/synchronous against the mock provider, unlike
  collections' two-call initiate/check split), and `selcom/` (the
  `PaymentProvider` interface in `client.py`, `MockSelcomClient` in
  `mock_client.py`, `LiveSelcomClient` in `live_client.py` — see
  `docs/selcom-live-go-live.md`).
- **`routers/`** — one file per resource, thin: parse auth/pagination, call
  a service, wrap the result in `APIResponse`. `payment_links.py` and
  `collections.py` each export more than one `APIRouter`. Every other
  resource nests its router under `/v1/merchants/{merchant_id}/...`;
  `payment_links.py` (`/v1/payment-links`), `invoices.py` (`/v1/invoices`),
  `disbursements.py` (`/v1/disbursements/{method}` to create, fully flat —
  unlike collections, its `GET` list/get are flat too, not nested), and
  collection initiation in `collections.py` (`/v1/collections/{method}`)
  are flat instead, `merchant_id` in the body for create (a required query
  param for the flat `GET` list endpoints) — reading collections back
  stays nested (`/v1/merchants/{id}/collections`, untouched by that split).
  `payment_links.py`'s public router is mounted at `/public/payment-links`
  instead of under `/v1` at all (see `docs/api.md`'s Authentication section
  for why); `invoices.py`/`disbursements.py` have no public router of their
  own at all — see "Invoices"/"Disbursements" below.
- **`schemas/`** — `common.py` has the response envelope; one file per
  resource for Create/Response models.

**Ledger posting** (`services/ledger.py`) implements the double-entry
design from `ledger_accounts`/`ledger_entries` for real: a successful
collection debits a platform `settlement_clearing` account and credits the
merchant's `merchant_wallet` (net of a flat `platform_fee_percentage`) plus
`platform_revenue` (the fee) — debits always equal credits, which a
deferred DB trigger enforces. A disbursement is the mirror image — debit
`merchant_wallet`, credit `settlement_clearing` — posted as a *reservation*
the moment a payout starts processing (before the provider is even
called), not only once it's confirmed; see "Disbursements" below for why.
Accounts are found-or-created per (merchant_id, purpose, currency) via ordinary
REST calls (idempotent — a unique index is the backstop against a
concurrent race); the entries themselves post via the `post_ledger_entries`
RPC (see below), which is the part that must be atomic with the balance
update.

**Webhook + ledger processing** (`routers/webhooks.py`,
`services/webhooks.py`, `supabase/migrations/20260814130*`): supabase-py/
PostgREST can't wrap multiple `.insert()`/`.update()` calls in one
client-side transaction, so posting several `ledger_entries` (e.g. a debit
+ two credits) alongside their accounts' `balance` updates can't safely
happen as separate REST calls — each would commit individually, and the
deferred debits-must-equal-credits trigger would fail on the first,
unbalanced entry alone. `post_ledger_entries` (a `plpgsql` function,
`SECURITY DEFINER`, `service_role`-only) is the fix: it loops over a whole
batch of entries and updates every account's cached `balance` inside the
single Postgres transaction that one `client.rpc(...)` call constitutes —
called from `services/ledger.py`'s `_post_entries()`. Balance direction
follows the standard convention: asset/expense accounts increase on debit;
liability/equity/revenue accounts (including `merchant_wallet`, modeled as
a liability — InfinityPay owes the merchant that balance) increase on credit.

`POST /v1/webhooks/selcom` is where a real Selcom callback would land.
Handling, in order: (1) the raw request body is read via `Request.body()`
rather than FastAPI's automatic parsing, so signature verification runs
against the exact bytes sent; (2) `X-Selcom-Signature` is checked as an
HMAC-SHA256 of that raw body against `SELCOM_WEBHOOK_SECRET`
(`services/providers/selcom_webhooks.py` — a mock scheme, since no live
Selcom integration exists to match a real one against); (3) the delivery
is logged to `selcom_webhook_events` *before* anything else, keyed by
`(provider, event_id)` — a second delivery of the same `event_id`
short-circuits as `{"status": "duplicate"}` rather than reprocessing (an
invalid signature is stored `status: 'failed'` and rejected `401`); (4)
`event_type` (`collection.success`/`collection.failed`/
`disbursement.success`/`disbursement.failed` — the only things Selcom
itself would ever report, having no concept of InfinityPay's
payment_link/invoice entities) is dispatched by `provider_reference` to
the existing `resolve_collection_from_callback`/
`resolve_disbursement_from_callback`, reusing all of the collection/
disbursement resolution logic below unchanged. `payment_link.paid` and
`invoice.paid` are the *outbound* webhook events those functions enqueue
as a side effect of a linked payment_link/invoice getting paid — never
something Selcom sends inbound.

**Disbursements** (`services/disbursements.py`): a payout has to actually
validate and safely deduct available balance, which collections never
need to (money only ever flows *into* `merchant_wallet` there). Two
mechanisms, matching the two-part requirement:

1. `get_wallet_balance()` — a fast, friendly check before even creating
   the `disbursements` row: `amount > available` raises
   `InsufficientBalanceError` (409 `insufficient_balance`) immediately.
2. The `post_ledger_entries` RPC's own balance check (see "Webhook +
   ledger processing" above and
   `supabase/migrations/20260814140001_post_ledger_entries_balance_check.sql`)
   — the atomic, race-proof guarantee, since two concurrent requests could
   both pass check #1 against the same starting balance.

Once past both, `_reserve_and_run_disbursement_provider` creates the
`transactions` row and *reserves* the amount — debits `merchant_wallet` via
`post_disbursement_entries` — before calling the provider at all, moving
`disbursements.status` `PENDING` → `PROCESSING`. If the provider then
confirms the payout, that reservation *is* the final settlement (nothing
more to post) and status becomes `SUCCESS`. If it declines,
`reverse_disbursement_entries` posts the offsetting pair against the same
`transaction_id` (nets to zero movement) and status becomes `FAILED` — the
transaction's own `status` becomes `reversed` (giving `TransactionStatus.REVERSED`
its first real use), while the disbursement's own status stays `FAILED`
rather than `REVERSED` — that value is reserved for reversing an
already-`SUCCESS` payout later (e.g. a bounced transfer discovered after
the fact); no endpoint triggers it yet, matching how `InvoiceStatus.OVERDUE`
or `PaymentLinkStatus.EXPIRED` are declared without every transition being
wired to an action.

At or above `disbursement_approval_threshold`, none of the above happens
immediately: the disbursement is created `PENDING`/`requires_approval=True`
and held for a super admin to `.../approve` (which runs the same
reserve-then-settle-or-reverse flow) or `.../reject` (status → `FAILED`
directly — nothing was ever reserved, so there's nothing to reverse) —
matching the super-admin "high-value disbursement approval queue".
`resolve_disbursement_from_callback` still exists for a real provider that
resolves a payout asynchronously instead of in one call like the mock —
unreachable today for the same reason it always was.

**Payment link expiry** (`services/payment_links.py`): nothing sweeps
`expires_at` on a timer. Expiry is lazy, on read — `with_effective_status`
promotes a stored `ACTIVE` link to `EXPIRED` (and persists that) the moment
anything reads it past its `expires_at`: the dashboard GET, the public GET,
a collect attempt, or a `/v1/collections/{method}` call whose
`payment_link_id` references it. The public GET always 200s for a slug
that exists (status ACTIVE/EXPIRED/CANCELLED/PAID in the body), so the
checkout page can explain *why* a link can't be paid rather than a bare
404; collect itself 409s with the specific status once it's not ACTIVE.
Cancelling is idempotent (repeat calls no-op onto the current state, no
duplicate audit log entries) and rejects an already-`PAID` link.

**Invoices** (`routers/invoices.py`, `schemas/invoices.py`): an itemized
bill (`invoices` + `invoice_items`, `invoice_items.line_total` a generated
column) with its own `invoice_number` (`generate_reference("INV")` — same
short human-showable format as `transactions.reference`) assigned
automatically on creation, always starting `DRAFT`. `PATCH /v1/invoices/{id}`
only works while still `DRAFT` (once `SENT`, its amounts are what the
customer was already shown) and recomputes `subtotal`/`total_amount` if
`items`/`tax_amount`/`discount_amount` are included.

Rather than invoices having their own separate public checkout (the
pre-redesign shape: a public `GET`/`POST .../collect` pair), an invoice
generates a payment_links row instead — `POST /v1/invoices/{id}/payment-link`
(`build_public_url`/`generate_public_slug`, moved from `routers/payment_links.py`
into `services/payment_links.py` so both routers share them) creates one
for the remaining balance (`total_amount - amount_paid`), or reuses the
existing one while it's still `ACTIVE`, and points `invoices.payment_link_id`
at it. The customer then pays through the ordinary payment-link checkout
(`/public/payment-links/{public_slug}`) — no invoice-specific public
surface at all. Only a `SENT`/`PARTIALLY_PAID`/`OVERDUE` invoice can
generate one (mirrors the old `_PAYABLE_STATUSES`); generating one for a
`DRAFT`/`PAID`/`CANCELLED` invoice, or one with no remaining balance, is
rejected.

This is also *how* invoice status stays linked to payment status:
`services/collections.py`'s `_apply_collection_success`, on a successful
collection carrying a `payment_link_id`, now also looks up whether any
`invoices` row references that same `payment_links.id` — if so it applies
the payment (`_apply_payment_to_invoice`: credits `amount_paid`, moves the
invoice to `PARTIALLY_PAID` or `PAID`, and enqueues `invoice.paid` once
fully paid) exactly as it already did for a collection carrying
`invoice_id` directly. The collection itself only ever knows about the
payment_link, never the invoice — this lookup is what closes that gap.

**Collection initiate/resolve split** (`services/collections.py`): every
collection gets exactly one transaction row, created alongside it (both
`processing`) *before* the provider confirms anything — reflecting that
money is "in flight" the moment a push/QR is issued, not only once it's
confirmed. `resolve_collection()` is the one place either ever leaves
`processing`: it updates both in place (never inserts a second
transaction), posts ledger entries only on success, and applies the result
to a linked payment_link/invoice. Two things reach it: `execute_collection()`
(initiate, then immediately `check_collection_status` and resolve —
synchronous, used by the public "collect" endpoints where the customer is
watching) and `resolve_collection_from_callback()` (a provider callback
resolves a collection some time after `initiate_collection()` /
`initiate_dynamic_qr_collection()` left it `processing` — used by
`/v1/collections/{method}`, which never resolves synchronously and returns
`processing` immediately, matching what a real push/QR payment actually
does). Nothing auto-resolves a `/v1/collections/{method}` collection in
this environment — see docs/api.md's "What's not built yet".

**Testing** (`apps/api/tests/`): `fakes.py` is an in-memory stand-in for
the supabase-py query builder (select/insert/update/delete, `.eq()`,
`.order()`, `.range()`, `.maybe_single()`, and a `.rpc("post_ledger_entries",
...)` that mirrors the real Postgres function's balance-update logic in
Python, *including* its insufficient-balance guard — validated,
two-phase, before any row is mutated, the same way the real function's
whole transaction rolls back on that exception — it also mirrors
`invoice_items.line_total`, a generated column, the same way, since a
plain insert wouldn't otherwise populate it), and `conftest.py`'s
`fake_client` fixture patches it into every already-imported module that
calls `get_supabase_admin()` — real router/service/auth code runs against
it end to end, with no real Supabase project needed. `factories.py` has the
shared seed helpers (`create_merchant`, `make_merchant_member`,
`make_api_key`, ...) used across `test_routers.py`, `test_payment_links.py`,
`test_collections.py`, `test_invoices.py`, `test_disbursements.py`, and
future router test modules.
Writing
`test_push_methods_reject_invalid_phone_format` surfaced a real bug in
`core/errors.py`'s validation handler: `RequestValidationError.errors()`
can embed a raw exception object in `ctx` when a Pydantic `field_validator`
raises `ValueError` (as the phone-format check does), which broke JSON
serialization of the error response itself — fixed by running
`exc.errors()` through `fastapi.encoders.jsonable_encoder` first.

## Status

Foundation + database schema + auth/RBAC + the full `/v1` API, including
inbound Selcom webhook processing and atomic ledger/balance posting — no
live Selcom integration, outbound webhook *delivery*, or dashboard UI yet.
