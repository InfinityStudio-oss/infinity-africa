"""POST /v1/auth/forgot-password — app/routers/auth_actions.py. The whole
point of this endpoint is that it must be indistinguishable from the
outside whether the email matched a real account, whether Supabase itself
errored, or whether Resend rejected the send — every path returns the
exact same response.
"""

import re
import uuid

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import TEST_JWT_SECRET

client = TestClient(app)

_GENERIC_MESSAGE = "If an account exists, we've sent password reset instructions."


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
    fake = _FakeResend()
    monkeypatch.setattr(resend.Emails, "send", fake.send)
    return fake


def test_forgot_password_returns_the_generic_message_for_a_registered_email(fake_client, fake_resend):
    user_id = uuid.uuid4()
    fake_client.seed_auth_user(user_id, email="amina@example.com", full_name="Amina")

    response = client.post("/v1/auth/forgot-password", json={"email": "amina@example.com"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["message"] == _GENERIC_MESSAGE
    assert len(fake_resend.calls) == 1
    assert fake_resend.calls[0]["to"] == ["amina@example.com"]


def test_forgot_password_returns_the_same_generic_message_for_an_unregistered_email(fake_client, fake_resend):
    """No account exists for this email at all — must look identical to
    the registered-email case from the outside (account enumeration
    prevention), and must not attempt a send."""
    response = client.post("/v1/auth/forgot-password", json={"email": "nobody@example.com"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["message"] == _GENERIC_MESSAGE
    assert len(fake_resend.calls) == 0


def test_forgot_password_returns_the_same_generic_message_when_email_delivery_fails(fake_client, fake_resend):
    """A registered email, but Resend itself rejects the send — still the
    exact same response; the failure is only visible in server-side logs
    and the email_deliveries table, never in the HTTP response."""
    user_id = uuid.uuid4()
    fake_client.seed_auth_user(user_id, email="amina@example.com", full_name="Amina")
    fake_resend.should_fail = True

    response = client.post("/v1/auth/forgot-password", json={"email": "amina@example.com"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["message"] == _GENERIC_MESSAGE


def test_forgot_password_uses_the_merchant_redirect_path_by_default(fake_client, fake_resend):
    user_id = uuid.uuid4()
    fake_client.seed_auth_user(user_id, email="amina@example.com", full_name="Amina")

    response = client.post("/v1/auth/forgot-password", json={"email": "amina@example.com"})

    assert response.status_code == 200
    assert "/dashboard/reset-password" in fake_resend.calls[0]["html"]


def test_forgot_password_accepts_the_admin_redirect_path(fake_client, fake_resend):
    user_id = uuid.uuid4()
    fake_client.seed_auth_user(user_id, email="admin@example.com", full_name="Admin")

    response = client.post(
        "/v1/auth/forgot-password",
        json={"email": "admin@example.com", "redirect_path": "/admin-login/reset-password"},
    )

    assert response.status_code == 200
    assert "/admin-login/reset-password" in fake_resend.calls[0]["html"]


def test_forgot_password_rejects_an_arbitrary_redirect_path(fake_client, fake_resend):
    """redirect_path is a closed enum, not a free-text URL — never let a
    caller redirect a real Supabase recovery link somewhere else."""
    response = client.post(
        "/v1/auth/forgot-password",
        json={"email": "amina@example.com", "redirect_path": "https://evil.example.com"},
    )
    assert response.status_code == 422


def test_forgot_password_email_uses_info_as_the_help_contact(fake_client, fake_resend):
    user_id = uuid.uuid4()
    fake_client.seed_auth_user(user_id, email="amina@example.com", full_name="Amina")

    response = client.post("/v1/auth/forgot-password", json={"email": "amina@example.com"})

    assert response.status_code == 200
    assert "info@infinitypay.me" in fake_resend.calls[0]["html"]
    assert "support@infinitypay.me" not in fake_resend.calls[0]["html"]


def test_forgot_password_does_not_log_the_reset_token_or_link(fake_client, fake_resend):
    user_id = uuid.uuid4()
    fake_client.seed_auth_user(user_id, email="amina@example.com", full_name="Amina")

    client.post("/v1/auth/forgot-password", json={"email": "amina@example.com"})

    delivery = fake_client.table("email_deliveries")._table.rows[-1]
    serialized = str(delivery)
    assert "token=" not in serialized
    assert "action_link" not in serialized


def test_forgot_password_button_and_fallback_link_are_identical(fake_client, fake_resend):
    """_cta_button renders the same url in both the button's href and the
    plain-text "Or copy this link" fallback — the link must never be
    modified, truncated, or re-escaped differently between the two."""
    user_id = uuid.uuid4()
    fake_client.seed_auth_user(user_id, email="amina@example.com", full_name="Amina")

    client.post("/v1/auth/forgot-password", json={"email": "amina@example.com"})

    html = fake_resend.calls[0]["html"]
    hrefs = re.findall(r'href="([^"]+)"', html)
    reset_hrefs = [h for h in hrefs if "token_hash=" in h]
    assert len(reset_hrefs) == 2  # the button, and the plain-text fallback
    assert reset_hrefs[0] == reset_hrefs[1]


def test_forgot_password_redirect_to_matches_the_production_reset_page(fake_client, fake_resend):
    """The recovery link's redirect_to must point at the exact route the
    frontend serves this on — a mismatch here is a real link Supabase
    itself would refuse (unlisted redirect URL), or would land the
    merchant on the wrong page entirely."""
    settings = get_settings()
    user_id = uuid.uuid4()
    fake_client.seed_auth_user(user_id, email="amina@example.com", full_name="Amina")

    client.post("/v1/auth/forgot-password", json={"email": "amina@example.com"})

    html = fake_resend.calls[0]["html"]
    assert f'href="{settings.app_url}/dashboard/reset-password?token_hash=' in html


# --- POST /v1/auth/resend-verification ---------------------------------
#
# The way back for a merchant who never received the signup link. Five
# businesses in production answered that by registering again under a
# second address, which is where the duplicate merchant records came
# from; once duplicate signups started being refused, two more were left
# with no way in at all.

_GENERIC_VERIFICATION_MESSAGE = (
    "If that account still needs verification, we've sent a fresh link. "
    "Check your inbox and spam folder."
)


@pytest.fixture
def auth_lookup(monkeypatch):
    """Stands in for the Supabase admin user lookup the service does over
    HTTP, driving the real _unverified_auth_user rather than replacing
    it - the matching and the verified check are the parts worth
    testing."""

    class _Lookup:
        def __init__(self):
            self.users: list[dict] = []
            self.should_fail = False
            self.params: list[dict] = []

        def get(self, url, **kwargs):
            self.params.append(kwargs.get("params") or {})
            if self.should_fail:
                raise Exception("Supabase admin API unreachable")  # noqa: TRY002

            class _Response:
                @staticmethod
                def raise_for_status():
                    return None

                @staticmethod
                def json():
                    return {"users": lookup.users}

            return _Response()

    lookup = _Lookup()
    monkeypatch.setattr("app.services.email.httpx.get", lookup.get)
    return lookup


def test_resend_verification_sends_a_fresh_link_to_an_unverified_account(
    fake_client, fake_resend, auth_lookup
):
    fake_client.seed_auth_user(uuid.uuid4(), email="amina@example.com", full_name="Amina")
    auth_lookup.users = [{"email": "amina@example.com", "email_confirmed_at": None}]

    response = client.post("/v1/auth/resend-verification", json={"email": "amina@example.com"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["message"] == _GENERIC_VERIFICATION_MESSAGE
    assert len(fake_resend.calls) == 1
    assert fake_resend.calls[0]["to"] == ["amina@example.com"]


def test_resend_verification_refuses_an_account_that_is_already_verified(
    fake_client, fake_resend, auth_lookup
):
    """The security of this endpoint rests here.

    generate_link("magiclink") mints a working sign-in link for any
    existing account, and InfinityPay has no magic-link login. Without
    the verified check, knowing a merchant's email address would be
    enough to have a link to their dashboard mailed to them.
    """
    fake_client.seed_auth_user(uuid.uuid4(), email="amina@example.com", full_name="Amina")
    auth_lookup.users = [
        {"email": "amina@example.com", "email_confirmed_at": "2026-10-01T09:00:00Z"}
    ]

    response = client.post("/v1/auth/resend-verification", json={"email": "amina@example.com"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["message"] == _GENERIC_VERIFICATION_MESSAGE
    assert fake_resend.calls == [], "a verified account must never be sent a sign-in link"


def test_resend_verification_says_the_same_thing_for_an_unknown_address(
    fake_client, fake_resend, auth_lookup
):
    auth_lookup.users = []

    response = client.post("/v1/auth/resend-verification", json={"email": "nobody@example.com"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["message"] == _GENERIC_VERIFICATION_MESSAGE
    assert fake_resend.calls == []


def test_resend_verification_requires_an_exact_address_match(fake_client, fake_resend, auth_lookup):
    """Supabase's `filter` is a partial match, so the lookup can come back
    with a neighbour of the address asked for. Mailing that neighbour a
    sign-in link would be the same bug as skipping the check entirely."""
    fake_client.seed_auth_user(uuid.uuid4(), email="amina@example.com", full_name="Amina")
    auth_lookup.users = [{"email": "amina.k@example.com", "email_confirmed_at": None}]

    response = client.post("/v1/auth/resend-verification", json={"email": "amina@example.com"})

    assert response.status_code == 200
    assert fake_resend.calls == []


def test_resend_verification_says_the_same_thing_when_the_lookup_fails(
    fake_client, fake_resend, auth_lookup
):
    fake_client.seed_auth_user(uuid.uuid4(), email="amina@example.com", full_name="Amina")
    auth_lookup.should_fail = True

    response = client.post("/v1/auth/resend-verification", json={"email": "amina@example.com"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["message"] == _GENERIC_VERIFICATION_MESSAGE
    assert fake_resend.calls == []


def test_resend_verification_link_points_at_onboarding(fake_client, fake_resend, auth_lookup):
    settings = get_settings()
    fake_client.seed_auth_user(uuid.uuid4(), email="amina@example.com", full_name="Amina")
    auth_lookup.users = [{"email": "amina@example.com", "email_confirmed_at": None}]

    client.post("/v1/auth/resend-verification", json={"email": "amina@example.com"})

    html = fake_resend.calls[0]["html"]
    assert f'href="{settings.app_url}/auth/callback?next=/onboarding&token_hash=' in html


def test_resend_verification_gives_the_caller_no_say_in_the_destination(
    fake_client, fake_resend, auth_lookup
):
    """There is no redirect_path field at all. A caller who sends one is
    ignored rather than obeyed - one fewer place an open redirect can
    appear."""
    settings = get_settings()
    fake_client.seed_auth_user(uuid.uuid4(), email="amina@example.com", full_name="Amina")
    auth_lookup.users = [{"email": "amina@example.com", "email_confirmed_at": None}]

    response = client.post(
        "/v1/auth/resend-verification",
        json={"email": "amina@example.com", "redirect_path": "https://evil.example.com"},
    )

    assert response.status_code == 200
    html = fake_resend.calls[0]["html"]
    assert "evil.example.com" not in html
    assert f'href="{settings.app_url}/auth/callback?next=/onboarding' in html


def test_resend_verification_does_not_log_the_token_or_link(fake_client, fake_resend, auth_lookup):
    fake_client.seed_auth_user(uuid.uuid4(), email="amina@example.com", full_name="Amina")
    auth_lookup.users = [{"email": "amina@example.com", "email_confirmed_at": None}]

    client.post("/v1/auth/resend-verification", json={"email": "amina@example.com"})

    delivery = fake_client.table("email_deliveries")._table.rows[-1]
    serialized = str(delivery)
    assert "token=" not in serialized
    assert "action_link" not in serialized


def test_resend_verification_rejects_a_malformed_address(fake_client, fake_resend, auth_lookup):
    response = client.post("/v1/auth/resend-verification", json={"email": "not-an-email"})

    assert response.status_code == 422
    assert fake_resend.calls == []
