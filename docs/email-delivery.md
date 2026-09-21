# Transactional email (Resend)

> **Brand/domain migration in progress**: the product is now **InfinityPay**
> (was Infinity Africa), and the long-term domain is `infinitypay.me` (was
> `infinityafrica.net`). Email templates already say InfinityPay, but every
> sender/reply-to/CEO address below **stays on `infinityafrica.net` until
> `infinitypay.me` is verified in Resend** — see "Sender addresses" below.
> Do not switch `EMAIL_FROM`/`INVOICE_EMAIL_FROM`/`EMAIL_REPLY_TO`/
> `CEO_EMAIL` to `@infinitypay.me` in Railway before that verification is
> confirmed; doing so would make transactional email fail to send or land
> in spam.

All outbound transactional email goes through [Resend](https://resend.com),
via `app/services/email.py`. `RESEND_API_KEY` is backend/Railway-only —
never set it in `apps/web`/Vercel (and never as `NEXT_PUBLIC_RESEND_API_KEY`
or any other `NEXT_PUBLIC_*` name), and nothing in `apps/web` imports this
module or reads that key.

The domain `infinityafrica.net` is verified in Resend (SPF/DKIM/DMARC DNS
records added in Cloudflare — see Resend's own domain-verification page for
the exact record values if they ever need re-adding; they aren't
reproduced here since they're config, not code). `infinitypay.me` is not
verified yet — verifying it (adding the equivalent DNS records) is a
prerequisite for switching any sender address to the new domain.

## What's wired up

Ten email types, all built on the same `send_email()` primitive and all
logged to `email_deliveries` (success or failure, every attempt):

| Email type | Sent from | Trigger |
| --- | --- | --- |
| Invoice payment request | `send_invoice_email` | `POST /v1/invoices/{id}/send`, `POST /v1/merchant/invoices/{id}/send` |
| Staff / developer invite | `send_staff_invite_email` | `POST /v1/merchant/users` (inviting a teammate) |
| Password reset | `send_password_reset_email` | `POST /v1/auth/forgot-password` |
| Payment receipt | `send_payment_receipt_email` | `app/services/collections.py::_apply_collection_success` (a collection reaching genuinely `successful`/cleared) |
| Merchant collection notification | `send_merchant_collection_notification_email` | Same call site as Payment receipt, right after it — see `docs/merchant-collection-notifications.md` |
| Inquiry notification (to CEO) | `send_inquiry_notification_email` | `POST /v1/public/inquiries` (the marketing site's Contact form) |
| Merchant welcome | `send_merchant_welcome_email` | `app/services/onboarding.py::approve_onboarding_submission` (a merchant's KYC being approved) |
| Withdrawal request notification (to CEO) | `send_withdrawal_request_notification_email` | `app/services/disbursements.py::execute_disbursement` (right after a withdrawal request row is saved) |
| Withdrawal success | `send_withdrawal_success_email` | `app/services/disbursements.py` — both places a disbursement reaches `SUCCESS` (the synchronous approval path and the delayed callback/refresh-resolved path) |
| Payment link customer delivery | `send_payment_link_customer_email` | `POST /v1/merchant/payment-links` (only when `customer_email` is provided) |

**Supabase never sends its own auth email for invites or password resets.**
Both flows use `auth.admin.generate_link()` (type `"invite"` /
`"recovery"`) — which creates the same underlying Supabase Auth
user/token but does *not* trigger Supabase's own unbranded email — and
this backend sends its own branded one via Resend instead, carrying the
same `action_link`. The raw link/token is never written to
`email_deliveries` or logged anywhere; only metadata (recipient, subject,
status, provider message id) is ever stored.

### Fail-open vs. fail-closed

Two of the six raise `EmailDeliveryError` (fail-closed) if the send
doesn't go through — the parent action refuses to claim success:

- **Invoice**: stays in its current status, not marked `SENT`, unless the
  email is actually delivered.
- **Staff invite**: `POST /v1/merchant/users` returns `502
  email_delivery_failed` rather than silently leaving an admin thinking
  the invite went out.

The other eight are best-effort (fail-open) — they never raise, and the
call sites additionally wrap them in `try/except` for defense in depth:

- **Password reset**: must never let a caller distinguish "no such
  account" from "email provider down" (account enumeration prevention) —
  `POST /v1/auth/forgot-password` always returns the exact same generic
  message regardless of what happened internally.
- **Payment receipt**: a receipt failing to send must never fail the
  payment itself.
- **Merchant collection notification**: same requirement as the receipt —
  a failure here must never block the wallet credit it's reporting on.
  Kept in its own separate `try/except`, next to (not inside) the receipt
  email's, so a failure sending one never prevents the other from being
  attempted.
- **Inquiry notification**: a notification failing to send must never
  lose the saved inquiry.
- **Merchant welcome**: a courtesy email failing to send must never fail
  the merchant's approval.
- **Withdrawal request notification**: the withdrawal request is already
  saved by the time this runs — a failed CEO notification must never look
  like a failed withdrawal request.
- **Withdrawal success**: must never reverse or fail an already-successful
  withdrawal.
- **Payment link customer delivery**: a missing or failed send must never
  fail link creation itself — `POST /v1/merchant/payment-links`'s response
  carries `customer_email_sent` (`true`/`false`/`null` for "not
  attempted") so the frontend can show the right outcome, and copy/
  WhatsApp-share stay available regardless.

## Sender addresses

Two senders, chosen by email type — not configurable per-email, only per
deployment:

| Email type | Sender | Env var |
| --- | --- | --- |
| Invoice payment requests | `InfinityPay Invoices <invoice@infinityafrica.net>` | `INVOICE_EMAIL_FROM` |
| Everything else (staff invites, password resets, payment receipts, merchant collection notifications, welcome emails, inquiry notifications, withdrawal request/success, payment link delivery) | `InfinityPay <notification@infinityafrica.net>` | `EMAIL_FROM` |

If `INVOICE_EMAIL_FROM` isn't set, invoice emails fall back to whatever
`EMAIL_FROM` is set to (see `Settings.invoice_email_from` in
`app/config/settings.py`) — a deployment that forgets to set the
invoice-specific sender still sends *something* sane rather than failing
outright.

**Reply-to** for every email is `EMAIL_REPLY_TO`, which defaults to
`info@infinityafrica.net` — the customer/merchant support contact shown
in every template's footer ("Need help? Reach us at..."). This replaced
an earlier `support@infinityafrica.net` default; every customer-facing
template and page now shows `info@infinityafrica.net` instead.

## Required Railway/backend env vars

```
RESEND_API_KEY=                                                    # backend-only, never in Vercel, never NEXT_PUBLIC_*
EMAIL_FROM="InfinityPay <notification@infinityafrica.net>"
INVOICE_EMAIL_FROM="InfinityPay Invoices <invoice@infinityafrica.net>"
EMAIL_REPLY_TO="info@infinityafrica.net"
CEO_EMAIL="ceo@infinityafrica.net"
APP_URL="https://infinitypay.me"
```

Once `infinitypay.me` is verified in Resend, switch the four sender/
contact addresses above to:

```
EMAIL_FROM="InfinityPay <notification@infinitypay.me>"
INVOICE_EMAIL_FROM="InfinityPay Invoices <invoice@infinitypay.me>"
EMAIL_REPLY_TO="info@infinitypay.me"
CEO_EMAIL="ceo@infinitypay.me"
```

`APP_URL` above is already on the new domain — it's just a link target
inside email bodies, not a Resend-verified sending domain, so it isn't
gated the same way.

`APP_URL` is distinct from the existing `PUBLIC_APP_URL` — `PUBLIC_APP_URL`
specifically builds the `/pay/{slug}` payment-link URL
(`app/services/payment_links.py::build_public_url`) and is untouched by
this feature; `APP_URL` (`Settings.app_url`, falls back to
`PUBLIC_APP_URL` when unset) is a general site base URL available for
email templates that need one (the welcome email's "Open Merchant Portal"
button, the receipt email's "Download Receipt" link), distinct from the
payment-link builder so neither has to guess the other's intent.

## Flow notes

**Staff invite** (`app/routers/merchant_portal.py::create_my_merchant_user`)
— generates the invite link, inserts the `merchant_users` row (status
`invited`), then sends the branded email. If the email send fails after
the Supabase Auth user + `merchant_users` row already exist, there's
currently no "resend invite" action — the admin would need to know to
retry the whole invite (this is a known, disclosed gap, not a silent
failure — the endpoint returns a clear error either way).

**Password reset** — `POST /v1/auth/forgot-password` accepts a
`redirect_path` that must be one of a closed set
(`/merchant/reset-password`, `/admin-login/reset-password` — see
`app/schemas/auth.py::ForgotPasswordRequest`), never an arbitrary URL, so
a real Supabase recovery link can never be redirected somewhere
attacker-controlled.

**Payment receipt** — `collections` has no `customer_email` column of its
own (collections are inherently phone-first — USSD/STK/wallet-push).
`app/services/email.py::_resolve_collection_customer_email` checks three
sources, in order: a linked `payment_links.customer_email`, a linked
`invoices.customer_email`, then `collection.metadata.customer_email` —
the last one covers "Request Collection" (merchant portal push/dynamic-QR/
hosted-checkout/wallet-push) and direct API collections, both of which
accept an optional `customer_email` on the request that
`create_processing_collection` stores into `metadata` since `collections`
has no dedicated column for it. Only a collection with none of the three
(e.g. a phone-only push with no email supplied at all) sends no receipt —
this is expected, not a bug. The receipt "Download" button/link is only
included when the collection has a `payment_links.public_slug` to point
at (the existing public receipt route needs one); otherwise the email
shows the full receipt inline with no button, rather than linking to a
broken URL.

**Merchant collection notification** — see `docs/merchant-collection-notifications.md`
for the full feature (Notification Settings in the Merchant Portal, Super
Admin's Notification Details view, and the idempotency rule). In short:
distinct from the payment-receipt email above — that goes to the paying
*customer*; this goes to the *merchant's own* configured notification
email(s) (`merchant_notification_settings`, up to 2), only while
`collection_notifications_enabled` is true.

**Inquiry notification** — `POST /v1/public/inquiries` is the only inquiry
source currently wired up (the marketing site's Contact form,
`components/landing/contact-form.tsx`). The site's other pages
(`/get-started`) just redirect into the real merchant signup flow, and
the Merchant Portal's own "Support" section is still mock data (not a
real ticket system) — neither triggers this email. There's no Super Admin
UI to browse saved inquiries yet; they're visible via the CEO notification
email and directly in the `inquiries` table.

**Merchant welcome** — sent on KYC *approval*
(`app/services/onboarding.py::approve_onboarding_submission`), not on
initial signup submission — a merchant can't meaningfully use the
portal (no verified wallet, no live API access) until approved, so a
"welcome" email at raw signup time would be premature. The Super Admin
onboarding review UI shows "Approved. Welcome email sent..." as its
success feedback for the Approve action.

**Withdrawal request notification / success** — the destination account
identifier is masked in both emails (`app/services/email.py::_mask_identifier`,
`•••• 1234` — the same convention `apps/web/src/lib/format.ts::maskAccountIdentifier`
already used on the frontend) rather than shown in full. The request
email's "Review Withdrawal" button links to `{APP_URL}/super-admin/withdrawals`
(the review queue — there's no per-withdrawal detail route yet); the
success email's "View Merchant Portal" button links to
`{APP_URL}/merchant/withdrawals`. Both are also surfaced on
`GET /v1/admin/withdrawals` as `request_email_status`/`success_email_status`
for Super Admin, via `batch_latest_email_deliveries`'s optional `email_type`
filter (needed here since a single disbursement can have two different
kinds of email attached to it, unlike every other resource this helper
serves).

**Payment link customer delivery** — sent right after
`POST /v1/merchant/payment-links` creates the row, only when
`customer_email` is present; a missing email is not a failure, just
nothing to send (`send_payment_link_customer_email` checks internally).
The email's "Pay Now" button uses the same `build_public_url` the
response's own `public_url` field does — never a placeholder domain. Note:
this is currently wired into the Merchant Portal's own create endpoint
(`app/routers/merchant_portal.py::create_my_payment_link`) only, not the
API-key-authenticated `POST /v1/payment-links` — an API integrator likely
wants to send their own email, not have InfinityPay's branded one sent
on their behalf. A "request collection" (merchant portal wallet-push)
equivalent was scoped out of this pass: unlike a payment link, a plain
phone push has no public payment page/URL to email in the first place (see
the payment-receipt flow note above for the same underlying fact).

## Safety notes

- The Resend API key is never logged, never included in an error message
  returned to a client, and never printed. `send_email`'s exception
  handler logs the *provider's* exception server-side only; the message
  raised to callers is a fixed, safe string.
- `email_deliveries` never stores an email body, a raw invite/reset link,
  or a token — only metadata (sender, recipient, subject, provider
  message id, status, failure reason).
- An invoice email is a **payment request**, never a receipt — it is
  never sent in response to a successful payment; that's what the
  separate payment-receipt email is for.
- Invite and reset emails never carry a plaintext password — only a
  Supabase-generated action link, which itself is never logged.
- Withdrawal emails never show a destination account/phone number in
  full — always masked to the last 4 digits (`_mask_identifier`).
- The merchant collection notification email masks the paying customer's
  phone number the same way (`_mask_identifier`, `•••• 1234`) — never the
  raw number.
