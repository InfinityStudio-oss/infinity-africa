"""Super Admin's date filters, in Tanzanian days.

`/v1/admin/collections` and `/v1/admin/transactions` took date_from and
date_to as raw strings and compared them straight against created_at.
A date box sends "2026-11-22", Postgres read that as midnight UTC, and
Tanzania is UTC+3 - so every payment taken between 00:00 and 03:00
local fell outside the day it belonged to. Measured against production,
that was 127 real payments on a single day.

The awkward part, and the reason these endpoints keep a string
parameter rather than a `date` one: they are called two ways.

  - an operator picking a day, which sends "2026-11-22"
  - the Super Admin dashboard's own counters, which already convert to
    "2026-11-22T00:00:00.000+03:00" themselves

Both have to keep working, so a bare date is anchored in Dar es Salaam
and a full timestamp is left exactly as the caller meant it. The tests
for the second group are regression tests for the dashboard, which
would have broken if these parameters had simply been retyped.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    create_transaction,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _headers(fake_client):
    user_id = uuid.uuid4()
    make_super_admin(fake_client, user_id)
    return auth_headers(user_id, aal="aal2")


def _merchant(fake_client):
    return uuid.UUID(create_merchant(fake_client)["id"])


def _collection(fake_client, merchant_id, *, reference, created_at):
    return fake_client.seed(
        "collections",
        {
            "id": str(uuid.uuid4()),
            "merchant_id": str(merchant_id),
            "reference": f"COL-{reference}",
            "merchant_reference": reference,
            "amount": "1000",
            "currency": "TZS",
            "status": "successful",
            "method": "USSD_PUSH",
            "source": "DASHBOARD_REQUEST",
            "customer_phone": "255762474101",
            "metadata": {},
            "initiated_at": created_at,
            "created_at": created_at,
            "updated_at": created_at,
        },
    )


def _refs(response, key="merchant_reference"):
    """References from a list response, read from a NAMED key.

    The admin collection response calls it merchant_reference and the
    transaction one calls it reference. Naming it per call beats a
    helper that tries several keys in turn - that trick already made a
    test in this project compare collection ids against transaction
    ids and fail while the code was right.
    """
    return {row[key] for row in response.json()["data"]}


# Tanzania is UTC+3 with no DST, so the Tanzanian day 2026-11-22 runs
# from 2026-11-21T21:00Z to 2026-11-22T21:00Z. Every timestamp below is
# chosen to sit near one of those edges; the middle of the day works
# under any implementation and proves nothing.
JUST_AFTER_LOCAL_MIDNIGHT = "2026-11-21T21:30:00+00:00"  # 00:30 EAT on the 22nd
LATE_LOCAL_EVENING = "2026-11-22T20:00:00+00:00"  # 23:00 EAT on the 22nd
NEXT_LOCAL_MORNING = "2026-11-22T21:30:00+00:00"  # 00:30 EAT on the 23rd


# --- collections --------------------------------------------------------------


def test_a_payment_just_after_local_midnight_is_in_that_tanzanian_day(fake_client):
    """The three-hour hole, on the collections screen.

    00:30 EAT on the 22nd is 21:30 UTC on the 21st. Read as a UTC day
    it belongs to the 21st and disappears from the 22nd.
    """
    headers = _headers(fake_client)
    merchant_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, reference="EARLY-22", created_at=JUST_AFTER_LOCAL_MIDNIGHT)

    response = client.get(
        "/v1/admin/collections?date_from=2026-11-22&date_to=2026-11-22", headers=headers
    )

    assert response.status_code == 200
    assert _refs(response) == {"EARLY-22"}


def test_the_end_date_includes_the_whole_tanzanian_day(fake_client):
    headers = _headers(fake_client)
    merchant_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, reference="LATE-22", created_at=LATE_LOCAL_EVENING)

    response = client.get(
        "/v1/admin/collections?date_from=2026-11-20&date_to=2026-11-22", headers=headers
    )

    assert response.status_code == 200
    assert _refs(response) == {"LATE-22"}


def test_a_payment_in_the_next_tanzanian_day_is_excluded(fake_client):
    """The mirror case: a UTC timestamp still reading the 22nd, but
    00:30 on the 23rd where the customer is."""
    headers = _headers(fake_client)
    merchant_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, reference="EARLY-23", created_at=NEXT_LOCAL_MORNING)

    inside = client.get(
        "/v1/admin/collections?date_from=2026-11-22&date_to=2026-11-22", headers=headers
    )
    after = client.get(
        "/v1/admin/collections?date_from=2026-11-23&date_to=2026-11-23", headers=headers
    )

    assert _refs(inside) == set()
    assert _refs(after) == {"EARLY-23"}


def test_a_single_day_range_is_a_whole_day_not_an_instant(fake_client):
    headers = _headers(fake_client)
    merchant_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, reference="EARLY-22", created_at=JUST_AFTER_LOCAL_MIDNIGHT)
    _collection(fake_client, merchant_id, reference="LATE-22", created_at=LATE_LOCAL_EVENING)

    response = client.get(
        "/v1/admin/collections?date_from=2026-11-22&date_to=2026-11-22", headers=headers
    )

    assert _refs(response) == {"EARLY-22", "LATE-22"}


# --- transactions -------------------------------------------------------------


def test_the_transactions_screen_uses_tanzanian_days_too(fake_client):
    headers = _headers(fake_client)
    merchant_id = _merchant(fake_client)
    create_transaction(
        fake_client, merchant_id, reference="TXN-EARLY-22", created_at=JUST_AFTER_LOCAL_MIDNIGHT
    )
    create_transaction(
        fake_client, merchant_id, reference="TXN-EARLY-23", created_at=NEXT_LOCAL_MORNING
    )

    response = client.get(
        "/v1/admin/transactions?date_from=2026-11-22&date_to=2026-11-22", headers=headers
    )

    assert response.status_code == 200
    assert _refs(response, "reference") == {"TXN-EARLY-22"}


# --- the dashboard's own callers, which send full timestamps -------------------


def test_a_full_timestamp_from_the_dashboard_still_works(fake_client):
    """Regression guard for the Super Admin dashboard.

    getAdminSuccessfulCollectionsToday and the collections trend already
    do this conversion themselves and send an offset-bearing timestamp.
    Retyping these parameters as a date would have rejected that with a
    422 and emptied the dashboard's counters.
    """
    headers = _headers(fake_client)
    merchant_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, reference="EARLY-22", created_at=JUST_AFTER_LOCAL_MIDNIGHT)
    _collection(fake_client, merchant_id, reference="EARLY-23", created_at=NEXT_LOCAL_MORNING)

    response = client.get(
        "/v1/admin/collections"
        "?date_from=2026-11-22T00:00:00.000%2B03:00"
        "&date_to=2026-11-22T23:59:59.999%2B03:00",
        headers=headers,
    )

    assert response.status_code == 200
    assert _refs(response) == {"EARLY-22"}


def test_a_timestamp_and_the_bare_date_agree(fake_client):
    """The two call styles must mean the same thing.

    If they diverge, the number on the dashboard and the number on the
    list below it disagree, and nobody can tell which is right.
    """
    headers = _headers(fake_client)
    merchant_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, reference="EARLY-22", created_at=JUST_AFTER_LOCAL_MIDNIGHT)
    _collection(fake_client, merchant_id, reference="LATE-22", created_at=LATE_LOCAL_EVENING)
    _collection(fake_client, merchant_id, reference="EARLY-23", created_at=NEXT_LOCAL_MORNING)

    by_date = client.get(
        "/v1/admin/collections?date_from=2026-11-22&date_to=2026-11-22", headers=headers
    )
    by_timestamp = client.get(
        "/v1/admin/collections"
        "?date_from=2026-11-22T00:00:00.000%2B03:00"
        "&date_to=2026-11-22T23:59:59.999%2B03:00",
        headers=headers,
    )

    assert _refs(by_date) == _refs(by_timestamp) == {"EARLY-22", "LATE-22"}


def test_a_utc_timestamp_is_honoured_as_utc(fake_client):
    """An explicit Z means what it says.

    Anchoring everything to Dar es Salaam regardless would be its own
    bug - a caller that states an offset has already decided.
    """
    headers = _headers(fake_client)
    merchant_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, reference="EARLY-22", created_at=JUST_AFTER_LOCAL_MIDNIGHT)

    response = client.get(
        "/v1/admin/collections?date_from=2026-11-21T21:00:00Z&date_to=2026-11-21T22:00:00Z",
        headers=headers,
    )

    assert response.status_code == 200
    assert _refs(response) == {"EARLY-22"}


# --- bad input ----------------------------------------------------------------


@pytest.mark.parametrize("value", ["not-a-date", "2026-13-45", "22/11/2026", ""])
def test_an_unparseable_date_is_a_clear_error_not_a_database_failure(fake_client, value):
    """Before this, a mistyped date went into the query and came back as
    a database error with nothing in it to say what was wrong."""
    headers = _headers(fake_client)

    response = client.get(f"/v1/admin/collections?date_from={value}", headers=headers)

    assert response.status_code == 422
    assert "date_from" in response.text


def test_the_bad_field_is_named(fake_client):
    headers = _headers(fake_client)

    response = client.get("/v1/admin/collections?date_to=nonsense", headers=headers)

    assert response.status_code == 422
    assert "date_to" in response.text


def test_no_date_filter_still_returns_everything(fake_client):
    # The default must not have become a filter.
    headers = _headers(fake_client)
    merchant_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, reference="EARLY-22", created_at=JUST_AFTER_LOCAL_MIDNIGHT)
    _collection(fake_client, merchant_id, reference="EARLY-23", created_at=NEXT_LOCAL_MORNING)

    response = client.get("/v1/admin/collections", headers=headers)

    assert _refs(response) == {"EARLY-22", "EARLY-23"}
