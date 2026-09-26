"""Throttle for everything this backend sends to Selcom.

Every merchant reaches Selcom through us, from our own whitelisted IPs.
That is the right design — merchants never hold Selcom credentials — but it
concentrates all of their traffic onto a handful of addresses. One ISP
billing partner running a monthly cycle across hundreds of subscribers can
therefore look, from Selcom's side, exactly like abuse from a single
source. Getting that IP blocked takes the whole platform down, not one
merchant.

Three limits, in the order they bite:

**Concurrency** — at most N requests in flight at once. Callers wait for a
slot rather than failing, which is what smooths a burst into a queue
without needing a queue.

**Rate** — at most N requests per minute overall. Also a wait, for the same
reason.

**Circuit breaker** — after N consecutive failures the breaker opens and
calls fail immediately for a cooldown, without touching the network. This
is the one that matters during an outage: retrying into a provider that is
already down is how a temporary problem becomes a blocked IP.

The breaker fails *fast*, not *closed* — an open breaker raises the same
`SelcomAPIError` the transport already raises on a connection failure, so
every caller's existing handling applies unchanged. Nothing new has to
learn about breakers.

In-memory and per-process, the same trade `app/core/rate_limit.py` makes
and documents. Correct at one replica; with two, each gets its own budget
and the effective ceiling doubles. That is the thing to fix before scaling
out, and it is written down in docs/PRODUCTION_TRAFFIC_MANAGEMENT.md.
"""

import asyncio
import logging
import time
from collections import deque
from typing import Self

from app.config import get_settings

logger = logging.getLogger("infinity.selcom_outbound")


class SelcomCircuitOpenError(Exception):
    """Raised instead of making a call, while the breaker is open.

    Callers convert this to their own provider error; it is deliberately
    not a subclass of anything in the transport layer so it cannot be
    mistaken for a real provider response.
    """


class _OutboundGuard:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._recent: deque[float] = deque()
        self._semaphore: asyncio.Semaphore | None = None
        self._semaphore_limit = 0
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def _sem(self, limit: int) -> asyncio.Semaphore:
        # Rebuilt if the configured limit changes, which in practice only
        # happens between tests.
        if self._semaphore is None or self._semaphore_limit != limit:
            self._semaphore = asyncio.Semaphore(limit)
            self._semaphore_limit = limit
        return self._semaphore

    def _breaker_is_open(self, *, cooldown: float) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= cooldown:
            # Cooldown elapsed: close it and let one attempt through. If
            # that fails the threshold trips again immediately.
            self._opened_at = None
            self._consecutive_failures = 0
            logger.info("selcom_circuit_closed")
            return False
        return True

    async def _await_rate_slot(self, *, limit: int, window: float = 60.0) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._recent and now - self._recent[0] > window:
                    self._recent.popleft()
                if len(self._recent) < limit:
                    self._recent.append(now)
                    return
                wait_for = window - (now - self._recent[0])
            # Slept outside the lock so other callers can still drain.
            await asyncio.sleep(min(max(wait_for, 0.05), 5.0))

    def record_success(self) -> None:
        self._consecutive_failures = 0

    def record_failure(self, *, threshold: int) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= threshold and self._opened_at is None:
            self._opened_at = time.monotonic()
            logger.warning(
                "selcom_circuit_opened consecutive_failures=%s", self._consecutive_failures
            )


_guard = _OutboundGuard()


class selcom_outbound:
    """Async context manager wrapping one outbound Selcom call.

    Records the outcome on exit: an exception counts as a failure toward
    the breaker, a clean exit resets it. Wrap only the network call, not
    the surrounding bookkeeping, so local errors do not trip the breaker.
    """

    async def __aenter__(self) -> Self:
        settings = get_settings()

        if _guard._breaker_is_open(cooldown=settings.selcom_circuit_breaker_cooldown_seconds):
            logger.warning("selcom_call_skipped_circuit_open")
            raise SelcomCircuitOpenError(
                "The payment provider is temporarily unavailable. Please try again shortly."
            )

        await _guard._await_rate_slot(limit=settings.selcom_outbound_max_per_minute)
        self._sem = _guard._sem(settings.selcom_outbound_max_concurrent)
        await self._sem.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self._sem.release()
        if exc_type is None:
            _guard.record_success()
        else:
            _guard.record_failure(
                threshold=get_settings().selcom_circuit_breaker_failure_threshold
            )
        return False


def reset_outbound_guard() -> None:
    """Test helper. The guard is a module-level singleton, so one test's
    exhausted window would otherwise leak into the next."""
    global _guard
    _guard = _OutboundGuard()
