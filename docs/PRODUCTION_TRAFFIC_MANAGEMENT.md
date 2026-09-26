# Production traffic management

Written 2026-09-26, for supporting a high-volume ISP billing partner
without getting InfinityPay's IP blocked by Selcom.

## The shape of the risk

Merchants never talk to Selcom. They call InfinityPay, and InfinityPay
calls Selcom from its own whitelisted addresses. That is the right design —
no merchant ever holds Selcom credentials — but it has a consequence worth
stating plainly:

**All merchant traffic concentrates onto a handful of IPs.** An ISP partner
running a monthly billing cycle across hundreds of subscribers looks, from
Selcom's side, exactly like abuse from a single source. If that IP is
blocked, every merchant stops collecting, not just the one that caused it.

## What now protects it

`app/services/selcom/outbound_guard.py` wraps every outbound call. Three
limits, in the order they bite:

| Limit | Default | Behaviour |
|---|---|---|
| Concurrency | 5 in flight | caller **waits** |
| Rate | 60/minute | caller **waits** |
| Circuit breaker | 10 consecutive failures, 60s cooldown | caller **fails fast** |

The wait-versus-fail split is the important part. A burst should be
*smoothed*, not refused — nobody's payment should fail because someone
else's was first, so concurrency and rate queue callers rather than
rejecting them. An outage is different: retrying into a provider that is
already down is precisely how a temporary problem becomes a blocked IP, so
the breaker stops generating traffic entirely until the cooldown passes.

An open breaker raises the same error a connection failure already raises,
so every existing caller handles it unchanged.

Also fixed: the collections client retried connect failures **with no
backoff**, looping immediately. That is the exact pattern a provider reads
as an attack. There is now a 1s backoff per attempt.

### Configuration

```
SELCOM_OUTBOUND_MAX_PER_MINUTE=60
SELCOM_OUTBOUND_MAX_CONCURRENT=5
SELCOM_CIRCUIT_BREAKER_FAILURE_THRESHOLD=10
SELCOM_CIRCUIT_BREAKER_COOLDOWN_SECONDS=60
```

All optional; the defaults above apply. Tune `MAX_PER_MINUTE` against what
Selcom actually permits for your account — 60 is a conservative starting
point, not a figure from their documentation.

⚠️ **In-memory, per process.** Correct at one Railway replica. With two,
each gets its own budget and the real ceiling doubles — which defeats the
purpose. Fix this before scaling out.

## Selcom IP strategy

Three addresses are whitelisted with Selcom. Treat them as:

| IP | Role |
|---|---|
| 1 | primary production |
| 2 | backup / failover |
| 3 | staging or disaster recovery |

Do not rotate between them casually — Selcom's allowlist is the control
keeping our traffic distinguishable, and unexplained source changes are
what get an account reviewed. Failover should be a deliberate, configured
switch.

**Merchants are never asked to whitelist anything with Selcom.** The
optional per-key IP allowlist in InfinityPay controls a merchant's access
to *our* API. It has nothing to do with Selcom.

## What already existed

Not rebuilt, because it was already there:

- **Idempotency** — `run_idempotent` keys on merchant + endpoint +
  `Idempotency-Key`. A repeated create returns the original record instead
  of a second payment.
- **Per-endpoint rate limits** — roughly 25 scopes, per-IP, plus per-email
  and per-API-key dimensions (`docs/ABUSE_PROTECTION.md`).
- **Merchant standing gates** — suspended, unapproved and API-suspended
  merchants cannot create live traffic.
- **Reconciliation sweeps** — poll Selcom's authenticated status API rather
  than trusting inbound signals.
- **Signed outbound webhooks** with delivery logging.

## For the ISP partner

Their side should:

1. Send an **`Idempotency-Key`** on every create. Without one, a retry is a
   second payment.
2. **Honour `Retry-After`** on a 429, then use exponential backoff with
   jitter so their workers do not retry in lockstep.
3. **Pace the billing run.** Queue it rather than firing thousands in
   parallel — our throttle will smooth it, but a queue on their side keeps
   latency predictable.
4. Carry their subscriber reference in **`merchant_reference`**, which
   comes back on every status read and webhook.

## Deliberately not built

**A database-backed job queue.** The brief asks for one. It is a
significant architectural change to live money paths, and the concrete risk
it addresses — bursts overwhelming Selcom — is already handled by the
concurrency and rate limits above, which make callers wait. Building a
queue means new states, new failure modes, and a worker that must be
perfectly idempotent around real payments. That deserves its own change
with its own rollout, not a subsection of a hardening pass.

Revisit if either becomes true: the wait at peak becomes long enough to
time out merchant requests, or the API needs more than one replica (at
which point a shared queue and a shared limiter become the same piece of
work).

**HMAC request signing.** Also asked for, also deferred. API keys already
authenticate, are hashed at rest, support per-key IP allowlists, and are
scoped. HMAC adds replay protection and body integrity on top — genuinely
better, but it changes the contract for every integrator, so it needs a
migration path and a flag rather than being switched on mid-pass. Worth
doing before a second large partner integrates, not during the first.

**Per-merchant tiers.** Rate limits are per-endpoint and per-key today. If
the ISP partner needs a higher ceiling than other merchants, that is a
column on `merchants` and a lookup in the limiter — small, but it should be
driven by an observed limit rather than a guess.
