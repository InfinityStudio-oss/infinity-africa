"""app/main.py's backend-initiated disbursement reconciliation loop — the
withdrawal counterpart to test_checkout_reconciliation_scheduler.py. Unlike
checkout collections, the disbursement webhook is signed and verified
successfully; this scheduler is a safety net for a delayed/dropped/never-sent
delivery, not a replacement for a broken signature. The reconciliation logic
itself (app/services/disbursements.py::reconcile_pending_disbursements) is
covered in tests/test_admin_withdrawals.py and its own per-row-isolation
tests; this just proves the scheduler calls it on a timer and keeps running
afterward.
"""

import asyncio

import pytest

import app.main as main_module
from app.main import (
    _disbursement_reconciliation_loop,
    _start_disbursement_reconciliation_task,
)

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
    task = asyncio.create_task(_disbursement_reconciliation_loop(interval))
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

    monkeypatch.setattr("app.main.reconcile_pending_disbursements", _fake_reconcile)
    monkeypatch.setattr("app.main.get_supabase_admin", lambda: object())

    asyncio.run(_run_loop_until_n_calls(interval=0.001, target_calls=3, call_counter=calls))

    assert len(calls) >= 3


async def _start_and_cancel() -> asyncio.Task | None:
    task = _start_disbursement_reconciliation_task()
    if task is not None:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    return task


def test_scheduler_starts_a_task_when_interval_is_positive(monkeypatch):
    monkeypatch.setattr(main_module.settings, "selcom_disbursement_reconcile_interval_seconds", 120)

    task = asyncio.run(_start_and_cancel())

    assert task is not None


def test_scheduler_disabled_when_interval_is_zero(monkeypatch):
    monkeypatch.setattr(main_module.settings, "selcom_disbursement_reconcile_interval_seconds", 0)

    task = asyncio.run(_start_and_cancel())

    assert task is None


def test_scheduler_disabled_when_interval_is_negative(monkeypatch):
    monkeypatch.setattr(main_module.settings, "selcom_disbursement_reconcile_interval_seconds", -5)

    task = asyncio.run(_start_and_cancel())

    assert task is None


def test_scheduler_disabled_when_auto_reconciliation_flag_is_off(monkeypatch):
    monkeypatch.setattr(main_module.settings, "selcom_disbursement_reconcile_interval_seconds", 120)
    monkeypatch.setattr(main_module.settings, "enable_auto_reconciliation", False)

    task = asyncio.run(_start_and_cancel())

    assert task is None


def test_loop_survives_a_failed_sweep_and_keeps_running(monkeypatch):
    calls = []

    async def _flaky_reconcile(client):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("simulated Selcom outage")
        return {"checked": 0, "resolved": 0, "still_pending": 0}

    monkeypatch.setattr("app.main.reconcile_pending_disbursements", _flaky_reconcile)
    monkeypatch.setattr("app.main.get_supabase_admin", lambda: object())

    asyncio.run(_run_loop_until_n_calls(interval=0.001, target_calls=2, call_counter=calls))

    assert len(calls) >= 2


def test_both_schedulers_can_run_independently(monkeypatch):
    """Regression guard for the lifespan wiring: starting/cancelling one
    scheduler must never depend on or interfere with the other — they're
    two independent tasks tracked in the same list in lifespan()."""
    checkout_calls = []
    disbursement_calls = []

    async def _fake_checkout_reconcile(client):
        checkout_calls.append(1)
        return {"checked": 0, "resolved": 0, "still_pending": 0}

    async def _fake_disbursement_reconcile(client):
        disbursement_calls.append(1)
        return {"checked": 0, "resolved": 0, "still_pending": 0}

    monkeypatch.setattr("app.main.reconcile_pending_checkout_collections", _fake_checkout_reconcile)
    monkeypatch.setattr("app.main.reconcile_pending_disbursements", _fake_disbursement_reconcile)
    monkeypatch.setattr("app.main.get_supabase_admin", lambda: object())
    monkeypatch.setattr(main_module.settings, "selcom_checkout_reconcile_interval_seconds", 120)
    monkeypatch.setattr(main_module.settings, "selcom_disbursement_reconcile_interval_seconds", 120)

    async def _start_both_and_cancel():
        checkout_task = main_module._start_checkout_reconciliation_task()
        disbursement_task = main_module._start_disbursement_reconciliation_task()

        assert checkout_task is not None
        assert disbursement_task is not None
        assert checkout_task is not disbursement_task

        for task in (checkout_task, disbursement_task):
            task.cancel()
        for task in (checkout_task, disbursement_task):
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(_start_both_and_cancel())
