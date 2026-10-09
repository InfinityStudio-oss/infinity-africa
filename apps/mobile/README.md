# InfinityPay Merchant App

An Expo (React Native) app for merchants, built on the same backend as the
web portal. A merchant signs in with their existing InfinityPay
credentials, sees the same wallet, the same transactions and the same
withdrawals, and gets the same answers — because it is the same API.

## What this is not

- **Not a second system.** No mobile-only merchant record, wallet,
  ledger, API keys, withdrawal flow or approval process. One backend,
  one source of truth.
- **Not a Super Admin tool.** There is no admin surface here, no
  `/v1/admin/*` call anywhere in the code, and no tab that could lead to
  one. Platform operations — merchant approvals, pricing, risk, audit
  logs, payout retries — stay on the web portal.
- **Not an authority on money.** Balances, fees, limits, eligibility and
  permissions are all computed by the API. This app formats numbers and
  renders statuses; it never decides them.

## Running it

```bash
cd apps/mobile
cp .env.example .env     # then fill in the three values
npm install              # from here, not the repo root - see below
npm start
```

This app is **not** part of the root npm workspace, on purpose. Expo pins
`react` and `react-native` to exact versions per SDK; the web app in a
shared hoisted tree resolves different ones, and two React Native copies
in one Metro bundle do not work. Keeping it separate also stops a web
deploy installing React Native. From the repo root, `npm run dev:mobile`
and `npm run typecheck:mobile` forward into this directory.

Then scan the QR code with Expo Go, or press `a` / `i` for an emulator.

Pointing at a local API from a physical device needs your machine's LAN
address in `EXPO_PUBLIC_API_BASE_URL` (`http://192.168.x.x:8000`), not
`localhost` — on the phone, `localhost` is the phone.

Checks, from this directory:

```bash
npm run typecheck
npm run lint
```

## Layout

```
app/                        expo-router: the file tree is the navigation
  _layout.tsx               session gate — signed in, or the login screen
  (tabs)/                   Home · Transactions · Wallet · Withdrawals · More
  withdrawals/new.tsx       raising one: check balance → review → emailed code
  more/                     API credentials, webhooks, IP allowlist,
                            reports, support, settings
  auth/                     login, forgot password
src/
  api/client.ts             every call to /v1/merchant/*; the only network layer
  export/csv.ts             CSV built on the device, handed to the share sheet
  api/useApi.ts             loading / error / refreshing, for each screen
  auth/session.ts           Supabase auth, session stored in the keychain
  components/index.tsx      the shared pieces screens are built from
  theme.ts                  the palette, copied from the web app's tokens
```

## Security

- The session lives in the device keychain (`expo-secure-store`), not
  AsyncStorage, and is chunked because SecureStore rejects values over
  about 2KB.
- Nothing is stored or logged that could be replayed: no secret API key
  (the API only ever returns one at creation, in the portal), no webhook
  signing secret, no one-time code, no bearer token in any log line.
- Phone numbers are masked to their last four digits wherever they are
  shown.
- Only `EXPO_PUBLIC_*` values reach the app, and everything with that
  prefix is compiled into the bundle — treat it as published. The
  Supabase anon key is safe there by design; a service role key never is.
- A 401 clears the session rather than retrying.

## Shipping it

[PLAY_STORE_INTERNAL_TESTING.md](PLAY_STORE_INTERNAL_TESTING.md) covers
EAS setup, the Android AAB build, Google Play internal testing, the Data
Safety declaration, and the full list of public-release blockers.

Two things worth knowing before you read it:

- **Password reset lands on the web portal**, by design. The app calls the
  same `POST /v1/auth/forgot-password` endpoint the portal does, so the
  merchant gets InfinityPay’s branded email and sets the new password at
  `/dashboard/reset-password`. No Supabase redirect change is needed.
- **The artwork is the 512×512 brand mark**, which is fine for internal
  testing and is already the right size for the Play listing icon, but the
  build wants 1024×1024 before a public release — see
  [assets/README.md](assets/README.md).

## Withdrawals and exports

Raising a withdrawal follows the portal exactly: check balance → review →
a code emailed to the account address → created as
`PENDING_ADMIN_APPROVAL`. An InfinityPay administrator still approves it
on the web, and the app never reaches a payment provider. It is
admin-only, matching the backend gate.

**No charges are shown, because merchant withdrawals are not charged.**
The quote endpoint is still called — it is the server's own validation of
the amount and destination, and it reports what the wallet must cover —
but what the merchant is told is that they receive the full amount, which
is the line the portal shows too.

Transactions and Wallet export the rows on screen as CSV through the OS
share sheet, with the same columns as the portal's export. Reports emails
the PDF statement over a date range, which is what the portal's Reports
page produces; it is deliberately not a CSV, and the account email always
receives it.

Still open as a product decision: what the app should do on a pending or
suspended account beyond the notice Home shows today.
