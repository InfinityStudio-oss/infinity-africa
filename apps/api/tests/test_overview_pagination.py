"""A dashboard counter must not depend on how many rows came before it.

On 11 Oct 2026 the Super Admin dashboard showed "Collections Today:
TZS 0.00" on a morning that had already taken 41 payments. Withdrawals
Today, on the same dashboard, was correct.

The cause was not the clock. Both counters selected their whole table and
filtered in Python, and PostgREST answers an unbounded select with a
single 1000-row page without saying so. Successful collection
transactions had just passed 1,133; the page it returned held the oldest
1000, dated 16 Aug to 10 Oct, and none of them were today. Withdrawals
kept working only because there were 34 payouts in total.

Which means the counter did not break when the code changed. It broke
when the platform grew, silently, and would have stayed broken.

These tests put more than one page of rows in front of each counter.
They fail against a select that is not narrowed or paged.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services.admin_overview import get_admin_overview
from app.services.crud import fetch_all
from app.services.merchant_overview import get_merchant_overview
from tests.fakes import POSTGREST_DEFAULT_PAGE, FakeSupabaseClient

EAT = timezone(timedelta(hours=3))
# Comfortably more than one page, so "today" cannot fit inside the first.
OLD_ROWS = POSTGREST_DEFAULT_PAGE + 200


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


@pytest.fixture
def client():
    return FakeSupabaseClient()


@pytest.fixture
def merchant(client):
    merchant_id = uuid.uuid4()
    client.table("merchants").insert(
        {
            "id": str(merchant_id),
            "business_name": "Hotspot Co",
            "currency": "TZS",
            "status": "active",
        }
    ).execute()
    return merchant_id


def _seed(client, merchant_id, *, today_amount: str):
    """A long history, then one payment taken today.

    The history is written first so that today's row is the one a single
    page would leave out — the production ordering.
    """
    now = datetime.now(timezone.utc)
    history_day = now.astimezone(EAT) - timedelta(days=30)

    for index in range(OLD_ROWS):
        client.table("transactions").insert(
            {
                "id": str(uuid.uuid4()),
                "merchant_id": str(merchant_id),
                "type": "collection",
                "status": "successful",
                "gross_amount": "10.00",
                "fee_amount": "1.00",
                "net_amount": "9.00",
                "created_at": _iso(history_day + timedelta(seconds=index)),
            }
        ).execute()

    client.table("transactions").insert(
        {
            "id": str(uuid.uuid4()),
            "merchant_id": str(merchant_id),
            "type": "collection",
            "status": "successful",
            "gross_amount": today_amount,
            "fee_amount": "0.00",
            "net_amount": today_amount,
            # Just after the merchant's own midnight — the window the old
            # UTC comparison also lost.
            "created_at": _iso(now.astimezone(EAT).replace(hour=0, minute=30, second=0, microsecond=0)),
        }
    ).execute()
    return now


def test_the_platform_still_sees_todays_collections(client, merchant):
    _seed(client, merchant, today_amount="4700.00")

    overview = get_admin_overview(client)

    assert overview["collections_today"] == Decimal("4700.00")


def test_a_merchant_still_sees_todays_collections(client, merchant):
    _seed(client, merchant, today_amount="4700.00")

    overview = get_merchant_overview(client, merchant_id=merchant)

    assert overview["collections_today"] == Decimal("4700.00")


def test_a_merchants_lifetime_total_counts_every_page(client, merchant):
    """The other half of the same flaw: a lifetime total that reads one
    page under-reports a busy merchant's takings."""
    _seed(client, merchant, today_amount="4700.00")

    overview = get_merchant_overview(client, merchant_id=merchant)

    expected = Decimal("10.00") * OLD_ROWS + Decimal("4700.00")
    assert overview["total_collections"] == expected
    assert overview["total_fees_charged"] == Decimal("1.00") * OLD_ROWS


def test_the_fake_client_truncates_like_postgrest(client, merchant):
    """The guard behind these tests. If the fake ever returns everything
    again, the tests above would pass against the very code that failed
    in production."""
    _seed(client, merchant, today_amount="1.00")

    unbounded = (
        client.table("transactions").select("id").eq("type", "collection").execute()
    ).data

    assert len(unbounded) == POSTGREST_DEFAULT_PAGE
    assert OLD_ROWS + 1 > POSTGREST_DEFAULT_PAGE


def test_fetch_all_crosses_page_boundaries(client, merchant):
    _seed(client, merchant, today_amount="1.00")

    rows = fetch_all(
        lambda: client.table("transactions").select("id").eq("type", "collection")
    )

    assert len(rows) == OLD_ROWS + 1
