"""Combined merchant signup — POST /v1/onboarding/signup — account
credentials + business details + mandatory NIDA + an optional TIN
certificate file, in one multipart/form-data call. The backend creates
the Supabase Auth user itself (service_role); the merchant is created
PENDING_VERIFICATION and is never auto-approved. CEO gets a signup
notification; the merchant approval/welcome email is NOT sent here (only
on Super Admin approval).
"""

import io
import logging
import uuid

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

client = TestClient(app)

_NIDA = "19900101-12345-12345-12"
_NIDA_DIGITS = "19900101123451234512"


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret-do-not-use")
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("CEO_EMAIL", "ceo@infinitypay.me")
    monkeypatch.setenv("APP_URL", "https://infinitypay.me")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakeResend:
    def __init__(self):
        self.calls: list[dict] = []

    def send(self, params: dict) -> dict:
        self.calls.append(params)
        return {"id": "resend-test-message-id"}


@pytest.fixture(autouse=True)
def fake_resend(monkeypatch):
    fake = _FakeResend()
    monkeypatch.setattr(resend.Emails, "send", fake.send)
    return fake


def _form(**overrides) -> dict:
    data = {
        "full_name": "Amani Mushi",
        "email": f"amani-{uuid.uuid4().hex[:8]}@example.com",
        "password": "Str0ng!pass",
        "contact_phone": "+255700000000",
        "nida_number": _NIDA,
        "business_name": "Amani Traders Ltd",
        "nature_of_business": "Online retail",
        "business_category": "Retail",
        "physical_address": "Mbezi",
        "region_city": "Dar es Salaam",
        "services_needed": ["PAYMENT_LINKS"],
        "accepted_terms": "true",
        "accepted_privacy": "true",
    }
    data.update(overrides)
    return data


def _post(form: dict, *, tin_certificate: tuple | None = None):
    files = {"tin_certificate": tin_certificate} if tin_certificate else None
    return client.post("/v1/onboarding/signup", data=form, files=files)


def _pdf(name: str = "tin.pdf") -> tuple:
    return (name, io.BytesIO(b"%PDF-1.4 fake tin certificate"), "application/pdf")


def test_signup_creates_user_merchant_and_pending_submission(fake_client):
    form = _form()
    response = _post(form)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["account_status"] == "PENDING_VERIFICATION"
    assert data["email_confirmation_required"] is True

    assert any(u.email == form["email"] for u in fake_client.auth.admin._users.values())

    merchant = next(m for m in fake_client.table("merchants")._table.rows if m["id"] == str(data["merchant_id"]))
    assert merchant["status"] == "pending"
    assert merchant["kyc_status"] == "unverified"
    assert merchant["contact_email"] == form["email"]
    membership = next(
        mu for mu in fake_client.table("merchant_users")._table.rows if mu["merchant_id"] == str(data["merchant_id"])
    )
    assert membership["role"] == "MERCHANT_ADMIN"
    submission = next(
        s for s in fake_client.table("onboarding_submissions")._table.rows if s["merchant_id"] == str(data["merchant_id"])
    )
    assert submission["review_status"] == "PENDING_VERIFICATION"
    assert submission["nida_number"] == _NIDA_DIGITS  # stored digits-only


def test_signup_stores_the_tin_certificate_document(fake_client):
    response = _post(_form(), tin_certificate=_pdf())
    assert response.status_code == 201, response.text
    merchant_id = response.json()["data"]["merchant_id"]

    docs = [d for d in fake_client.table("onboarding_documents")._table.rows if d["merchant_id"] == str(merchant_id)]
    assert len(docs) == 1
    assert docs[0]["document_type"] == "TIN_CERTIFICATE"
    assert docs[0]["upload_status"] == "UPLOADED"
    # landed in the private merchant-documents bucket, keyed by merchant id
    assert f"merchant-documents/{merchant_id}/TIN_CERTIFICATE.pdf" in fake_client._storage_objects


def test_signup_succeeds_without_a_tin_certificate(fake_client):
    response = _post(_form())
    assert response.status_code == 201
    merchant_id = response.json()["data"]["merchant_id"]
    docs = [d for d in fake_client.table("onboarding_documents")._table.rows if d["merchant_id"] == str(merchant_id)]
    assert docs == []


def test_signup_rejects_a_non_pdf_image_tin_certificate(fake_client):
    response = _post(_form(), tin_certificate=("tin.txt", io.BytesIO(b"not a real doc"), "text/plain"))
    assert response.status_code == 422
    # nothing created — the file type is checked before the auth user is made
    assert fake_client.table("merchants")._table.rows == []
    assert fake_client.auth.admin._users == {}


def test_signup_requires_nida(fake_client):
    response = _post(_form(nida_number=""))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "nida_required"
    assert fake_client.table("merchants")._table.rows == []


def test_signup_rejects_malformed_nida(fake_client):
    response = _post(_form(nida_number="12345"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "nida_invalid"
    assert fake_client.table("merchants")._table.rows == []


def test_signup_duplicate_email_conflicts(fake_client):
    form = _form()
    assert _post(form).status_code == 201
    second = _post(_form(email=form["email"]))
    assert second.status_code == 409
    assert len(fake_client.table("merchants")._table.rows) == 1


def test_signup_notifies_ceo_with_masked_nida_not_full(fake_client, fake_resend):
    _post(_form())

    ceo_calls = [c for c in fake_resend.calls if c["to"] == ["ceo@infinitypay.me"]]
    assert len(ceo_calls) == 1
    ceo = ceo_calls[0]
    assert ceo["subject"] == "New merchant signup submitted"
    # EMAIL_FROM/EMAIL_REPLY_TO aren't overridden by this test, so these
    # reflect settings.py's actual defaults.
    assert ceo["from"] == "InfinityPay <notification@infinitypay.me>"
    assert ceo["reply_to"] == "info@infinitypay.me"
    assert "4512" in ceo["html"]
    assert _NIDA_DIGITS not in ceo["html"]
    assert _NIDA not in ceo["html"]
    assert "collected offline" in ceo["html"].lower()


def test_signup_does_not_send_approval_email(fake_client, fake_resend):
    _post(_form())
    approval_calls = [c for c in fake_resend.calls if c["subject"] == "Your InfinityPay account has been approved"]
    assert approval_calls == []
    verify_calls = [c for c in fake_resend.calls if c["subject"] == "Confirm your email address"]
    assert len(verify_calls) == 1
    assert verify_calls[0]["to"] != ["ceo@infinitypay.me"]


def test_signup_does_not_log_full_nida(fake_client, caplog):
    with caplog.at_level(logging.DEBUG):
        _post(_form())
    assert _NIDA_DIGITS not in caplog.text
    assert _NIDA not in caplog.text


def test_signup_is_rate_limited(fake_client):
    from app.core.rate_limit import _limiter

    for _ in range(5):
        _limiter.check("merchant_signup:testclient", limit=5, window_seconds=300)

    response = _post(_form())
    assert response.status_code == 429


# --- New Get Started fields: legal name / business email+phone / notes ------


def test_signup_saves_legal_business_name_and_business_contact_details(fake_client):
    form = _form(
        legal_business_name="Amani Traders Company Limited",
        business_email="hello@amanitraders.co.tz",
        business_phone="+255711222333",
        notes="Also sells online via Instagram.",
    )
    response = _post(form)
    assert response.status_code == 201, response.text
    merchant_id = response.json()["data"]["merchant_id"]

    merchant = next(m for m in fake_client.table("merchants")._table.rows if m["id"] == str(merchant_id))
    assert merchant["legal_name"] == "Amani Traders Company Limited"
    # Business email/phone are distinct from the owner's own login
    # email/contact_phone — never silently overwritten by them.
    assert merchant["contact_email"] == "hello@amanitraders.co.tz"
    assert merchant["contact_email"] != form["email"]
    assert merchant["contact_phone"] == "255711222333"

    submission = next(
        s for s in fake_client.table("onboarding_submissions")._table.rows if s["merchant_id"] == str(merchant_id)
    )
    assert submission["notes"] == "Also sells online via Instagram."


def test_signup_falls_back_to_owner_email_and_phone_when_business_ones_are_blank(fake_client):
    form = _form()  # no legal_business_name/business_email/business_phone/notes
    response = _post(form)
    assert response.status_code == 201, response.text
    merchant_id = response.json()["data"]["merchant_id"]

    merchant = next(m for m in fake_client.table("merchants")._table.rows if m["id"] == str(merchant_id))
    assert merchant["legal_name"] is None
    assert merchant["contact_email"] == form["email"]
    assert merchant["contact_phone"] == "255700000000"

    submission = next(
        s for s in fake_client.table("onboarding_submissions")._table.rows if s["merchant_id"] == str(merchant_id)
    )
    assert submission["notes"] is None


def test_signup_ceo_notification_includes_tin_when_provided(fake_client, fake_resend):
    _post(_form(tin_number="123-456-789"))

    ceo_calls = [c for c in fake_resend.calls if c["to"] == ["ceo@infinitypay.me"]]
    assert len(ceo_calls) == 1
    assert "123-456-789" in ceo_calls[0]["html"]


# --- Fields dropped from the Get Started form ---------------------------------


def test_signup_succeeds_without_address_region_or_services(fake_client):
    """The Get Started form no longer collects business address, region/city
    or "services needed", so the endpoint must accept a payload that omits
    all three. onboarding_submissions.physical_address/region_city are
    NOT NULL columns, so they have to land as "" rather than null, and
    services_needed as an empty array."""
    form = _form()
    for dropped in ("physical_address", "region_city", "services_needed"):
        form.pop(dropped)

    response = _post(form)

    assert response.status_code == 201, response.text
    merchant_id = str(response.json()["data"]["merchant_id"])
    submission = next(
        r for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )
    # Empty string, never None — the column is NOT NULL.
    assert submission["physical_address"] == ""
    assert submission["region_city"] == ""
    assert submission["services_needed"] == []


def test_signup_still_accepts_address_region_and_services_when_sent(fake_client):
    """The older two-step /onboarding form still sends all three, so making
    them optional must not stop them being stored when they are supplied."""
    response = _post(_form())

    assert response.status_code == 201, response.text
    merchant_id = str(response.json()["data"]["merchant_id"])
    submission = next(
        r for r in fake_client.table("onboarding_submissions")._table.rows if r["merchant_id"] == merchant_id
    )
    assert submission["physical_address"] == "Mbezi"
    assert submission["region_city"] == "Dar es Salaam"
    assert submission["services_needed"] == ["PAYMENT_LINKS"]
