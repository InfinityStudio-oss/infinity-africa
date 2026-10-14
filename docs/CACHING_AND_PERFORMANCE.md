# Caching and performance

> **The rule, before anything else.** Cache dashboard and report *reads*
> only. Nothing cached may decide whether money is credited, withdrawn,
> approved, settled, reconciled or marked successful. The database is the
> only source of truth for payment status, wallet balance, ledger writes,
> withdrawal approval, webhook processing, reconciliation, and API
> authentication and authorization.

**There is no application cache today, and that is deliberate.** This
document records what was measured, what was done instead, and what the
evidence would have to say before adding one.

---

## What the latency is actually made of

Measured 2026-10-14. Best of six samples each, so these are floors rather
than averages.

| Hop | Cost | Who pays it |
|---|---|---|
| Merchant in Dar es Salaam → API | **135 ms** | every click |
| Merchant → `infinitypay.me` (Vercel) | 93 ms | every page |
| Merchant → Supabase | 91 ms | auth only |
| **API (Amsterdam) → Supabase (Frankfurt)** | **5–8 ms** | every query |

Two conclusions shaped everything below.

**The API is the slowest thing a merchant touches**, and it is slow for a
reason no server move fixes: Vercel and Supabase both sit behind a CDN
that terminates TLS near the user, and the API does not. The browser
negotiates all the way to Amsterdam.

**The database is not the bottleneck.** A dashboard making ten queries
spends ~70 ms on database round trips against 135 ms simply reaching the
API. An application cache attacks the smaller number.

---

## What was done instead of caching

### Fewer round trips

`crud.fetch_in_chunks` batches `.in_()` lookups. Raising the chunk from
200 to 300 took the wallet ledger from ~11 round trips to ~7 for a
merchant with 883 entries — most of what co-locating the API with the
database would have given, for a one-line change. The chunk size is
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

## What is NOT cached, and must never be

Confirmed by audit, 2026-10-14. None of these read from any cache, and
there is no cache to read from:

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

The structural guarantee is `tests/test_tenant_isolation_route_guards.py`,
which walks the whole route table and fails on any route that is not
deliberately classified.

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

Not yet, on the evidence above. It attacks ~70 ms of database time while
135 ms goes on reaching the API, and half the database time was removed
by a one-line change.

It would also add a new production dependency, a new failure mode, and a
staleness decision: a 15-second TTL on the overview means a merchant can
wait 15 seconds to see a payment they have just been told about.

**Revisit when** `/health/db-latency` or the slow-query log shows real
database pressure, or when a merchant's history is large enough that
reports cannot be served inside a request. Add it with evidence, not
ahead of it.

---

## Future work, in the order it is likely to be worth doing

1. **CDN in front of the API.** The only change that addresses the 135 ms.
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
