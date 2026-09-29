"""Expiring an abandoned mobile money push.

A customer who dismisses the prompt or mistypes their PIN used to leave
the collection `processing` forever — no terminal webhook to the
integrator, and a permanent slice of the shared Selcom budget spent
re-polling it. The oldest on this platform is from 2026-08-16.

The dangerous half is not the expiry, it is being wrong about it.
`resolve_collection()` no-ops on anything that is not `processing`, so a
collection marked failed and later paid would never credit: the debit
leaves the customer's wallet and the merchant is never paid. Most of what
is pinned here is that guard, not the happy path.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.config import get_settings
from app.services.collection_expiry import expire_stale_pushes
from tests.test_checkout_reconciliation import _seed_pending_collection

_REFRESH = "app.services.collection_expiry.refresh_checkout_collection_status"
_PAID = "app.services.collection_expiry._provider_now_reports_paid"


@pytest.fixture(autouse=True)
def _expiry_settings(monkeypatch):
    monkeypatch.setenv("COLLECTION_PUSH_EXPIRY_MINUTES", "30")
    monkeypatch.setenv("COLLECTION_PUSH_EXPIRY_BATCH_SIZE", "25")
    monkeypatch.setenv("COLLECTION_PUSH_EXPIRY_GRACE_HOURS", "24")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _age(fake_client, collection, *, minutes):
    """Backdates a collection so the sweep sees it as abandoned."""
    when = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    row = _row(fake_client, collection["id"])
    row["created_at"] = when
    return row


def _row(fake_client, collection_id):
    return next(r for r in fake_client.table("collections")._table.rows if r["id"] == str(collection_id))


def _merchant_row(fake_client, merchant_id):
    return next(r for r in fake_client.table("merchants")._table.rows if r["id"] == str(merchant_id))


def _backdate_failure(fake_client, collection, *, minutes):
    """Simulates time passing since we gave up. A collection expired in
    the current sweep is deliberately not re-queried in that same sweep."""
    row = _row(fake_client, collection["id"])
    row["failed_at"] = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    return row


def _sweep(fake_client):
    return asyncio.run(expire_stale_pushes(fake_client))


# --- the basic behaviour ----------------------------------------------------


def test_an_abandoned_push_is_given_a_terminal_answer(fake_client, monkeypatch):
    collection, _ctx = _seed_pending_collection(fake_client, monkeypatch)
    _age(fake_client, collection, minutes=90)

    # The provider is still saying nothing useful — the whole problem.
    with patch(_REFRESH, return_value={"status": "processing"}):
        summary = _sweep(fake_client)

    assert summary["expired"] == 1
    row = _row(fake_client, collection["id"])
    assert row["status"] == "failed"
    assert row["failure_reason_code"] == "expired"
    assert row["failed_at"]


def test_the_partner_is_told(fake_client, monkeypatch):
    """The point of the whole feature: a terminal event actually reaches
    the integrator, rather than silence forever."""
    collection, ctx = _seed_pending_collection(fake_client, monkeypatch)
    _merchant_row(fake_client, ctx["merchant_id"])["webhook_url"] = "https://partner.example.com/hooks"
    _age(fake_client, collection, minutes=90)

    with patch(_REFRESH, return_value={"status": "processing"}):
        _sweep(fake_client)

    events = fake_client.table("webhook_events")._table.rows
    assert [e["event_name"] for e in events] == ["collection.failed"]
    assert events[0]["payload"]["failure_reason_code"] == "expired"


def test_a_push_inside_the_window_is_left_alone(fake_client, monkeypatch):
    """Someone reading the prompt is not someone who abandoned it."""
    collection, _ctx = _seed_pending_collection(fake_client, monkeypatch)
    _age(fake_client, collection, minutes=5)

    with patch(_REFRESH, return_value={"status": "processing"}):
        summary = _sweep(fake_client)

    assert summary["candidates"] == 0
    assert _row(fake_client, collection["id"])["status"] == "processing"


def test_expiry_can_be_switched_off_entirely(fake_client, monkeypatch):
    monkeypatch.setenv("COLLECTION_PUSH_EXPIRY_MINUTES", "0")
    get_settings.cache_clear()
    collection, _ctx = _seed_pending_collection(fake_client, monkeypatch)
    _age(fake_client, collection, minutes=600)

    with patch(_REFRESH, return_value={"status": "processing"}):
        summary = _sweep(fake_client)

    assert summary == {"candidates": 0, "expired": 0, "resolved_instead": 0, "recovered": 0, "errors": 0}
    assert _row(fake_client, collection["id"])["status"] == "processing"


# --- not being wrong about it -----------------------------------------------


def test_the_provider_gets_the_last_word_before_anything_is_failed(fake_client, monkeypatch):
    """A collection the provider has quietly settled must resolve, never
    expire. Without this check we would fail a payment that succeeded."""
    collection, _ctx = _seed_pending_collection(fake_client, monkeypatch)
    _age(fake_client, collection, minutes=90)

    def _settles_it(client, *, collection_id):
        _row(client, collection_id)["status"] = "successful"
        return {"status": "successful"}

    with patch(_REFRESH, side_effect=_settles_it):
        summary = _sweep(fake_client)

    assert summary["expired"] == 0
    assert summary["resolved_instead"] == 1
    assert _row(fake_client, collection["id"])["status"] == "successful"


def test_a_late_payment_is_recovered_and_credited(fake_client, monkeypatch):
    """The money-safety case. The customer paid after we had given up, so
    the debit left their wallet. resolve_collection() no-ops on a failed
    collection, so it has to be reopened before it can settle."""
    collection, _ctx = _seed_pending_collection(fake_client, monkeypatch)
    _age(fake_client, collection, minutes=90)

    with patch(_REFRESH, return_value={"status": "processing"}):
        _sweep(fake_client)
    assert _row(fake_client, collection["id"])["status"] == "failed"
    _backdate_failure(fake_client, collection, minutes=60)

    settled = []
    status_when_settled = []

    def _settles_it(client, *, collection_id):
        # What the row looked like at the moment settlement was attempted
        # is the whole assertion: resolve_collection() silently no-ops on
        # anything that is not "processing", so a recovery that forgets to
        # reopen the collection first looks successful here and credits
        # nobody.
        status_when_settled.append(_row(client, collection_id)["status"])
        _row(client, collection_id)["status"] = "successful"
        settled.append(collection_id)
        return {"status": "successful"}

    with patch(_PAID, return_value=True), patch(_REFRESH, side_effect=_settles_it):
        summary = _sweep(fake_client)

    assert summary["recovered"] == 1
    assert settled == [uuid.UUID(collection["id"])]
    assert status_when_settled == ["processing"], "settlement ran against a failed row and would have no-opped"
    assert _row(fake_client, collection["id"])["status"] == "successful"


def test_an_expired_push_the_provider_still_calls_pending_stays_failed(fake_client, monkeypatch):
    """The recheck must not flap a collection back to processing on a
    provider answer that has not changed."""
    collection, _ctx = _seed_pending_collection(fake_client, monkeypatch)
    _age(fake_client, collection, minutes=90)

    with patch(_REFRESH, return_value={"status": "processing"}):
        _sweep(fake_client)
    _backdate_failure(fake_client, collection, minutes=60)

    with patch(_PAID, return_value=False) as asked, patch(_REFRESH) as refresh:
        summary = _sweep(fake_client)

    assert asked.called
    refresh.assert_not_called()
    assert summary["recovered"] == 0
    assert _row(fake_client, collection["id"])["status"] == "failed"


def test_nothing_is_rechecked_once_the_grace_window_closes(fake_client, monkeypatch):
    """This is what bounds the polling cost — otherwise expiry would swap
    one unbounded sweep for another."""
    collection, _ctx = _seed_pending_collection(fake_client, monkeypatch)
    _age(fake_client, collection, minutes=90)

    with patch(_REFRESH, return_value={"status": "processing"}):
        _sweep(fake_client)

    row = _row(fake_client, collection["id"])
    row["failed_at"] = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()

    with patch(_PAID) as asked:
        summary = _sweep(fake_client)

    asked.assert_not_called()
    assert summary["recovered"] == 0


# --- not taking the provider budget down with it ----------------------------


def test_one_sweep_expires_at_most_a_batch(fake_client, monkeypatch):
    """Every candidate costs a live provider call on a shared, rate-limited
    budget. A six-week backlog must drain over many sweeps, not saturate
    the provider in one."""
    monkeypatch.setenv("COLLECTION_PUSH_EXPIRY_BATCH_SIZE", "3")
    get_settings.cache_clear()

    for _ in range(7):
        collection, _ctx = _seed_pending_collection(fake_client, monkeypatch)
        _age(fake_client, collection, minutes=90)

    with patch(_REFRESH, return_value={"status": "processing"}):
        summary = _sweep(fake_client)

    assert summary["expired"] == 3


def test_one_bad_row_does_not_stop_the_sweep(fake_client, monkeypatch):
    first, _a = _seed_pending_collection(fake_client, monkeypatch)
    second, _b = _seed_pending_collection(fake_client, monkeypatch)
    _age(fake_client, first, minutes=120)
    _age(fake_client, second, minutes=90)

    calls = {"n": 0}

    def _first_one_explodes(client, *, collection_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("provider lookup blew up")
        return {"status": "processing"}

    with patch(_REFRESH, side_effect=_first_one_explodes):
        summary = _sweep(fake_client)

    assert summary["errors"] == 1
    assert summary["expired"] == 1
    assert _row(fake_client, second["id"])["status"] == "failed"
