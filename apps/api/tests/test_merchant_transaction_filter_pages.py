"""Status filters across pages, totals and combinations.

The customer report was "Successful and Failed do not work". The backend
already narrowed correctly; what the merchant saw was the dashboard
fetching page 1 (20 rows) and never anything after it, exporting only
those 20, and showing nothing at all - "no transactions match" - when the
request failed. These pin the server half of the fix: every status the
ledger supports filters before pagination, the total reflects the filter,
and each page is a distinct slice of the same filtered set.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.schemas.enums import TransactionStatus
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
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    user = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user, "MERCHANT_STAFF")
    return merchant_id, auth_headers(user)


def _get(headers, query):
    response = client.get(f"/v1/merchant/transactions?{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("status", [s.value for s in TransactionStatus])
def test_every_supported_status_filters_across_every_page(fake_client, status):
    merchant_id, headers = _merchant(fake_client)
    # 5 of the wanted status interleaved with 2 of every other status.
    wanted = set()
    for i in range(5):
        wanted.add(create_transaction(fake_client, merchant_id, reference=f"W-{status}-{i}", status=status)["reference"])
        for other in TransactionStatus:
            if other.value != status and i < 2:
                create_transaction(fake_client, merchant_id, reference=f"X-{other.value}-{i}", status=other.value)

    seen: list[str] = []
    for page in (1, 2, 3):
        body = _get(headers, f"status={status}&page={page}&page_size=2")
        assert body["meta"]["total"] == 5
        assert body["meta"]["total_pages"] == 3
        assert all(row["status"] == status for row in body["data"])
        seen += [row["reference"] for row in body["data"]]

    assert len(seen) == 5 and set(seen) == wanted, "pages must be disjoint and together complete"


def test_status_combines_with_type_date_and_search(fake_client):
    merchant_id, headers = _merchant(fake_client)
    # 22 Nov EAT starts 21 Nov 21:00 UTC.
    create_transaction(fake_client, merchant_id, reference="HIT-1", status="successful", type="collection",
                       created_at="2026-11-21T21:30:00+00:00")
    create_transaction(fake_client, merchant_id, reference="HIT-2", status="successful", type="collection",
                       created_at="2026-11-22T20:59:00+00:00")
    create_transaction(fake_client, merchant_id, reference="MISS-STATUS", status="failed", type="collection",
                       created_at="2026-11-22T10:00:00+00:00")
    create_transaction(fake_client, merchant_id, reference="MISS-TYPE", status="successful", type="disbursement",
                       created_at="2026-11-22T10:00:00+00:00")
    create_transaction(fake_client, merchant_id, reference="MISS-DATE", status="successful", type="collection",
                       created_at="2026-11-22T21:00:00+00:00")

    body = _get(headers, "status=successful&type=collection&date_from=2026-11-22&date_to=2026-11-22")
    assert {r["reference"] for r in body["data"]} == {"HIT-1", "HIT-2"}
    assert body["meta"]["total"] == 2

    narrowed = _get(headers, "status=successful&type=collection&date_from=2026-11-22&date_to=2026-11-22&search=HIT-2")
    assert [r["reference"] for r in narrowed["data"]] == ["HIT-2"]
    assert narrowed["meta"]["total"] == 1


def test_a_filter_never_reaches_another_merchants_rows(fake_client):
    mine, headers = _merchant(fake_client)
    theirs, _ = _merchant(fake_client)
    create_transaction(fake_client, mine, reference="MINE", status="failed")
    create_transaction(fake_client, theirs, reference="THEIRS", status="failed")

    body = _get(headers, "status=failed")

    assert [r["reference"] for r in body["data"]] == ["MINE"]
    assert body["meta"]["total"] == 1


def test_the_method_filter_the_overview_chart_links_to(fake_client):
    merchant_id, headers = _merchant(fake_client)
    create_transaction(fake_client, merchant_id, reference="MM", method="MOBILE_MONEY")
    create_transaction(fake_client, merchant_id, reference="QR", method="DYNAMIC_QR")

    assert [r["reference"] for r in _get(headers, "method=MOBILE_MONEY")["data"]] == ["MM"]


def test_a_malformed_method_is_rejected_not_silently_empty(fake_client):
    _merchant_id, headers = _merchant(fake_client)
    response = client.get("/v1/merchant/transactions?method=mobile%20money;drop", headers=headers)
    assert response.status_code == 422
