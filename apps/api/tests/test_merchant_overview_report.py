"""The Overview's reporting figures.

The property worth testing hardest is that the bar chart and the donut
agree. They are two views of one set of rows, and a merchant who adds up
the bars and compares the result to the donut's centre has no way to tell
which one is lying when they differ. So the service builds both from the
same fetch, and the tests below check the sums rather than trusting that.

The rest is boundaries. Dates are Africa/Dar_es_Salaam calendar days, and
Tanzania is UTC+3 with no DST, so a payment at 01:00 local is 22:00 the
previous day in UTC. Getting that wrong moves money between days on the
chart without changing any total, which is the kind of error that is only
noticed when someone reconciles a single day against a bank statement.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.merchant_overview import get_merchant_overview_report
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_api_key,
    make_merchant_member,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _merchant(fake_client, role="MERCHANT_ADMIN"):
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, role)
    return merchant_id, user_id


def _collection(
    fake_client,
    merchant_id,
    *,
    amount="1000.00",
    fee="30.00",
    method="MOBILE_MONEY",
    created_at=None,
    status="successful",
):
    return fake_client.seed(
        "transactions",
        {
            "merchant_id": str(merchant_id),
            "reference": f"TXN-{uuid.uuid4().hex[:12]}",
            "type": "collection",
            "method": method,
            "gross_amount": amount,
            "fee_amount": fee,
            "net_amount": str(Decimal(amount) - Decimal(fee)),
            "currency": "TZS",
            "status": status,
            "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        },
    )


def _report(fake_client, merchant_id, *, days=7):
    today = datetime.now(timezone.utc).date()
    return get_merchant_overview_report(
        fake_client,
        merchant_id=merchant_id,
        start_date=today - timedelta(days=days - 1),
        end_date=today,
    )


# --- the two charts must agree ----------------------------------------------


def test_the_bar_total_and_the_donut_total_are_the_same_number(fake_client):
    """The headline property. Two views of one set of rows."""
    merchant_id, _user_id = _merchant(fake_client)
    for method, amount in (
        ("MOBILE_MONEY", "5000.00"),
        ("MOBILE_MONEY", "2500.00"),
        ("CARD", "7000.00"),
        ("BANK_TRANSFER", "1500.00"),
    ):
        _collection(fake_client, merchant_id, amount=amount, method=method)

    report = _report(fake_client, merchant_id)

    series_total = sum(Decimal(point["amount"]) for point in report["series"])
    donut_total = sum(Decimal(entry["amount"]) for entry in report["by_method"])

    assert series_total == donut_total
    assert series_total == Decimal(report["successful_collections"])
    assert series_total == Decimal("16000.00")


def test_the_counts_agree_too(fake_client):
    merchant_id, _user_id = _merchant(fake_client)
    for _ in range(5):
        _collection(fake_client, merchant_id, amount="100.00")

    report = _report(fake_client, merchant_id)

    assert sum(p["count"] for p in report["series"]) == 5
    assert sum(e["count"] for e in report["by_method"]) == 5
    assert report["successful_count"] == 5


def test_only_successful_collections_count(fake_client):
    """A pending or failed payment is not takings. It must not appear in
    either chart."""
    merchant_id, _user_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, amount="1000.00")
    _collection(fake_client, merchant_id, amount="9999.00", status="pending")
    _collection(fake_client, merchant_id, amount="8888.00", status="failed")

    report = _report(fake_client, merchant_id)

    assert Decimal(report["successful_collections"]) == Decimal("1000.00")
    assert sum(Decimal(e["amount"]) for e in report["by_method"]) == Decimal("1000.00")


def test_a_reversed_collection_stops_counting(fake_client):
    """Same rule the wallet balance follows: only `successful` counts, so
    a reversal drops out of reporting rather than being subtracted
    somewhere a merchant cannot see."""
    merchant_id, _user_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, amount="4000.00")
    _collection(fake_client, merchant_id, amount="4000.00", status="reversed")

    report = _report(fake_client, merchant_id)

    assert Decimal(report["successful_collections"]) == Decimal("4000.00")


def test_another_merchants_collections_never_appear(fake_client):
    mine, _user_id = _merchant(fake_client)
    theirs, _other = _merchant(fake_client)
    _collection(fake_client, mine, amount="1000.00")
    _collection(fake_client, theirs, amount="999999.00")

    report = _report(fake_client, mine)

    assert Decimal(report["successful_collections"]) == Decimal("1000.00")


# --- fees --------------------------------------------------------------------


def test_fees_are_the_posted_amounts(fake_client):
    """Summed from what was charged on each transaction, not recomputed
    from a pricing rule - the rule may have changed since."""
    merchant_id, _user_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, amount="1000.00", fee="30.00")
    _collection(fake_client, merchant_id, amount="2000.00", fee="60.00")

    report = _report(fake_client, merchant_id)

    assert Decimal(report["fees_paid"]) == Decimal("90.00")


def test_fees_follow_the_same_filter_as_the_charts(fake_client):
    merchant_id, _user_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, amount="1000.00", fee="30.00")
    _collection(fake_client, merchant_id, amount="1000.00", fee="999.00", status="failed")

    report = _report(fake_client, merchant_id)

    assert Decimal(report["fees_paid"]) == Decimal("30.00")


# --- the window --------------------------------------------------------------


def test_every_day_in_the_window_is_present_even_when_empty(fake_client):
    """A dense series. A sparse one lets the chart close its own gaps, so
    a day with no takings renders as if it never happened."""
    merchant_id, _user_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, amount="1000.00")

    report = _report(fake_client, merchant_id, days=7)

    assert len(report["series"]) == 7
    assert sum(1 for p in report["series"] if Decimal(p["amount"]) == 0) == 6


def test_a_collection_before_the_window_is_excluded(fake_client):
    merchant_id, _user_id = _merchant(fake_client)
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    _collection(fake_client, merchant_id, amount="5000.00", created_at=old)
    _collection(fake_client, merchant_id, amount="1000.00")

    report = _report(fake_client, merchant_id, days=7)

    assert Decimal(report["successful_collections"]) == Decimal("1000.00")


def test_a_wider_window_includes_it_again(fake_client):
    merchant_id, _user_id = _merchant(fake_client)
    old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    _collection(fake_client, merchant_id, amount="5000.00", created_at=old)
    _collection(fake_client, merchant_id, amount="1000.00")

    report = _report(fake_client, merchant_id, days=30)

    assert Decimal(report["successful_collections"]) == Decimal("6000.00")
    assert len(report["series"]) == 30


def test_a_late_evening_payment_lands_on_the_local_day(fake_client):
    """Tanzania is UTC+3 with no DST. A payment at 01:00 local on the 10th
    is 22:00 UTC on the 9th; it belongs to the 10th on this chart, because
    that is the day the merchant was open.
    """
    merchant_id, _user_id = _merchant(fake_client)
    today_local = (datetime.now(timezone.utc) + timedelta(hours=3)).date()
    # 01:00 EAT today == 22:00 UTC yesterday.
    one_am_eat = datetime.combine(
        today_local, datetime.min.time(), tzinfo=timezone(timedelta(hours=3))
    ) + timedelta(hours=1)
    _collection(
        fake_client,
        merchant_id,
        amount="2500.00",
        created_at=one_am_eat.astimezone(timezone.utc).isoformat(),
    )

    report = _report(fake_client, merchant_id, days=7)

    on_today = next(p for p in report["series"] if p["date"] == today_local.isoformat())
    assert Decimal(on_today["amount"]) == Decimal("2500.00")


# --- pending is about now, not the window ------------------------------------


def test_pending_is_not_narrowed_by_the_date_filter(fake_client):
    """"What is still in flight" is a question about now. Narrowing to
    last week does not stop a merchant caring about today's pending
    payment."""
    merchant_id, _user_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, amount="3000.00", status="pending")

    narrow = _report(fake_client, merchant_id, days=1)
    wide = _report(fake_client, merchant_id, days=30)

    assert Decimal(narrow["pending_collections"]) == Decimal("3000.00")
    assert Decimal(wide["pending_collections"]) == Decimal("3000.00")


# --- the donut's legend ------------------------------------------------------


def test_methods_come_back_biggest_first(fake_client):
    """A legend ordered by size reads top-down as a ranking, which is the
    question being asked of it."""
    merchant_id, _user_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, amount="1000.00", method="CARD")
    _collection(fake_client, merchant_id, amount="9000.00", method="MOBILE_MONEY")
    _collection(fake_client, merchant_id, amount="4000.00", method="BANK_TRANSFER")

    report = _report(fake_client, merchant_id)

    assert [e["method"] for e in report["by_method"]] == [
        "MOBILE_MONEY",
        "BANK_TRANSFER",
        "CARD",
    ]


def test_only_methods_actually_used_appear(fake_client):
    """No zero slices. A donut listing methods a merchant has never taken
    money through is a legend of noise."""
    merchant_id, _user_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, method="MOBILE_MONEY")

    report = _report(fake_client, merchant_id)

    assert [e["method"] for e in report["by_method"]] == ["MOBILE_MONEY"]


def test_no_collections_means_empty_rather_than_a_fabricated_slice(fake_client):
    merchant_id, _user_id = _merchant(fake_client)

    report = _report(fake_client, merchant_id)

    assert report["by_method"] == []
    assert Decimal(report["successful_collections"]) == 0
    assert len(report["series"]) == 7


# --- the endpoint ------------------------------------------------------------


def test_the_endpoint_returns_the_report(fake_client):
    merchant_id, user_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, amount="1000.00")

    response = client.get(
        "/v1/merchant/overview-report", params={"days": 7}, headers=auth_headers(user_id)
    )

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert len(body["series"]) == 7
    assert Decimal(body["successful_collections"]) == Decimal("1000.00")


def test_the_endpoint_accepts_an_explicit_range(fake_client):
    merchant_id, user_id = _merchant(fake_client)

    response = client.get(
        "/v1/merchant/overview-report",
        params={"start_date": "2026-11-01", "end_date": "2026-11-05"},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["start_date"] == "2026-11-01"
    assert body["end_date"] == "2026-11-05"
    assert len(body["series"]) == 5


def test_a_backwards_range_is_refused(fake_client):
    merchant_id, user_id = _merchant(fake_client)

    response = client.get(
        "/v1/merchant/overview-report",
        params={"start_date": "2026-11-20", "end_date": "2026-11-01"},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 422, response.text


def test_an_api_key_cannot_read_the_report(fake_client):
    merchant_id, _user_id = _merchant(fake_client)
    raw_key, _row = make_api_key(fake_client, merchant_id, scopes=["transactions:read"])

    response = client.get(
        "/v1/merchant/overview-report", headers={"X-API-Key": raw_key}
    )

    assert response.status_code == 403, response.text


def test_an_unauthenticated_request_is_refused(fake_client):
    assert client.get("/v1/merchant/overview-report").status_code == 401
