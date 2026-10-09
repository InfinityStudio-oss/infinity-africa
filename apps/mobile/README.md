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
address in `EXPO_PUBLIC_API_URL` (`http://192.168.x.x:8000`), not
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
  more/                     API credentials, webhooks, IP allowlist,
                            reports, support, settings
  auth/                     login, forgot password
src/
  api/client.ts             every call to /v1/merchant/*; the only network layer
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

## Before a store release

- Replace `assets/icon.png`, `assets/splash.png` and
  `assets/adaptive-icon.png` with 1024×1024 artwork (these are the
  512×512 brand mark, fine for development).
- Set up EAS (`eas build:configure`) with production `EXPO_PUBLIC_*`
  values, and confirm `EXPO_PUBLIC_API_URL` points at the production API.
- Decide what the app does on a pending or suspended account beyond the
  notice Home shows today.
