# Super Admin MFA (TOTP) rollout runbook

**Status: not implemented.** This is the plan and its preconditions. No
code reads `REQUIRE_SUPER_ADMIN_MFA` today.

Written 2026-09-25, after the auth hardening pass in `43478d2`.

## Why

A Super Admin approves withdrawals, approves merchants, and sets pricing.
Every one of those moves real money or changes what merchants are charged.
Today a single stolen or reused password reaches all of it — there is no
second factor anywhere on the platform-admin path.

Everything else in the auth model is already strong: roles are re-read from
`platform_admins` on every request, forged token claims are ignored, and no
product path can create an admin. That makes the password the single
remaining point of failure, which is exactly what TOTP removes.

## Capability check (done)

Verified by inspecting the installed clients, not by version assumption:

- `@supabase/supabase-js` **2.112.3** — `enroll`, `challenge`, `verify`,
  `challengeAndVerify`, `listFactors`, `getAuthenticatorAssuranceLevel`
- `supabase` (Python) **2.22.4** via `supabase_auth` — `enroll`,
  `challenge`, `verify`, `challenge_and_verify`, `list_factors`,
  `get_authenticator_assurance_level`, `unenroll`

Both halves of the stack can do this with no dependency upgrade.

**Still to confirm manually:** that MFA is enabled for the project in the
Supabase dashboard (Authentication → Providers / MFA). The client libraries
having the methods does not mean the project permits enrollment.

### How enforcement should work

Supabase puts an **`aal`** claim (`aal1` / `aal2`) in the access token.
`aal2` means a second factor was actually presented for that session.

Enforce on the **backend**, in `require_super_admin`, by reading `aal` from
the verified claims — not in the frontend layout. That claim is set by
Supabase and signed; it is not user-supplied, so it is safe to read in a
way `user_metadata` never was. A frontend-only check would be bypassed by
calling `/v1/admin/*` directly with an `aal1` token.

This means `decode_access_token` must return the claim to the dependency —
it already returns the full claims dict, so no change is needed there.

## Preconditions

Do not start until **all** of these hold:

1. **Auth hardening deployed.** `43478d2` live on Railway and Vercel.
2. **`TRUSTED_PROXY_HOPS` verified in production.** Start at `0`. After
   deploying, make one real API-key request and check
   `api_keys.last_used_ip` is a genuine public IP. See
   `docs/AUTH_SECURITY_CHECKLIST.md`.
3. **At least two Super Admin accounts exist**, on inboxes the owner
   controls, both confirmed able to log in *before* MFA is enforced. One
   admin plus mandatory MFA is one lost phone away from nobody being able
   to approve a withdrawal.
4. **Both inboxes accessible right now** — not "probably still works".
5. **Supabase project MFA enabled** in the dashboard.
6. **Recovery path agreed and written down** (below).

### Current state (checked 2026-09-25)

**One Super Admin exists: `ceo@infinitypay.me`** — email confirmed, last
signed in 2026-09-24. Healthy, but a single point of failure.

**This blocks mandatory MFA.** With one admin and enforcement on, a lost or
wiped phone means nobody can approve a withdrawal until someone gets into
the Railway dashboard to flip the flag back — while real merchant money
sits unpaid. Add a second Super Admin before enabling enforcement.

Adding one is deliberately manual and is the owner's decision, not
something to automate:

1. Create (or identify) the user in Supabase Auth and confirm their email.
2. Insert their `user_id` into `public.platform_admins` via the SQL editor.
3. Confirm they can log in **before** MFA is enforced.

Re-run the query below afterwards; it should return two rows.

### Verifying the admin accounts

Run in the Supabase SQL editor:

```sql
select pa.user_id,
       u.email,
       u.email_confirmed_at is not null as email_confirmed,
       u.last_sign_in_at
  from public.platform_admins pa
  join auth.users u on u.id = pa.user_id
 order by u.last_sign_in_at desc nulls last;
```

Expected: **two or more rows**, each a real address the owner controls,
each `email_confirmed = true`, each with a recent `last_sign_in_at`.

One row means stop and add a second admin before going further.

Admins are created by hand in SQL, deliberately — there is no product path
that writes `platform_admins`, and adding one would turn a merchant account
takeover into a platform takeover. Creating the second admin is an explicit
owner decision, not something to automate.

## Rollout flag

`REQUIRE_SUPER_ADMIN_MFA`, on the Railway API service.

- `false` — enrollment available, enforcement off. Ships in this state.
- `true` — a Super Admin without `aal2` is refused on `/v1/admin/*`.

Ship the code with the flag `false`, enroll both admins, confirm both can
complete a challenge, and only then flip it. Do not ship enforcement and
enrollment in the same change: that is the version where a bug locks
everyone out with no way back in.

## Test plan (staging / local)

1. Log in as Super Admin with the flag `false` — unchanged behaviour.
2. Enroll a TOTP factor; scan the QR into an authenticator app.
3. Log out, log back in, complete the challenge. Confirm the session
   reaches `aal2`.
4. Set the flag `true`. Confirm an `aal1` session is refused on
   `/v1/admin/*` **with a direct API call**, not only in the UI.
5. Confirm an enrolled admin still passes.
6. Confirm a merchant login is completely unaffected.
7. Confirm public payment pages are unaffected.

## Production enablement

1. Deploy with `REQUIRE_SUPER_ADMIN_MFA=false`.
2. Enroll admin #1. Verify a challenge end to end.
3. Enroll admin #2, on a different device. Verify independently.
4. Keep both authenticator apps in reach.
5. Set `REQUIRE_SUPER_ADMIN_MFA=true`. Redeploy.
6. Immediately run the smoke checklist below.

Do not enable while a withdrawal is waiting for approval. Clear the queue
first, so a lockout cannot strand a merchant's money.

## Recovery and lockout

Losing an authenticator does **not** mean losing the account:

1. Use the second Super Admin account. This is what it is for.
2. Unenroll the lost factor — `unenroll` as that user, or remove the factor
   from the Supabase dashboard under the user's record.
3. Re-enroll on the new device.

If **both** factors are lost at once:

1. Set `REQUIRE_SUPER_ADMIN_MFA=false` in Railway and redeploy. Password
   login works again immediately.
2. Remove the stale factors in the Supabase dashboard.
3. Re-enroll both, then set the flag back to `true`.

This is why enforcement is a flag and not a hardcoded rule. Keep it a flag.

## Rollback

`REQUIRE_SUPER_ADMIN_MFA=false` and redeploy. That is the whole rollback —
it restores password-only admin login without touching enrollments, so
nothing has to be re-enrolled afterwards. No migration, no code revert.

## Smoke checklist after enabling

- [ ] Super Admin login prompts for the code
- [ ] Enrollment flow works for a new factor
- [ ] Challenge succeeds with a valid code, fails with a wrong one
- [ ] Withdrawal approval blocked on an `aal1` session
- [ ] Pricing management blocked on an `aal1` session
- [ ] Merchant approval blocked on an `aal1` session
- [ ] All three succeed on an `aal2` session
- [ ] Merchant login and dashboard unaffected
- [ ] Merchant withdrawal request (incl. email OTP) unaffected
- [ ] Public payment pages and Pay by Link unaffected
- [ ] `/v1/admin/*` refuses an `aal1` token when called **directly**, not
      just through the UI

The last one is the one that actually proves enforcement is server-side.

## Scope boundary

Super Admin only. Merchant MFA is a separate decision with different
tradeoffs — merchants are customers, and forcing TOTP on them affects
onboarding conversion. Do not widen this rollout to merchants without
deciding that on its own terms.
