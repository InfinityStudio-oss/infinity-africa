"""GET /v1/admin/overview — end to end against the in-memory
FakeSupabaseClient, same pattern as test_admin_onboarding.py.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_overview_requires_super_admin(fake_client):
    response = client.get("/v1/admin/overview", headers=auth_headers(uuid.uuid4()))
    assert response.status_code == 403


def test_overview_counts_merchants_and_pending_onboarding(fake_client):
    create_merchant(fake_client)
    create_merchant(fake_client)
    merchant = create_merchant(fake_client)
    fake_client.seed(
        "onboarding_submissions",
        {
            "merchant_id": merchant["id"],
            "nature_of_business": "Retail",
            "business_category": "Retail",
            "physical_address": "Addr",
            "region_city": "Dar",
            "services_needed": [],
            "review_status": "PENDING_VERIFICATION",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    response = client.get("/v1/admin/overview", headers=auth_headers(admin_id))
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["total_merchants"] == 3
    assert body["pending_onboarding_requests"] == 1


def test_overview_platform_revenue_is_mtd_not_running_balance(fake_client):
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    account = fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": None,
            "name": "Platform Revenue",
            "account_type": "revenue",
            "purpose": "platform_revenue",
            "currency": "TZS",
            "balance": "999999",  # all-time running balance — must NOT be what overview reports
        },
    )

    last_month = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    this_month = datetime.now(timezone.utc).isoformat()

    fake_client.seed(
        "ledger_entries",
        {
            "transaction_id": str(uuid.uuid4()),
            "ledger_account_id": account["id"],
            "direction": "credit",
            "amount": "500",
            "currency": "TZS",
            "created_at": last_month,
        },
    )
    fake_client.seed(
        "ledger_entries",
        {
            "transaction_id": str(uuid.uuid4()),
            "ledger_account_id": account["id"],
            "direction": "credit",
            "amount": "700",
            "currency": "TZS",
            "created_at": this_month,
        },
    )

    response = client.get("/v1/admin/overview", headers=auth_headers(admin_id))
    assert response.status_code == 200
    assert response.json()["data"]["platform_revenue"] == "700.00" or float(
        response.json()["data"]["platform_revenue"]
    ) == 700


def _seed_revenue_account(fake_client):
    return fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": None,
            "name": "Platform Revenue",
            "account_type": "revenue",
            "purpose": "platform_revenue",
            "currency": "TZS",
            "balance": "999999",
        },
    )


def _credit(fake_client, account, amount, created_at):
    fake_client.seed(
        "ledger_entries",
        {
            "transaction_id": str(uuid.uuid4()),
            "ledger_account_id": account["id"],
            "direction": "credit",
            "amount": str(amount),
            "currency": "TZS",
            "created_at": created_at,
        },
    )


def test_revenue_today_is_separate_from_the_month(fake_client):
    """The daily figure the Super Admin asked for: what the platform has
    earned since midnight, beside the month-to-date one."""
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    account = _seed_revenue_account(fake_client)

    now = datetime.now(timezone.utc)
    eat_now = now.astimezone(timezone(timedelta(hours=3)))
    # Earlier in the same Tanzanian month, but not today.
    earlier_this_month = (eat_now.replace(day=1, hour=12) ).astimezone(timezone.utc)
    if earlier_this_month >= now:
        earlier_this_month = now - timedelta(days=1)
    _credit(fake_client, account, "700", earlier_this_month.isoformat())
    _credit(fake_client, account, "250", now.isoformat())

    body = client.get("/v1/admin/overview", headers=auth_headers(admin_id)).json()["data"]

    assert float(body["platform_revenue_today"]) == 250
    assert float(body["platform_revenue"]) == 950


def test_revenue_counts_every_page_of_entries(fake_client):
    """Production had 1,083 credit entries in one month, so the single
    page the old code read stopped 83 short: month-to-date showed
    TZS 27,592.58 against a true 29,430.08."""
    from tests.fakes import POSTGREST_DEFAULT_PAGE

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    account = _seed_revenue_account(fake_client)

    now = datetime.now(timezone.utc)
    entries = POSTGREST_DEFAULT_PAGE + 83
    for index in range(entries):
        _credit(fake_client, account, "1", (now - timedelta(seconds=index)).isoformat())

    body = client.get("/v1/admin/overview", headers=auth_headers(admin_id)).json()["data"]

    assert float(body["platform_revenue"]) == entries
    assert float(body["platform_revenue_today"]) == entries


def test_collections_this_month_counts_every_page(fake_client):
    """A month of successful collections already runs past a thousand
    rows in production, so a single select would report a page as if it
    were the month."""
    from tests.fakes import POSTGREST_DEFAULT_PAGE

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    now = datetime.now(timezone.utc)
    eat_now = now.astimezone(timezone(timedelta(hours=3)))
    rows = POSTGREST_DEFAULT_PAGE + 120
    for index in range(rows):
        # Spread across the current Tanzanian month, newest first, so
        # none falls outside the window.
        at = now - timedelta(minutes=index)
        if at.astimezone(timezone(timedelta(hours=3))).month != eat_now.month:
            at = now
        fake_client.seed(
            "transactions",
            {
                "id": str(uuid.uuid4()),
                "merchant_id": str(uuid.uuid4()),
                "type": "collection",
                "status": "successful",
                "gross_amount": "100",
                "created_at": at.isoformat(),
            },
        )

    body = client.get("/v1/admin/overview", headers=auth_headers(admin_id)).json()["data"]

    assert float(body["collections_this_month"]) == rows * 100


def test_collections_this_month_excludes_failed_collections(fake_client):
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    now = datetime.now(timezone.utc).isoformat()

    for status, amount in (("successful", "1000"), ("failed", "9999")):
        fake_client.seed(
            "transactions",
            {
                "id": str(uuid.uuid4()),
                "merchant_id": str(uuid.uuid4()),
                "type": "collection",
                "status": status,
                "gross_amount": amount,
                "created_at": now,
            },
        )

    body = client.get("/v1/admin/overview", headers=auth_headers(admin_id)).json()["data"]

    assert float(body["collections_this_month"]) == 1000
