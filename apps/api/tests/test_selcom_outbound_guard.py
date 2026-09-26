"""The throttle on everything this backend sends to Selcom.

Every merchant reaches Selcom through us, from our own whitelisted IPs, so
their traffic concentrates onto a few addresses. One ISP partner running a
billing cycle can look like abuse from a single source, and a blocked IP
takes the whole platform down rather than one merchant.

The distinction these tests protect: concurrency and rate make a caller
*wait*, because a burst should be smoothed rather than failed. The breaker
makes a caller *fail fast*, because retrying into a provider that is
already down is how a temporary outage becomes a blocked IP.
"""

import asyncio
import time

import pytest

from app.config import get_settings
from app.services.selcom.outbound_guard import (
    SelcomCircuitOpenError,
    reset_outbound_guard,
    selcom_outbound,
)


@pytest.fixture(autouse=True)
def _fresh_guard(monkeypatch):
    monkeypatch.setenv("SELCOM_OUTBOUND_MAX_PER_MINUTE", "1000")
    monkeypatch.setenv("SELCOM_OUTBOUND_MAX_CONCURRENT", "5")
    monkeypatch.setenv("SELCOM_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("SELCOM_CIRCUIT_BREAKER_COOLDOWN_SECONDS", "60")
    get_settings.cache_clear()
    reset_outbound_guard()
    yield
    get_settings.cache_clear()
    reset_outbound_guard()


# --- concurrency ----------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_calls_are_capped(monkeypatch):
    monkeypatch.setenv("SELCOM_OUTBOUND_MAX_CONCURRENT", "2")
    get_settings.cache_clear()
    reset_outbound_guard()

    in_flight = 0
    peak = 0

    async def call():
        nonlocal in_flight, peak
        async with selcom_outbound():
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1

    await asyncio.gather(*(call() for _ in range(10)))

    assert peak <= 2, f"{peak} requests were in flight at once"


@pytest.mark.asyncio
async def test_every_caller_still_completes(monkeypatch):
    """Capped, not dropped. A burst is smoothed into a queue — nobody's
    payment is refused because someone else was first."""
    monkeypatch.setenv("SELCOM_OUTBOUND_MAX_CONCURRENT", "2")
    get_settings.cache_clear()
    reset_outbound_guard()

    completed = 0

    async def call():
        nonlocal completed
        async with selcom_outbound():
            completed += 1

    await asyncio.gather(*(call() for _ in range(20)))

    assert completed == 20


# --- rate -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_per_minute_rate_makes_callers_wait(monkeypatch):
    """Beyond the limit the caller waits rather than failing. Measured by
    elapsed time, since a wait is the observable behaviour."""
    monkeypatch.setenv("SELCOM_OUTBOUND_MAX_PER_MINUTE", "2")
    get_settings.cache_clear()
    reset_outbound_guard()

    async def call():
        async with selcom_outbound():
            pass

    await call()
    await call()

    started = time.monotonic()
    third = asyncio.create_task(call())
    await asyncio.sleep(0.2)
    assert not third.done(), "the third call should be waiting for a slot"
    third.cancel()
    assert time.monotonic() - started >= 0.2


# --- circuit breaker ------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_failures_open_the_breaker():
    async def failing_call():
        async with selcom_outbound():
            raise RuntimeError("provider down")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await failing_call()

    # Threshold reached: the next call must not reach the network at all.
    with pytest.raises(SelcomCircuitOpenError):
        async with selcom_outbound():
            pytest.fail("a request was made while the breaker was open")


@pytest.mark.asyncio
async def test_an_open_breaker_does_not_call_the_provider():
    """The point of the breaker: during an outage we stop generating
    traffic entirely, rather than retrying into it."""
    calls = 0

    async def failing_call():
        nonlocal calls
        async with selcom_outbound():
            calls += 1
            raise RuntimeError("provider down")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await failing_call()

    before = calls
    for _ in range(10):
        with pytest.raises(SelcomCircuitOpenError):
            await failing_call()

    assert calls == before, "requests were still being made with the breaker open"


@pytest.mark.asyncio
async def test_a_success_resets_the_failure_count():
    """Only *consecutive* failures count. Intermittent errors during
    normal operation must not accumulate into an outage."""
    async def failing_call():
        async with selcom_outbound():
            raise RuntimeError("blip")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await failing_call()

    async with selcom_outbound():
        pass

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await failing_call()

    # 2 + 2 with a success between them is below a threshold of 3.
    async with selcom_outbound():
        pass


@pytest.mark.asyncio
async def test_the_breaker_closes_after_its_cooldown(monkeypatch):
    monkeypatch.setenv("SELCOM_CIRCUIT_BREAKER_COOLDOWN_SECONDS", "0")
    get_settings.cache_clear()
    reset_outbound_guard()

    async def failing_call():
        async with selcom_outbound():
            raise RuntimeError("provider down")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await failing_call()

    # Cooldown of zero means the next attempt is allowed straight through.
    async with selcom_outbound():
        pass


# --- it surfaces as the error callers already handle ----------------------


@pytest.mark.asyncio
async def test_the_collections_client_reports_an_open_breaker_as_a_provider_error():
    """Callers should not need to learn a new exception type; an open
    breaker looks like any other failure to reach Selcom."""
    from app.core.errors import SelcomAPIError
    from app.services.selcom.live_client import SelcomHTTPClient

    async def failing_call():
        async with selcom_outbound():
            raise RuntimeError("provider down")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await failing_call()

    client = SelcomHTTPClient(
        base_url="https://selcom.invalid", api_key="k", api_secret="s", vendor_id="v"
    )

    with pytest.raises(SelcomAPIError):
        await client._post("/test", {"a": 1})
