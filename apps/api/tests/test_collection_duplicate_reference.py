"""Selcom repeating a reference must not lose a pushed collection.

The sibling of tests/test_checkout_order_duplicate_reference.py, one table
along. `collections.provider_reference` holds Selcom's own identifier
under a unique index of ours, and when they repeated one the insert hit

    duplicate key value violates unique constraint
    "collections_provider_reference_key"

This one is worse than the checkout_orders case. The insert happens
*after* the wallet push has gone out, so a 500 there means the customer
has been prompted to pay and no collection row exists at all — an
unrecorded payment, not just a failed request.

The row is now written with our own `transid` in that column instead,
which is already what the linked transactions row falls back to when
Selcom returns no reference. Null would not do: that column is exactly
what resolve_collection_from_callback looks a collection up by, so a null
would leave the payment unmatchable when the callback arrives.
"""

import pytest
from postgrest.exceptions import APIError

from app.services.provider_references import (
    COLLECTIONS_PROVIDER_REFERENCE_INDEX,
    insert_collection_tolerating_repeated_reference,
    is_duplicate_provider_reference,
    update_collection_tolerating_repeated_reference,
)


def _api_error(message: str, code: str) -> APIError:
    return APIError({"message": message, "code": code, "details": None, "hint": None})


_DUPLICATE = _api_error(
    'duplicate key value violates unique constraint "collections_provider_reference_key"', "23505"
)


class RecordingInserter:
    """Fails the first insert the way Postgres does, records every attempt."""

    def __init__(self, fail_times: int = 1, error: Exception | None = None):
        self.attempts: list[dict] = []
        self.fail_times = fail_times
        self.error = error or _DUPLICATE

    def __call__(self, _client, _table, row):
        self.attempts.append(row)
        if len(self.attempts) <= self.fail_times:
            raise self.error
        return {"id": "collection-1", **row}


@pytest.fixture
def inserter(monkeypatch):
    recorder = RecordingInserter()
    monkeypatch.setattr("app.services.provider_references.insert_row", recorder)
    return recorder


# --- the detection is deliberately narrow ----------------------------------


def test_a_repeated_provider_reference_is_recognised():
    assert is_duplicate_provider_reference(_DUPLICATE, COLLECTIONS_PROVIDER_REFERENCE_INDEX) is True


def test_a_different_unique_violation_is_not():
    """A collision on a column we generate is a real bug, and must keep
    raising rather than be retried into a second row."""
    other = _api_error(
        'duplicate key value violates unique constraint "collections_reference_key"', "23505"
    )
    assert is_duplicate_provider_reference(other, COLLECTIONS_PROVIDER_REFERENCE_INDEX) is False


def test_a_non_unique_error_is_not():
    not_null = _api_error('null value in column "amount" violates not-null constraint', "23502")
    assert is_duplicate_provider_reference(not_null, COLLECTIONS_PROVIDER_REFERENCE_INDEX) is False


# --- the recovery -----------------------------------------------------------


def test_the_collection_is_still_recorded(inserter):
    row = {"provider_reference": "SELCOM-REPEATED", "provider_transid": "TXN-OURS", "amount": "1000"}

    saved = insert_collection_tolerating_repeated_reference(
        None, row, fallback_reference="TXN-OURS", context="wallet_push"
    )

    assert saved["id"] == "collection-1"
    assert len(inserter.attempts) == 2


def test_it_falls_back_to_our_own_reference_not_null(inserter):
    """Null would leave the collection unmatchable by
    resolve_collection_from_callback, which looks up on this column."""
    row = {"provider_reference": "SELCOM-REPEATED", "provider_transid": "TXN-OURS"}

    saved = insert_collection_tolerating_repeated_reference(
        None, row, fallback_reference="TXN-OURS", context="wallet_push"
    )

    assert saved["provider_reference"] == "TXN-OURS"
    assert saved["provider_reference"] is not None


def test_everything_else_on_the_row_survives(inserter):
    """Only the duplicated column changes — Selcom's reply in particular
    stays whole, so their real reference is never lost."""
    row = {
        "provider_reference": "SELCOM-REPEATED",
        "provider_transid": "TXN-OURS",
        "raw_response": {"reference": "SELCOM-REPEATED", "result": "SUCCESS"},
        "amount": "1000",
    }

    saved = insert_collection_tolerating_repeated_reference(
        None, row, fallback_reference="TXN-OURS", context="wallet_push"
    )

    assert saved["raw_response"] == {"reference": "SELCOM-REPEATED", "result": "SUCCESS"}
    assert saved["provider_transid"] == "TXN-OURS"
    assert saved["amount"] == "1000"


def test_a_real_failure_still_raises(monkeypatch):
    """The guard must not become a blanket retry."""
    recorder = RecordingInserter(
        error=_api_error('null value in column "amount" violates not-null constraint', "23502")
    )
    monkeypatch.setattr("app.services.provider_references.insert_row", recorder)

    with pytest.raises(APIError):
        insert_collection_tolerating_repeated_reference(
            None, {"provider_reference": "X"}, fallback_reference="TXN", context="wallet_push"
        )

    assert len(recorder.attempts) == 1


def test_it_does_not_retry_forever(monkeypatch):
    """If the fallback itself collides, that is our own identifier
    colliding — a real bug, and it must surface rather than loop."""
    recorder = RecordingInserter(fail_times=2)
    monkeypatch.setattr("app.services.provider_references.insert_row", recorder)

    with pytest.raises(APIError):
        insert_collection_tolerating_repeated_reference(
            None, {"provider_reference": "X"}, fallback_reference="TXN", context="wallet_push"
        )

    assert len(recorder.attempts) == 2


# --- the reconciliation update ---------------------------------------------
#
# The path that most likely produced the production alert: every webhook
# delivery and every sweep refreshes provider_reference from whatever
# Selcom last returned. A collision there fails the whole resolution, so a
# paid collection never gets credited.


class RecordingUpdater:
    def __init__(self, fail_times: int = 1, error: Exception | None = None):
        self.attempts: list[dict] = []
        self.fail_times = fail_times
        self.error = error or _DUPLICATE

    def __call__(self, _client, _table, _row_id, changes):
        self.attempts.append(changes)
        if len(self.attempts) <= self.fail_times:
            raise self.error
        return {"id": "collection-1", **changes}


@pytest.fixture
def updater(monkeypatch):
    recorder = RecordingUpdater()
    monkeypatch.setattr("app.services.provider_references.update_row", recorder)
    return recorder


_CHANGES = {
    "provider_reference": "SELCOM-BELONGS-TO-ANOTHER-ROW",
    "provider_transid": "809642361225",
    "provider_result": "SUCCESS",
    "raw_response": {"reference": "SELCOM-BELONGS-TO-ANOTHER-ROW"},
}


def test_the_resolution_still_applies(updater):
    saved = update_collection_tolerating_repeated_reference(
        None, "collection-1", dict(_CHANGES), context="checkout_reconciliation"
    )

    assert saved["id"] == "collection-1"
    assert len(updater.attempts) == 2


def test_it_keeps_the_reference_the_row_already_has(updater):
    """We cannot adopt a value that identifies a different collection, and
    the row's existing reference is what callbacks already match on."""
    update_collection_tolerating_repeated_reference(
        None, "collection-1", dict(_CHANGES), context="checkout_reconciliation"
    )

    assert "provider_reference" not in updater.attempts[1]


def test_the_rest_of_the_resolution_is_not_dropped(updater):
    """Only the colliding column is withheld — Selcom's reply still lands,
    so their reference is recorded even though it cannot be adopted."""
    saved = update_collection_tolerating_repeated_reference(
        None, "collection-1", dict(_CHANGES), context="checkout_reconciliation"
    )

    assert saved["provider_result"] == "SUCCESS"
    assert saved["provider_transid"] == "809642361225"
    assert saved["raw_response"] == {"reference": "SELCOM-BELONGS-TO-ANOTHER-ROW"}


def test_an_unrelated_update_failure_still_raises(monkeypatch):
    recorder = RecordingUpdater(
        error=_api_error("deadlock detected", "40P01")
    )
    monkeypatch.setattr("app.services.provider_references.update_row", recorder)

    with pytest.raises(APIError):
        update_collection_tolerating_repeated_reference(
            None, "collection-1", dict(_CHANGES), context="checkout_reconciliation"
        )

    assert len(recorder.attempts) == 1
