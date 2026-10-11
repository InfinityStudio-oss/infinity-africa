# Auth security

Who can act as whom, and what stops them acting as someone else. For the
pre-launch tick-list version see [AUTH_SECURITY_CHECKLIST.md](AUTH_SECURITY_CHECKLIST.md);
this document explains the design those items check.

## Three identities, three mechanisms

| Caller | Credential | Resolved by |
|---|---|---|
| Merchant staff in the portal or mobile app | Supabase Auth JWT | `get_current_user` → `get_own_merchant` |
| Partner integration | Secret API key (`sk_live_…` / `sk_test_…`) | `verify_api_key` |
| Super Admin | Supabase Auth JWT + `platform_admins` row + TOTP | `require_super_admin` |

**InfinityPay does not handle passwords.** Supabase Auth owns them end to
end — this codebase never sees, hashes or stores one. That is also why
login cannot be rate-limited here; see
[ABUSE_PROTECTION.md](ABUSE_PROTECTION.md#login-is-not-limited-here).

## The merchant is never taken from the request

This is the rule that prevents one merchant reading another's money.

- `/v1/merchant/*` routes take **no** `merchant_id` at all. It is resolved
  from the caller's own `merchant_users` membership (`get_own_merchant`).
  There is no Super Admin bypass on this surface.
- `/v1/merchants/{merchant_id}/*` routes check the path id against the
  caller's membership (`get_merchant_actor`).
- Flat routes that cannot know the merchant at auth time
  (`POST /v1/payment-links`, `POST /v1/collections/*`) authenticate first
  and call `authorize_merchant_action(caller, merchant_id, *roles)` the
  moment the merchant is known.

`apps/api/tests/test_tenant_isolation_route_guards.py` enforces this
structurally: it walks the entire FastAPI route table and fails if any
route is not deliberately classified into one of those patterns. A new
endpoint that forgets its check fails the suite rather than shipping.

## API keys

Full detail in [SECRETS_AND_API_KEY_SECURITY.md](SECRETS_AND_API_KEY_SECURITY.md).
The security-relevant properties:

- A key is `secrets.token_urlsafe(24)` — 192 bits from the OS CSPRNG.
- Only `sha256(key)` is stored (`api_keys.hashed_key`). The plaintext is
  shown **once**, at creation, and is not recoverable afterwards by anyone
  including Super Admin. See `apps/api/app/auth/hashing.py` for why a plain
  SHA-256 is correct here and when it would have to become Argon2id.
- `ApiKeyCreateResponse` is the only schema that carries the secret.
  `ApiKeyResponse` — used by every other endpoint — has no field that
  could carry one, not even an optional one.
- Lookup is indexed equality on the hash, so no secret is compared
  byte-by-byte in application code.
- Failed key auth is rate-limited per IP (20 per 5 min) and written to the
  auth audit log. Working integrations never touch that path.
- `live` keys additionally pass an IP allowlist when one is enabled.
- The public half (`pk_…`) is stored in plaintext and cannot authenticate;
  presenting one returns an explicit "use your secret key" error rather
  than a generic failure, because the usual cause is a partner pasting the
  wrong half.

## Super Admin

- Membership is a row in `platform_admins`. Role is not inferable from the
  JWT alone.
- TOTP MFA is enforced when `REQUIRE_SUPER_ADMIN_MFA=true`. The API refuses
  every `/v1/admin/*` call from an `aal1` session regardless of what the
  portal decides, so the portal's MFA redirect is convenience, not the
  control. Enrolment and recovery: [SUPER_ADMIN_MFA_RUNBOOK.md](SUPER_ADMIN_MFA_RUNBOOK.md).
- Every Super Admin action is written to `audit_logs` with the actor, and
  that table is append-only at the database level.

## Suspension closes every door

A Super Admin suspending a business in Super Admin → Businesses (or
rejecting its onboarding, which sets the same status) shuts it off in four
places:

| Layer | Mechanism |
|---|---|
| Collections, payment links, invoices, API-key minting | `require_approved_merchant` |
| Withdrawals | `_check_merchant_is_verified` |
| Every `/v1/merchant/*` route | `get_own_merchant` |
| Login | `loginAction` reads `merchant_status` and signs the session out |

Two deliberate exceptions, both load-bearing:

- **`status = 'pending'` is still allowed through `get_own_merchant`.** A
  new signup uses that same surface to see where its application stands.
  Blocking it would lock every new merchant out of the portal.
- **`GET /v1/onboarding/status` resolves the user directly**, not through
  `get_own_merchant`. It is how login and the portal find out *why* they
  are blocked. Gating it gives a suspended merchant a broken dashboard
  instead of the suspended page.

Note that suspension does **not** revoke an already-issued Supabase refresh
token — a session open at the moment of suspension is refused by the API
and redirected to `/dashboard/suspended`, but the token itself remains
valid until it expires. Banning the auth user in Supabase is the stronger
action and is separate.

## Sessions

- Web: Supabase session in cookies, refreshed by `src/proxy.ts`. Server
  components read it through `lib/supabase/session.ts`, which is marked
  `server-only` — a client component importing it fails the production
  build, which is the only check that catches it.
- Mobile: session in the device keychain via `expo-secure-store`, chunked
  because SecureStore rejects values over ~2KB. `AsyncStorage` is used
  **only** when `Platform.OS === "web"` (Expo web, where it is
  localStorage — the same place the portal keeps it). The shipped Android
  app never uses it.
- Access tokens are used to set the `Authorization` header and nothing
  else: never logged, never rendered, never persisted outside the keychain.

## Rate limits that protect auth

| Endpoint | Limit |
|---|---|
| Merchant signup | 5 / 5 min |
| Onboarding submit | 5 / min |
| Forgot password | 5 / min per IP, 3 / 15 min per email |
| API key creation | 10 / min |
| Failed API key auth | 20 / 5 min per IP |
| Withdrawal OTP request | 5 / 5 min |
| Withdrawal OTP verify | 10 / 5 min, plus 5 attempts per challenge then locked |

The OTP comparison uses `hmac.compare_digest`, so a wrong code cannot be
narrowed down by response timing.
