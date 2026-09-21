# Supabase Auth settings — merchant signup & email verification

> **Brand/domain migration**: the platform's public domain is moving from
> `infinityafrica.net` (Infinity Africa) to `infinitypay.me` (InfinityPay).
> **Add** the new `infinitypay.me` redirect URLs below alongside the
> existing `infinityafrica.net` ones — do **not** remove the old ones yet.
> Site URL should only move to `https://infinitypay.me` once the old
> domain's redirect is confirmed working end to end (so a verification/
> reset link opened from an old, already-sent email still lands
> correctly). See `docs/MVP_LAUNCH_CHECKLIST.md`.

These are **dashboard settings**, not code. They must be set on the
production Supabase project (`vtwnhxwtnllgispjbkaz`) for the merchant
signup → email verification → onboarding flow to work end to end. Code
changes alone can't fix a wrong Site URL or a missing redirect allow-list
entry — Supabase silently refuses to redirect anywhere not on the list.

## Auth → Providers → Email

| Setting | Value | Why |
| --- | --- | --- |
| **Confirm email** | **On** (recommended) | Merchants must verify ownership of the address before onboarding. When on, `supabase.auth.signUp` returns a user with **no session**, and the frontend now shows *"Check your email to verify your account…"* instead of bouncing to login. If this is off, signup returns a session and the merchant is sent straight to `/onboarding` — also handled. |

## Auth → URL Configuration

| Setting | Value |
| --- | --- |
| **Site URL** | `https://infinityafrica.net` today; move to `https://infinitypay.me` once the redirect below is confirmed working end to end |

**Redirect URLs** (allow-list — add every one; keep the old
`infinityafrica.net` entries until the domain migration is complete, do
not remove them yet):

```
https://infinitypay.me/auth/callback
https://infinitypay.me/onboarding
https://infinitypay.me/merchant/login
https://infinitypay.me/merchant/reset-password
https://infinitypay.me/admin-login/reset-password
https://infinitypay.me/merchant/invite/accept

https://infinityafrica.net/auth/callback
https://infinityafrica.net/onboarding
https://infinityafrica.net/merchant/login
https://infinityafrica.net/merchant/reset-password
https://infinityafrica.net/admin-login/reset-password
https://infinityafrica.net/merchant/invite/accept
```

If the site is also served on `www.`, add the `www.` variant of each
(for both domains). For Vercel preview deployments, add
`https://*.vercel.app/auth/callback` (or the specific preview host) while
testing.

## App environment variables

These are already documented in `apps/web/.env.example` /
`apps/api/.env.example` — listed here so the whole flow is in one place.
**Never** put a service-role key in `apps/web`.

| Var | Where | Value (prod) |
| --- | --- | --- |
| `NEXT_PUBLIC_SITE_URL` | `apps/web` | `https://infinitypay.me` — used to build the `emailRedirectTo` sent to Supabase at signup (`lib/auth/actions.ts`). Falls back to the request host if unset. |
| `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `apps/web` | public project URL + anon key only |
| `CEO_EMAIL` | `apps/api` | `ceo@infinityafrica.net` — merchant signup/business-submission notification recipient. If unset, that notification is silently skipped (never sent anywhere else). Stays on the old domain until `infinitypay.me` is verified in Resend — see `docs/email-delivery.md`. |
| `APP_URL` | `apps/api` | `https://infinitypay.me` — base URL in the approval / welcome email to the merchant. |

## The flow, once the above is set

1. Merchant submits `/create-account`. `supabase.auth.signUp` is called with
   `emailRedirectTo = {NEXT_PUBLIC_SITE_URL}/auth/callback?next=/onboarding`.
2. **No session** in the response → the form switches to a *"check your
   email"* panel with a **Resend verification email** button. It does
   **not** redirect to login, and login now shows *"Please verify your
   email…"* (not *"Incorrect email or password"*) if they try to sign in
   early.
3. Merchant clicks the link in the email → lands on
   `/auth/callback` with `?code=…` (or `?token_hash=…&type=signup`) →
   `app/auth/callback/route.ts` establishes the session and redirects to
   `/onboarding`.
   - If the link is opened on a **different device** (no PKCE verifier) or
     a second time, the callback redirects to `/merchant/login` with
     *"Your email is verified. Sign in to continue…"* — the account is
     fine, they just sign in.
4. Merchant completes `/onboarding` (business details only — no KYC
   document upload; compliance docs are requested by the Super Admin
   during review if needed). Backend creates `merchants` + `merchant_users` +
   `onboarding_submissions` (`review_status = PENDING_VERIFICATION`) and
   emails **`CEO_EMAIL`** the signup notification.
5. Super Admin reviews at `/super-admin/onboarding`. On **approve**:
   `merchants.status = active`, `kyc_status = verified`, wallet created,
   **welcome email to the merchant** (never the CEO).
6. Only now can the merchant reach collections / payment links / Pay by
   Link / invoices / withdrawals — enforced both in the UI
   (`lib/onboarding/guard.ts`) and in the API (`merchant_gate.py` +
   `disbursements._check_merchant_is_verified`).

## Manual verification checklist

- [ ] Create a brand-new merchant account with a real inbox.
- [ ] Supabase → Authentication → Users shows the user as *Waiting for
      verification*.
- [ ] The app shows the *"check your email"* panel (no *"Incorrect email
      or password"*).
- [ ] Trying to log in before verifying shows the verify-email message.
- [ ] Click the email link → lands on `/onboarding` signed in.
- [ ] (Mobile) open the same link on a phone → lands on `/merchant/login`
      with the *"email is verified, sign in"* notice; signing in works.
- [ ] Submit onboarding → `ceo@infinityafrica.net` receives the signup
      notification; merchant status is *Pending Verification*.
- [ ] Before approval: `/merchant/payment-links`, `/merchant/pay-by-link`,
      `/merchant/withdrawals`, `/merchant/invoices` all redirect to
      `/merchant/overview` (pending banner). Direct API calls to create a
      payment link / invoice / collection return `403 merchant_not_approved`;
      a withdrawal returns `409 withdrawal_restricted`.
- [ ] Super Admin approves → merchant receives the welcome email (CEO does
      not).
- [ ] Merchant logs in → reaches the full portal; money-movement pages now
      load.
