"""A minimal, dependency-free rate limiter for abuse-prone endpoints
(forgot-password, public payment attempts, webhooks, withdrawal
request/approval, merchant API key creation) — see
docs/MVP_LAUNCH_CHECKLIST.md, "Rate limiting" for the full endpoint list
and known limitation below.

In-memory, fixed-window, per-process. Deliberately simple rather than
pulling in a new dependency (no rate-limiting package existed anywhere in
this codebase before this) — correct for this deployment's current
single-replica Railway setup (confirmed 2026-08-28), but **does not
share state across replicas**: if this API is ever scaled to more than
one instance without a shared store (Redis, etc.), each replica enforces
its own independent limit rather than one combined limit. Revisit with a
Redis-backed limiter (or a proxy/edge-level limiter — Railway/Cloudflare)
before scaling horizontally.
"""

import hashlib
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request

from app.core.errors import APIError
from app.core.request_ip import client_ip


class RateLimitExceededError(APIError):
    """429 with a deliberately generic message.

    `retry_after` is rendered as the standard Retry-After header so a
    well-behaved client backs off for the right length of time instead of
    guessing — see register_exception_handlers. It says nothing about
    which limit was hit or what the caller is, because a limiter that
    explains itself tells an attacker how to pace around it."""

    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class _InMemoryRateLimiter:
    """Fixed-window counter per (scope, key) — `key` is normally the
    caller's IP, so each scope's limit applies per-IP, independent of
    every other scope. Thread-safe: uvicorn can run a sync dependency
    function in a worker thread, and multiple requests can race here
    concurrently even on a single process."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, bucket_key: str, *, limit: int, window_seconds: float) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[bucket_key]
            while hits and now - hits[0] > window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                # Seconds until the oldest hit falls out of the window —
                # the earliest moment the caller could succeed.
                retry_after = max(1, int(window_seconds - (now - hits[0])) + 1)
                raise RateLimitExceededError(
                    "Too many requests. Please try again in a few minutes.",
                    retry_after=retry_after,
                )
            hits.append(now)


_limiter = _InMemoryRateLimiter()


def rate_limit(*, scope: str, limit: int, window_seconds: float):
    """Returns a FastAPI dependency: `Depends(rate_limit(scope="...",
    limit=N, window_seconds=W))`. `scope` namespaces the bucket so the
    same caller IP is tracked independently per endpoint/purpose — hitting
    the limit on one scope never affects another. Keyed by IP (via
    app.core.request_ip.client_ip); a request with no resolvable client IP
    at all (host missing, e.g. some test clients) falls back to a shared
    "unknown" bucket rather than skipping the limit entirely."""

    def _dependency(request: Request) -> None:
        ip = client_ip(request) or "unknown"
        _limiter.check(f"{scope}:{ip}", limit=limit, window_seconds=window_seconds)

    return _dependency

def enforce_rate_limit(
    *, scope: str, key: str, limit: int, window_seconds: float, request: Request | None = None
) -> None:
    """Apply a limit from inside a handler, keyed on something the
    dependency layer cannot see.

    The `rate_limit` dependency can only key on the IP, because it runs
    before the body is parsed. Some limits need a second dimension that
    lives in the request itself -- the email on a password reset, the API
    key on a server-to-server call, the merchant on a withdrawal. Keying on
    IP alone lets one attacker rotate addresses against a single account,
    and keying on the account alone lets one address attack many accounts;
    call this alongside the dependency to close both.

    `key` is hashed before use so an email or an API key id never becomes
    part of an in-memory bucket name that could surface in a traceback or a
    heap dump.

    When `request` is given, the caller IP is folded in too, so the bucket
    is (scope, key, ip) rather than (scope, key).
    """
    digest = hashlib.sha256(key.strip().lower().encode("utf-8")).hexdigest()[:32]
    bucket = f"{scope}:{digest}"
    if request is not None:
        bucket = f"{bucket}:{client_ip(request) or 'unknown'}"
    _limiter.check(bucket, limit=limit, window_seconds=window_seconds)
