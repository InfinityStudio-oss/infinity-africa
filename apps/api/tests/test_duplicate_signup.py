"""One business, one account.

From production, 2026-10-16: five businesses held eleven accounts between
them, and every case was the same accident - a merchant mistyped their
email on the Get Started form, never received the verification link, and
signed up again with the address spelled right. KILUNGULE's abandoned
account sat next to one carrying 1409 collections; BEACH WiFi had three.

They signed up again because it was the only thing the product allowed:
the "check your email" screen offers "Resend verification email", which
resends to the address that was already wrong.

The tests that matter most here are the ones in the other direction. A
guard on the signup form that turns away a real merchant costs far more
than a duplicate account costs to clean up, so much of what follows is
about who must still get through.
"""

import uuid

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.duplicate_signup import find_existing_application, mask_email

client = TestClient(app)

_NIDA = "19900101-12345-12345-12"
_NIDA_DIGITS = "19900101123451234512"
_OTHER_NIDA = "19880202-54321-54321-21"


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret-do-not-use")
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("CEO_EMAIL", "ceo@infinitypay.me")
    monkeypatch.setenv("APP_URL", "https://infinitypay.me")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fake_resend(monkeypatch):
    monkeypatch.setattr(resend.Emails, "send", lambda params: {"id": "test"})


def _form(**overrides) -> dict:
    data = {
        "full_name": "Hussein Said",
        "email": f"hussein-{uuid.uuid4().hex[:8]}@example.com",
        "password": "Str0ng!pass",
        "contact_phone": "+255766771207",
        "nida_number": _NIDA,
        "business_name": "BEACH WiFi",
        "nature_of_business": "Internet service",
        "business_category": "Telecom",
        "accepted_terms": "true",
        "accepted_privacy": "true",
    }
    data.update(overrides)
    return data


def _post(form: dict):
    return client.post("/v1/onboarding/signup", data=form)


def _merchants(fake_client):
    return fake_client.table("merchants")._table.rows


# --- the accident this exists to stop ---------------------------------------


def test_the_same_business_cannot_create_a_second_account(fake_client):
    """The production case exactly: same person, same NIDA, email spelled
    differently the second time."""
    assert _post(_form(email="huseinsaid211@gmail.com")).status_code == 201

    second = _post(_form(email="husseinsaid211@gmail.com"))

    assert second.status_code == 409
    assert len(_merchants(fake_client)) == 1, "a second BEACH WiFi was created"


def test_a_third_attempt_is_refused_too(fake_client):
    """BEACH WiFi reached three accounts, not two."""
    _post(_form(email="huseinsaid211@gmail.com"))
    _post(_form(email="husseinsaid211@gmail.com"))
    _post(_form(email="hussensaid211@gmail.com"))

    assert len(_merchants(fake_client)) == 1


def test_a_different_phone_with_the_same_nida_is_still_caught(fake_client):
    """ENZOH WI-FI's two accounts used two different phone numbers and one
    NIDA. Matching on phone alone would have missed it, which is why NIDA
    is the primary key here."""
    assert _post(_form(contact_phone="+255629674047")).status_code == 201

    second = _post(_form(contact_phone="+255712999888"))

    assert second.status_code == 409
    assert len(_merchants(fake_client)) == 1


def test_the_phone_is_still_a_fallback_when_no_nida_is_on_record(fake_client):
    """Four of the 60 live merchants have no NIDA on file, so phone cannot
    be dropped as a key. NIDA is mandatory at the API edge, so the only
    way to be in that state is a merchant row with no submission behind
    it - which is exactly where those four sit."""
    assert _post(_form()).status_code == 201
    fake_client.table("onboarding_submissions")._table.rows.clear()

    existing = find_existing_application(
        fake_client, nida=_NIDA_DIGITS, phone="255766771207"
    )

    assert existing is not None
    assert existing["business_name"] == "BEACH WiFi"


def test_no_auth_user_is_left_behind_when_a_duplicate_is_refused(fake_client):
    """The guard runs before create_user on purpose. Creating the auth
    user first and failing after would burn the email address - the real
    signup would then hit "already registered" and the merchant would be
    stuck for good."""
    _post(_form(email="first@example.com"))
    before = len(fake_client.auth.admin._users)

    _post(_form(email="second@example.com"))

    assert len(fake_client.auth.admin._users) == before


def test_the_nida_is_compared_after_normalisation(fake_client):
    """Dashes and spaces are accepted on the form and stripped before
    storage. A second signup typed in a different grouping is the same
    identity and must still be caught."""
    assert _post(_form(nida_number="19900101-12345-12345-12")).status_code == 201

    second = _post(_form(nida_number="1990 0101 12345 12345 12"))

    assert second.status_code == 409


# --- who must still get through ---------------------------------------------


def test_an_unrelated_business_signs_up_normally(fake_client):
    """The ordinary case. Nothing about this guard may touch it."""
    assert _post(_form()).status_code == 201

    second = _post(
        _form(
            business_name="GEO_NETWORK",
            nida_number=_OTHER_NIDA,
            contact_phone="+255768486279",
        )
    )

    assert second.status_code == 201
    assert len(_merchants(fake_client)) == 2


def test_a_lookup_failure_lets_the_signup_through(fake_client):
    """Fails open, deliberately. A duplicate account is an afternoon of
    cleanup; a signup form that rejects real merchants because a lookup
    hiccuped is lost business we never hear about."""

    class _Broken:
        def table(self, _name):
            raise RuntimeError("supabase unreachable")

    assert find_existing_application(_Broken(), nida=_NIDA_DIGITS, phone="255766771207") is None


def test_the_oldest_application_is_the_one_returned(fake_client):
    """The original is the account whose address should be corrected. If
    the lookup returned the newest instead, support would be told to fix
    the stray and leave the real one broken."""
    first = {
        "id": str(uuid.uuid4()),
        "business_name": "BEACH WiFi",
        "merchant_code": "27141957",
        "contact_email": "huseinsaid211@gmail.com",
        "contact_phone": "255766771207",
        "created_at": "2026-10-15T20:50:00+00:00",
    }
    second = {
        **first,
        "id": str(uuid.uuid4()),
        "merchant_code": "27042291",
        "contact_email": "husseinsaid211@gmail.com",
        "created_at": "2026-10-16T04:37:00+00:00",
    }
    fake_client.seed("merchants", second)
    fake_client.seed("merchants", first)

    existing = find_existing_application(fake_client, nida="", phone="255766771207")

    assert existing["merchant_code"] == "27141957"


# --- what the merchant is told ----------------------------------------------


def test_the_message_names_the_business_code_and_what_to_do(fake_client):
    """"You have already applied" on its own leaves them stuck, which is
    how this mess started. They need the code support will ask for and
    the instruction not to try again."""
    _post(_form(email="huseinsaid211@gmail.com"))

    body = _post(_form(email="husseinsaid211@gmail.com")).json()
    message = body["error"]["message"]
    code = _merchants(fake_client)[0]["merchant_code"]

    assert code in message
    assert "support" in message.lower()
    assert "second account" in message.lower()


def test_the_existing_address_is_masked_not_echoed(fake_client):
    """The response is unauthenticated: anyone who guesses a NIDA number
    gets this message. A masked hint is enough for the person who just
    mistyped their own address and not enough to harvest one."""
    _post(_form(email="huseinsaid211@gmail.com"))

    message = _post(_form(email="husseinsaid211@gmail.com")).json()["error"]["message"]

    assert "huseinsaid211@gmail.com" not in message
    assert "@gmail.com" in message


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("husseinsaid211@gmail.com", "h••••••••••••1@gmail.com"),
        ("ab@gmail.com", "a•@gmail.com"),
        ("a@gmail.com", "a•@gmail.com"),
        (None, "•••"),
        ("not-an-email", "•••"),
    ],
)
def test_mask_email_keeps_the_domain_readable(email, expected):
    """The domain is where the typo usually is - KILUNGULE's dead account
    was on @kilungulesupe... when they meant @gmail.com - so masking the
    domain as well would hide the one part that helps them recognise it."""
    assert mask_email(email) == expected
