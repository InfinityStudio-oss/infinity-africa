"""A cache that is allowed to be wrong, and never allowed to be slow.

Supabase REST costs 56-60ms per query from this API, measured through
/health/db-latency, so an endpoint that makes nine of them spends most of
a second in the database. That is what this exists to avoid paying twice.

**Three rules shape everything here.**

*Display only.* Nothing cached may decide whether money exists, moves, or
is owed. The withdrawal path, collection crediting, webhook processing,
reconciliation, API-key authentication and every authorization check read
the database directly and have no code path into this module. A cached
value can be stale; a stale number must never become a decision.

*A miss is always correct.* Every failure here - Redis down, a timeout, a
value that will not deserialise, a wrong type - returns None, and the
caller falls through to the database exactly as if no cache existed.
There is no error this module raises.

*Slow is worse than absent.* A cache that hangs turns a 500ms page into a
timeout, which is a worse outcome than never having added it. Hence
aggressive socket timeouts and a circuit breaker: after a few
consecutive failures this stops calling Redis at all for a while, so an
outage costs one timeout rather than one per request per endpoint.

Turning it off is `CACHE_ENABLED=false`, which takes effect on the next
deploy and needs no code change. With no REDIS_URL set it is off anyway,
which is the default.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

from app.config import get_settings

logger = logging.getLogger("infinity.cache")

# How long a Redis call may take before we give up and read the database.
# Deliberately short: the whole value of the cache is being faster than a
# ~57ms query, so a cache lookup that takes longer than that has already
# lost, and waiting longer only makes the page slower than no cache.
_SOCKET_TIMEOUT_SECONDS = 0.25

# Circuit breaker. After this many consecutive failures, stop calling
# Redis entirely for _BREAKER_COOLDOWN_SECONDS.
#
# Without this, a Redis outage costs every cached endpoint a 0.25s
# timeout on every request - turning a performance feature into a
# performance regression at exactly the moment nobody is watching for it.
_BREAKER_THRESHOLD = 3
_BREAKER_COOLDOWN_SECONDS = 30.0

_consecutive_failures = 0
_breaker_open_until = 0.0


class _SafeEncoder(json.JSONEncoder):
    """Decimal to string, never to float.

    float(Decimal("0.1")) is not 0.1, and this platform caches money
    amounts. Pydantic coerces the string back to Decimal on the way out,
    so the round trip is exact.
    """

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, uuid.UUID):
            return str(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return super().default(o)


@lru_cache
def _client():
    """The Redis client, or None when caching is off or unconfigured.

    lru_cached so the connection pool is shared. Returns None rather than
    raising for every "not available" case, because every caller treats
    None as "read the database", which is always a correct answer.
    """
    settings = get_settings()
    if not settings.cache_enabled:
        return None
    url = (settings.redis_url or "").strip()
    if not url:
        return None
    try:
        import redis
    except ImportError:
        logger.warning("cache_disabled reason=redis_package_not_installed")
        return None
    try:
        return redis.from_url(
            url,
            socket_timeout=_SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
            retry_on_timeout=False,
            decode_responses=True,
        )
    except Exception:  # noqa: BLE001 — see module docstring: a miss is always correct
        # The URL carries the password, so the exception text does not go
        # in the log. The reason code is enough to act on.
        logger.warning("cache_disabled reason=redis_url_unusable")
        return None


def _breaker_is_open() -> bool:
    return time.monotonic() < _breaker_open_until


def _record_failure(operation: str) -> None:
    global _consecutive_failures, _breaker_open_until
    _consecutive_failures += 1
    if _consecutive_failures >= _BREAKER_THRESHOLD and not _breaker_is_open():
        _breaker_open_until = time.monotonic() + _BREAKER_COOLDOWN_SECONDS
        logger.warning(
            "cache_breaker_open operation=%s cooldown_seconds=%s",
            operation,
            int(_BREAKER_COOLDOWN_SECONDS),
        )


def _record_success() -> None:
    global _consecutive_failures
    _consecutive_failures = 0


def reset_breaker() -> None:
    """Test hook. Production never needs this - the breaker closes itself
    on the first success after the cooldown."""
    global _consecutive_failures, _breaker_open_until
    _consecutive_failures = 0
    _breaker_open_until = 0.0
    # Guarded because a test may have replaced _client with a plain
    # function, which has no lru_cache to clear.
    clear = getattr(_client, "cache_clear", None)
    if clear is not None:
        clear()


def _namespace() -> str:
    """Keys are scoped by environment so a staging deploy pointed at the
    same Redis cannot answer a production request."""
    return f"infinitypay:{get_settings().environment}:"


def merchant_key(merchant_id: uuid.UUID | str, resource: str, *parts: str) -> str:
    """A cache key scoped to one merchant.

    The merchant id is in every key by construction rather than by
    convention, which is what stops one merchant's dashboard answering
    another's request. `parts` are for things like a date range; callers
    must hash or bucket anything free-form rather than passing it
    through, because a key is stored and logged and must not carry a
    phone number, a customer name or raw search text.
    """
    suffix = ":".join(str(part) for part in parts)
    key = f"{_namespace()}merchant:{merchant_id}:{resource}"
    return f"{key}:{suffix}" if suffix else key


def cache_get(key: str) -> Any | None:
    """The cached value, or None for a miss, an outage, or anything
    unreadable. Never raises."""
    client = _client()
    if client is None or _breaker_is_open():
        return None
    try:
        raw = client.get(key)
    # Blind on purpose. A connection reset, a DNS failure, an SSL error
    # and a redis-py bug must all mean the same thing here: read the
    # database. Catching only redis exceptions would let the rest break
    # a request that had a perfectly good answer available.
    except Exception:  # noqa: BLE001
        _record_failure("get")
        logger.warning("cache_error operation=get")
        return None
    _record_success()
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        # A value written by an older deploy with a different shape. Treat
        # it as a miss rather than letting it reach a response model.
        logger.warning("cache_unreadable_value operation=get")
        return None


def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    """Store a value with a required TTL. Never raises.

    The TTL is a positional argument with no default on purpose: a cache
    entry with no expiry on a payments platform is a number that can be
    wrong forever.
    """
    client = _client()
    if client is None or _breaker_is_open():
        return
    if ttl_seconds <= 0:
        logger.warning("cache_set_rejected reason=non_positive_ttl")
        return
    try:
        client.setex(key, ttl_seconds, json.dumps(value, cls=_SafeEncoder))
    except (TypeError, ValueError):
        # Not serialisable. A bug worth seeing, but not worth failing a
        # request that has already produced a correct answer.
        logger.warning("cache_unserialisable_value operation=set")
    except Exception:  # noqa: BLE001 — never fail a request over a cache write
        _record_failure("set")
        logger.warning("cache_error operation=set")
    else:
        _record_success()


def cache_delete(*keys: str) -> None:
    """Drop keys. Never raises.

    Invalidation is best-effort by design. If it fails the entry expires
    on its own TTL, which is why every TTL here is short - correctness
    must not depend on a delete succeeding.
    """
    client = _client()
    if client is None or _breaker_is_open() or not keys:
        return
    try:
        client.delete(*keys)
    except Exception:  # noqa: BLE001 — a failed delete expires on its TTL instead
        _record_failure("delete")
        logger.warning("cache_error operation=delete")
    else:
        _record_success()


# Resources a merchant's display caches are stored under. Listed here so
# invalidation cannot drift from what is actually cached - adding a
# cached read without adding it here is the bug this list prevents.
_MERCHANT_DISPLAY_RESOURCES = ("overview", "settings")

# How many pages of a paginated cached list to clear. The lists cached
# this way are short-TTL and rarely deep; anything past this expires on
# its own in at most a minute.
_MAX_PAGED_INVALIDATION = 5


def invalidate_merchant_display(merchant_id: uuid.UUID | str) -> None:
    """Drop one merchant's cached dashboard reads. Never raises.

    Called after the events that change what a merchant sees: a
    collection credited, a transaction status changing, a ledger write, a
    withdrawal requested or decided, settings edited, an API key created
    or revoked.

    **This is a freshness mechanism, not a correctness one.** Nothing
    cached decides anything, so a failed invalidation means a merchant
    sees a number up to its TTL old - at most twenty seconds for the
    overview - and never that money was handled wrongly. That is also why
    it is safe to call from inside a money path: it cannot fail the
    caller, and the caller's correctness does not depend on it.
    """
    keys = [merchant_key(merchant_id, resource) for resource in _MERCHANT_DISPLAY_RESOURCES]
    for page in range(1, _MAX_PAGED_INVALIDATION + 1):
        for size in (20, 25, 50, 100):
            keys.append(merchant_key(merchant_id, "api-keys", str(page), str(size)))
    cache_delete(*keys)
