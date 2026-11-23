# Payment tracking for billing integrations

For the support case "the customer paid, but our billing system never
activated their internet".

## The reference to share: `collection_id`

InfinityPay's stable id for a payment is the **`collection_id`**. It is not
new. It is already:

| Where | Field |
| --- | --- |
| Collections API create response (`POST /v1/collections`, `/wallet-push`, `/selcom-pesa`, `/qr`) | `collection_id` |
| Status response (`GET /v1/collections/{collection_id}`) | `collection_id` |
| Every `collection.*` webhook payload (`collection.success`, `collection.failed`, …) | `collection_id` |
| `GET /v1/transactions/{reference}` (`TransactionResponse`) | `collection_id` |

The Merchant Portal labels it **InfinityPay Payment ID**, and the Super Admin
transactions table shows it in a **Payment ID** column. Both can be searched by
it: the merchant search box takes the full UUID, and Super Admin has a Payment
ID filter (`GET /v1/admin/transactions?collection_id=`).

It is deliberately kept apart from the two other references a payment has:

| Name in the portal | Field | Whose it is |
| --- | --- | --- |
| InfinityPay Payment ID | `collection_id` | InfinityPay's. Share this one. |
| Your order reference | `reference` / `merchant_reference` in the API and webhooks | The integrator's own, exactly as they sent it |
| Provider Reference | `provider_reference` | The mobile-money provider's receipt id |
| Transaction Reference | `transactions.reference` (`TXN-…`) | InfinityPay's ledger row |

No new identifier was added, and no existing field changed name or meaning.

## The timeline

`GET /v1/merchant/transactions/{transaction_id}/tracking` (a merchant's own
transactions only; anything else returns 404) and
`GET /v1/admin/transactions/{transaction_id}/tracking` (Super Admin). Both are
read-only and built by `apps/api/app/services/payment_tracking.py` from
records the platform already keeps.

1. **Payment**: initiated (`collections.initiated_at`), then one of confirmed
   (`completed_at`), failed (`failed_at`, with the merchant-safe
   `failure_reason_message`), cancelled, reversed, or awaiting confirmation.
2. **Webhook delivery**: one entry per `webhook_events` row for this payment
   and merchant: queued, retrying, delivered or exhausted, plus the attempt
   count, the time of the last attempt, the merchant server's HTTP status, the
   delivery time, and when the worker will next retry. The next-retry time
   comes from the worker's own backoff schedule
   (`webhook_delivery.next_attempt_at`). It isn't stored.
3. **Service activation**: always **"Service activation not confirmed"**.

### What a delivered webhook proves

A delivered webhook proves **receipt only**: the merchant's server answered
HTTP 2xx. It does not prove the billing system activated anything. No billing
integration sends InfinityPay an activation acknowledgement, so the platform
has no evidence of activation, and the timeline never claims it. The billing
system controls activation and is where to check it, using the Payment ID.

### Limitations

- **Activation is never confirmed.** See below for what an acknowledgement API
  would need. None was built here.
- **Only the latest attempt per delivery is recorded.** `webhook_events` keeps
  `attempts`, `last_attempted_at` and `response_status_code` for the most
  recent attempt, not a row per attempt. Earlier attempts' times and statuses
  are not available. A Super Admin resend resets the same row (it is audited
  in `audit_logs`), so the timeline shows the state after the resend.
- **Reversal time is not recorded.** A reversed payment shows "Payment
  reversed" without a time, because there is no column for it.
- **Withdrawal webhooks are not linked.** `disbursement.*` events carry no
  `collection_id`, so tracking shows webhook delivery for customer payments
  only.

### Never returned

Webhook payloads, target URLs, signing secrets, provider raw responses,
provider status codes, free-text provider failure messages, or stack traces.

## If activation acknowledgement is ever added

This is not built. Before anyone builds it, the contract needs at least:

- **Authentication**: the merchant's own secret API key (`verify_api_key`)
  with a new, narrowly scoped permission. Never the webhook signing secret,
  which only ever authenticates InfinityPay to the merchant.
- **Ownership**: the `collection_id` must belong to the calling key's merchant.
  Another merchant's id must return the same 404 as a non-existent one, so ids
  cannot be probed.
- **Meaning**: an acknowledgement records the merchant's own claim that *they*
  activated the service, with their timestamp. It is shown as "confirmed by
  your billing system", never as something InfinityPay verified.
- **Idempotency**: repeated acknowledgements for one payment are a no-op. Only
  a payment that is `successful` can be acknowledged.
- **Storage**: a new, append-only table with a reviewed migration.

## Not included

There is no "retry payment" button, and no merchant-side webhook replay.
Super Admin keeps the existing audited resend
(`POST /v1/admin/merchant-webhooks/{id}/resend`). Signing, retries and
idempotency are unchanged.
