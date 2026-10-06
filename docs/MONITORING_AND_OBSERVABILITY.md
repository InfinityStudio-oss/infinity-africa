# Monitoring and observability

Error monitoring (Sentry) and product analytics (PostHog), both built to
one rule: **they ship switched off, and nothing they do can break a
payment.**

With no environment variables set, no SDK initialises, no network call
is made, and the platform behaves exactly as it did before any of this
existed. Turning monitoring on is a deploy-time decision. That is
deliberate — this went onto a platform already carrying real merchants
and real money, and the safest version of a new dependency is one that
is inert until someone chooses otherwise.

## Switching it on

Four services, two of them optional. Nothing here is in the repo; all of
it is set in a dashboard.

### 1. Sentry — API errors (Railway)

Create a Sentry project of platform **Python**, then in Railway:

| Variable | Value |
|---|---|
| `SENTRY_DSN` | the project's DSN |
| `SENTRY_ENVIRONMENT` | `production` |
| `SENTRY_TRACES_SAMPLE_RATE` | leave at `0.0` |

The API's DSN is **server-side only**. A DSN cannot read anything back
out of Sentry, but a public one lets anyone forge error reports into the
project, so it is not a `NEXT_PUBLIC_` value.

### 2. Sentry — browser and Next server errors (Vercel)

Create a **second**, separate project, of platform **Next.js**. It has to
be separate: a browser DSN ships inside the JavaScript bundle and is
therefore public by necessity, which is not something the API's DSN may
ever be.

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_SENTRY_DSN` | the Next project's DSN |
| `NEXT_PUBLIC_SENTRY_ENVIRONMENT` | `production` |
| `SENTRY_DSN` | the same DSN again, for server components and Server Actions |
| `SENTRY_ENVIRONMENT` | `production` |

**Redeploy after setting these.** `NEXT_PUBLIC_*` values are baked into
the bundle at build time, and — see below — so is the CSP entry that
allows events to be sent at all.

### 3. PostHog — product analytics (optional)

Pick the **EU** region, to match where the database and API already live.

| Where | Variable | Value |
|---|---|---|
| Vercel | `NEXT_PUBLIC_POSTHOG_KEY` | project API key |
| Vercel | `NEXT_PUBLIC_POSTHOG_HOST` | `https://eu.i.posthog.com` |
| Railway | `POSTHOG_API_KEY` | the same project key |
| Railway | `POSTHOG_HOST` | `https://eu.i.posthog.com` |

Analytics is genuinely optional. Sentry answers "is it broken"; PostHog
answers "is it working" — are collections succeeding, are webhooks
landing, are merchants getting through onboarding.

### 4. Sentry alerts — the manual step that makes it useful

An error tracker nobody looks at is a log file with a nicer font.
Sentry sends no alerts by default beyond its own digest, so these are
worth creating by hand in **Alerts → Create Alert** on the API project:

| Alert | Condition | Why |
|---|---|---|
| **Webhook exhausted** | an issue whose message contains `webhook delivery exhausted` | A merchant has permanently missed a transaction notification, and there is no replay. This is the one to wake someone for |
| **New issue in production** | a new issue is created, environment `production` | A 500 nobody has seen before |
| **Error spike** | more than ~20 events in 5 minutes | Provider outage, bad deploy, or an endpoint failing for everyone |

Set the delivery address to the same mailbox that already receives
withdrawal approvals, so there is one place to watch rather than two.

## The Content-Security-Policy catch

The frontend serves a strict CSP whose `connect-src` is `'self'` plus
Supabase and the API. Sentry and PostHog both report by POSTing to their
own hosts — which that policy forbids.

So `apps/web/next.config.ts` adds each origin to `connect-src` **only
when the matching key is configured at build time**. Nothing to do by
hand, but worth knowing, because the failure mode is quiet: without it
the SDKs initialise, report themselves healthy, and have every single
event dropped by the browser. If a dashboard stays empty after setup,
check the browser console for a CSP violation before anything else — and
check that the deploy happened *after* the variable was set.

## What creates an alert, and what does not

Sentry's default turns every `logger.error()` and `logger.exception()`
into its own alert. That is wrong for this codebase, where catching an
error and carrying on is the design rather than an accident. Twenty-odd
such sites existed — a reconciliation sweep logging one bad row and
continuing, a provider returning 502 on a call the next tick will redo —
and each one paged on something already handled. On the first day of real
traffic the signal drowned.

So `init_sentry()` sets `LoggingIntegration(event_level=CRITICAL)`.
Breadcrumbs stay at INFO, so a real error still arrives with the log trail
that led to it.

| Situation | Alerts? | Why |
|---|---|---|
| `logger.error` / `logger.exception` | No | Already handled; the code carried on deliberately |
| Client error — 400, 404, 409, 422 | No | The API correctly told a caller they were wrong |
| Unhandled exception (500) | Yes | A merchant's request failed and nobody caught it |
| Provider 5xx reaching a merchant | Yes | Selcom down mid-payment is worth knowing |
| Worker sweep failing outright | Yes | Explicit `capture_exception` in the scheduler loops |
| Webhook delivery exhausted | Yes | A merchant will never receive that event; no replay |
| Audit log write failed | Yes | The compliance record of who moved money |
| Security alert email failed | Yes | Every other alert is going unseen too |
| `logger.critical` | Yes | Unused today; left as the escape hatch |

The last two are explicit `capture_exception()` calls, added precisely
because raising the log threshold would otherwise have silenced them.
`apps/api/tests/test_monitoring_alert_policy.py` pins the whole table, and
was verified to fail if the noisy default comes back.

## What is never sent

The part worth reviewing properly. An error report is a payload leaving
this infrastructure for a third party, and the things an SDK attaches by
default — the request, its headers, its body, the local variables in the
stack frame — are exactly the things carrying a merchant's API key, a
customer's phone number and a provider's credentials.

Three layers, because each alone has a hole:

1. **Whole sections are dropped**, not redacted: request bodies, query
   strings, cookies, the server environment. A payment body is sensitive
   in its entirety — the amount, the phone and the reference *are* the
   payload, so there is nothing to redact it down to.
2. **Headers are allow-listed, not deny-listed.** A deny-list protects
   the headers someone thought of; an allow-list protects against the one
   they did not.
3. **Whatever survives is walked and pattern-redacted**, because a secret
   can arrive inside an exception message, a breadcrumb or a tag — places
   no structural rule reaches.

Redacted wherever it appears, in any field: API keys (`sk_`/`pk_`),
Resend keys, anything JWT-shaped (Supabase access and refresh tokens),
bearer tokens, email addresses, Tanzanian phone numbers in every accepted
format, and NIDA numbers.

Also off, by explicit configuration rather than by default:

| Setting | Why |
|---|---|
| Session replay | It records the DOM — a payment form mid-entry, a revealed API secret in the portal |
| Autocapture | It records the text of whatever was clicked, which on a checkout page is a phone number |
| Automatic pageviews | They send the full URL; this app's URLs carry reset tokens, OTP codes and `?email=` |
| Console and `ui.input` breadcrumbs | One carries anything ever logged, the other carries what was typed |
| Stack-frame local variables | A frame captured mid-payment holds the phone, the amount, and sometimes provider credentials |
| Performance tracing | A payment platform's URLs and timings are themselves information worth not exporting by default |
| PostHog remote script loading | It would let a third party decide what JavaScript runs on a payment page |

Sentry SDK v11 replaced the old single `sendDefaultPii: false` switch
with a granular `dataCollection` object **whose defaults are permissive**
— cookies, headers, bodies, query params and local variables are all
collected unless turned off. Every `false` in
`apps/web/src/lib/monitoring/sentry-privacy.ts` is therefore
load-bearing. Removing one silently starts exporting customer data, which
is why they live in one shared file with a comment each rather than
duplicated across three init files.

PostHog carries one identity and no more: `merchant_id`, a UUID this
platform issued, which identifies no human. Properties are **allow-listed
by name** in `apps/api/app/core/analytics.py` — a key nobody listed is
discarded rather than sent, which is what stops a well-meaning future
call site adding `customer_name`. Amounts are banded (`<1k`, `1k-10k`, …)
rather than sent, because an exact amount plus a timestamp re-identifies
one payment and with it one payer.

## Why analytics cannot break a payment

`track()` is called inside `resolve_collection()` — the single function
every crediting path funnels through. If PostHog being down could
propagate out of that call, an analytics outage would become a payment
outage: the collection would not credit, and a merchant would be told
their customer's money had not arrived.

So `track()` swallows its own exceptions, hands events to a background
queue rather than sending inline, and is never awaited.
`test_a_broken_analytics_client_still_credits_the_wallet` in
`apps/api/tests/test_collections.py` pins this by breaking the analytics
client outright and asserting the ledger still balances. That test has
been checked to fail when the swallow is removed, so it is testing
something real.

## Turning it off in a hurry

Unset the variable and redeploy. There is no feature flag to find and no
code to revert:

| To stop | Unset | Where |
|---|---|---|
| All API error reporting | `SENTRY_DSN` | Railway |
| All browser error reporting | `NEXT_PUBLIC_SENTRY_DSN` and `SENTRY_DSN` | Vercel |
| All analytics | `POSTHOG_API_KEY`, `NEXT_PUBLIC_POSTHOG_KEY` | Railway, Vercel |

The frontend ones need a redeploy to take effect, for the same build-time
reason as above. If something needs stopping *immediately* and a deploy is
too slow, disable the key in the Sentry or PostHog dashboard instead —
that takes effect without touching this platform at all.

## What this does not replace

Railway logs remain the source of truth, and `capture_exception()` is
called *after* `logger.exception()`, never instead of it. The signals
worth watching in the logs, the append-only `audit_logs` table and the
security alert emails are all unchanged — see
`docs/SECURE_DEPLOYMENT_AND_MONITORING.md` and
`docs/LAUNCH_DAY_RUNBOOK.md`.

Still not covered, and worth knowing:

- **No uptime monitoring.** Nothing tells you the API is down if it is
  down in a way that produces no errors. An external pinger against
  `/health` is a separate, and cheaper, thing to add.
- **No source maps uploaded.** Browser stack traces will be minified.
  Fixing that means a Sentry auth token and the build-time plugin, which
  adds a failure mode to the Vercel build — deliberately not done in the
  same change as everything else.
- **No alerting on absence.** A worker that stops ticking produces no
  error. The existing `scheduled_*` log lines are still how you notice.

## Where the code is

| Concern | File |
|---|---|
| API Sentry init and scrubber | `apps/api/app/core/monitoring.py` |
| API analytics | `apps/api/app/core/analytics.py` |
| Scrubber contract (API) | `apps/api/tests/test_monitoring_scrubber.py` |
| Analytics safety contract | `apps/api/tests/test_analytics_safety.py` |
| Browser scrubber | `apps/web/src/lib/monitoring/scrub.ts` |
| What Sentry may collect | `apps/web/src/lib/monitoring/sentry-privacy.ts` |
| Browser / Node / edge init | `apps/web/instrumentation-client.ts`, `sentry.server.config.ts`, `sentry.edge.config.ts` |
| PostHog provider | `apps/web/src/components/providers/analytics-provider.tsx` |
| CSP origins | `apps/web/next.config.ts` |
