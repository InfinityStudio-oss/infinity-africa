"""The Customers KPI cards must count customers, not rows received.

The page asks for page_size=100, which the API caps at 100, and the cards
counted the rows that came back. So they read "Total Customers 100 / New
This Month 100 / Repeat 53" while production actually held 940 customers
and 461 repeats - 840 of them never sent to the browser at all.

A total that is exactly the page size is not a total. These tests put
more customers than one page in front of the summary.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.admin_customers import summarise_admin_customers
from tests.fakes import FakeSupabaseClient

EAT = timezone(timedelta(hours=3))
PAGE_SIZE = 100
CUSTOMERS = PAGE_SIZE + 40  # more than one page, like production


@pytest.fixture
def fake_client():
    return FakeSupabaseClient()


@pytest.fixture
def merchant(fake_client):
    merchant_id = uuid.uuid4()
    fake_client.seed(
        "merchants",
        {"id": str(merchant_id), "business_name": "Hotspot Co", "merchant_code": "27000000"},
    )
    return merchant_id


def _collection(fake_client, merchant_id, phone, created_at, status="successful"):
    fake_client.seed(
        "collections",
        {
            "merchant_id": str(merchant_id),
            "customer_phone": phone,
            "payment_link_id": None,
            "amount": "1000",
            "currency": "TZS",
            "status": status,
            "completed_at": created_at,
            "created_at": created_at,
        },
    )


def _seed(fake_client, merchant_id, *, repeats: int):
    now = datetime.now(timezone.utc)
    for index in range(CUSTOMERS):
        phone = f"2557{index:08d}"
        _collection(fake_client, merchant_id, phone, (now - timedelta(minutes=index)).isoformat())
        if index < repeats:
            _collection(
                fake_client, merchant_id, phone, (now - timedelta(minutes=index, seconds=30)).isoformat()
            )
    return now


def test_the_total_counts_every_customer_not_one_page(fake_client, merchant):
    _seed(fake_client, merchant, repeats=0)

    summary = summarise_admin_customers(fake_client, merchant_id=None)

    assert summary["total_customers"] == CUSTOMERS
    assert summary["total_customers"] != PAGE_SIZE


def test_repeat_customers_are_counted_across_every_page(fake_client, merchant):
    _seed(fake_client, merchant, repeats=CUSTOMERS)

    summary = summarise_admin_customers(fake_client, merchant_id=None)

    assert summary["repeat_customers"] == CUSTOMERS


def test_a_customer_who_paid_once_is_not_a_repeat(fake_client, merchant):
    _seed(fake_client, merchant, repeats=10)

    summary = summarise_admin_customers(fake_client, merchant_id=None)

    assert summary["repeat_customers"] == 10


def test_new_this_month_uses_the_tanzanian_month(fake_client, merchant):
    """Consistent with every other "this month" figure on the platform."""
    now = datetime.now(timezone.utc)
    this_month = now.astimezone(EAT).replace(day=1, hour=0, minute=30).astimezone(timezone.utc)
    this_month = min(this_month, now)
    long_ago = (now - timedelta(days=120)).isoformat()

    _collection(fake_client, merchant, "255700000001", this_month.isoformat())
    _collection(fake_client, merchant, "255700000002", long_ago)

    summary = summarise_admin_customers(fake_client, merchant_id=None)

    assert summary["total_customers"] == 2
    assert summary["new_this_month"] == 1


def test_the_summary_can_be_scoped_to_one_business(fake_client, merchant):
    other = uuid.uuid4()
    fake_client.seed("merchants", {"id": str(other), "business_name": "Other Co"})
    now = datetime.now(timezone.utc).isoformat()
    _collection(fake_client, merchant, "255700000001", now)
    _collection(fake_client, other, "255700000002", now)

    assert summarise_admin_customers(fake_client, merchant_id=merchant)["total_customers"] == 1
    assert summarise_admin_customers(fake_client, merchant_id=None)["total_customers"] == 2


def test_a_failed_only_customer_still_counts_as_a_customer(fake_client, merchant):
    """They appear in the table with TZS 0.00 spent - 27 failed attempts
    was a real row - so the total must include them or the card and the
    table disagree."""
    now = datetime.now(timezone.utc).isoformat()
    _collection(fake_client, merchant, "255700000001", now, status="failed")

    assert summarise_admin_customers(fake_client, merchant_id=None)["total_customers"] == 1
