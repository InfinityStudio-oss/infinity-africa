# Tenant isolation and IDOR review

Reviewed 2026-09-26, against commit `bf78063`.

**Outcome: no IDOR vulnerabilities found.** Every route enumerated, every
by-id lookup on the merchant surface inspected, every public route checked.
The isolation model is sound and consistently applied. The work in this
review was therefore to *pin* that — a structural guard so a future route
cannot ship unclassified — rather than to fix holes.

## The merchant isolation model

A merchant is a row in `merchants`. A user reaches one through an **active**
`merchant_users` row; a platform admin through a `platform_admins` row.
Neither is ever read from a token claim — both are looked up in the database
on every request (`app/auth/dependencies.py`).

Four scoping strategies, by path family:

| Surface | Guard | How the tenant is decided |
|---|---|---|
| `/v1/merchant/*` | `require_own_merchant_role` / `get_own_merchant` | From the caller's own membership. **No `merchant_id` is accepted from the request at all** |
| `/v1/merchants/{merchant_id}/*` | `require_role` / `get_merchant_actor` | Path id checked against the caller's membership |
| Flat routes (`/v1/collections`, `/v1/payment-links`, …) | `get_authenticated_caller` + `authorize_merchant_action` | Merchant known only from the body or a fetched row, then authorized explicitly |
| `/v1/admin/*` | `require_super_admin` | `platform_admins`, plus an `aal2` session when `REQUIRE_SUPER_ADMIN_MFA` is on |

The first is the strongest and covers most of the dashboard: with no
`merchant_id` in the request, the classic "change the tenant id" attack has
nothing to change.

## Endpoint inventory

184 routes:

| Guard | Count |
|---|---|
| `require_super_admin` | 71 |
| `require_own_merchant_role` / `get_own_merchant` | 66 |
| `get_authenticated_caller` (+ in-handler authorization) | 26 |
| `require_role` (path `merchant_id`) | 9 |
| Public, by design | 18 |
| Self-scoped, authenticated | 3 |

The self-scoped three (`accept-invite`, `create-merchant-account`,
`onboarding/status`) take no resource id and resolve any merchant from the
caller's own `user_id`. They exist because they run *before* an active
membership exists, so requiring one would reject every legitimate call.

## What was checked

**By-id lookups on `/v1/merchant/*`** — 23 routes take a resource id in the
path. Every one fetches the row and then compares its `merchant_id` against
`membership.merchant_id`, raising **404** rather than 403. That choice
matters: a 403 on a real id and a 404 on a fake one would itself be an
oracle for enumerating other merchants' records.

**Flat money routes** — the six collection- and disbursement-creation
endpoints take `merchant_id` in the body. They delegate to
`_create_push_collection` / `_create_disbursement`, both of which call
`authorize_merchant_action(caller, payload.merchant_id, …)` before anything
else. A body `merchant_id` therefore cannot move another merchant's money.

**API keys** — a key maps to exactly one merchant;
`get_merchant_actor`/`authorize_merchant_action` reject a key whose
`merchant_id` does not match the target, scopes are enforced separately, and
no admin route accepts a key at all.

**Public routes** — the riskiest is
`/public/payment-links/{public_slug}/collections/{collection_id}/status`,
which takes two ids. It is correctly scoped: the collection must match both
its own id **and** `payment_link_id` of the slug's link, so a collection id
cannot be used to probe an unrelated link. It returns three fields
(`status`, `provider_payment_status`, `failure_reason`) and no merchant or
customer data.

Webhook routes are unauthenticated by necessity and verified by provider
signature instead.

## Super Admin cross-merchant access

Deliberate and total: a platform admin can read and act across every
merchant, because approving withdrawals, approving businesses and setting
pricing require it. It is constrained by being a database role no product
path can grant (`platform_admins` is populated by hand in SQL), by MFA when
`REQUIRE_SUPER_ADMIN_MFA=true`, and by audit logging plus email alerts on
every sensitive action.

## Not present in InfinityPay

The review brief mentions resources this platform does not have, and none
were invented: no routers, hotspot packages, vouchers, ISP sessions or WiFi
billing. There is also **no customers table** — customer identity lives on
collections and invoices as contact fields, so "customer isolation" is
covered by the isolation of those records.

## What this review added

- `tests/test_tenant_isolation_route_guards.py` — enumerates the live route
  table and asserts each route's protection matches its path family.
  Unclassified routes fail; public routes must be listed by hand. It earned
  its place on the first run by flagging `POST /v1/onboarding/documents`,
  which turned out to be correctly guarded by `get_own_merchant` but had not
  been considered.
- `tests/test_cross_merchant_idor.py` — 12 probes that seed a row under
  merchant B and attempt it as merchant A: reading and modifying payment
  links and invoices, reading disputes, revoking and rotating API keys,
  deactivating and promoting staff, plus list-endpoint bleed and a user with
  no membership at all.

## Remaining risks

**Rate limiting is per-process** (`app/core/rate_limit.py`), so limits
multiply by replica count if the API is ever scaled out. Not an isolation
issue, but it weakens abuse protection on enumeration attempts.

**RLS is enabled without policies** on service-role tables. Correct, since
the backend is the only writer, but it means isolation rests entirely on
application code — which is what the guard test above exists to hold in
place.

**The frontend is not the control.** `/super-admin` and `/portal` layouts
redirect, but every page's data comes from the API, which re-checks
independently. A missed frontend guard leaks an empty shell, not data.
