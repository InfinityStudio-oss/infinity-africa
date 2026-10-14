# Caching and performance

> **The rule, before anything else.** Cache dashboard and report *reads*
> only. Nothing cached may decide whether money is credited, withdrawn,
> approved, settled, reconciled or marked successful. The database is the
> only source of truth for payment status, wallet balance, ledger writes,
> withdrawal approval, webhook processing, reconciliation, and API
> authentication and authorization.

**A Redis cache was added on 2026-10-14**, after measurement showed the
database was the dominant cost. It holds three merchant *display* reads
and nothing else. It is off unless `CACHE_ENABLED=true` and `REDIS_URL`
are both set, and turning it off is a performance change, never a
correctness one.

---

## What the latency is actually made of

Measured 2026-10-14. Best of six samples each, so these are floors rather
than averages.

| Hop | Cost | Who pays it |
|---|---|---|
| Merchant in Dar es Salaam → API | **135 ms** | every click |
| Merchant → `infinitypay.me` (Vercel) | 93 ms | every page |
| Merchant → Supabase | 91 ms | auth only |
| **API (Amsterdam) → Supabase (Frankfurt)** | **~57 ms** | every query |

> **That last number was predicted at 5–8 ms and measured at ~57 ms.**
> Amsterdam to Frankfurt is ~400 km, so the network portion really is
> 5–8 ms — but a Supabase REST query is not just network. It passes
> through Supabase's own edge and gateway, PostgREST, and then Postgres,
> and the measured floor for the most trivial possible query (one
> indexed id, `limit 1`) is 56–60 ms. Warming the connection pool does
> not help: twelve back-to-back probes floored at 56 ms, and a 30-second
> idle gap cost only the first one. **Measure, then conclude.** The
> original estimate was out by roughly eight times and pointed at the
> wrong fix.

**The API is the slowest single hop a merchant touches**, and it is slow
for a reason no server move fixes: Vercel and Supabase both sit behind a
CDN that terminates TLS near the user, and the API does not.

**But per-query overhead, not distance, dominates anything that makes
several queries.** At ~57 ms each, a ten-query dashboard spends ~570 ms
in the database against 135 ms reaching the API. The round-trip *count*
is therefore the most important performance variable on this platform —
far more than indexes, and more than where the server sits.

---

## What was done instead of caching

### Fewer round trips

**The highest-value lever, now that a query is known to cost ~57 ms.**

`crud.fetch_in_chunks` batches `.in_()` lookups. Raising the chunk from
200 to 300 took the wallet ledger from ~11 round trips to ~7 for a
merchant with 883 entries. At the measured cost that is roughly **230 ms
saved** from one changed constant — not the ~15 ms the original estimate
implied. The chunk size is
bounded by a URL limit measured at 675 ids; see
`tests/test_in_chunk_size.py`, which is what stops a future increase from
quietly re-creating a production outage.

### Composite indexes

`supabase/migrations/20261014120000_merchant_list_composite_indexes.sql`.
Every index on the busy tables was single-column, so
`where merchant_id = $1 order by created_at desc limit 50` had to sort a
merchant's whole history before returning a page. Eight composites now
match the real access pattern.

Honest about the size of this win: the largest table holds ~8,000 rows,
where sorting is sub-millisecond and Postgres may ignore the index. These
are written for where the platform is heading, not where it is.

### Pagination

Already enforced before this work: `app/core/pagination.py` caps
`page_size` at **100** (`le=100`), default 20. No endpoint accepts an
unbounded limit.

### Explicit cache policy

Every API response now sends `Cache-Control: no-store`. See below.

---

## What is cached

| Read | Key | TTL | Why safe |
|---|---|---|---|
| Dashboard aggregates | `merchant:{id}:overview` | **20 s** | Totals describing a merchant's own history. Nine queries become one cache read. |
| Merchant settings | `merchant:{id}:settings` | **300 s** | The merchant's own profile. `MerchantResponse` carries no secret. |
| API key list (masked) | `merchant:{id}:api-keys:{page}:{size}` | **60 s** | Serialised through `ApiKeyResponse`, which has **no field capable of holding a secret**. |

Every key is prefixed `infinitypay:{environment}:`, so a staging deploy
sharing a Redis cannot answer a production request, and every merchant
key contains the merchant id **by construction** — which is what prevents
one merchant's dashboard answering another's request.

### The wallet balance is deliberately not cached

`get_merchant_overview` caches eight aggregates and reads
`available_balance` **fresh on every call**. It is one query of nine, so
caching it would buy about a ninth of the saving, and it is the single
number a merchant trusts most: the one they look at to decide whether to
withdraw. A stale total-collections figure is a cosmetic lag. A stale
balance tells a merchant they have money they have already moved.

This does not make the displayed balance authoritative — the withdrawal
path reads it again for itself in `app/services/disbursements.py`, which
is what actually protects the money.

The merchant row is also read live, so a settings change shows at once.

### Super Admin is never cached — a decision, not an oversight

**`/v1/admin/*` has no cache and must not get one.** Confirmed by the
platform owner, 2026-10-14. Do not propose it again without a new reason.

The cache is wired into `/v1/merchant/*` only. Super Admin is where
withdrawals are approved, businesses are suspended and fraud alerts are
reviewed. Those are decisions about money, and a decision made on a
cached figure is the exact failure this whole design exists to prevent.

The Super Admin overview makes **13 queries** — more than the merchant
dashboard's 9 — so there is a real temptation here, which is why the
decision is written down rather than left to judgement. If that page
needs to be faster, the answer is **fewer queries**, not cached ones:
platform-wide totals computed database-side help whether or not anything
is cached, and introduce no staleness into a screen where money decisions
are made.

Indexes are different and already apply everywhere — they are
database-level, so Super Admin benefits from
`20261014120000_merchant_list_composite_indexes.sql` with no caching
involved.

### What the brief asked for that does not exist here

- **"Today collections summary"** is not a separate endpoint; it is a
  field inside the overview and is cached with it.
- **"Reports summary"** has no cacheable read. `POST /v1/merchant/reports`
  *builds and emails* a report — caching it would cache an email send.
  Report figures are read from the database every time.

---

## What is NOT cached, and must never be

Confirmed by audit, 2026-10-14, and enforced structurally — see below.
None of these read from any cache:

- customer payment page status polling
- payment success/failure verification
- collection crediting
- webhook processing and webhook idempotency checks
- reconciliation
- wallet balance used for withdrawal eligibility
- wallet ledger writes
- withdrawal creation, approval and rejection
- settlement status
- Super Admin approval decisions
- API key authentication
- merchant authorization checks
- auth and session state
- raw provider callbacks and provider verification responses

**This is enforced, not just documented.**
`tests/test_cache_never_reaches_money.py` parses every module's imports
and fails if `app/core/cache.py` is imported by anything outside a
four-module allowlist — and names each money path individually so a
failure says which one. A module that cannot import the cache cannot read
a stale value from one. Adding an import means arguing for it in a diff
rather than hoping it is noticed in review.

Route-level authorization is held separately by
`tests/test_tenant_isolation_route_guards.py`.

## Invalidation

Display freshness only. **Correctness never depends on an invalidation
succeeding** — if one fails, a figure is stale until its TTL expires, at
most twenty seconds for the overview. That is also why it is safe to call
from inside a money path: it cannot raise, and the caller's correctness
does not rest on it.

| Event | Hook |
|---|---|
| Any ledger write — collection credit, disbursement, refund, either reversal | all five posting functions in `app/services/ledger.py` |
| Merchant settings or status change | `crud.update_row` on `merchants` |
| API key create / revoke / update | `crud.insert_row` and `crud.update_row` on `api_keys` |

The last two are hooked centrally in `crud` rather than in each handler,
so a mutation added later cannot forget to invalidate.

## When Redis is unavailable

The API keeps working from the database. Specifically:

- Every failure — outage, timeout, unparseable value, wrong type —
  returns a **miss**, and the caller reads the database as if no cache
  existed. No operation in `app/core/cache.py` raises.
- **Socket timeouts are 0.25 s.** A cache lookup slower than a ~57 ms
  query has already lost; waiting longer would make the page slower than
  no cache at all.
- **A circuit breaker** opens after 3 consecutive failures and stops
  calling Redis for 30 seconds. Without it, an outage would cost every
  cached endpoint a timeout on *every* request — turning a performance
  feature into a regression precisely when nobody is watching.

## Rollback

Set `CACHE_ENABLED=false` on Railway and redeploy. Nothing else changes:
no code path, no schema, no financial behaviour. Clearing `REDIS_URL` has
the same effect. Both are safe to do at any time, including mid-incident.

---

## Cache-Control and the CDN question

**Until 2026-10-14 this API sent no `Cache-Control` header at all.**

A cache with no explicit policy falls back to heuristics. Most refuse to
store a response to a request carrying an `Authorization` header — which
is the only reason this has been safe. That is an accident of convention,
not a decision.

It matters because **putting Cloudflare in front of the API is the single
change merchants would feel** (it attacks the 135 ms, which no amount of
database work touches). But pointing a CDN at an origin that states no
policy is how one merchant's wallet response gets served to another. That
is not a stale page; it is one business reading another's money.

So every response now sends `Cache-Control: no-store`, set with
`setdefault` so a specific route can later opt into `private, max-age=N`
— `private` meaning the browser only, never a shared cache. Pinned by
`tests/test_security_headers.py`.

**If a CDN is added**, the order is: no-store first (done), then cache
rules that are opt-in per path, never a blanket rule. And one trap from
[ABUSE_PROTECTION.md](ABUSE_PROTECTION.md): **never challenge
`/v1/webhooks/*`** — a managed challenge served to Selcom silently breaks
settlement.

---

## Measuring

### `GET /health/db-latency`

```json
{ "ok": true, "database": "ok", "latency_ms": 7, "timestamp": "..." }
```

One trivial indexed read, timed from the API. This is the number that
cannot be measured from a browser — a merchant is ~90 ms from anything in
Europe, which swamps a 5–8 ms signal entirely.

Unauthenticated on purpose so an uptime monitor can call it, rate limited
because of it, and it reports no host, no query and no row counts. An
outage answers `ok: false` rather than raising: a 500 would tell a
monitor the monitor is broken.

### Slow query warnings

`app/database/session.py::_log_if_slow` times every Supabase round trip
at the transport — the same place the stale-connection retry lives, so it
covers all query call sites including ones not yet written. Over
`SLOW_QUERY_WARNING_MS` (default 400, `0` disables) it logs one line:

```
slow_supabase_query table=transactions method=GET duration_ms=812
```

**Table only, never the query string.** A PostgREST URL carries its
filters, and on this platform those are a customer's phone number, a
merchant id and a payment reference.

---

## Would Redis help?

**The measurement reopened this.** The case against it rested on database
time being ~70 ms against 135 ms of network. At ~57 ms per query the real
figure for a multi-query endpoint is several hundred milliseconds, and
the database is the dominant cost rather than the smaller half.

What has not changed is the order of operations. Caching a result still
costs a staleness decision — a 15-second TTL on the overview means a
merchant can wait 15 seconds to see a payment they were just notified
about — while **removing a query costs nothing and helps every caller,
cached or not**. Seven round trips cached is still seven round trips on
every miss, every invalidation and every first view.

So: finish the two round-trip reductions below first (they are bounded,
testable, and need no new infrastructure), re-measure, and then size
Redis against what is left. The evidence now says it is likely worth it —
which is the opposite of what this document said before the number was
measured, and the reason it was worth measuring.

---

## Future work, in the order it is likely to be worth doing

1. **Wallet ledger fast path and PostgREST embedding** — moved to the top
   by the measurement. Each removed query is worth ~57 ms. See 2 and 3
   below, which are now the highest-value work on this list.
1. **CDN in front of the API.** Addresses the 135 ms, which is no longer
   the largest term for a multi-query page but is still every page's
   floor.
2. **Wallet ledger fast path.** `_wallet_ledger_entries` replays a
   merchant's complete history on every page view to compute running
   balances. It no longer needs to for almost anyone: **8,067 ledger rows
   exist and only 93 lack the `balance_before`/`balance_after` snapshot**
   captured at posting time since migration `20260828010000`. A page
   whose rows all carry snapshots can be fetched with `.range()` at the
   database instead of in Python. The legacy rows keep today's replay.
   This is the largest remaining win and is deliberately left as its own
   change, because it touches how balances are displayed.
3. **PostgREST resource embedding.** `select=*,transactions(*)` would make
   the ledger one request instead of seven. Blocked on the fake Supabase
   client, which ignores its `select` argument entirely and cannot model
   a join — so this starts by teaching the fake, not by changing a query.
4. Merchant daily summary table, or materialized views, if reports
   outgrow live queries.
5. Read replicas, if read volume justifies it.

---

## Deployment checklist

This change needs **no new environment variables** — there is no Redis.

1. **Apply the migration first.** The API must never deploy ahead of its
   schema. `20261014120000_merchant_list_composite_indexes.sql` builds
   eight indexes; they lock writes (not reads) for the duration, which at
   current table sizes is milliseconds.
2. Deploy the API.
3. `curl https://api.infinitypay.me/health/db-latency` — expect
   `ok: true` and a `latency_ms` in single or low double digits.
4. `curl -sI https://api.infinitypay.me/health | grep -i cache-control` —
   expect `no-store`.
5. Watch Railway logs for `slow_supabase_query`. Silence is the expected
   result; a repeating table name is the next thing to look at.
6. No frontend redeploy is required. Nothing in `apps/web` changed.
