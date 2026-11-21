"""The payout worker has to actually be run by something.

`sweep_payouts` was written with the Disbursement API and never called
outside its own tests. Seventeen tests covered what it does; none
covered whether anything invokes it. So the first real payout reached
`processing` - funds reserved, TZS 1,010 taken out of the merchant's
available balance - and stayed there with dispatch_attempts=0, because
no scheduler existed.

That is the gap these tests close: not "does the sweep work" but "is the
sweep wired in".
"""

import asyncio

import pytest

from app.config import get_settings
from app.main import _start_payout_dispatch_task


@pytest.fixture(autouse=True)
def _clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_the_sweep_is_reachable_from_the_application(monkeypatch):
    """The thing that was missing. main.py must import and schedule it -
    a sweep nothing calls is money reserved and never sent."""
    from app import main

    assert hasattr(main, "sweep_payouts"), "main.py does not import the payout sweep"

    source = (main.__file__ or "").replace("\\", "/")
    with open(source, encoding="utf-8") as fh:
        text = fh.read()
    # Registered in the lifespan task list, not merely defined.
    assert "_start_payout_dispatch_task()," in text, (
        "the payout dispatch task is defined but not added to the startup task list"
    )


@pytest.mark.asyncio
async def test_no_interval_means_no_background_dispatch(monkeypatch):
    """Opt-in, like every other sweep here, so a test run or local dev
    never dispatches a real payout in the background."""
    monkeypatch.setenv("PAYOUT_DISPATCH_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    from app import main

    monkeypatch.setattr(main, "settings", get_settings())
    assert _start_payout_dispatch_task() is None


@pytest.mark.asyncio
async def test_an_interval_starts_the_worker(monkeypatch):
    monkeypatch.setenv("PAYOUT_DISPATCH_INTERVAL_SECONDS", "15")
    get_settings.cache_clear()
    from app import main

    monkeypatch.setattr(main, "settings", get_settings())
    task = _start_payout_dispatch_task()
    assert task is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_the_worker_takes_a_lease_before_dispatching(monkeypatch):
    """Two API instances must not both send one payout. The lease and the
    `processing` claim inside dispatch_payout are what stand between one
    payout and two payments, so the loop must not call the sweep when the
    lease is refused."""
    from app import main

    swept: list[int] = []
    monkeypatch.setattr(main, "get_supabase_admin", lambda: object())
    monkeypatch.setattr(main, "acquire_lease", lambda _client, _name: False)

    async def _sweep(_client):
        swept.append(1)
        return {}

    monkeypatch.setattr(main, "sweep_payouts", _sweep)

    task = asyncio.create_task(main._payout_dispatch_loop(0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert swept == [], "the sweep ran without holding the lease"
