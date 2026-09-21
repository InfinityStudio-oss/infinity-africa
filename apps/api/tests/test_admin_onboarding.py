"""Super-admin onboarding review — /v1/admin/onboarding/* — end to end
against the in-memory FakeSupabaseClient, same pattern as
test_merchant_portal.py / test_onboarding.py.
"""

import logging
import uuid

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import TEST_JWT_SECRET, auth_headers, make_super_admin

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakeResend:
    def __init__(self):
        self.calls: list[dict] = []
        self.should_fail = False

    def send(self, params: dict) -> dict:
        self.calls.append(params)
        if self.should_fail:
            raise Exception("Resend rejected the request")  # noqa: TRY002
        return {"id": "resend-test-message-id"}


@pytest.fixture(autouse=True)
def fake_resend(monkeypatch):
    """Approving a merchant now sends a real (mocked) welcome email — see
    tests/test_invoices.py's identical fixture for why this patches
    resend.Emails.send directly."""
    fake = _FakeResend()
    monkeypatch.setattr(resend.Emails, "send", fake.send)
    return fake


def _valid_payload(**overrides) -> dict:
    return {
        "business_name": "Kilimanjaro Fresh Produce",
        "nature_of_business": "Agriculture",
        "business_category": "Wholesale",
        "physical_address": "Njiro Road",
        "region_city": "Arusha",
        "website_url": None,
        "contact_phone": "+255712345678",
        "nida_number": "19900101-12345-12345-12",
        "services_needed": ["PAYMENT_COLLECTION"],
        "accepted_terms": True,
        "accepted_privacy": True,
        **overrides,
    }


def _submit_onboarding(user_id: uuid.UUID, **overrides) -> dict:
    response = client.post(
        "/v1/onboarding/merchant-account", headers=auth_headers(user_id), json=_valid_payload(**overrides)
    )
    assert response.status_code == 201
    return response.json()["data"]


def _seed_required_documents(fake_client, merchant_id: str, *, document_types=("NIDA", "TIN_CERTIFICATE")) -> None:
    """NIDA + TIN are required before a submission can be approved
    (BUSINESS_LICENCE deliberately excluded — it's optional)."""
    for document_type in document_types:
        fake_client.seed(
            "onboarding_documents",
            {
                "merchant_id": merchant_id,
                "document_type": document_type,
                "file_path": f"{merchant_id}/{document_type}.pdf",
                "original_filename": f"{document_type.lower()}.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 100,
                "upload_status": "UPLOADED",
                "uploaded_by": str(uuid.uuid4()),
                "uploaded_at": "2026-08-15T00:00:00+00:00",
            },
        )


def test_list_requires_super_admin(fake_client):
    _submit_onboarding(uuid.uuid4())
    response = client.get("/v1/admin/onboarding", headers=auth_headers(uuid.uuid4()))
    assert response.status_code == 403


def test_list_returns_submitted_merchant(fake_client):
    _submit_onboarding(uuid.uuid4())
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    response = client.get("/v1/admin/onboarding", headers=auth_headers(admin_id))
    assert response.status_code == 200
    rows = response.json()["data"]
    assert len(rows) == 1
    row = rows[0]
    assert row["business_name"] == "Kilimanjaro Fresh Produce"
    assert row["owner_email"] == "user@example.com"
    assert row["contact_phone"] == "255712345678"  # normalized, no leading +
    assert row["nature_of_business"] == "Agriculture"
    assert row["physical_address"] == "Njiro Road"
    assert row["services_needed"] == ["PAYMENT_COLLECTION"]
    assert row["document_status"] == "VERIFIED"  # no docs required for approval -> nothing outstanding
    assert row["review_status"] == "PENDING_VERIFICATION"


def test_get_detail_includes_signed_urls_for_documents(fake_client):
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    fake_client.seed(
        "onboarding_documents",
        {
            "merchant_id": merchant_id,
            "document_type": "NIDA",
            "file_path": f"{merchant_id}/NIDA.pdf",
            "original_filename": "nida.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 100,
            "upload_status": "UPLOADED",
            "uploaded_by": str(uuid.uuid4()),
            "uploaded_at": "2026-08-15T00:00:00+00:00",
        },
    )
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    response = client.get(f"/v1/admin/onboarding/{submission_id}", headers=auth_headers(admin_id))
    assert response.status_code == 200
    body = response.json()["data"]
    assert len(body["documents"]) == 1
    assert body["documents"][0]["signed_url"] is not None
    assert body["documents"][0]["signed_url"].startswith("https://fake.storage.test/")


def test_approve_promotes_merchant_status(fake_client):
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    _seed_required_documents(fake_client, merchant_id)
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    response = client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin_id))
    assert response.status_code == 200
    assert response.json()["data"]["review_status"] == "VERIFIED"

    merchant = next(r for r in fake_client.table("merchants")._table.rows if r["id"] == merchant_id)
    assert merchant["status"] == "active"
    assert merchant["kyc_status"] == "verified"


def test_approval_sends_a_welcome_email(fake_client, fake_resend):
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    _seed_required_documents(fake_client, merchant_id)
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    response = client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin_id))
    assert response.status_code == 200

    assert len(fake_resend.calls) == 1
    assert fake_resend.calls[0]["to"] == ["user@example.com"]
    assert fake_resend.calls[0]["subject"] == "Your InfinityPay account has been approved"
    html = fake_resend.calls[0]["html"]
    assert "Kilimanjaro Fresh Produce" in html
    assert "Request collections" in html
    assert "Generate payment links" in html
    assert "info@infinityafrica.net" in html
    assert "support@infinityafrica.net" not in html


def test_approval_succeeds_even_when_welcome_email_delivery_fails(fake_client, fake_resend):
    fake_resend.should_fail = True
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    _seed_required_documents(fake_client, merchant_id)
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    response = client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin_id))

    assert response.status_code == 200, response.text
    merchant = next(r for r in fake_client.table("merchants")._table.rows if r["id"] == merchant_id)
    assert merchant["status"] == "active"


def test_welcome_email_never_goes_to_ceo(fake_client, fake_resend, monkeypatch):
    """Regression test for the exact live bug this was reported against:
    the welcome/approval email must go to the merchant's own contact
    email, never to CEO_EMAIL, even when CEO_EMAIL is configured."""
    monkeypatch.setenv("CEO_EMAIL", "ceo@infinitypay.me")
    get_settings.cache_clear()

    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    _seed_required_documents(fake_client, merchant_id)
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    response = client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin_id))
    assert response.status_code == 200, response.text

    welcome_calls = [c for c in fake_resend.calls if c["subject"] == "Your InfinityPay account has been approved"]
    assert len(welcome_calls) == 1
    assert welcome_calls[0]["to"] == ["user@example.com"]
    assert welcome_calls[0]["to"] != ["ceo@infinitypay.me"]


def test_welcome_email_reply_to_is_info_email(fake_client, fake_resend):
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    _seed_required_documents(fake_client, merchant_id)
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin_id))

    welcome_call = next(c for c in fake_resend.calls if c["subject"] == "Your InfinityPay account has been approved")
    assert welcome_call["reply_to"] == "info@infinityafrica.net"


def test_email_delivery_log_for_welcome_email_uses_merchant_email(fake_client, fake_resend):
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    _seed_required_documents(fake_client, merchant_id)
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin_id))

    delivery = next(
        d for d in fake_client.table("email_deliveries")._table.rows if d["email_type"] == "merchant_welcome"
    )
    assert delivery["recipient_email"] == "user@example.com"
    assert delivery["merchant_id"] == merchant_id
    assert delivery["related_resource_type"] == "merchant"
    assert delivery["related_resource_id"] == merchant_id
    assert delivery["status"] == "sent"
    assert delivery["provider_message_id"]


def test_missing_merchant_email_does_not_fall_back_to_ceo(fake_client, fake_resend, monkeypatch, caplog):
    """A merchant with no contact_email must never receive the welcome
    email at CEO_EMAIL instead — no email should be sent at all, approval
    must still succeed, and the gap must be logged and surfaced to the
    Super Admin."""
    monkeypatch.setenv("CEO_EMAIL", "ceo@infinitypay.me")
    get_settings.cache_clear()

    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    _seed_required_documents(fake_client, merchant_id)
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )

    # Simulate a merchant with no contact_email on file.
    for row in fake_client.table("merchants")._table.rows:
        if row["id"] == merchant_id:
            row["contact_email"] = None

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    # caplog's capturing handler is only attached to the root logger by
    # default — app/main.py::_configure_logging deliberately sets
    # propagate=False on the "infinity" logger namespace (so production
    # logs aren't duplicated/interfered with), which also means those
    # records never bubble up to caplog's handler unless it's attached
    # here directly.
    infinity_logger = logging.getLogger("infinity")
    infinity_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level("WARNING", logger="infinity.email"):
            response = client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin_id))
    finally:
        infinity_logger.removeHandler(caplog.handler)

    assert response.status_code == 200, response.text
    # Approval itself still succeeds.
    merchant = next(r for r in fake_client.table("merchants")._table.rows if r["id"] == merchant_id)
    assert merchant["status"] == "active"

    # No welcome email sent anywhere — in particular, never to CEO_EMAIL.
    welcome_calls = [c for c in fake_resend.calls if c["subject"] == "Your InfinityPay account has been approved"]
    assert welcome_calls == []
    assert not any(d["email_type"] == "merchant_welcome" for d in fake_client.table("email_deliveries")._table.rows)

    # Clearly logged.
    assert "Merchant welcome email not sent: merchant email missing." in caplog.text

    # Surfaced to the Super Admin in the approve response.
    assert (
        response.json()["data"]["welcome_email_warning"]
        == "Merchant approved, but welcome email was not sent because merchant email is missing."
    )


def test_new_merchant_signup_notification_goes_to_ceo(fake_client, fake_resend, monkeypatch):
    """The internal 'new merchant signup submitted for review' email is a
    distinct notification from the merchant welcome email — this one goes
    to CEO_EMAIL, fired at submission time, not approval time, with subject
    exactly 'New merchant signup submitted'."""
    monkeypatch.setenv("CEO_EMAIL", "ceo@infinitypay.me")
    get_settings.cache_clear()

    _submit_onboarding(uuid.uuid4())

    signup_calls = [c for c in fake_resend.calls if c["subject"] == "New merchant signup submitted"]
    assert len(signup_calls) == 1
    assert signup_calls[0]["to"] == ["ceo@infinitypay.me"]
    assert "Kilimanjaro Fresh Produce" in signup_calls[0]["html"]

    delivery = next(
        d for d in fake_client.table("email_deliveries")._table.rows if d["email_type"] == "merchant_signup_notification"
    )
    assert delivery["recipient_email"] == "ceo@infinitypay.me"
    assert delivery["merchant_id"] is not None
    assert delivery["related_resource_type"] == "merchant"
    assert delivery["status"] == "sent"
    assert delivery["provider_message_id"]


def test_signup_notification_includes_merchant_business_and_contact_details(fake_client, fake_resend, monkeypatch):
    """Every field the brief asks for: business name, contact person name,
    merchant email, phone, business type/category, business location,
    submitted date, merchant ID, and status."""
    monkeypatch.setenv("CEO_EMAIL", "ceo@infinitypay.me")
    get_settings.cache_clear()

    user_id = uuid.uuid4()
    # seed_auth_user only backs best_effort_user_profile's lookup (full_name)
    # — auth_headers(user_id) below always embeds a fixed "user@example.com"
    # as the JWT's own email claim, independent of this, and that's what
    # ends up as the merchant's contact_email (see
    # test_list_returns_submitted_merchant's identical assumption).
    fake_client.seed_auth_user(user_id, email="owner@kilimanjarofresh.co.tz", full_name="Amina Juma")

    submitted = _submit_onboarding(user_id, contact_phone="+255712345678")

    signup_call = next(c for c in fake_resend.calls if c["subject"] == "New merchant signup submitted")
    html = signup_call["html"]
    assert "Kilimanjaro Fresh Produce" in html  # business name
    assert "Amina Juma" in html  # contact person name
    assert "user@example.com" in html  # merchant email (= the JWT's own email claim)
    assert "255712345678" in html  # phone number
    assert "Agriculture" in html  # nature_of_business
    assert "Wholesale" in html  # business_category
    assert "Njiro Road" in html and "Arusha" in html  # business location
    assert "Pending Review" in html  # status
    assert submitted["merchant"]["merchant_code"] in html  # merchant ID


def test_no_signup_notification_without_ceo_email_configured(fake_client, fake_resend):
    """CEO_EMAIL unset (the default in tests/most local dev) must never
    raise or block submission — same convention as every other
    CEO-notification email in this codebase."""
    _submit_onboarding(uuid.uuid4())

    assert fake_resend.calls == []
    assert fake_client.table("email_deliveries")._table.rows == []


def test_signup_submission_succeeds_even_when_ceo_notification_delivery_fails(fake_client, fake_resend, monkeypatch):
    """A Resend failure on the internal CEO notification must never fail
    the merchant's own signup submission — the merchant record is already
    saved by the time this email is even attempted."""
    monkeypatch.setenv("CEO_EMAIL", "ceo@infinitypay.me")
    get_settings.cache_clear()
    fake_resend.should_fail = True

    response = client.post(
        "/v1/onboarding/merchant-account", headers=auth_headers(uuid.uuid4()), json=_valid_payload()
    )

    assert response.status_code == 201, response.text
    delivery = next(
        d for d in fake_client.table("email_deliveries")._table.rows if d["email_type"] == "merchant_signup_notification"
    )
    assert delivery["status"] == "failed"
    assert delivery["error_message"]


def test_approve_succeeds_with_no_documents(fake_client):
    """KYC document upload was removed from onboarding — a submission with
    no documents attached at all is approvable; the Super Admin's manual
    review is the gate, not an in-app upload."""
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    response = client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin_id))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["review_status"] == "VERIFIED"

    merchant = next(r for r in fake_client.table("merchants")._table.rows if r["id"] == merchant_id)
    assert merchant["status"] == "active"
    assert merchant["kyc_status"] == "verified"


def test_business_licence_is_optional_for_approval(fake_client):
    """Approval must succeed with only NIDA + TIN uploaded — no
    BUSINESS_LICENCE document required or seeded here at all."""
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    _seed_required_documents(fake_client, merchant_id)  # NIDA + TIN only
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    response = client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin_id))
    assert response.status_code == 200
    assert response.json()["data"]["review_status"] == "VERIFIED"


def test_approval_creates_wallet_and_assigns_custom_pricing_rule(fake_client):
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    _seed_required_documents(fake_client, merchant_id)
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    response = client.post(
        f"/v1/admin/onboarding/{submission_id}/approve",
        headers=auth_headers(admin_id),
        json={"percentage_fee": "1.5", "flat_fee": "200", "label": "Negotiated rate"},
    )
    assert response.status_code == 200

    wallet = next(
        r
        for r in fake_client.table("ledger_accounts")._table.rows
        if r["merchant_id"] == merchant_id and r["purpose"] == "merchant_wallet"
    )
    assert wallet["balance"] == "0"

    rules = [r for r in fake_client.table("merchant_pricing_rules")._table.rows if r["merchant_id"] == merchant_id]
    assert len(rules) == 1
    assert rules[0]["percentage_fee"] == "1.5"
    assert rules[0]["flat_fee"] == "200"
    assert rules[0]["label"] == "Negotiated rate"
    assert rules[0]["created_by"] == str(admin_id)


def test_approval_without_custom_pricing_creates_no_merchant_specific_rule(fake_client):
    """No custom pricing entered -> no merchant-specific row is created;
    the merchant relies on whatever platform fallback rule (merchant_id
    IS NULL) is configured, same as every other merchant."""
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    _seed_required_documents(fake_client, merchant_id)
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    response = client.post(f"/v1/admin/onboarding/{submission_id}/approve", headers=auth_headers(admin_id))
    assert response.status_code == 200

    rules = [r for r in fake_client.table("merchant_pricing_rules")._table.rows if r["merchant_id"] == merchant_id]
    assert rules == []


def test_reject_sets_status_and_note_without_touching_merchant(fake_client):
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    response = client.post(
        f"/v1/admin/onboarding/{submission_id}/reject",
        headers=auth_headers(admin_id),
        json={"review_note": "Business licence photo is unreadable"},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["review_status"] == "REJECTED"
    assert body["review_note"] == "Business licence photo is unreadable"

    merchant = next(r for r in fake_client.table("merchants")._table.rows if r["id"] == merchant_id)
    assert merchant["status"] == "pending"  # untouched by reject
    assert merchant["kyc_status"] == "unverified"


def test_request_more_info(fake_client):
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    response = client.post(
        f"/v1/admin/onboarding/{submission_id}/request-more-info",
        headers=auth_headers(admin_id),
        json={"review_note": "Please upload a clearer TIN certificate"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["review_status"] == "INFO_REQUESTED"


def test_rejected_merchant_can_resubmit_and_reappears_pending(fake_client):
    user_id = uuid.uuid4()
    submitted = _submit_onboarding(user_id)
    merchant_id = submitted["merchant"]["id"]
    submission_id = next(
        r["id"] for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    client.post(f"/v1/admin/onboarding/{submission_id}/reject", headers=auth_headers(admin_id), json={})

    status_response = client.get("/v1/onboarding/status", headers=auth_headers(user_id))
    assert status_response.json()["data"]["next_path"] == "/onboarding"

    resubmit = client.post(
        "/v1/onboarding/merchant-account", headers=auth_headers(user_id), json=_valid_payload()
    )
    assert resubmit.status_code == 201

    status_after = client.get("/v1/onboarding/status", headers=auth_headers(user_id))
    assert status_after.json()["data"]["account_status"] == "PENDING_VERIFICATION"


# --- PATCH .../{merchant_id}/approve|reject|request-more-info ---------------


def test_approve_by_merchant_id(fake_client):
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]
    _seed_required_documents(fake_client, merchant_id)

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    response = client.patch(f"/v1/admin/onboarding/{merchant_id}/approve", headers=auth_headers(admin_id))
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["review_status"] == "VERIFIED"
    assert body["merchant_id"] == merchant_id

    merchant = next(r for r in fake_client.table("merchants")._table.rows if r["id"] == merchant_id)
    assert merchant["status"] == "active"


def test_reject_by_merchant_id(fake_client):
    submitted = _submit_onboarding(uuid.uuid4())
    merchant_id = submitted["merchant"]["id"]

    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    response = client.patch(
        f"/v1/admin/onboarding/{merchant_id}/reject",
        headers=auth_headers(admin_id),
        json={"review_note": "Unreadable licence"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["review_status"] == "REJECTED"


def test_patch_by_id_404_when_no_submission_for_merchant(fake_client):
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    response = client.patch(f"/v1/admin/onboarding/{uuid.uuid4()}/approve", headers=auth_headers(admin_id))
    assert response.status_code == 404
