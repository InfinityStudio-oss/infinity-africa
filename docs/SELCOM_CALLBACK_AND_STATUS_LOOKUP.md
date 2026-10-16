# Payment confirmation: the callback, the status lookup, and how to verify both

Written after investigating Kinange Wifi (merchant `27607535`) on
2026-10-16. Two separate defects surfaced, one of which affects every
merchant on the platform.

## Finding 1 — the status lookup required a parameter nothing else did

`GET /v1/collections/{id}` and `POST /v1/collections/{id}/refresh-status`
required a `merchant_id` query parameter. The four *create* endpoints
beside them did not: they call `_resolve_merchant_id` and take the
merchant from the API key. A partner could therefore start a payment and
then be refused when asking what happened to it.

The published integration guide shows the lookup with no query string at
all, so a partner following our own documentation received `422`.

Production, 15 October: Kinange made 70 API requests. Seven were
`POST /v1/collections/wallet-push` and returned `202`. **Sixty-one were
`GET /v1/collections/{uuid}` and every one returned `422`** — five
collections, polled up to 25 times each, roughly every four seconds,
never once answered.

The ids were well-formed UUIDs, and an invalid key returns `401` on this
route rather than `422`, so their credential was fine and `merchant_id`
was the only remaining input that could fail.

**Fixed** by using `_resolve_merchant_id` on both routes. This tightens
scoping rather than loosening it — the merchant now comes from the
credential instead of the URL. A key naming a different merchant is still
rejected by `authorize_merchant_action`, cross-merchant reads are still
`404`, and sandbox keys still cannot see live data. See
`tests/test_collection_status_lookup_contract.py`.

### Verifying the fix

Read-only, no payment required. With a live key for any merchant that has
at least one collection:

```
GET https://api.infinitypay.me/v1/collections/{a_known_collection_id}
Authorization: Bearer sk_live_...
```

- **Before the fix:** `422`, `{"loc": ["query","merchant_id"], "msg": "Field required"}`
- **After:** `200` with the collection status

Then confirm the guard rails still hold, which matters more than the fix
itself:

```
# another merchant's collection id -> must be 404, never 200
GET /v1/collections/{someone_elses_collection_id}

# explicitly claiming a different merchant -> must be 403
GET /v1/collections/{your_collection_id}?merchant_id={another_merchant}
```

### Rolling back

Revert the two signatures in `app/routers/collections_api.py` to
`merchant_id: uuid.UUID` and redeploy. Nothing persists and no data
changes, so a rollback costs only the return of the original `422`.

## Finding 2 — Selcom sends no signature, so no callback has ever been processed

**3,825 inbound Selcom callbacks between 22 August and 16 October. Zero
processed.** Every one recorded as `invalid or missing signature`.

The captured `raw_headers` on recent deliveries explain it: Selcom's
callbacks carry **no signature header at all**. Not a wrong scheme — no
`Authorization`, no `Digest`, no `X-Signature`, nothing. The scheme in
`signer.py` was inferred from Selcom's *outbound* auth and has never
matched anything they actually send.

**Consequence, platform-wide:** every collection on this platform is
confirmed by the reconciliation sweep polling Selcom, not by the
callback. Kinange's two real payments took 78 and 108 seconds from
creation to credit. That delay is this, and it applies to every merchant.

### The already-built fix

`SELCOM_CHECKOUT_ACCEPT_UNSIGNED_CALLBACKS` (default `false`).

It does **not** make us believe an unsigned payload. The handler ignores
everything a callback claims — status, amount, result code — and uses it
only to learn which order to ask Selcom about, over our own authenticated
connection. An unsigned callback becomes a "look at this one now" nudge
for a lookup that already happens on a timer; the answer still comes from
Selcom directly.

It is rate limited per event id and per caller address, and only acts on
a collection still `processing`. A forged callback can at most make us
re-ask about a payment we were already going to ask about.

### Turning it on, controlled

1. Confirm the current state first: Super Admin → Webhooks shows the
   inbound callback log. Every row should read `invalid or missing
   signature`. If any are processed, this finding is stale — stop and
   re-check.
2. Set `SELCOM_CHECKOUT_ACCEPT_UNSIGNED_CALLBACKS=true` on the API
   service in Railway and redeploy.
3. Take **one** small real payment on a non-Tigo number (TZS 1,000 so it
   clears every operator floor).
4. Watch for, in order:
   - the inbound callback row processing instead of failing
   - `collection.credited` in the audit log within a few seconds of the
     prompt being approved, rather than 60–120 seconds
   - exactly **one** transaction row and **one** wallet credit
   - one `collection.success` webhook to the merchant
5. Compare the wallet balance before and after. It must move by the net
   amount exactly once.

The thing to watch for is duplication, not speed. The callback path and
the reconciliation sweep can now both reach the same collection at the
same moment; `resolve_collection`'s guard treats any non-`processing`
collection as already resolved, which is what makes that safe. Step 4's
"exactly one" checks are the ones that matter.

### Rolling back

Set `SELCOM_CHECKOUT_ACCEPT_UNSIGNED_CALLBACKS=false` and redeploy.
Callbacks go back to being rejected and reconciliation resumes being the
only confirmation path — which is the behaviour the platform has had
since August. No data changes, nothing to undo, and no payment is
affected either way.

## Retrying a merchant webhook, safely

Never replay automatically, and never before checking whether the partner
already acted on it.

1. Confirm what we sent and what came back:
   ```sql
   select id, event_name, status, attempts, response_status_code,
          delivered_at, created_at
   from webhook_events
   where merchant_id = '<merchant uuid>'
   order by created_at desc;
   ```
   A `200` in `response_status_code` means their server accepted the
   delivery. **It does not mean they created a voucher or activated a
   customer** — only their logs show that.
2. Ask the partner whether the payment was processed on their side,
   quoting the `collection_id` and `merchant_reference` from the payload.
3. If they confirm it was **not** processed, and only then, requeue that
   one event by setting it back to `pending`:
   ```sql
   update webhook_events set status = 'pending'
   where id = '<the one event id>';
   ```
   The delivery sweep picks it up on its next tick. Requeue one event at
   a time and confirm each before the next.
4. If their handler is not idempotent, do not requeue at all — ask them
   to fix that first. A receiver should acknowledge only after durable
   acceptance and then activate asynchronously with duplicate protection.

Requeuing a webhook never touches money: `webhook_events` is a delivery
log, and nothing in the payment or ledger path reads it.

## What was already correct

- **Kinange's webhook URL** was already configured on merchant
  `27607535`, with all events enabled. No configuration change was needed.
  (`KISINGA WiFi` is a different merchant — do not confuse the two.)
- **Operator minimums.** Mixx/Tigo TZS 1,000, everything else TZS 200,
  enforced before any collection, transaction or Selcom call is created,
  with an error naming the network and suggesting another. A TZS 200 or
  TZS 500 package simply cannot be paid on a Tigo number; the partner
  must offer those on another network or price them at TZS 1,000.
- **No double credits.** Kinange's two real payments each produced
  exactly one transaction and one wallet credit, with the expected
  `balance_after` progression.

## On the reconciliation interval

Lowering `SELCOM_CHECKOUT_RECONCILE_INTERVAL_SECONDS` does not fix either
defect. It would not have changed the `422`, and the merchant webhook was
not rejected — it was delivered with a `200`. All it changes is how long
a payment sits unconfirmed *because its callback was discarded*. Finding
2 removes that wait; the interval only shortens it.
