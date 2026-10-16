"""app/main.py's backend-initiated reconciliation loop — the piece that
actually keeps Selcom Checkout collections crediting now that the inbound
webhook fails closed on every real (unsigned) delivery. The reconciliation
logic itself (app/services/checkout_reconciliation.py::
reconcile_pending_checkout_collections) is fully covered in
tests/test_checkout_reconciliation.py; this just proves the scheduler
actually calls it on a timer and keeps running afterward.
"""

import asyncio

import pytest

import app.main as main_module
from app.main import _checkout_reconciliation_loop, _start_checkout_reconciliation_task

# A generous ceiling, not a target — _run_loop_until_n_calls returns as soon
# as the Nth call happens, on any machine speed; this only bounds how long a
# genuinely broken/hung loop is allowed to block the test suite before failing.
_WAIT_TIMEOUT = 10.0

@pytest.fixture(autouse=True)
def _lease_is_available(monkeypatch):
    """These tests are about the loop's timing, not about which replica
    runs it. The lease has its own tests in test_scheduler_lease.py.

    Without this the loops would skip every tick: they monkeypatch
    get_supabase_admin to a bare object, which has no .table(), so
    acquire_lease catches the error and answers "someone else has it".
    """
    monkeypatch.setattr("app.main.acquire_lease", lambda _client, _name: True)
    monkeypatch.setattr("app.main.release_lease", lambda _client, _name: None)



async def _run_loop_until_n_calls(interval: float, target_calls: int, call_counter: list) -> None:
    """Runs the real loop and returns as soon as call_counter has grown to
    target_calls, rather than guessing a sleep duration — immune to the
    test machine being fast or slow (a fixed sleep() budget is exactly
    the kind of assumption that flakes under load)."""
    task = asyncio.create_task(_checkout_reconciliation_loop(interval))
    try:
        async with asyncio.timeout(_WAIT_TIMEOUT):
            while len(call_counter) < target_calls:
                await asyncio.sleep(0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_loop_calls_reconciliation_repeatedly_until_cancelled(monkeypatch):
    calls = []

    async def _fake_reconcile(client):
        calls.append(1)
        return {"checked": 0, "resolved": 0, "still_pending": 0}

    monkeypatch.setattr("app.main.reconcile_pending_checkout_collections", _fake_reconcile)
    monkeypatch.setattr("app.main.get_supabase_admin", lambda: object())

    asyncio.run(_run_loop_until_n_calls(interval=0.001, target_calls=3, call_counter=calls))

    assert len(calls) >= 3  # ran more than once — genuinely on a timer, not a one-shot


async def _start_and_cancel() -> asyncio.Task | None:
    task = _start_checkout_reconciliation_task()
    if task is not None:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    return task


def test_scheduler_starts_a_task_when_interval_is_positive(monkeypatch):
    monkeypatch.setattr(main_module.settings, "selcom_checkout_reconcile_interval_seconds", 120)

    task = asyncio.run(_start_and_cancel())

    assert task is not None


def test_scheduler_disabled_when_interval_is_zero(monkeypatch):
    monkeypatch.setattr(main_module.settings, "selcom_checkout_reconcile_interval_seconds", 0)

    task = asyncio.run(_start_and_cancel())

    assert task is None


def test_scheduler_disabled_when_interval_is_negative(monkeypatch):
    """Defensive — a misconfigured negative value must not be treated as
    "on" (e.g. via a truthy/nonzero check instead of > 0)."""
    monkeypatch.setattr(main_module.settings, "selcom_checkout_reconcile_interval_seconds", -5)

    task = asyncio.run(_start_and_cancel())

    assert task is None


def test_scheduler_disabled_when_auto_reconciliation_flag_is_off(monkeypatch):
    """ENABLE_AUTO_RECONCILIATION=false must pause this scheduler even
    with a real positive interval configured — a single flag to stop
    both reconciliation schedulers at once."""
    monkeypatch.setattr(main_module.settings, "selcom_checkout_reconcile_interval_seconds", 120)
    monkeypatch.setattr(main_module.settings, "enable_auto_reconciliation", False)

    task = asyncio.run(_start_and_cancel())

    assert task is None


def test_loop_survives_a_failed_sweep_and_keeps_running(monkeypatch):
    """One bad tick (e.g. Selcom/DB unreachable) must never kill the loop
    for the rest of the app's lifetime — the next tick tries again."""
    calls = []

    async def _flaky_reconcile(client):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("simulated Selcom outage")
        return {"checked": 0, "resolved": 0, "still_pending": 0}

    monkeypatch.setattr("app.main.reconcile_pending_checkout_collections", _flaky_reconcile)
    monkeypatch.setattr("app.main.get_supabase_admin", lambda: object())

    # target_calls=2 only reachable if the loop survived the first call's
    # exception and went on to tick again.
    asyncio.run(_run_loop_until_n_calls(interval=0.001, target_calls=2, call_counter=calls))

    assert len(calls) >= 2  # kept ticking after the first tick raised
