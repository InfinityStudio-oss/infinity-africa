# InfinityPay merchant app — Android internal testing

How to get this app onto real phones through Google Play's internal
testing track. Internal testing distributes to a named list of up to 100
testers, needs no Google review, and is live within minutes of upload.

Nothing here touches production payments. The app is a client of the
`/v1/merchant/*` API the web portal already uses.

---

## 1. Install dependencies

```bash
cd apps/mobile
npm install
```

Run it **from `apps/mobile`**, not from the repo root. This app is
deliberately not part of the root npm workspace: Expo pins `react` and
`react-native` to exact versions per SDK, `apps/web` pins different ones,
and two React Native copies in one Metro bundle do not work. Installing
from the root also drags React Native into every web deploy.

## 2. Set environment variables

```bash
cp .env.example .env
```

| Variable | Value |
|---|---|
| `EXPO_PUBLIC_API_BASE_URL` | `https://<production-api-host>` for a Play build; your machine's LAN address (`http://192.168.x.x:8000`) for local work |
| `EXPO_PUBLIC_SUPABASE_URL` | Same Supabase project as the web portal |
| `EXPO_PUBLIC_SUPABASE_ANON_KEY` | The **anon** key — never the service role key |

Every `EXPO_PUBLIC_*` value is compiled into the bundle as a literal
string and is readable by anyone who installs the app. `.env.example`
lists what must never go in one. Secrets stay in Railway, on the backend.

Sentry and PostHog are **not** wired into this app yet. The variable names
are reserved in `.env.example`, but nothing reads them, so setting them
does nothing.

## 3. Run locally

```bash
npm start          # then scan the QR code with Expo Go, or press a / i
```

Checks:

```bash
npx tsc --noEmit
npx expo lint
npx expo export --platform android     # full production bundle, no device needed
```

## 4. Configure EAS

[`eas.json`](eas.json) is already committed with three build profiles. It
holds **no** secrets and no environment values.

```bash
npm install -g eas-cli      # or use npx eas
eas login
eas init                    # writes extra.eas.projectId into app.json - commit that
```

| Profile | Artifact | For |
|---|---|---|
| `development` | APK, dev client | Day-to-day work on a device |
| `internal` | AAB | Play Console internal testing |
| `production` | AAB | Public release (still blocked — see the checklist) |

Two things about this file that are deliberate:

- The `development` profile sets `developmentClient: true`, which needs a
  package this app does not install. Run `npx expo install expo-dev-client`
  before using that profile. It is left out until someone wants it — the
  internal-testing path below does not need it.
- Both `submit` profiles target the **`internal`** track, including
  `production`. An accidental `eas submit --profile production` therefore
  cannot push a build to the public track. Change the track deliberately,
  in a commit, when a public release is actually intended.

`cli.appVersionSource` is `local`, so `version` and
`android.versionCode` come from [`app.json`](app.json) and are reviewable
in git. **Play rejects a re-upload with a `versionCode` it has already
seen**, so bump `android.versionCode` for every upload.

Build-time environment values reach an EAS cloud build one of two ways:

```bash
# Option A - stored on EAS, per environment (preferred for shared builds)
eas env:create --name EXPO_PUBLIC_API_BASE_URL --value https://... --environment production --visibility plaintext
eas env:create --name EXPO_PUBLIC_SUPABASE_URL --value https://... --environment production --visibility plaintext
eas env:create --name EXPO_PUBLIC_SUPABASE_ANON_KEY --value eyJ... --environment production --visibility plaintext

# Option B - a local build reads apps/mobile/.env
eas build --platform android --profile internal --local
```

`plaintext` is correct for these three: they are public by construction,
and marking them "secret" would hide values that are visible in the
bundle anyway, which misleads whoever reads the EAS dashboard next.

## 5. Build the Android AAB

```bash
cd apps/mobile
eas build --platform android --profile internal
```

The first run offers to generate an upload keystore — let EAS manage it.
If you generate your own, it never goes in git (`.gitignore` already
blocks `*.jks`, `*.keystore`, `*.p12`, `*.p8`). **Losing the upload key
means you cannot update the app**, so whatever you choose, record where it
lives.

A cloud build costs build minutes. `--local` builds free on a machine with
Android SDK + JDK installed.

When it finishes, download the `.aab` from the link EAS prints.

## 6. Upload to Google Play Console

First time only — create the app:

| Field | Value |
|---|---|
| App name | **InfinityPay** |
| Default language | English (United Kingdom) or English (United States) |
| App or game | **App** |
| Free or paid | Free |
| Category | **Finance** (Business is the fallback if Finance is contested) |
| Package name | **`me.infinitypay.merchant`** — permanent, and cannot be changed after the first upload |
| Support email | **help@infinitypay.me** |

Then:

1. **Testing → Internal testing → Create new release**
2. Upload the `.aab`
3. Add release notes (plain text is fine: "First internal build")
4. **Save → Review release → Start rollout to Internal testing**

Play may warn that the app is not signed with an app-signing key yet;
accepting Play App Signing on the first upload is the normal path.

### Testers

1. **Internal testing → Testers → Create email list**
2. Add tester Google account addresses (up to 100). They must be the
   addresses the testers use on their phones.
3. Copy the **join link** and send it to them.
4. Each tester opens the link, accepts, then installs from Play.

A tester who gets "item not found" has either not accepted the invite or
is signed into a different Google account on the device.

### Store listing assets

Internal testing does **not** require a full store listing, but Play asks
for most of this before it will let you promote the app to a public
track:

| Asset | Requirement | Status |
|---|---|---|
| App icon | 512×512 PNG | `apps/web/public/brand/infinity-mark.png` is already this size |
| Feature graphic | 1024×500 PNG/JPG | **Missing** — needs a designer; see [`assets/README.md`](assets/README.md) |
| Phone screenshots | 2–8, min 1080px on the short side | **Missing** — take from a real build |
| Short description | ≤ 80 characters | Not written |
| Full description | ≤ 4000 characters | Not written |
| Privacy Policy URL | Required for a finance app | `https://infinitypay.me/privacy` — confirm it is reachable and current |
| Terms URL | Expected for a finance app | `https://infinitypay.me/terms` — confirm |
| Support email | Required | `help@infinitypay.me` |

### Data Safety declaration

Play requires this before any release. What is true of this app:

- **Account authentication.** Merchants sign in with their existing
  InfinityPay email and password through Supabase Auth. The app has no
  separate account system and no sign-up flow.
- **Financial information is displayed.** Wallet balance, transaction
  history, the wallet ledger and withdrawal status. All of it is fetched
  for display; the app computes no balances and no fees.
- **Financial actions.** A merchant admin can raise a withdrawal from
  their own InfinityPay balance to their own destination. It requires a
  code emailed to the account address, and an InfinityPay administrator
  still approves it before any money moves. The app never reaches a
  payment provider.
- **Collected vs. displayed.** The app itself collects nothing beyond the
  credentials needed to sign in, and the withdrawal details a merchant
  types about their own payout. Everything else is read from a merchant's
  own InfinityPay account.
- **Files the app writes.** CSV exports are written to the app's own cache
  directory and handed straight to the OS share sheet. Nothing is written
  to shared storage, which is why no storage permission is requested, and
  the OS reclaims the cache on its own.
- **No data is shared with third parties** by the app. No analytics or
  crash-reporting SDK is installed (Sentry and PostHog are on the backend
  and the web portal, not here).
- **Secure session storage.** The session token is kept in the OS keychain
  / Keystore via `expo-secure-store`, not in plain app storage.
- **Secret API keys are never fetched, stored or displayed.** A merchant's
  secret key is shown once at creation, in the web portal only.
- **Encryption in transit.** All API traffic is HTTPS to the InfinityPay
  backend. (A local `http://` base URL is for development only.)
- **Data deletion.** Account deletion is handled by InfinityPay support,
  not in the app — Play wants a URL or an email for this; use
  `help@infinitypay.me`.
- **Permissions.** `android.permissions` is set to `[]` in `app.json`, so
  the app declares only the minimum Expo requires. It asks for no camera,
  location, contacts or storage access.

---

## Password reset — where does the link land?

**The web portal.** This is a deliberate decision, not an oversight.

Tapping "Forgot your password?" in the app calls
`POST /v1/auth/forgot-password` — the same backend endpoint the web
portal's form calls — with `redirect_path: "/dashboard/reset-password"`.
The backend generates the Supabase recovery link and sends InfinityPay's
own branded email through Resend. The merchant opens it, sets a new
password at `https://infinitypay.me/dashboard/reset-password`, and returns
to the app to sign in.

**No Supabase dashboard change is needed for this.**
`https://infinitypay.me/dashboard/reset-password` is already in the
redirect allow-list (see [`docs/supabase-auth-settings.md`](../../docs/supabase-auth-settings.md)),
and the mobile app sends no new redirect target.

The app does **not** call `supabase.auth.resetPasswordForEmail` directly.
Doing so would send Supabase's unbranded default template pointed at the
project's Site URL — `https://infinitypay.me`, the marketing homepage —
where a merchant would arrive holding a recovery token with no form to
type a new password into.

### If you later want reset to finish inside the app

The pieces that would be needed, none of which exist today:

1. A deep-link redirect target. The app already declares
   `"scheme": "infinitypay"` in `app.json`, so `infinitypay://` links
   resolve to it.
2. Add `infinitypay://auth/callback` to **Supabase → Authentication →
   URL Configuration → Redirect URLs**, exactly, with no trailing slash.
   Supabase silently falls back to the Site URL on an allow-list miss.
3. Widen the `redirect_path` `Literal` in
   `apps/api/app/schemas/auth.py::ForgotPasswordRequest`, which is
   currently a closed set of two web paths specifically so a caller cannot
   aim a real recovery link at a host they control. Widening it is a
   security decision, not a config change.
4. Build a set-new-password screen in the app and handle the recovery
   token from the deep link.

Until all four are done, leave reset on the web. The current flow works
and breaks nothing.

---

## Public release blockers

Internal testing can start without these. A public release cannot.

### Artwork
- [ ] Final **1024×1024** app icon (`assets/icon.png` is the 512×512 mark)
- [ ] Final **1024×1024** adaptive icon foreground
- [ ] Splash artwork at full resolution
- [ ] Feature graphic, 1024×500
- [ ] Phone screenshots from a real build

### Configuration
- [ ] `EXPO_PUBLIC_API_BASE_URL` points at the production API over HTTPS
- [ ] Production Supabase URL + anon key set on the EAS `production` environment
- [ ] `android.versionCode` bumped past every version Play has seen
- [ ] Sentry / PostHog mobile config — **decide first whether to add them
      at all**; if yes, only the public DSN/key may be bundled, and the
      privacy scrubbing the API already does would need porting
- [ ] Supabase redirect URLs confirmed (no change needed unless reset moves
      into the app)

### Listing and legal
- [ ] `https://infinitypay.me/privacy` reachable and current
- [ ] `https://infinitypay.me/terms` reachable and current
- [ ] Support email `help@infinitypay.me` monitored
- [ ] Short and full descriptions written
- [ ] Google Play **Data Safety** form completed (notes above)

### Product decisions
- [x] **Withdrawal creation** — done. Same three steps as the portal
      (check balance → review → emailed code), created as
      PENDING_ADMIN_APPROVAL, no charges shown because merchant
      withdrawals are not charged. Admin-only, matching the backend gate.
- [x] **CSV export** — done. Transactions and Wallet export the rows on
      screen via the share sheet; Reports emails the PDF statement, which
      is what the portal's Reports page produces.
- [ ] Decide what a **pending or suspended** account should see beyond the
      notice Home shows today
- [ ] A test merchant account prepared for reviewers and testers, with
      realistic but non-sensitive data
- [ ] Walk one real withdrawal through the app end to end on the internal
      track, including the Super Admin approval, before a public release

### Verification
- [ ] `npx tsc --noEmit` clean
- [ ] `npx expo lint` clean
- [ ] `npx expo export --platform android` succeeds
- [ ] Bundle scanned for secrets with control strings (see below)
- [ ] Internal testing round signed off by a real merchant

---

## Bundle secret scan

Run after any export, from `apps/mobile`:

```bash
npx expo export --platform android --output-dir /tmp/mobile-export
B=$(ls /tmp/mobile-export/_expo/static/js/android/*.hbc)

# Controls must be > 0, or the scan is proving nothing
for p in "Available balance" "InfinityPay" "v1/merchant/overview"; do
  echo "control $p: $(grep -a -c -- "$p" "$B")"
done

# These must all be 0
for p in sk_live sk_test service_role RESEND_API SELCOM_ DATABASE_URL \
         JWT_SECRET whsec_ SUPABASE_SERVICE_ROLE eyJhbGciOi v1/admin; do
  echo "secret $p: $(grep -a -o -- "$p" "$B" | wc -l)"
done
```

`grep -a` matters: the bundle is Hermes bytecode, and `strings` is not
installed in this environment — a scan that silently finds nothing because
the tool is missing looks identical to a clean result.
