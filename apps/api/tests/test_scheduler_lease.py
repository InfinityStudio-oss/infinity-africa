"""Only one replica may run each background sweep.

The schedulers start in app/main.py's lifespan, so they start in every
replica. With one replica that has always been fine. With two it is not,
and webhook delivery is the sharp edge: deliver_event reads a pending
row, POSTs it, and only then records the outcome. Two replicas sweeping
at once would both read the same event as pending and both send it, so a
merchant receives collection.success twice — which can activate a
customer's service twice. BillNasi holds no webhook signing secret, so
their endpoint cannot tell a duplicate from a fresh event.

These tests are what makes it safe to run more than one replica, which is
in turn what makes rolling deploys possible.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services import scheduler_lease
from app.services.scheduler_lease import acquire_lease, release_lease


def _lease_row(fake_client, name):
    rows = fake_client.table("scheduler_leases")._table.rows
    return next((r for r in rows if r["name"] == name), None)


def _seed_expired(fake_client, name):
    """Past-dated on purpose. "now" would leave the lease free only
    strictly after this instant, and two datetime.now() calls in a row
    can return the same microsecond - which would make the first claim
    fail for a reason that has nothing to do with what is being tested."""
    now = datetime.now(timezone.utc)
    fake_client.seed(
        "scheduler_leases",
        {
            "name": name,
            "holder": "nobody",
            "acquired_at": now.isoformat(),
            "expires_at": (now - timedelta(seconds=1)).isoformat(),
            "updated_at": now.isoformat(),
        },
    )


# --- the property the whole thing exists for --------------------------------


def test_two_replicas_cannot_both_run_the_same_sweep(fake_client, monkeypatch):
    """The double-webhook scenario, directly."""
    _seed_expired(fake_client, "webhook_delivery")

    monkeypatch.setattr(scheduler_lease, "_HOLDER", "replica-a")
    first = acquire_lease(fake_client, "webhook_delivery")

    monkeypatch.setattr(scheduler_lease, "_HOLDER", "replica-b")
    second = acquire_lease(fake_client, "webhook_delivery")

    assert first is True
    assert second is False, "two replicas would both deliver the same webhook"


def test_the_second_replica_gets_its_turn_once_the_lease_is_released(fake_client, monkeypatch):
    _seed_expired(fake_client, "webhook_delivery")
    monkeypatch.setattr(scheduler_lease, "_HOLDER", "replica-a")
    acquire_lease(fake_client, "webhook_delivery")
    release_lease(fake_client, "webhook_delivery")

    monkeypatch.setattr(scheduler_lease, "_HOLDER", "replica-b")
    assert acquire_lease(fake_client, "webhook_delivery") is True


def test_a_replica_cannot_release_a_lease_it_does_not_hold(fake_client, monkeypatch):
    """Otherwise a replica could cut short a sweep running elsewhere,
    reintroducing the double delivery this exists to prevent."""
    _seed_expired(fake_client, "webhook_delivery")
    monkeypatch.setattr(scheduler_lease, "_HOLDER", "replica-a")
    acquire_lease(fake_client, "webhook_delivery")

    monkeypatch.setattr(scheduler_lease, "_HOLDER", "replica-b")
    release_lease(fake_client, "webhook_delivery")

    monkeypatch.setattr(scheduler_lease, "_HOLDER", "replica-c")
    assert acquire_lease(fake_client, "webhook_delivery") is False


def test_a_crashed_replicas_lease_expires_and_the_work_resumes(fake_client, monkeypatch):
    """No cleanup job and no stuck state: a replica that dies mid-sweep
    simply stops holding the lease once it expires."""
    _seed_expired(fake_client, "webhook_delivery")
    monkeypatch.setattr(scheduler_lease, "_HOLDER", "replica-a")
    acquire_lease(fake_client, "webhook_delivery")

    row = _lease_row(fake_client, "webhook_delivery")
    row["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

    monkeypatch.setattr(scheduler_lease, "_HOLDER", "replica-b")
    assert acquire_lease(fake_client, "webhook_delivery") is True


def test_different_sweeps_do_not_block_each_other(fake_client, monkeypatch):
    """Webhook delivery holding its lease must not stop reconciliation."""
    _seed_expired(fake_client, "webhook_delivery")
    _seed_expired(fake_client, "disbursement_reconciliation")
    monkeypatch.setattr(scheduler_lease, "_HOLDER", "replica-a")

    assert acquire_lease(fake_client, "webhook_delivery") is True
    assert acquire_lease(fake_client, "disbursement_reconciliation") is True


# --- failure must always mean "skip", never "run twice" ----------------------


def test_a_database_error_skips_the_tick_rather_than_running(fake_client):
    """A skipped sweep costs one tick — every sweep here is idempotent
    and on a timer. Running twice costs a duplicate webhook."""

    class _Broken:
        def table(self, _name):
            raise RuntimeError("supabase unreachable")

    assert acquire_lease(_Broken(), "webhook_delivery") is False


def test_releasing_never_raises(fake_client):
    class _Broken:
        def table(self, _name):
            raise RuntimeError("supabase unreachable")

    release_lease(_Broken(), "webhook_delivery")  # no exception


# --- the deploy-ordering hazard ---------------------------------------------


def test_a_missing_lease_row_is_created_rather_than_halting_the_sweep(fake_client):
    """If this code ships before its migration, every lease lookup would
    match no row and every sweep would skip forever — webhook delivery
    would stop silently. A guard whose failure mode is "the platform
    quietly stops working" is worse than no guard.
    """
    assert _lease_row(fake_client, "webhook_delivery") is None

    assert acquire_lease(fake_client, "webhook_delivery") is True
    assert _lease_row(fake_client, "webhook_delivery") is not None


def test_self_healing_still_excludes_a_second_replica(fake_client, monkeypatch):
    """Creating the row on demand must not become a way for both
    replicas to claim it."""
    monkeypatch.setattr(scheduler_lease, "_HOLDER", "replica-a")
    assert acquire_lease(fake_client, "webhook_delivery") is True

    monkeypatch.setattr(scheduler_lease, "_HOLDER", "replica-b")
    assert acquire_lease(fake_client, "webhook_delivery") is False


@pytest.mark.parametrize(
    "name",
    [
        "webhook_delivery",
        "checkout_reconciliation",
        "disbursement_reconciliation",
        "collection_expiry",
        "referral_recalculation",
    ],
)
def test_every_scheduler_has_a_lease_name_that_works(fake_client, name):
    """The names here must match the ones app/main.py passes and the ones
    the migration seeds; a typo in either would silently disable a sweep
    or, worse, leave it unguarded."""
    assert acquire_lease(fake_client, name) is True


def test_the_holder_id_is_unique_per_process():
    """Two replicas must not accidentally share an identity, or each
    would be able to release the other's lease."""
    assert scheduler_lease._HOLDER
    assert uuid.uuid4().hex[:8] not in scheduler_lease._HOLDER
