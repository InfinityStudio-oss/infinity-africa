"""The Type / Status / From / To filters on the merchant dashboard.

These four were dropdowns and date pickers wired to nothing: no handler,
no value, and two hardcoded August dates sitting in the date boxes as
though a range had been chosen. A filter that looks set and filters
nothing is worse than no filter, because the merchant believes the list
in front of them is narrowed when it is not.

Pinned here:

1. Each filter narrows server-side, so a match on page two is found
   rather than reported missing.
2. The filters combine, and combine with the phone search.
3. Dates are TANZANIAN calendar days, inclusive at both ends. This is
   the one with history: Tanzania is UTC+3, so a day treated as a UTC
   day loses everything taken between 00:00 and 03:00 local. The
   boundary cases below are the point of this file.
4. A type or status outside the allowed set is a 422, not an empty list.
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
    make_merchant_member,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _merchant(fake_client):
    return uuid.UUID(create_merchant(fake_client)["id"])


def _headers(fake_client, merchant_id):
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    return auth_headers(user_id)


def _txn(fake_client, merchant_id, **overrides):
    return create_transaction(fake_client, merchant_id, **overrides)


def _refs(response):
    return {row["reference"] for row in response.json()["data"]}


def _get(headers, query=""):
    return client.get(f"/v1/merchant/transactions{query}", headers=headers)


# --- type ---------------------------------------------------------------------


def test_filtering_by_type_returns_only_that_type(fake_client):
    merchant_id = _merchant(fake_client)
    headers = _headers(fake_client, merchant_id)
    _txn(fake_client, merchant_id, reference="A-COLLECTION", type="collection")
    _txn(fake_client, merchant_id, reference="A-WITHDRAWAL", type="disbursement")
    _txn(fake_client, merchant_id, reference="A-PAYOUT", type="payout")

    response = _get(headers, "?type=disbursement")

    assert response.status_code == 200
    assert _refs(response) == {"A-WITHDRAWAL"}


def test_a_withdrawal_and_a_payout_are_not_the_same_filter(fake_client):
    """Both are money going out, and both are live.

    A merchant withdrawing their own balance is a disbursement; money
    sent through the Disbursement API is a payout. Collapsing them would
    make one of the two unfindable.
    """
    merchant_id = _merchant(fake_client)
    headers = _headers(fake_client, merchant_id)
    _txn(fake_client, merchant_id, reference="A-WITHDRAWAL", type="disbursement")
    _txn(fake_client, merchant_id, reference="A-PAYOUT", type="payout")

    assert _refs(_get(headers, "?type=payout")) == {"A-PAYOUT"}
    assert _refs(_get(headers, "?type=disbursement")) == {"A-WITHDRAWAL"}


def test_an_unknown_type_is_rejected_rather_than_matching_nothing(fake_client):
    merchant_id = _merchant(fake_client)
    headers = _headers(fake_client, merchant_id)
    _txn(fake_client, merchant_id, reference="A-COLLECTION", type="collection")

    response = _get(headers, "?type=banana")

    # 422, not 200 with []. "Nothing matched" and "you asked for
    # something that does not exist" are different answers.
    assert response.status_code == 422


# --- status -------------------------------------------------------------------


def test_filtering_by_status_returns_only_that_status(fake_client):
    merchant_id = _merchant(fake_client)
    headers = _headers(fake_client, merchant_id)
    _txn(fake_client, merchant_id, reference="A-OK", status="successful")
    _txn(fake_client, merchant_id, reference="A-FAILED", status="failed")

    response = _get(headers, "?status=failed")

    assert response.status_code == 200
    assert _refs(response) == {"A-FAILED"}


def test_an_unknown_status_is_rejected(fake_client):
    merchant_id = _merchant(fake_client)
    headers = _headers(fake_client, merchant_id)
    _txn(fake_client, merchant_id, reference="A-OK", status="successful")

    assert _get(headers, "?status=almost").status_code == 422


# --- the date range, in Tanzanian days ----------------------------------------
#
# Tanzania is UTC+3 with no DST. So the Tanzanian day 2026-11-22 runs
# from 2026-11-21T21:00Z to 2026-11-22T21:00Z. Every case below is
# chosen to sit near one of those two edges, because the middle of the
# day works under any implementation and proves nothing.


def test_a_payment_just_after_local_midnight_is_in_that_day(fake_client):
    """00:30 EAT on 22 Nov is 21:30 UTC on the 21st.

    Filtered as a UTC day this payment falls on the 21st and vanishes
    from the 22nd - the exact three-hour hole this project has already
    shipped once, on pricing effective dates.
    """
    merchant_id = _merchant(fake_client)
    headers = _headers(fake_client, merchant_id)
    _txn(
        fake_client,
        merchant_id,
        reference="JUST-AFTER-LOCAL-MIDNIGHT",
        created_at="2026-11-21T21:30:00+00:00",
    )

    response = _get(headers, "?date_from=2026-11-22&date_to=2026-11-22")

    assert response.status_code == 200
    assert _refs(response) == {"JUST-AFTER-LOCAL-MIDNIGHT"}


def test_a_payment_just_before_local_midnight_is_in_the_previous_day(fake_client):
    """23:30 EAT on 21 Nov is 20:30 UTC on the 21st - still the 21st."""
    merchant_id = _merchant(fake_client)
    headers = _headers(fake_client, merchant_id)
    _txn(
        fake_client,
        merchant_id,
        reference="LATE-ON-THE-21ST",
        created_at="2026-11-21T20:30:00+00:00",
    )

    assert _refs(_get(headers, "?date_from=2026-11-21&date_to=2026-11-21")) == {"LATE-ON-THE-21ST"}
    assert _refs(_get(headers, "?date_from=2026-11-22&date_to=2026-11-22")) == set()


def test_the_end_date_includes_the_whole_of_that_day(fake_client):
    """An inclusive "to" that quietly stops at 00:00 loses a full day.

    23:00 EAT on the 22nd is 20:00 UTC on the 22nd, and a merchant who
    asked for "up to the 22nd" means it.
    """
    merchant_id = _merchant(fake_client)
    headers = _headers(fake_client, merchant_id)
    _txn(
        fake_client,
        merchant_id,
        reference="LATE-ON-THE-LAST-DAY",
        created_at="2026-11-22T20:00:00+00:00",
    )

    assert _refs(_get(headers, "?date_from=2026-11-20&date_to=2026-11-22")) == {
        "LATE-ON-THE-LAST-DAY"
    }


def test_a_payment_after_the_end_date_is_excluded(fake_client):
    """00:30 EAT on the 23rd is 21:30 UTC on the 22nd.

    The mirror of the first case: it must NOT be counted in the 22nd
    just because its UTC timestamp still says the 22nd.
    """
    merchant_id = _merchant(fake_client)
    headers = _headers(fake_client, merchant_id)
    _txn(
        fake_client,
        merchant_id,
        reference="EARLY-ON-THE-23RD",
        created_at="2026-11-22T21:30:00+00:00",
    )

    assert _refs(_get(headers, "?date_from=2026-11-22&date_to=2026-11-22")) == set()
    assert _refs(_get(headers, "?date_from=2026-11-23&date_to=2026-11-23")) == {
        "EARLY-ON-THE-23RD"
    }


def test_only_a_start_date_leaves_the_end_open(fake_client):
    merchant_id = _merchant(fake_client)
    headers = _headers(fake_client, merchant_id)
    _txn(fake_client, merchant_id, reference="OLD", created_at="2026-11-01T09:00:00+00:00")
    _txn(fake_client, merchant_id, reference="NEW", created_at="2026-11-22T09:00:00+00:00")

    assert _refs(_get(headers, "?date_from=2026-11-10")) == {"NEW"}


def test_only_an_end_date_leaves_the_start_open(fake_client):
    merchant_id = _merchant(fake_client)
    headers = _headers(fake_client, merchant_id)
    _txn(fake_client, merchant_id, reference="OLD", created_at="2026-11-01T09:00:00+00:00")
    _txn(fake_client, merchant_id, reference="NEW", created_at="2026-11-22T09:00:00+00:00")

    assert _refs(_get(headers, "?date_to=2026-11-10")) == {"OLD"}


# --- combining ----------------------------------------------------------------


def test_the_filters_combine(fake_client):
    merchant_id = _merchant(fake_client)
    headers = _headers(fake_client, merchant_id)
    _txn(
        fake_client,
        merchant_id,
        reference="WANTED",
        type="collection",
        status="failed",
        created_at="2026-11-22T09:00:00+00:00",
    )
    # Each of these differs from WANTED in exactly one way, so a filter
    # that is being ignored shows up as an extra row here.
    _txn(
        fake_client,
        merchant_id,
        reference="WRONG-TYPE",
        type="disbursement",
        status="failed",
        created_at="2026-11-22T09:00:00+00:00",
    )
    _txn(
        fake_client,
        merchant_id,
        reference="WRONG-STATUS",
        type="collection",
        status="successful",
        created_at="2026-11-22T09:00:00+00:00",
    )
    _txn(
        fake_client,
        merchant_id,
        reference="WRONG-DAY",
        type="collection",
        status="failed",
        created_at="2026-11-01T09:00:00+00:00",
    )

    response = _get(headers, "?type=collection&status=failed&date_from=2026-11-22&date_to=2026-11-22")

    assert response.status_code == 200
    assert _refs(response) == {"WANTED"}


def test_no_filters_still_returns_everything(fake_client):
    # The default must not have become a filter for nothing.
    merchant_id = _merchant(fake_client)
    headers = _headers(fake_client, merchant_id)
    _txn(fake_client, merchant_id, reference="ONE")
    _txn(fake_client, merchant_id, reference="TWO")

    assert _refs(_get(headers)) == {"ONE", "TWO"}


def test_a_filter_cannot_reach_another_merchants_transactions(fake_client):
    mine = _merchant(fake_client)
    theirs = _merchant(fake_client)
    headers = _headers(fake_client, mine)
    _txn(fake_client, theirs, reference="NOT-MINE", type="collection", status="successful")

    assert _refs(_get(headers, "?type=collection&status=successful")) == set()
