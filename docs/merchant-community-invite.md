# Merchant WhatsApp community invitation

One server-side setting adds an invitation to the InfinityPay WhatsApp
community to two existing merchant notifications. The invitation is appended
to those messages. No new message is sent, and nobody is added to the group.

## Configuration

| Variable (API service, Railway) | Default |
| --- | --- |
| `MERCHANT_COMMUNITY_WHATSAPP_URL` | empty, which means no invitation |

Production value:

```
MERCHANT_COMMUNITY_WHATSAPP_URL=https://chat.whatsapp.com/Ku5UwtoPC5ZFzeL2DXWSfg?s=cl&p=i&iam=2
```

`apps/api/app/services/community_invite.py` is the only code that reads it.
The link is sent only if it is `https`, the host is exactly
`chat.whatsapp.com`, it has no credentials, uses the default port, has an
invite path, and contains no whitespace or control characters. Anything else
is ignored with a warning in the log. A blank or invalid value **never** fails
or delays a notification: the message goes out exactly as it did before this
feature existed.

The link is used byte-for-byte as configured. In HTML it is entity-escaped
(`&` becomes `&amp;`), which mail clients decode back to the same destination.

## Where it appears

| Event | Channel | Template | Existing switch |
| --- | --- | --- | --- |
| Merchant approval (`POST /v1/admin/onboarding/{submission_id}/approve` and `PATCH /v1/admin/onboarding/{merchant_id}/approve`, both via `approve_onboarding_submission`) | Email | `send_merchant_welcome_email` (to `contact_email`) | always sends |
| | SMS | `render_welcome` (welcome, once per merchant ever) | `OASIS_SMS_ENABLED` + `OASIS_SMS_WELCOME_ENABLED` |
| Withdrawal confirmed `SUCCESS`: manual approval, automated policy, retry, provider callback, status refresh, reconciliation sweep (all reach the two `SUCCESS` branches in `disbursements.py`) | Email | `send_withdrawal_success_email` (to the notification address, falling back to `contact_email`) | `SEND_MERCHANT_WITHDRAWAL_EMAILS` |
| | SMS | `render_withdrawal_complete` (once per withdrawal) | `OASIS_SMS_ENABLED` + `OASIS_SMS_WITHDRAWAL_ENABLED` |

Recipients are unchanged: the same single business address and number each
message already used.

The invitation is never added to:

- pending, approved, processing, timed-out, needs-reconciliation, failed,
  rejected or reversed withdrawals (both senders now refuse anything but
  `SUCCESS` themselves)
- payout recipients or customers
- developer webhook payloads
- the Payout API, CEO/operator emails or Super Admin SMS
- checkout pages or the homepage

In-app notifications (`notifications` table) are not changed. The web app
does not display merchant notifications anywhere (`listMyNotifications` has no
caller), so adding the link there would reach no one.

## Duplicates

- SMS: the existing partial unique indexes (one welcome per merchant, one
  withdrawal confirmation per disbursement) plus provider idempotency keys.
- Withdrawal success email: now skipped when a `sent` `email_deliveries` row
  already exists for that disbursement. Two success branches running
  concurrently could still both pass this check before either logs its row.
  That is a narrow race, and closing it fully would need a unique constraint.
- Welcome email: unchanged. A repeated approval call sends it again, as it
  did before this feature.

## SMS length and cost

Measured with the production link (63 characters, all GSM-7):

| Message | Before | After |
| --- | --- | --- |
| Welcome | 123 chars, **1 part** | 221 chars, **2 parts** |
| Withdrawal confirmation (typical) | 165 chars, 2 parts | 263 chars, 2 parts |
| Withdrawal confirmation (TZS 999,999,999.99 amount and balance, 99,999.99 fee) | 181 chars, 2 parts | 279 chars, 2 parts (306 max) |

The welcome doubles in cost, but it is sent once per merchant. The withdrawal
confirmation costs nothing extra. No transaction detail is shortened to make
room.

## Previews

**SMS: welcome**

```
Karibu InfinityPay! Akaunti yako imeidhinishwa. Pokea malipo, tengeneza API keys na weka webhooks. Kwa msaada: 255747730270
Jiunge na jumuiya ya InfinityPay: https://chat.whatsapp.com/Ku5UwtoPC5ZFzeL2DXWSfg?s=cl&p=i&iam=2
```

**SMS: withdrawal confirmed**

```
Imethibitishwa. Umepokea TZS 50,000 kutoka InfinityPay. Ada: TZS 1,500. Salio baada ya muamala: TZS 161,638.13. Kumb: TXN-20261123-ABCD1234. Kwa msaada: 255747730270
Jiunge na jumuiya ya InfinityPay: https://chat.whatsapp.com/Ku5UwtoPC5ZFzeL2DXWSfg?s=cl&p=i&iam=2
```

**Email (both)**: after the existing button, a divider, the line "Join the
InfinityPay WhatsApp community for service updates, support and ideas:", an
outlined **Join WhatsApp Community** button, and the link written out. The
plain-text part carries the same line and the raw link. Both emails now send
a plain-text alternative.

## Rollback

Set `MERCHANT_COMMUNITY_WHATSAPP_URL` to empty. No deploy is needed. SMS
already queued keep the text they were queued with.
