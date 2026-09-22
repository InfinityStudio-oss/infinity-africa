"""Self-service onboarding: POST /v1/onboarding/merchant-account,
POST /v1/onboarding/documents, GET /v1/onboarding/status — end to end
against the in-memory FakeSupabaseClient (see tests/fakes.py), same pattern
as test_merchant_portal.py.
"""

import io
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import TEST_JWT_SECRET, auth_headers, make_merchant_member

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _valid_payload(**overrides) -> dict:
    return {
        "business_name": "Amani Traders Ltd",
        "nature_of_business": "Online retail",
        "business_category": "Retail",
        "physical_address": "Mbezi Luis",
        "region_city": "Dar es Salaam",
        "website_url": None,
        "contact_phone": "+255700000000",
        "nida_number": "19900101-12345-12345-12",
        "services_needed": ["PAYMENT_LINKS", "INVOICES"],
        "accepted_terms": True,
        "accepted_privacy": True,
        **overrides,
    }


# --- POST /v1/onboarding/merchant-account -----------------------------------


def test_create_merchant_account_requires_auth(fake_client):
    response = client.post("/v1/onboarding/merchant-account", json=_valid_payload())
    assert response.status_code == 401


def test_create_merchant_account_success(fake_client):
    user_id = uuid.uuid4()
    response = client.post(
        "/v1/onboarding/merchant-account", headers=auth_headers(user_id), json=_valid_payload()
    )
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["merchant"]["business_name"] == "Amani Traders Ltd"
    assert body["merchant"]["contact_email"] == "user@example.com"  # from the JWT, not the body
    assert body["merchant"]["status"] == "pending"
    assert body["account_status"] == "PENDING_VERIFICATION"
    assert re.fullmatch(r"27\d{6}", body["merchant"]["merchant_code"])

    merchant_id = body["merchant"]["id"]
    membership = next(
        r for r in fake_client.table("merchant_users")._table.rows if r["user_id"] == str(user_id)
    )
    assert membership["merchant_id"] == merchant_id
    assert membership["role"] == "MERCHANT_ADMIN"
    assert membership["status"] == "active"

    submission = next(
        r for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )
    assert submission["review_status"] == "PENDING_VERIFICATION"
    assert submission["services_needed"] == ["PAYMENT_LINKS", "INVOICES"]


def test_create_merchant_account_is_rate_limited(fake_client):
    """Wiring test for app/core/rate_limit.py's merchant_onboarding_submit
    scope (MVP security-hardening pass — this endpoint previously had no
    rate limit despite being a public-ish, unauthenticated-in-spirit
    business-submission form gated only by a fresh Supabase Auth signup)."""
    from app.core.rate_limit import _limiter

    for _ in range(5):
        _limiter.check("merchant_onboarding_submit:testclient", limit=5, window_seconds=60)

    response = client.post(
        "/v1/onboarding/merchant-account", headers=auth_headers(uuid.uuid4()), json=_valid_payload()
    )
    assert response.status_code == 429


def test_create_merchant_account_requires_terms(fake_client):
    response = client.post(
        "/v1/onboarding/merchant-account",
        headers=auth_headers(uuid.uuid4()),
        json=_valid_payload(accepted_terms=False),
    )
    assert response.status_code == 422


def test_create_merchant_account_requires_privacy(fake_client):
    response = client.post(
        "/v1/onboarding/merchant-account",
        headers=auth_headers(uuid.uuid4()),
        json=_valid_payload(accepted_privacy=False),
    )
    assert response.status_code == 422


def test_create_merchant_account_duplicate_prevented(fake_client):
    user_id = uuid.uuid4()
    first = client.post(
        "/v1/onboarding/merchant-account", headers=auth_headers(user_id), json=_valid_payload()
    )
    assert first.status_code == 201

    second = client.post(
        "/v1/onboarding/merchant-account", headers=auth_headers(user_id), json=_valid_payload()
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"


def test_create_merchant_account_resubmission_after_rejection(fake_client):
    user_id = uuid.uuid4()
    first = client.post(
        "/v1/onboarding/merchant-account", headers=auth_headers(user_id), json=_valid_payload()
    )
    merchant_id = first.json()["data"]["merchant"]["id"]
    original_merchant_code = first.json()["data"]["merchant"]["merchant_code"]
    submission_row = next(
        r for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )
    submission_row["review_status"] = "REJECTED"
    submission_row["review_note"] = "Business licence unclear"

    second = client.post(
        "/v1/onboarding/merchant-account",
        headers=auth_headers(user_id),
        json=_valid_payload(business_name="Amani Traders Ltd (updated)"),
    )
    assert second.status_code == 201
    assert second.json()["data"]["merchant"]["business_name"] == "Amani Traders Ltd (updated)"
    assert second.json()["data"]["merchant"]["id"] == merchant_id
    # Merchant ID is generated once and never changes — a resubmission
    # updates the business profile in place, not the identifier.
    assert second.json()["data"]["merchant"]["merchant_code"] == original_merchant_code

    all_submissions = [
        r for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    ]
    assert len(all_submissions) == 1  # updated in place, not duplicated
    assert all_submissions[0]["review_status"] == "PENDING_VERIFICATION"


# --- GET /v1/onboarding/status -----------------------------------------------


def test_onboarding_status_no_account(fake_client):
    response = client.get("/v1/onboarding/status", headers=auth_headers(uuid.uuid4()))
    assert response.status_code == 200
    body = response.json()["data"]
    assert body == {
        "has_account": False,
        "onboarding_completed": False,
        "merchant_id": None,
        "account_status": None,
        "next_path": "/onboarding",
    }


def test_onboarding_status_pending_verification(fake_client):
    user_id = uuid.uuid4()
    client.post("/v1/onboarding/merchant-account", headers=auth_headers(user_id), json=_valid_payload())

    response = client.get("/v1/onboarding/status", headers=auth_headers(user_id))
    body = response.json()["data"]
    assert body["has_account"] is True
    assert body["onboarding_completed"] is True
    assert body["account_status"] == "PENDING_VERIFICATION"
    assert body["next_path"] == "/dashboard/overview"


def test_onboarding_status_rejected_sends_back_to_onboarding(fake_client):
    user_id = uuid.uuid4()
    create_response = client.post(
        "/v1/onboarding/merchant-account", headers=auth_headers(user_id), json=_valid_payload()
    )
    merchant_id = create_response.json()["data"]["merchant"]["id"]
    submission_row = next(
        r for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )
    submission_row["review_status"] = "REJECTED"

    response = client.get("/v1/onboarding/status", headers=auth_headers(user_id))
    body = response.json()["data"]
    assert body["onboarding_completed"] is False
    assert body["next_path"] == "/onboarding"


# --- POST /v1/onboarding/documents -------------------------------------------


def _pdf_file(name: str = "nida.pdf"):
    return (name, io.BytesIO(b"%PDF-1.4\n%fake\n"), "application/pdf")


def test_upload_document_requires_own_merchant(fake_client):
    response = client.post(
        "/v1/onboarding/documents",
        headers=auth_headers(uuid.uuid4()),
        data={"document_type": "NIDA"},
        files={"file": _pdf_file()},
    )
    assert response.status_code == 404


def test_upload_document_success(fake_client):
    merchant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    fake_client.seed("merchants", {"id": str(merchant_id), "business_name": "Test", "contact_email": "m@example.com"})
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")

    response = client.post(
        "/v1/onboarding/documents",
        headers=auth_headers(user_id),
        data={"document_type": "NIDA"},
        files={"file": _pdf_file()},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["document_type"] == "NIDA"
    assert body["upload_status"] == "UPLOADED"
    assert body["mime_type"] == "application/pdf"

    stored = [
        r for r in fake_client.table("onboarding_documents")._table.rows if r["merchant_id"] == str(merchant_id)
    ]
    assert len(stored) == 1
    assert stored[0]["document_type"] == "NIDA"
    assert f"merchant-documents/{merchant_id}/NIDA.pdf" in fake_client._storage_objects


def test_upload_document_wrong_mime_type_rejected(fake_client):
    merchant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    fake_client.seed("merchants", {"id": str(merchant_id), "business_name": "Test", "contact_email": "m@example.com"})
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")

    response = client.post(
        "/v1/onboarding/documents",
        headers=auth_headers(user_id),
        data={"document_type": "NIDA"},
        files={"file": ("nida.txt", io.BytesIO(b"not a real document"), "text/plain")},
    )
    assert response.status_code == 422


def test_reupload_same_document_type_replaces_row(fake_client):
    merchant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    fake_client.seed("merchants", {"id": str(merchant_id), "business_name": "Test", "contact_email": "m@example.com"})
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")

    client.post(
        "/v1/onboarding/documents",
        headers=auth_headers(user_id),
        data={"document_type": "TIN_CERTIFICATE"},
        files={"file": _pdf_file("tin-v1.pdf")},
    )
    second = client.post(
        "/v1/onboarding/documents",
        headers=auth_headers(user_id),
        data={"document_type": "TIN_CERTIFICATE"},
        files={"file": _pdf_file("tin-v2.pdf")},
    )
    assert second.status_code == 200

    stored = [
        r
        for r in fake_client.table("onboarding_documents")._table.rows
        if r["merchant_id"] == str(merchant_id) and r["document_type"] == "TIN_CERTIFICATE"
    ]
    assert len(stored) == 1
    assert stored[0]["original_filename"] == "tin-v2.pdf"
