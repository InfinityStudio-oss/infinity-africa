# Deployment Checklist — Frontend/Backend Live Testing

Status checklist for getting the deployed `apps/web` (Vercel) and `apps/api`
(Railway) talking to each other and to Selcom's sandbox, and for testing the
Selcom Business Disbursement API directly while its sandbox UI sample
accounts are blocked. For the full Selcom go-live procedure (Static Outbound
IP, whitelisting, credentials, response-shape verification) see
[`docs/selcom-live-go-live.md`](./selcom-live-go-live.md); for general
env-var setup see [`docs/backend-setup.md`](./backend-setup.md).

## 1. CORS — letting the deployed frontend call the deployed backend

The backend reads exactly one env var for this: **`CORS_ORIGINS`**
(`app/config/settings.py`'s `cors_origins_raw` field, `validation_alias`
`CORS_ORIGINS`). `FRONTEND_ORIGIN`/`ALLOWED_ORIGINS`/any other name is not
recognized and has no effect. `app/main.py` passes it straight to
`CORSMiddleware(allow_origins=settings.cors_origins, allow_credentials=True, ...)`.

**Accepted formats** — either works, pick whichever is easier to type
correctly into Railway's env var UI:

- JSON array: `CORS_ORIGINS=["https://infinitypay.me","https://www.infinitypay.me"]`
- Comma-separated: `CORS_ORIGINS=https://infinitypay.me,https://www.infinitypay.me`

**Never `"*"` in a deployed environment.** `allow_credentials=True` means a
wildcard origin is both meaningless (browsers reject the combination) and a
real credential-leak risk. `Settings` refuses to construct at all if
`CORS_ORIGINS` contains `"*"` while `ENVIRONMENT` isn't `"development"` — the
app won't start with that combination in Railway, by design.

### Railway value to set

Replace the placeholders with the actual deployed URLs once known — the
Vercel production domain, `www` alias if used, and (optionally, for testing
Vercel preview deployments against the live backend) the preview URL
pattern:

```
CORS_ORIGINS=["https://infinitypay.me","https://www.infinitypay.me","https://<vercel-preview-url>.vercel.app"]
```

Local dev keeps the `.env.example` default: `CORS_ORIGINS=["http://localhost:3000"]`.

After changing this in Railway, redeploy — env var changes don't apply to an
already-running instance.

### Verifying it — CORS preflight check

Run this against the deployed Railway API URL, with `Origin` set to the
actual deployed frontend origin:

```bash
curl -i -X OPTIONS "$API_URL/v1/merchant/me" \
  -H "Origin: https://infinitypay.me" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: authorization,content-type"
```

Expected response:

- `access-control-allow-origin` header is present and **exactly matches**
  the `Origin` sent (`https://infinitypay.me`) — CORS middleware always
  echoes back the specific matched origin, never a wildcard, when
  `allow_credentials=True`.
- `access-control-allow-credentials: true` is present.
- Status is `200 OK` (FastAPI/Starlette answers `OPTIONS` preflights
  directly; the route itself is never invoked).

If `access-control-allow-origin` is **missing** (`null`/absent), the
`Origin` sent doesn't match anything in `CORS_ORIGINS` — check the exact
value set in Railway (including `https://` and any `www.` variant) against
what the browser is actually sending. If it's `*`, that means
`CORS_ORIGINS` still contains a wildcard somewhere, which contradicts the
startup guard above — check `ENVIRONMENT` is actually set to something
other than `development` on Railway.

Once this returns the right origin, retest the actual failing frontend
request in a real browser (Network tab → the failed request → check for a
CORS error banner in the console, which disappears once this is fixed).

## 2. Local Selcom sandbox credentials — for direct backend testing only

Selcom sandbox UI testing is currently blocked by the sandbox's sample
account formats. To test signing/connectivity/IP-whitelisting independently
of that UI, add Selcom sandbox credentials to **`apps/api/.env`** (local
only) and use the direct test script below — never the merchant-facing
Withdrawal form for this, since that form's validation is intentionally not
relaxed (see §4).

```
SELCOM_BUSINESS_MODE=sandbox
SELCOM_BUSINESS_API_KEY=
SELCOM_BUSINESS_PRIVATE_KEY_BASE64=
SELCOM_BUSINESS_ACCOUNT_NUMBER=
SELCOM_BUSINESS_SANDBOX_BASE_URL=https://sandbox.selcom.business
SELCOM_BUSINESS_PRODUCTION_BASE_URL=https://api.selcom.business/v1
SELCOM_BUSINESS_TIMEOUT_SECONDS=30
```

**Important:**

- `apps/api/.env` is git-ignored — never commit it.
- Never print these values (the test script below only ever prints masked
  summaries — see its docstring).
- Never expose any `SELCOM_BUSINESS_*` variable to `apps/web`/Vercel or any
  frontend code path. Selcom credentials are backend-only, full stop — see
  [`docs/selcom-live-go-live.md`](./selcom-live-go-live.md#selcom-credential-placement).
- Selcom's sandbox enforces the same source-IP allowlist as production (see
  [`docs/selcom-live-go-live.md`](./selcom-live-go-live.md#why-this-waits)).
  Only Railway's static outbound IP has been shared with Selcom so far — a
  local run against real sandbox credentials may still fail with a 611/403
  IP-whitelist error even with correct credentials and signing. That's a
  distinct, informative result (see the script's output below), not a bug
  in this codebase.

## 3. Direct Selcom sandbox connectivity test script

[`apps/api/scripts/test_selcom_disbursement_sandbox.py`](../apps/api/scripts/test_selcom_disbursement_sandbox.py)
calls `SelcomBusinessClient.process_transaction()` directly — the same call
site `app/services/disbursements.py`'s Super Admin approval path uses in
production — bypassing merchant-facing phone/account format validation
entirely, so Selcom's sandbox sample values (e.g. `TESTBANK`/`TESTWALLET`,
which the real merchant UI provider list would reject) can be used purely
for connectivity/signing testing.

```bash
python apps/api/scripts/test_selcom_disbursement_sandbox.py \
  --recipient-fi-code TESTBANK \
  --recipient-account 8774738353235 \
  --recipient-name "Sandbox Test" \
  --amount 1000 \
  --purpose "Sandbox withdrawal test" \
  --remarks "InfinityPay sandbox direct test"
```

For Selcom's own known-good sandbox sample recipients (internal
transfer/Selcom-to-Selcom, bank, wallet), use `--preset selcom` /
`--preset bank` / `--preset wallet` instead of typing the fields above by
hand — see
[`docs/selcom-sandbox-test-accounts.md`](./selcom-sandbox-test-accounts.md)
for the full account table and example commands.

Every flag also has an env var fallback (`SELCOM_TEST_RECIPIENT_FI_CODE`,
`SELCOM_TEST_RECIPIENT_ACCOUNT`, `SELCOM_TEST_RECIPIENT_NAME`,
`SELCOM_TEST_AMOUNT`, `SELCOM_TEST_PURPOSE`, `SELCOM_TEST_REMARKS`,
`SELCOM_TEST_TRANS_ID`) — see the script's `--help`. It prints a masked
request summary, then either Selcom's parsed result (`status`,
`transaction_id`, `receipt`, `raw_status`) and raw response body
(account-shaped fields masked), or a structured error if Selcom rejected
the call — including whether it was flagged as an IP-whitelist error
(`is_ip_whitelist_error`).

Run manually only — it is not part of the test suite or any CI/CD step, and
refuses to run at all if `SELCOM_BUSINESS_MODE=mock` (nothing to test
against, since mock never calls Selcom) and asks for interactive
confirmation if `SELCOM_BUSINESS_MODE=live` (to prevent an accidental real
payout).

### What a successful run proves

- RSA-SHA256 request signing (`app/services/selcom_business/signing.py`) is
  well-formed enough for Selcom to accept the request at all (a rejected
  signature would come back as a Selcom API error, not a network failure).
- Network reachability to `SELCOM_BUSINESS_SANDBOX_BASE_URL`.
- Whether the caller's outbound IP is whitelisted (`is_ip_whitelist_error`
  in the error output if not).
- Selcom's real response field names for `status`/`transId`/`receipt`/etc —
  compare the printed raw response body against
  `app/services/selcom_business/parsing.py`'s guessed field names (see §5).

## 4. Merchant UI validation stays strict

The sandbox test script's ability to bypass validation is deliberately
scoped to that script only:

- Wallet/mobile withdrawals still require `255XXXXXXXXX` phone format (no
  `+`) via `app/core/phone.py::normalize_tz_phone()`.
- Bank withdrawals still require a real account-number format.
- The Merchant Portal withdrawal form and `POST /v1/merchant/withdrawals`
  are not changed to accommodate Selcom's sandbox sample values — doing so
  would weaken production-facing validation for a sandbox-only testing
  convenience.

## 5. After a real sandbox response comes back

Compare the raw response body the script prints against
`app/services/selcom_business/parsing.py`'s guessed field names
(`status`/`transactionStatus`/`result`, `transId`/`transactionId`/
`reference`, `receipt`/`receiptNumber`/`selcomReceipt`) and status-code
mapping (`000` → successful, `001` → processing, etc. — see
`_extract_status` in that file). If real field names or codes differ,
update `parsing.py` accordingly — see
[`docs/selcom-live-go-live.md`](./selcom-live-go-live.md#selcom-readiness--whats-confirmed-vs-still-unverified)
for the full "what's confirmed vs. still unverified" breakdown. Don't guess
further changes without a real response in hand.

## 6. Running checks

Backend (`apps/api`):

```bash
cd apps/api
python -m pytest
python -m ruff check .
```

Frontend (`apps/web`, from repo root):

```bash
npm run lint --workspace=apps/web
npx tsc --noEmit -p apps/web
npm run build --workspace=apps/web
```
