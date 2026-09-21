# Withdrawal Production Pilot Checklist

> **Superseded (2026-08-28):** the pilot's `WITHDRAWAL_PILOT_MODE`/
> `WITHDRAWAL_PILOT_MAX_AMOUNT_TZS` cap described here has been replaced by
> permanent, always-on production limits (`MIN_WITHDRAWAL_AMOUNT_TZS`,
> `MAX_WITHDRAWAL_AMOUNT_TZS`, `DAILY_WITHDRAWAL_LIMIT_TZS`) as the project
> moves from this pilot to MVP launch — see
> [`docs/MVP_LAUNCH_CHECKLIST.md`](./MVP_LAUNCH_CHECKLIST.md). **Remove
> `WITHDRAWAL_PILOT_MODE`/`WITHDRAWAL_PILOT_MAX_AMOUNT_TZS` from Railway**
> (they're no longer read by any code — `extra="ignore"` means leaving them
> set is harmless but misleading) and set the three new vars instead. The
> rest of this document (guardrails, test flow, stop conditions) still
> reflects real, currently-accurate architecture — only §3/§6's specific
> env vars are stale.

A **controlled internal pilot**, not a public launch — one approved merchant,
one verified real destination account, a small capped amount, manual
Super Admin approval and observation on every transaction. For the general
pricing/approval mechanics see
[`docs/withdrawal-pricing-and-approval.md`](./withdrawal-pricing-and-approval.md);
for the Selcom sandbox verification history see
[`docs/selcom-sandbox-test-accounts.md`](./selcom-sandbox-test-accounts.md).

## 1. Pre-pilot checks

- [ ] Full merchant withdrawal flow verified end-to-end in sandbox: quote,
      submit, approve, reject, request-info (done — see
      `docs/selcom-sandbox-test-accounts.md` and
      `docs/withdrawal-pricing-and-approval.md`'s "Real end-to-end pipeline
      verification" section)
- [ ] Desktop and mobile UI verified (done — 390px viewport, no clipping,
      hamburger nav, horizontal-scroll tables working correctly)
- [ ] Backend test suite green: `python -m pytest` (414+ passing as of this
      checklist's authoring)
- [ ] `python -m ruff check .`, `npm run lint --workspace=apps/web`,
      `npx tsc --noEmit`, `npm run build --workspace=apps/web` all clean
- [ ] Selcom Business signing key was generated **via Selcom's own Business
      portal** (Signing Keys → Regenerate Signing Key), never
      self-generated — see §6 below
- [ ] Railway's static outbound IP is confirmed whitelisted by Selcom for
      the **production** environment specifically (sandbox whitelisting is
      a separate approval — confirm production separately, don't assume it
      carries over)
- [ ] `WITHDRAWAL_PILOT_MODE=true` and `WITHDRAWAL_PILOT_MAX_AMOUNT_TZS`
      set in Railway (§5)

## 2. Required approvals

- [ ] Explicit internal go-ahead from whoever owns the Selcom relationship
      to move `SELCOM_BUSINESS_MODE` from `sandbox` to `live` in production
- [ ] The one pilot merchant has explicitly agreed to participate and
      understands this is a real-money test
- [ ] A specific Super Admin is designated to personally approve/monitor
      every pilot transaction (not left to whoever happens to be online) —
      confirmed 2026-08-22: same account as the pilot merchant above (on
      file). Flagging this plainly: the same person submitting
      the withdrawal is the one approving it, so the approval step isn't
      providing independent oversight for this pilot the way it would with
      a separate merchant/approver. Acceptable for a single-person internal
      test of the mechanics, but not a substitute for real dual-control once
      the pilot expands to actual third-party merchants.

## 3. Required environment variables (Railway backend only)

Never set any of these in Vercel/frontend — confirmed clean as of this
checklist (`rg -i selcom apps/web` finds zero references to any
`SELCOM_BUSINESS_*`/`SELCOM_API_*`/`SELCOM_VENDOR_*` variable anywhere in
the frontend).

```
SELCOM_BUSINESS_MODE=live
SELCOM_BUSINESS_API_KEY=<issued by Selcom for the production account>
SELCOM_BUSINESS_PRIVATE_KEY_BASE64=<from Selcom's Business portal — see §6>
SELCOM_BUSINESS_ACCOUNT_NUMBER=<production account number>
SELCOM_BUSINESS_PRODUCTION_BASE_URL=https://api.selcom.business/v1
SELCOM_BUSINESS_TIMEOUT_SECONDS=30

WITHDRAWAL_PILOT_MODE=true
WITHDRAWAL_PILOT_MAX_AMOUNT_TZS=1000
```

`SELCOM_BUSINESS_PRODUCTION_BASE_URL` and `SELCOM_BUSINESS_TIMEOUT_SECONDS`
already default to the values above in `app/config/settings.py` — only
`SELCOM_BUSINESS_MODE`, the API key, the private key, and the account
number are things Railway doesn't already have real values for going into
the pilot.

## 4. Test merchant details (confirmed 2026-08-22)

| Field | Value |
|---|---|
| Merchant business name | Merchant |
| Merchant contact email | p•••••••••8@gmail.com (on file — see internal record) |
| Merchant ID (UUID) | `c9e9bc9a-e0d9-4712-ba0e-d575fb7d2fbd` |
| Confirmed `status = active`, `kyc_status = verified`? | yes (verified directly against production DB) |
| Wallet balance at confirmation time | comfortably above the 1,000 TZS pilot cap |

## 5. Test destination account

Merchant intends to test **more than one** destination type during the
pilot — Selcom Pesa (`destination_code=SELCOM`) and one or more mobile
wallets (`MPESA`/`AIRTELMONEY`/`HALOPESA`/`MIXXBYYAS`/`TTCLPESA`). This is
broader than this checklist's original "one verified real destination
account only" scope statement (§ intro) — noted here explicitly so it's a
conscious choice, not scope creep that slipped in unnoticed. Recommend
still doing them **one at a time**, fully reconciling each (§10) before
moving to the next, rather than firing them off together.

| Field | Value |
|---|---|
| Method(s) | Selcom Pesa + mobile wallet(s) (to be run individually) |
| `destination_code` | `SELCOM` for the first test; specific telco code(s) for subsequent tests |
| Destination account/phone | _fill in per test, masked in any shared doc_ |
| Destination display name | _fill in per test_ |
| Confirmed this is a **real, verified** account the merchant actually controls | _yes/no — confirm before each test_ |

## 6. Amount limit

Enforced in code, not just by convention —
`app/services/disbursements.py::_check_pilot_amount_limit()`, called from
`execute_disbursement()` (the real merchant withdrawal submission path,
shared by both `/v1/merchant/withdrawals` and the legacy
`/v1/disbursements/*` routes). While `WITHDRAWAL_PILOT_MODE=true`, any
withdrawal request above `WITHDRAWAL_PILOT_MAX_AMOUNT_TZS` is rejected with
a `409 withdrawal_restricted` error and a clear message
("Withdrawals are currently limited to `<limit>` TZS during the production
pilot...") — before any fee calculation, balance check, or ledger
reservation happens. See §9 for the regression tests covering this.

**Turn `WITHDRAWAL_PILOT_MODE` off (or raise the limit) only after**:
successful pilot reconciliation (§10) and explicit approval to expand —
never leave pilot mode on indefinitely as a substitute for real
per-merchant pricing/limits, and never treat it as the only real
safeguard (it's an extra cap on top of everything in §7, not a
replacement for any of it).

## 7. Guardrails already in place (verified, not newly added except §6's cap)

All of the following were confirmed already implemented and covered by
existing tests before this pilot checklist was written — no other new
guardrail code was needed:

| Guardrail | Where enforced | Confirmed |
|---|---|---|
| Super Admin approval required | `approve_disbursement()` only reachable via `/v1/admin/withdrawals/{id}/approve`, `require_super_admin`-gated | ✅ |
| Merchant must be active + KYC verified | `_check_merchant_is_verified()` in `execute_disbursement()` | ✅ |
| No open high-risk fraud alert | `_check_no_open_high_risk_alerts()` in `execute_disbursement()` | ✅ |
| Available balance checked | `get_wallet_balance()` vs. `total_reserved_amount` in `execute_disbursement()` | ✅ |
| Fee quote available before submit | `POST /v1/merchant/withdrawals/quote` — read-only, no side effects | ✅ |
| Fee snapshot frozen at submission | `pricing_snapshot_json` + individual fee columns written once in `execute_disbursement()`, never recalculated on approval | ✅ |
| Ledger reservation only on approval | `post_disbursement_entries()` called only from `_reserve_and_run_disbursement_provider()`, itself only called by `approve_disbursement()` | ✅ |
| Selcom called only after approval | `execute_disbursement()` never imports `get_selcom_business_client` at all — regression-tested (`test_withdrawal_request_creates_pending_admin_approval_and_never_calls_selcom`) | ✅ |
| Failure reversal | `_fail_and_reverse()` — reverses the full reservation, verified to net exactly to zero movement; made resilient to a partial-save failure this session (`test_selcom_raw_response_save_failure_still_reaches_failed_status`) | ✅ |
| Audit log on every terminal state | `write_audit_log()` calls throughout `disbursements.py` | ✅ |
| Merchant notification on every terminal state | `notify_merchant()` — success, failure, rejection, and info-requested all covered (rejection was missing until this session, now fixed and covered by `NotificationType` enum + `test_notification_types.py`) | ✅ |
| Pilot amount cap | `_check_pilot_amount_limit()` — **new this checklist**, see §6 | ✅ |

## 8. Selcom production signing-key process

**Confirmed the hard way this project cycle** (see
`docs/selcom-sandbox-test-accounts.md`'s "Invalid signature" root-cause
writeup): Selcom's Business Disbursement API manages its own signing
keypair per account — there is no flow to upload a merchant-generated
public key. A self-generated keypair will never verify, no matter how
correct the request signing code is.

1. In Selcom's Business portal, go to **Signing Keys** → **Regenerate
   Signing Key**. This is a one-time download — Selcom's own UI warns it
   cannot be recovered after leaving the page, so save it immediately.
2. Base64-encode the downloaded file's raw bytes (it's already PEM text):
   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("<path-to-downloaded-key>")) | Set-Clipboard
   ```
3. Set `SELCOM_BUSINESS_PRIVATE_KEY_BASE64` in Railway's `web` service →
   Variables to that value. Never commit it, never put it in Vercel, never
   print it in a terminal or log.
4. Railway redeploys automatically on env var save. **Redeploy is required
   for a new env var to take effect** — an already-running instance
   doesn't pick it up.
5. Regenerating the key **invalidates the previous one immediately** —
   only do this when you're ready to update Railway right away, not ahead
   of time.

## 9. Tests added for the pilot guardrail

`apps/api/tests/test_disbursements.py`:

- `test_pilot_mode_blocks_amount_above_max` — `WITHDRAWAL_PILOT_MODE=true`,
  a withdrawal above the limit gets `409 withdrawal_restricted` with the
  limit amount in the message, no disbursement row created, balance
  untouched
- `test_pilot_mode_allows_amount_at_max` — exactly at the limit succeeds
- `test_pilot_mode_allows_amount_below_max` — below the limit succeeds
- `test_pilot_mode_off_does_not_limit_amount` — `WITHDRAWAL_PILOT_MODE=false`
  (the default) means a large withdrawal is unaffected even if
  `WITHDRAWAL_PILOT_MAX_AMOUNT_TZS` happens to be set

## 10. Production pilot test flow

### Merchant

1. Log in to the Merchant Portal.
2. Open **Withdrawals**.
3. Choose the verified destination method/account (§5).
4. Enter a small amount (at or under the pilot limit).
5. Click **Calculate Charges** and confirm the fee breakdown looks right.
6. Click **Confirm Withdrawal**.
7. Confirm the new row shows **Pending Approval** in Withdrawal History —
   not Processing, not Successful.

### Super Admin

1. Log in to the Super Admin console.
2. Open **Withdrawals** → find the pending request in the Approval Queue.
3. Review merchant, destination, amount, fee breakdown carefully — this is
   real money.
4. Click **Approve**.
5. Watch the response — this is the real Selcom production call, not a
   sandbox one.
6. Confirm the resulting status (`SUCCESS`/`PROCESSING`/`FAILED`/etc.) and,
   if present, the receipt/`selcom_trans_id`.
7. Confirm the merchant's own Withdrawal History reflects the same final
   status.

### Post-pilot reconciliation

1. Check the transaction's status directly in Selcom's own Business
   portal/dashboard.
2. Compare against InfinityPay's own `disbursements` row status.
3. Confirm the `ledger_entries` for this transaction are balanced (debits
   == credits) and match the expected amount + fee split.
4. Confirm the merchant wallet balance reflects exactly what's expected —
   no drift.
5. Confirm the merchant received the expected notification(s).
6. Record the Selcom receipt/reference number somewhere durable (this
   checklist, a ticket, wherever the team tracks pilot results).
7. **Separately confirm with the actual recipient** that funds physically
   arrived — a `SUCCESS` status from Selcom is not itself proof of
   settlement; only confirm the pilot fully succeeded once this is
   checked.

## 11. Stop conditions — halt the pilot immediately if any of these occur

- Fee math doesn't match what `docs/withdrawal-pricing-and-approval.md`
  documents
- Wallet balance doesn't reconcile exactly (before/after, or against the
  ledger entries)
- Any sign of a duplicate Selcom call for the same withdrawal (check
  `provider_reference`/`selcom_trans_id` uniqueness and Selcom's own
  transaction history)
- A resolved withdrawal has no receipt/status where one is expected
- The merchant can't see their withdrawal's current status
- A Super Admin can't approve or reject a pending withdrawal
- A failed/rejected withdrawal's ledger reversal doesn't net to zero
- Selcom returns an error not covered by `parsing.py`'s known
  success/processing/ambiguous/failed handling
- **Any Selcom credential, Supabase service role key, or private key
  appears anywhere in the browser** — page source, DevTools console,
  Network tab request/response bodies, or any frontend log

If any of these happen: stop approving new withdrawals, do not set
`WITHDRAWAL_PILOT_MODE=false` (keep the cap in place while investigating),
and treat it as an incident — root-cause before resuming, not just retry.
