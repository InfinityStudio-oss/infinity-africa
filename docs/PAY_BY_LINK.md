# Pay by Link

A merchant's permanent public checkout page — one URL, shared once,
reused forever. Additive to the existing generated/shareable Payment
Links (`docs/` — see `app/routers/payment_links.py`); neither feature
changes or removes the other.

## Feature overview

Every merchant can create exactly one permanent page:

```
https://infinitypay.me/pay/{merchant_slug}
```

Example: `https://infinitypay.me/pay/paul-masanja`

The merchant copies this link once and shares it anywhere — WhatsApp,
Instagram, Facebook, TikTok, a website, a business profile, or (later) a
printed poster QR code. A customer who opens it fills in their own
details and amount, then proceeds to the exact same secure checkout flow
every other InfinityPay payment already uses.

## Merchant use cases

Built for SMEs who need one standing payment address rather than
generating a new link per sale: restaurants, retail shops, bodaboda and
delivery riders, salons, freelancers, fundis, and other service
providers who take ad-hoc amounts from walk-in or social-media customers.

## URL format

`/pay/{slug}` is a **shared namespace** between two different resources:

- An existing generated/shareable payment link (`payment_links.public_slug`
  — a random 128-bit token, created per-transaction, fixed amount).
- A merchant's permanent Pay by Link page (`merchant_pay_links.slug` — a
  human-chosen, lowercase-hyphenated slug, created once, no fixed amount).

**Resolver rule** (`apps/web/src/app/pay/[slug]/page.tsx`): a generated
payment link is always checked first; only when that lookup finds
nothing does the page fall back to checking Pay by Link. This means an
already-shared generated link can never be shadowed by a later-created
permanent page. If neither table has the slug, the page shows a clean
"Link unavailable" state.

Slug rules (`app/services/pay_by_link.py`):

- Lowercase letters, digits, and single hyphens only; 3-60 characters.
- Must not collide with another merchant's Pay by Link slug, nor with
  any existing generated `payment_links.public_slug` — checked
  case-insensitively, since a generated token can contain characters
  (uppercase, `_`) a Pay by Link slug format rejects outright anyway.
- Reserved words are rejected: `admin`, `merchant`, `api`, `auth`,
  `login`, `signup`, `dashboard`, `invoices`, `collections`,
  `payment-links`, `support`, `contact`, `settings`, `webhook`,
  `webhooks`.

## Merchant setup

Merchant Portal → **Pay by Link** (`/merchant/pay-by-link`):

1. **Create** — display name defaults to the merchant's own business
   name; a slug is generated from it automatically (`Paul Masanja` →
   `paul-masanja`, `paul-masanja-2` if taken, and so on). A merchant may
   override either before creating.
2. **View/copy/share** — the permanent URL, a copy button, and a
   WhatsApp share button, plus a scannable QR code for print use.
3. **Edit** — display name and description can be changed anytime.
4. **Change slug** — allowed, with an explicit on-screen warning that any
   already-shared copies of the old URL stop working once saved. Live
   availability checking (`GET /v1/merchant/pay-by-link/slug-availability`)
   shows "This slug is already taken." before the merchant even submits.
5. **Enable/disable** — a merchant-controlled kill switch for this one
   page, independent of the platform-wide `ENABLE_COLLECTIONS` flag. A
   disabled page shows a clean "payments paused" state to any customer
   who opens it.

Only one permanent page exists per merchant today (`merchant_pay_links.merchant_id`
is unique) — revisit with a real multi-page design if merchants ever
need more than one.

## Customer flow

1. Customer opens `/pay/{slug}` and sees the merchant's name, optional
   description, and a "secure payment" note.
2. Fills in first name, last name, email, mobile number, amount
   (TZS), and an optional reason/description.
3. Clicks **Proceed to Pay**.
4. Backend resolves the merchant purely from the slug (never from
   anything the browser sends), creates a fresh, entirely ordinary
   `payment_links` row for that merchant (tagged `created_via="pay_by_link"`),
   and returns its public checkout URL.
5. The browser does a full-page redirect there — landing on the exact
   same "Choose how you want to pay" flow every generated payment link
   already uses.
6. Customer completes payment there, normally.
7. Once Selcom confirms the payment (webhook or scheduled
   reconciliation — never a bare unsigned callback), the merchant's
   wallet is credited through the existing safe crediting path.
8. If the customer's email was captured, they receive the normal
   receipt email once payment actually succeeds — never before.

## Payment / reconciliation flow

Pay by Link's checkout endpoint (`POST /public/pay-by-link/{slug}/checkout`)
does exactly one thing: create a `payment_links` row. It never touches a
collection, a ledger entry, or a wallet balance directly. Every safety
guarantee already proven for a generated payment link therefore applies
here unchanged, by construction, not by re-implementation:

- Unsigned webhooks are rejected; only a backend-authenticated Selcom
  status confirmation can resolve a collection.
- `resolve_collection()` is the single idempotent chokepoint every
  crediting path funnels through — a collection can only ever be
  credited once, however many times reconciliation/webhook/manual
  refresh run against it.
- Scheduled reconciliation and the manual "Refresh status" fallback both
  work identically for a Pay by Link-originated collection as for any
  other payment link.

The endpoint is itself `Idempotency-Key`-guarded (same convention as
every other money-adjacent public POST) — a retried or double-clicked
submission reuses the same `payment_links` row rather than minting a
second one for the same customer intent.

## Source tracking

A collection resulting from a Pay by Link submission is tagged
`source = "PAY_BY_LINK"` (`app/schemas/enums.py::CollectionSource`,
resolved server-side in `app/services/collection_source.py` from the
underlying `payment_links.created_via = "pay_by_link"` — never trusted
from client input). This distinguishes it from `DASHBOARD_REQUEST`,
`PAYMENT_LINK`, `INVOICE`, and the `API_*` sources in every collections/
transactions view, filter, and export, for both the merchant and Super
Admin.

## Receipt flow

Unchanged — the normal payment-success receipt flow
(`app/services/email.py::send_payment_receipt_email`) fires only once a
collection genuinely reaches `"successful"`, using whatever
`customer_email` the Pay by Link checkout form captured. No new receipt
path was built; none is needed.

## Super Admin visibility

Merchant detail page (`/super-admin/merchants/{id}`) → **Pay by Link**
section: slug, active/disabled status, created/last-used timestamps
(`GET /v1/admin/merchants/{id}/pay-by-link`). Payments created through
Pay by Link already appear in the regular Collections/Transactions views
with `source = PAY_BY_LINK` — no separate view needed. Slug create/
update/enable/disable events are ordinary audit-log entries
(`pay_by_link.created` / `.updated` / `.enabled` / `.disabled`), visible
in the existing Audit Logs page like any other action.

## Security rules

- Merchant ID is resolved exclusively from the slug lookup, server-side
  — the checkout request schema (`PayByLinkCheckoutRequest`) has no
  `merchant_id` field at all; an extra one in the JSON body is silently
  ignored by Pydantic, never read.
- A merchant must be `status="active"` to accept a payment — re-checked
  at every checkout submission, not just once at page-creation time, so
  a merchant suspended after sharing their link stops accepting payments
  immediately.
- No Selcom credentials, Supabase service role key, Resend API key, or
  any other backend secret is ever reachable from the public checkout
  page or its API responses — the public lookup endpoint
  (`GET /public/pay-by-link/{slug}`) returns only `display_name`,
  `description`, and `is_active`.
- Amount/fee/wallet logic is 100% backend-controlled, same as every
  other collection path — the frontend never computes or asserts a fee
  or net amount.
- Rate-limited: `pay_by_link_checkout` (20/min/IP, public), `pay_by_link_manage`
  (10/min/IP, merchant create/update), `pay_by_link_slug_check`
  (30/min/IP, merchant live-availability check).
- Audit-logged: page created/updated/enabled/disabled (actor = the
  merchant user), and each payment initiated (actor_type="system",
  amount/currency/slug only — never the customer's name, email, or
  phone).

## Limitations

- One permanent page per merchant (see "Merchant setup" above).
- Currency is fixed at TZS — the checkout schema rejects anything else
  explicitly, matching every other collection path in this codebase
  today (no multi-currency support exists anywhere yet).
- No minimum-amount floor beyond "greater than zero" — matches the
  existing convention for every other collection/payment-link amount
  field in this codebase (none of them enforce a higher floor either).

## Future: QR code

A scannable QR code encoding the permanent URL is already shown in the
Merchant Portal (`QrCode` component, client-side generated, nothing sent
to a third party) for a merchant to save or print themselves. A
dedicated printable poster/table-tent template is a natural next step,
not yet built.
