# Selcom Business Disbursement — Sandbox Test Accounts

**Sandbox only.** These three recipients come from Selcom's own Business
Disbursement API sandbox portal — they exist purely so an integrator can
exercise a real sandbox transaction without needing a live recipient. None
of them are secrets (Selcom hands them out to every sandbox integrator), but
they resolve to nothing in production — `SELCOM`/`TESTBANK`/`TESTWALLET`
must never appear as an accepted `recipient_fi_code` in merchant-facing
withdrawal validation. See §4 below and
[`docs/deployment-checklist.md`](./deployment-checklist.md#4-merchant-ui-validation-stays-strict).

## 1. Internal Transfer (Selcom to Selcom)

| Field | Value |
| --- | --- |
| Display format (with spaces, as shown in Selcom's portal) | `87747 38533 235` |
| API format (no spaces — what actually gets sent) | `8774738533235` |
| `recipientFiCode` | `SELCOM` |
| Recipient name | `Sandbox Selcom to Selcom` |

## 2. Bank

| Field | Value |
| --- | --- |
| Display format | `48423 18480 086` |
| API format | `4842318480086` |
| `recipientFiCode` | `TESTBANK` |
| Recipient name | `Sandbox Bank` |

## 3. Wallet

| Field | Value |
| --- | --- |
| Display format | `11405 54577 325` |
| API format | `1140554577325` |
| `recipientFiCode` | `TESTWALLET` |
| Recipient name | `Sandbox Wallet` |

## Running the direct sandbox test with these accounts

[`apps/api/scripts/test_selcom_disbursement_sandbox.py`](../apps/api/scripts/test_selcom_disbursement_sandbox.py)
has a `--preset` flag (`selcom` / `bank` / `wallet`) that fills in
`recipient_fi_code`/`recipient_account`/`recipient_name` from the table
above — no need to retype or reformat these account numbers by hand. The
account number is space-normalized automatically (spaces stripped) even if
pasted straight from the portal's display format.

```bash
cd apps/api

python scripts/test_selcom_disbursement_sandbox.py \
  --preset selcom \
  --amount 1000 \
  --purpose "Sandbox internal transfer test" \
  --remarks "InfinityPay sandbox test"

python scripts/test_selcom_disbursement_sandbox.py \
  --preset bank \
  --amount 1000 \
  --purpose "Sandbox bank withdrawal test" \
  --remarks "InfinityPay sandbox test"

python scripts/test_selcom_disbursement_sandbox.py \
  --preset wallet \
  --amount 1000 \
  --purpose "Sandbox wallet withdrawal test" \
  --remarks "InfinityPay sandbox test"
```

A manual `--recipient-fi-code`/`--recipient-account`/`--recipient-name`
passed alongside `--preset` overrides just that field — everything else in
[`docs/deployment-checklist.md`](./deployment-checklist.md#3-direct-selcom-sandbox-connectivity-test-script)
about this script (masked output, requires `SELCOM_BUSINESS_MODE=sandbox`,
IP-whitelist behavior) still applies unchanged.

## Selcom's whitelisted outbound IPs

As of 2026-08-21, the Selcom Business Disbursement API portal shows these
three static/public IPs as whitelisted (status Active, "Continue without IP
whitelisting" unchecked):

```
208.77.244.241
152.55.184.240
152.55.185.189
```

**No local development machine is whitelisted, and never will be** — only
Railway's static outbound IP is. Confirmed by direct comparison: a local
machine's public IP (`curl https://api.ipify.org`) does not match any of
the three above, while Railway's (checked via `railway ssh`, see below)
matched `152.55.184.240` exactly. Running the sandbox test script locally
will always fail with an IP-whitelist error (HTTP 403, or Selcom error code
`611`) regardless of credentials — this is structural, not a transient
propagation delay. Always run it via Railway SSH instead.

## Running the sandbox tests via Railway SSH (required)

`railway run` / `railway shell` execute **locally** with Railway's env vars
injected — they do NOT route traffic through Railway's network, so they
don't help here. Only `railway ssh` connects into the actual running
deployment instance, so a request from inside that session genuinely
egresses via Railway's whitelisted static IP.

Prerequisites (one-time): install the Railway CLI
(`npm install -g @railway/cli`), `railway login`, link this project
(`railway link` — the Railway dashboard project is internally named
"content-manifestation", not "infinity-africa"; confirm with `railway
status` that `repo: BizLink-Africa/infinity-africa` and the service URL
match), and register a local SSH public key
(`railway ssh keys add -k <path-to-.pub> -n "<name>"` — only ever share the
`.pub` file, never the private key). The first `railway ssh` connection
prompts to accept Railway's SSH host key interactively — accept it once
per machine.

**Verify the outbound IP first:**

```bash
railway ssh -- python -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org').read().decode())"
```

(the container has no `curl` — use the Python one-liner above, not
`curl https://api.ipify.org`). The result must be one of the three IPs
listed above, or Selcom testing will still fail.

**Verify Selcom config is loaded correctly** (safe — prints only booleans
and the non-secret sandbox base URL, no key material):

```bash
railway ssh -- python -c "from app.config import get_settings; s = get_settings(); print('mode:', s.selcom_business_mode); print('api_key_present:', bool(s.selcom_business_api_key)); print('private_key_present:', bool(s.selcom_business_private_key_base64)); print('account_number_present:', bool(s.selcom_business_account_number)); print('sandbox_base_url:', s.selcom_business_sandbox_base_url)"
```

**Run the three presets** — the container's working directory is already
`apps/api` (confirmed via `railway ssh -- pwd` / `ls`, which show
`scripts/`, `app/`, `tests/` directly), so the commands are unchanged from
running locally, just prefixed with `railway ssh --`:

```bash
railway ssh -- python scripts/test_selcom_disbursement_sandbox.py \
  --preset selcom --amount 1000 \
  --purpose "Sandbox internal transfer test" \
  --remarks "InfinityPay sandbox test"

railway ssh -- python scripts/test_selcom_disbursement_sandbox.py \
  --preset bank --amount 1000 \
  --purpose "Sandbox bank withdrawal test" \
  --remarks "InfinityPay sandbox test"

railway ssh -- python scripts/test_selcom_disbursement_sandbox.py \
  --preset wallet --amount 1000 \
  --purpose "Sandbox wallet withdrawal test" \
  --remarks "InfinityPay sandbox test"
```

If the container's working directory ever isn't the app root, wrap it:
`railway ssh -- bash -lc "cd apps/api && python scripts/test_selcom_disbursement_sandbox.py ..."`.

### Interpreting the result

| Response | Meaning | Next step |
| --- | --- | --- |
| HTTP 403, or Selcom code `611` (`is_ip_whitelist_error: True`) | Outbound IP isn't whitelisted, or the whitelist setting wasn't saved/applied on Selcom's side | Re-check the outbound IP command above against the whitelist list; don't touch signing code |
| `{"success": false, "message": "Invalid signature."}` (HTTP 401) | IP whitelist is fine — Selcom received and evaluated the request. The RSA signature itself doesn't verify | Regenerate the signing key from Selcom's Business portal (Signing Keys → Regenerate Signing Key) rather than self-generating a keypair — see below, this was the confirmed root cause and fix on 2026-08-21 |
| `SUCCESS` / result code `000`, or `INPROGRESS` / `111` / `927` | IP whitelist and signature are both working — real Selcom business logic is now being evaluated | Confirmed 2026-08-21 for `INPROGRESS`/`111` — see "Real sandbox response shape" below. `parsing.py` already handles this shape |
| `AMBIGUOUS` / `999` | Selcom itself is unsure of the outcome (needs reconciliation) | Capture the shape and verify the parser's ambiguous-status handling |

**"Invalid signature" root cause, confirmed 2026-08-21:** an earlier
self-generated keypair was used, but Selcom's Business Disbursement API
portal manages its **own** signing keypair per account — there's no flow
for uploading a merchant-generated public key. Fixed via the portal's
**Signing Keys** section → **Regenerate Signing Key**, which generates a
new keypair on Selcom's side and hands back the new private key as a
one-time download (their own UI warns "it cannot be recovered after
leaving this page" — save it somewhere durable immediately). That
downloaded file is the new `SELCOM_BUSINESS_PRIVATE_KEY_BASE64` value —
base64-encode its raw bytes (it's already PEM text) and set it in both
local `apps/api/.env` and Railway's `web` service Variables, then
redeploy:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("<path-to-downloaded-.pem>")) | Set-Clipboard
```

After this fix, all three presets reached real Selcom business logic —
signature verification passing, not failing — confirming this was the
correct fix. Do not attempt to self-generate a keypair for this API again;
always use the portal's Regenerate Signing Key flow.

## 4. Sandbox-only — never a production destination

These three `recipientFiCode` values (`SELCOM`, `TESTBANK`, `TESTWALLET`)
and account numbers are for the direct sandbox test script only:

- The Merchant Portal withdrawal form and `POST /v1/merchant/withdrawals`
  are not changed to accept them.
- Wallet/mobile withdrawals still require a real `255XXXXXXXXX` phone
  format (no `+`) via `app/core/phone.py::normalize_tz_phone()`.
- Bank withdrawals still require a real, configured bank destination code.

## Real sandbox response shape — confirmed 2026-08-21

`app/services/selcom_business/parsing.py` is updated and tested against
two real captured responses (see
`apps/api/tests/test_selcom_business_parsing.py`'s
`REAL_PROCESSING_RESPONSE`/`REAL_FAILED_RESPONSE` fixtures):

```json
// bank preset — processing (HTTP 200)
{
  "success": true, "error_code": 1,
  "message": "Transaction processed successfully.",
  "result": "INPROGRESS", "resultcode": "111",
  "data": {
    "trans_id": "INF-...", "selcom_receipt": "SBS-...", "status": "ACCEPTED",
    "amount": 1300, "principal_amount": 1000, "total_charges": 300,
    "charges_summary": "Fee 231, VAT 46, Excise Duty 23", "currency": "TZS"
  }
}

// selcom preset — failed (HTTP 400, raised as SelcomAPIError before
// reaching parse_transaction_result — see live_client.py)
{
  "success": false, "error_code": -40,
  "message": "Invalid account number for the provided bank/FI code.",
  "result": "FAIL", "resultcode": "-40", "data": []
}
```

Two things the earlier guessed field names got wrong (now fixed): the
transaction id and receipt are nested inside `data`, not top-level, and the
real "processing" resultcode is `"111"`, not the previously guessed
`"001"`. `data` is `[]` (not a dict) on failure — the parser handles both
shapes. `"927"` (processing) and `"999"` (ambiguous) remain
Selcom-documented-but-not-yet-observed codes, included on that basis, not
guessed.

Still unconfirmed: a real `SUCCESS`/`000` (fully completed, not
`INPROGRESS`) response, and a real `AMBIGUOUS`/`999` response — the parser
handles both per Selcom's documented codes, but hasn't been checked
against a real example of either yet.

The `selcom` preset's specific "Invalid account number for the provided
bank/FI code." result is Selcom's own business-logic response to that
sandbox sample account — not an integration bug on our side, and not
investigated further here (the `bank` preset's success already proves the
integration itself works end-to-end).

**`wallet` preset — also confirmed successful (2026-08-21).** Same shape as
the `bank` preset above (`result: INPROGRESS`, `resultcode: 111`, receipt
correctly parsed), no new field names — just a different fee schedule
(`total_charges: 500` vs. `bank`'s `300`, i.e. `principal_amount: 1000` →
`amount: 1500`). All three presets have now been run successfully at least
once against real Selcom sandbox infrastructure.

## Real end-to-end pipeline test — confirmed 2026-08-21

Beyond the direct sandbox script (which bypasses all merchant-facing
validation), the actual backend pipeline was exercised for real: a real
platform fallback pricing rule was created
(`POST /v1/admin/pricing-rules/platform-fallback`), a real quote was
computed (`quote_withdrawal_fee`, correctly applied the new fallback rule),
a real withdrawal was submitted (`execute_disbursement` →
`PENDING_ADMIN_APPROVAL`, fee snapshot frozen, Selcom not called), and a
real Super Admin approval was run (`approve_disbursement`) — which does
call Selcom for real. Since `DestinationCode` (the real, merchant-facing
enum) deliberately doesn't include `TESTBANK`/`TESTWALLET`, this used a
real code (`CRDB`) with a fabricated account number, which Selcom's
sandbox correctly rejected the same way the `selcom` preset's account was
rejected — a real, informative `FAILED` result, not a code bug.

This surfaced two real bugs in `app/services/disbursements.py`'s
`_fail_and_reverse` (now fixed, with regression tests in
`apps/api/tests/test_admin_withdrawals.py`):

1. The failure reason was never persisted onto `disbursements.admin_status_reason`
   — it only ever reached the audit log and the merchant notification text.
2. On the `SelcomAPIError` exception path specifically (as opposed to a
   clean `result.status == "failed"`), `_fail_and_reverse` was called
   without `raw_response` at all — `exc.provider_response_body` (added in
   an earlier session specifically to surface Selcom's real error body) was
   being silently dropped instead of reaching `disbursements.selcom_raw_response`.

Ledger correctness was independently verified: reservation and reversal
are exactly symmetric (`amount + fee_amount` both ways), confirmed by
comparing wallet balance before/after a full reserve → Selcom rejection →
reverse cycle.
