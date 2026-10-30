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
    # Both strays have an owner who never verified - that is what they
    # were. Seeded explicitly now, because an application only blocks a
    # new signup if its owner never confirmed their email.
    for merchant, when in ((first, "2026-10-15T20:50:00+00:00"), (second, "2026-10-16T04:37:00+00:00")):
        user_id = uuid.uuid4()
        fake_client.seed_auth_user(user_id, email=merchant["contact_email"], full_name="Hussein Said")
        fake_client.seed(
            "merchant_users",
            {
                "merchant_id": merchant["id"],
                "user_id": str(user_id),
                "role": "MERCHANT_ADMIN",
                "status": "active",
                "created_at": when,
            },
        )

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


# --- one person, two businesses ---------------------------------------------
#
# The other direction, and the expensive one. Everything above is about
# an accident that leaves an abandoned account behind; none of it should
# touch a merchant who is trading and wants to open something new.


def _verify(fake_client, email: str) -> None:
    """Confirm the address on the account that was just created, the way
    clicking the emailed link does."""
    for user in fake_client.auth.admin._users.values():
        if user.email == email:
            user.email_confirmed_at = "2026-10-22T09:00:00+00:00"
            return
    raise AssertionError(f"no auth user for {email}")


def test_a_verified_merchant_can_open_a_second_business(fake_client):
    """2026-10-30, in production: a merchant carrying 19,968 payments was
    refused a second account for a separate billing system, and told he
    had already applied.

    He had - with the same national ID, because it is his. Identity alone
    cannot tell "this person already applied and never got in" apart from
    "this person runs two businesses", and only the first is the accident
    this guard exists for.
    """
    assert _post(_form(email="benny@example.com", business_name="BennyWiFi")).status_code == 201
    _verify(fake_client, "benny@example.com")

    second = _post(
        _form(email="benny-billing@example.com", business_name="Benny Billing", contact_phone="+255766771299")
    )

    assert second.status_code == 201, second.text
    assert len(_merchants(fake_client)) == 2


def test_the_second_business_is_allowed_even_on_the_very_same_phone(fake_client):
    """Phone is only a fallback key, and it is a weaker one than NIDA: a
    business owner may well give the same number twice. A verified first
    account must not block on it either."""
    assert _post(_form(email="benny@example.com")).status_code == 201
    _verify(fake_client, "benny@example.com")

    second = _post(_form(email="benny-two@example.com", business_name="Benny Billing"))

    assert second.status_code == 201, second.text


def test_an_unverified_first_account_still_blocks(fake_client):
    """The guard has not been turned off. Same identity, first account
    never verified - still refused, exactly as before."""
    assert _post(_form(email="huseinsaid211@gmail.com")).status_code == 201

    second = _post(_form(email="husseinsaid211@gmail.com"))

    assert second.status_code == 409
    assert len(_merchants(fake_client)) == 1


def test_the_unverified_one_is_found_even_when_a_verified_one_is_older(fake_client):
    """A merchant with a real account AND an abandoned one must still be
    pointed at the abandoned one - that is the row whose email support
    corrects. Being verified elsewhere does not make the stray invisible.
    """
    assert _post(_form(email="benny@example.com", business_name="BennyWiFi")).status_code == 201
    _verify(fake_client, "benny@example.com")
    assert _post(_form(email="bennu@example.con", business_name="Benny Billing")).status_code == 201

    third = _post(_form(email="benny-billing@example.com", business_name="Benny Billing"))

    assert third.status_code == 409
    assert "bennu@example.con"[0] in third.json()["error"]["message"]


def test_a_merchant_row_with_no_owner_never_blocks_a_signup(fake_client):
    """An account with no active owner cannot be verified by anyone and
    cannot be corrected by support either - correct_merchant_contact_email
    raises on exactly this state. Refusing because of one would hand a
    merchant a message telling them to contact support about something
    support cannot fix, which is the dead end this whole area has been
    spent getting people out of.
    """
    fake_client.seed(
        "merchants",
        {
            "id": str(uuid.uuid4()),
            "business_name": "Ownerless",
            "merchant_code": "27000001",
            "contact_email": "nobody@example.com",
            "contact_phone": "255766771207",
            "created_at": "2026-09-01T00:00:00+00:00",
        },
    )

    assert find_existing_application(fake_client, nida="", phone="255766771207") is None


# --- what the reviewer is shown ---------------------------------------------


def test_the_review_screen_is_told_about_the_owners_other_businesses(fake_client):
    """Signup no longer refuses a second business, so the judgement moves
    to the person approving it. They cannot judge what they are not
    shown."""
    from app.services.duplicate_signup import identity_siblings

    assert _post(_form(email="benny@example.com", business_name="BennyWiFi")).status_code == 201
    _verify(fake_client, "benny@example.com")
    assert _post(
        _form(email="benny-billing@example.com", business_name="Benny Billing")
    ).status_code == 201

    merchants = _merchants(fake_client)
    index = identity_siblings(fake_client)

    assert len(merchants) == 2
    for merchant in merchants:
        others = index[str(merchant["id"])]
        assert [o["business_name"] for o in others] == [
            m["business_name"] for m in merchants if m["id"] != merchant["id"]
        ]


def test_a_merchant_with_no_sibling_is_absent_from_the_index(fake_client):
    """Almost every application. The badge must not appear on them."""
    from app.services.duplicate_signup import identity_siblings

    assert _post(_form()).status_code == 201

    assert identity_siblings(fake_client) == {}


def test_the_index_uses_the_same_keys_the_guard_does(fake_client):
    """NIDA first, phone only as the fallback. If the screen grouped
    people differently from the rule, the two would disagree about who is
    the same person."""
    from app.services.duplicate_signup import identity_siblings

    assert _post(_form(email="a@example.com", business_name="One")).status_code == 201
    _verify(fake_client, "a@example.com")
    # Same person, same NIDA, different phone — still one owner.
    assert _post(
        _form(email="b@example.com", business_name="Two", contact_phone="+255712999888")
    ).status_code == 201

    index = identity_siblings(fake_client)

    assert len(index) == 2, "a different phone must not split one owner into two"
