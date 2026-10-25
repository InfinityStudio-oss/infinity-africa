"""The two dashboard figures that were quietly wrong.

**Failed transactions read exactly 1,000.** It summed the rows a plain
select returned, and PostgREST caps a response at 1000 whatever you ask
for. On 2026-10-24 the true figure was 1,049. The card did not drift - it
pinned, and would have stayed pinned at 1,000 however far the real number
rose. It became wrong precisely because the platform finally grew enough
to cross that line in one day.

**Total businesses counted every row ever created**, including accounts
that had been closed - so the headline number drifted further from the
truth with each one wound up, duplicate signups among them.

Both are read by whoever is deciding whether the platform is healthy, so
a number that is quietly capped is worse than no number at all.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.services.admin_overview import get_admin_overview
from tests.factories import create_merchant


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret-do-not-use")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _failed_transaction(fake_client, merchant_id, *, when=None):
    when = when or datetime.now(timezone.utc)
    return fake_client.seed(
        "transactions",
        {
            "merchant_id": str(merchant_id),
            "reference": f"TXN-{uuid.uuid4().hex[:10]}",
            "type": "collection",
            "method": "WALLET_PUSH",
            "gross_amount": "500",
            "fee_amount": "11.5",
            "net_amount": "488.5",
            "currency": "TZS",
            "status": "failed",
            "created_at": when.isoformat(),
        },
    )


# --- failed transactions ----------------------------------------------


def test_more_than_a_thousand_failures_is_not_reported_as_a_thousand(fake_client):
    """The exact production symptom. 1,049 must not read 1,000."""
    merchant = create_merchant(fake_client)
    for _ in range(1049):
        _failed_transaction(fake_client, merchant["id"])

    assert get_admin_overview(fake_client)["failed_transactions"] == 1049


def test_the_count_is_exact_well_past_the_page_cap(fake_client):
    merchant = create_merchant(fake_client)
    for _ in range(1200):
        _failed_transaction(fake_client, merchant["id"])

    assert get_admin_overview(fake_client)["failed_transactions"] == 1200


def test_a_small_number_is_still_right(fake_client):
    """The cap fix must not break the ordinary case."""
    merchant = create_merchant(fake_client)
    for _ in range(3):
        _failed_transaction(fake_client, merchant["id"])

    assert get_admin_overview(fake_client)["failed_transactions"] == 3


def test_yesterdays_failures_are_not_counted_as_todays(fake_client):
    """This counter is "today" on the merchant's calendar. Widening the
    query to fix the cap must not widen the period."""
    merchant = create_merchant(fake_client)
    _failed_transaction(fake_client, merchant["id"])
    _failed_transaction(
        fake_client, merchant["id"], when=datetime.now(timezone.utc) - timedelta(days=3)
    )

    assert get_admin_overview(fake_client)["failed_transactions"] == 1


def test_successful_transactions_are_not_counted(fake_client):
    merchant = create_merchant(fake_client)
    _failed_transaction(fake_client, merchant["id"])
    fake_client.seed(
        "transactions",
        {
            "merchant_id": str(merchant["id"]),
            "reference": f"TXN-{uuid.uuid4().hex[:10]}",
            "type": "collection",
            "method": "WALLET_PUSH",
            "gross_amount": "500",
            "fee_amount": "11.5",
            "net_amount": "488.5",
            "currency": "TZS",
            "status": "successful",
        },
    )

    assert get_admin_overview(fake_client)["failed_transactions"] == 1


# --- total businesses --------------------------------------------------


def test_a_closed_account_is_not_a_business(fake_client):
    create_merchant(fake_client, status="active")
    create_merchant(fake_client, status="active")
    create_merchant(fake_client, status="closed")

    assert get_admin_overview(fake_client)["total_merchants"] == 2


def test_a_suspended_account_still_counts(fake_client):
    """Suspended is a customer temporarily blocked, not one who has left.
    Dropping them would understate the platform just as badly as counting
    closed ones overstated it."""
    create_merchant(fake_client, status="active")
    create_merchant(fake_client, status="suspended")

    assert get_admin_overview(fake_client)["total_merchants"] == 2


def test_closing_a_duplicate_removes_it_from_the_count(fake_client):
    """The practical reason this matters: a typo creates a second account
    for a business that already trades, and closing it should make the
    headline figure honest again."""
    create_merchant(fake_client, business_name="KILUNGULE SUPER WiFi", status="active")
    create_merchant(fake_client, business_name="KILUNGULE SUPER WiFi", status="closed")

    assert get_admin_overview(fake_client)["total_merchants"] == 1


def test_no_merchants_reads_zero(fake_client):
    assert get_admin_overview(fake_client)["total_merchants"] == 0
