# Super Admin password recovery with MFA

## Why a reset alone is not enough

Supabase refuses `updateUser({ password })` from an **aal1** session once
an account has a verified TOTP factor:

```
AAL2 session is required to update email or password when MFA is enabled.
```

A password-recovery link always produces an aal1 session. Possession of
the mailbox proves one factor, not two — and if a reset could change the
password on that alone, anyone who reached the inbox would bypass MFA
entirely. That is the whole point of the rule, and it is correct.

So a Super Admin reset needs **both**: the emailed link (or code), and
the authenticator.

## How the flow works now

1. Request a reset at `/admin-login/forgot-password`.
2. The email carries a link **and** an 8-digit code — either establishes
   the recovery session. See `docs/password-reset-runbook.md` for why both.
3. The page asks Supabase `mfa.getAuthenticatorAssuranceLevel()`. If
   `nextLevel` is `aal2` and `currentLevel` is not, it asks for the
   6-digit authenticator code **before** showing the password fields.
4. That code is verified via `mfa.challenge()` + `mfa.verify()`, raising
   the session to aal2.
5. Only then does the password form appear, and `updateUser` succeeds.

The order matters. Before this, the password form came first and the
failure arrived after the new password had been typed — behind the
message "this reset link is invalid or has expired", which was wrong and
sent several days of debugging at the link instead of the session.

A merchant account with no MFA never sees step 3.

## If the authenticator is lost

There is **no bypass in the product**, deliberately. A "skip MFA" path
reachable from an email link is the same thing as no MFA.

Recovery is through a second Super Admin:

1. **Verify identity out of band.** Not over email — the mailbox may be
   the thing that is compromised. Voice or in person.
2. Another Super Admin unenrols the factor, in the Supabase dashboard:
   **Authentication → Users → the account → Factors → remove**.
3. The locked-out admin resets their password normally. With no verified
   factor, step 3 above is skipped.
4. **Re-enrol immediately** at `/admin-mfa/enroll`. An account left
   unenrolled is a standing hole, and `REQUIRE_SUPER_ADMIN_MFA` will
   route them there anyway.
5. Record what happened: who asked, who verified them, who unenrolled,
   when it was re-enrolled.

Removing someone's second factor is the single most powerful thing an
admin can do to another admin's account. It should feel heavier than
clicking a button, and it should never happen on the strength of an
email.

## Why two Super Admins is a hard requirement

Step 2 needs *another* admin. With one admin, a lost authenticator means
nobody can reach the platform — no support path, no self-service, no way
back without Supabase project credentials.

The roster is visible at **Super Admin → Settings → Admin Team**, which
also shows **Last Signed In**. An account that has never signed in is not
a working backup: it satisfies the count while being unproven. Sign in
with the second account at least once, and before enabling
`REQUIRE_SUPER_ADMIN_MFA`.

## What is never logged

TOTP codes, recovery tokens, `token_hash`, access and refresh tokens, and
full callback URLs. A failed TOTP attempt reports one message for a wrong
code and an expired challenge alike — distinguishing them would confirm
to someone guessing that they had reached a live challenge.

## Related

- `docs/SUPER_ADMIN_MFA_RUNBOOK.md` — enrolment and enforcement rollout
- `docs/password-reset-runbook.md` — the reset flow itself, and why the
  email carries a code as well as a link
- `apps/web/src/components/auth/reset-password-form.tsx` — the flow
- `apps/web/src/lib/auth/super-admin-mfa.ts` — the server-side guard
