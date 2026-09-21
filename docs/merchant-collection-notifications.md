# Merchant collection notification emails

Lets a merchant configure up to 2 email addresses that get an automatic
email every time one of their collection transactions is successfully
confirmed and credited to their wallet.

**Distinct from a customer's payment receipt.** The receipt
(`send_payment_receipt_email`, see `docs/email-delivery.md`) goes to the
*paying customer*, wherever their email came from (a payment link, an
invoice, or a direct `customer_email` on the request). This feature goes
to the *merchant's own* configured notification address(es) — a
completely separate audience, separately configured, separately sent.

## Data model

`merchant_notification_settings` — one row per merchant
(`supabase/migrations/20260901010000_merchant_notification_settings.sql`):

| Column | Notes |
| --- | --- |
| `primary_notification_email` | nullable |
| `secondary_notification_email` | nullable |
| `collection_notifications_enabled` | boolean, default `true` |
| `updated_by` | who last changed it — a merchant admin or a Super Admin |

Fixed two-column shape (not a normalized `email` + `notification_type`
recipients table) — MVP only ever needs "up to 2 emails", and the
underlying validation function
(`app/services/merchant_notifications.py::validate_notification_emails`)
still enforces the max-2/no-duplicates/at-least-1-if-enabled rules
generically against a list, so nothing about that logic is tied to the
column shape.

## API

Same validation, same error messages, whether the merchant or a Super
Admin is editing — both routes call
`app/services/merchant_notifications.py::validate_notification_emails`:

| Method | Path | Who |
| --- | --- | --- |
| `GET` | `/v1/merchant/notification-settings` | Merchant admin (own merchant only, resolved from JWT) |
| `PATCH` | `/v1/merchant/notification-settings` | Merchant admin |
| `GET` | `/v1/admin/merchants/{id}/notification-settings` | Super Admin — settings + delivery summary |
| `PATCH` | `/v1/admin/merchants/{id}/notification-settings` | Super Admin |

Validation rules and their exact error messages:

| Rule | Message |
| --- | --- |
| Invalid email format | `Enter a valid notification email.` |
| More than 2 emails | `You can add up to 2 notification emails only.` |
| Duplicate emails (case-insensitive) | `Duplicate notification emails are not allowed.` |
| `collection_notifications_enabled = true` with no valid email | `Enter a valid notification email.` |

A merchant who has never opened Notification Settings gets a lazily-created
default row on first `GET` (`collection_notifications_enabled = true`,
both emails `null`) rather than a 404 — "not configured yet" is a normal
first-visit state.

Both write paths (`app/routers/merchant_portal.py`,
`app/routers/admin.py`) write an `audit_logs` row —
`notification_settings.updated` (merchant) or
`notification_settings.updated_by_admin` (Super Admin) — with the acting
user's own id, so it's always clear who last changed a merchant's
notification email(s).

## Sending the email

`app/services/email.py::send_merchant_collection_notification_email`, called
from `app/services/collections.py::_apply_collection_success` — the single
chokepoint every collection source (Request Collection, Payment Link, Pay
by Link, Invoice, API Collection, Wallet Push, Push to Selcom Pesa, TanQR)
funnels through once a collection reaches genuinely `successful` and its
wallet credit is posted. Never sent for `pending`/`processing`/
`prompt_sent`/`failed`/`cancelled`/`reversed`/`pending_review`/
`pending_clearance` — those statuses never reach `_apply_collection_success`
in the first place.

Best-effort, same as the receipt email right next to it: a failure here
must never block the wallet credit it's reporting on. Kept in its own
`try/except`, separate from the receipt email's, so a failure sending one
never prevents the other.

**Subject**: `Collection payment received - {currency} {amount}` (the feature
brief's literal `TZS` is substituted with the collection's real currency —
this platform is TZS-only today, so in practice these read identically).

**Content**: business name, gross amount, fee, net amount credited,
currency, payment method, customer name/phone/email (when available —
phone always masked, `_mask_identifier`, `•••• 1234`), provider reference,
merchant/internal reference, date, status ("Successful"), a link back to
`{APP_URL}/portal/collections`, and the shared branded footer ("Powered by
InfinityPay", support contact `info@infinityafrica.net`).

**Sender**: `InfinityPay <notification@infinityafrica.net>` (`EMAIL_FROM`)
— same as most other transactional email, see `docs/email-delivery.md`.
The sender/reply-to addresses stay on the old `infinityafrica.net` domain
until `infinitypay.me` is verified in Resend (brand/domain migration —
see `docs/email-delivery.md`).
**Reply-to**: `info@infinityafrica.net` (`EMAIL_REPLY_TO`).

## Idempotency

`_apply_collection_success` is only ever called once per collection in
practice — `resolve_collection()`/`finalize_pending_review_collection()`
(its only two callers) each refuse to re-process a collection whose status
has already left `processing`/`pending_review`. Belt-and-suspenders on top
of that, `send_merchant_collection_notification_email` independently
checks, per `(collection_id, recipient_email)`, whether an
`email_deliveries` row already has `status = 'sent'` for that exact pair
before sending — if one exists, it writes a `status = 'skipped'` row
instead of sending again. This is what actually protects against a
webhook redelivery, a manual "Refresh status" click, or a reconciliation
sweep somehow re-entering the success path for the same collection.

`email_deliveries.status` accepts `'skipped'` as of
`supabase/migrations/20260901020000_email_deliveries_add_skipped_status.sql`
— it didn't before this feature (only `'sent'`/`'failed'`).

## Delivery log

One `email_deliveries` row per recipient per attempt — `email_type =
'merchant_collection_notification'`, `related_resource_type = 'collection'`,
`related_resource_id = <collection id>`. Configuring both a primary and a
secondary email means two separate rows for the same collection. Never
logs a secret — no API key, no provider credential, ever.

## Super Admin — Notification Details

Shown on a merchant's detail page (`/super-admin/merchants/{id}`):
primary/secondary email, enabled/disabled, last notification status +
timestamp, failed-delivery count, and the 10 most recent per-recipient
delivery rows. Editable inline (same max-2/duplicate/audit-log rules as
the merchant's own settings) — never exposes `RESEND_API_KEY` or any other
provider secret.

## Testing

- `apps/api/tests/test_merchant_notification_settings.py` — settings
  CRUD/validation, merchant-scoping, audit logs, Super Admin access.
- `apps/api/tests/test_merchant_collection_notification_email.py` —
  sending across collection sources, content, idempotency, delivery
  logging, failure isolation from wallet credit.
