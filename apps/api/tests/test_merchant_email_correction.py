"""Fixing a mistyped signup email instead of the merchant signing up again.

Signup now refuses a second application for an identity that already has
one (test_duplicate_signup.py). That refusal is only fair if there is some
way to correct the address that was wrong - otherwise a merchant who
mistypes their email is permanently stuck, which is worse than the
duplicate accounts the guard exists to prevent. This is that way.

It is a Super Admin action rather than a self-service one on purpose. A
merchant who cannot receive mail at the address on their account has only
their password left to prove who they are, and an unauthenticated "change
the email on this account" endpoint is not something a live payments
platform should grow. At 60 merchants every signup is approved by hand
anyway.

The sharp edge here is the new address being left *unverified*: a Super
Admin typo in the correction must not hand the account to whoever happens
to own the mistyped address.
"""

import uuid

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("APP_URL", "https://infinitypay.me")
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


def _setup(fake_client, *, email="huseinsaid211@gmail.com"):
    """A merchant stuck exactly where BEACH WiFi was: an account on a
    mistyped address, with an unverified auth user behind it."""
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    merchant = create_merchant(
        fake_client, business_name="BEACH WiFi", contact_email=email
    )
    owner_id = uuid.uuid4()
    make_merchant_member(
        fake_client, uuid.UUID(merchant["id"]), owner_id, "MERCHANT_ADMIN"
    )
    fake_client.auth.admin.seed_user(str(owner_id), email=email, full_name="Hussein Said")
    return merchant, owner_id, auth_headers(admin_id)


def _correct(merchant, headers, email):
    return client.post(
        f"/v1/admin/merchants/{merchant['id']}/correct-contact-email",
        json={"email": email},
        headers=headers,
    )


# --- what it is for ---------------------------------------------------------


def test_the_address_is_corrected_on_the_merchant_and_the_login(fake_client):
    """Both have to move together. Changing only merchants.contact_email
    would fix what the Super Admin sees and leave the merchant unable to
    sign in; changing only the auth user would leave support looking at
    the wrong address."""
    merchant, owner_id, headers = _setup(fake_client)

    response = _correct(merchant, headers, "hussensaid211@gmail.com")

    assert response.status_code == 200
    row = fake_client.table("merchants")._table.rows[0]
    assert row["contact_email"] == "hussensaid211@gmail.com"
    assert fake_client.auth.admin._users[str(owner_id)].email == "hussensaid211@gmail.com"


def test_a_fresh_verification_link_goes_to_the_new_address(fake_client, fake_resend):
    """The whole reason they were stuck is that the link kept going to the
    wrong address."""
    merchant, _owner_id, headers = _setup(fake_client)

    _correct(merchant, headers, "hussensaid211@gmail.com")

    sent = [c for c in fake_resend.calls if c["to"] == ["hussensaid211@gmail.com"]]
    assert len(sent) == 1
    assert "confirm" in sent[0]["subject"].lower()


def test_the_link_points_at_our_own_callback(fake_client, fake_resend):
    """Same reason as signup (test_merchant_signup.py): Supabase's
    action_link ignores redirect_to and returns the token in a URL
    fragment the server cannot read, so the merchant lands on the public
    homepage. For a correction that would be especially cruel - this link
    is the entire reason they were contacted."""
    merchant, _owner_id, headers = _setup(fake_client)

    _correct(merchant, headers, "hussensaid211@gmail.com")

    html = next(c for c in fake_resend.calls if c["to"] == ["hussensaid211@gmail.com"])["html"]

    assert "/auth/callback?next=/dashboard/overview" in html
    assert "token_hash=" in html
    assert "type=magiclink" in html
    assert "fake.supabase.test" not in html


def test_the_new_address_is_left_unverified(fake_client):
    """The merchant still has to click the link. If the correction
    confirmed the address outright, a Super Admin typo would hand the
    account to whoever owns the mistyped address - and nothing would
    reveal it, because the merchant would simply still be unable to sign
    in."""
    merchant, owner_id, headers = _setup(fake_client)

    _correct(merchant, headers, "hussensaid211@gmail.com")

    assert fake_client.auth.admin._users[str(owner_id)].email_confirmed_at is None


def test_the_address_still_changes_when_the_email_cannot_be_sent(
    fake_client, fake_resend
):
    """Best-effort, like signup's own verification email. The address is
    already changed by the time the mail goes out, so a Resend outage must
    not report failure and send the Super Admin round again."""
    merchant, _owner_id, headers = _setup(fake_client)
    fake_resend.should_fail = True

    response = _correct(merchant, headers, "hussensaid211@gmail.com")

    assert response.status_code == 200
    assert (
        fake_client.table("merchants")._table.rows[0]["contact_email"]
        == "hussensaid211@gmail.com"
    )


# --- the cases it must refuse -----------------------------------------------


def test_an_address_already_in_use_is_refused(fake_client):
    """The one case where going ahead does real damage: two merchants
    fighting over one login."""
    merchant, _owner_id, headers = _setup(fake_client)
    fake_client.auth.admin.seed_user(str(uuid.uuid4()), email="taken@example.com")

    response = _correct(merchant, headers, "taken@example.com")

    assert response.status_code == 409
    assert fake_client.table("merchants")._table.rows[0]["contact_email"] == (
        "huseinsaid211@gmail.com"
    )


def test_a_malformed_address_is_refused(fake_client):
    merchant, _owner_id, headers = _setup(fake_client)

    assert _correct(merchant, headers, "not-an-email").status_code == 422


def test_an_unknown_merchant_is_a_404(fake_client):
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)

    response = client.post(
        f"/v1/admin/merchants/{uuid.uuid4()}/correct-contact-email",
        json={"email": "someone@example.com"},
        headers=auth_headers(admin_id),
    )

    assert response.status_code == 404


# --- who may call it --------------------------------------------------------


def test_a_merchant_cannot_change_their_own_login_this_way(fake_client):
    """This endpoint changes a login without proving ownership of either
    address. Super Admin only - a merchant reaching it would be an account
    takeover primitive."""
    merchant, owner_id, _headers = _setup(fake_client)

    response = _correct(merchant, auth_headers(owner_id), "attacker@example.com")

    assert response.status_code == 403
    assert fake_client.auth.admin._users[str(owner_id)].email == "huseinsaid211@gmail.com"


def test_an_anonymous_caller_is_rejected(fake_client):
    merchant, _owner_id, _headers = _setup(fake_client)

    response = client.post(
        f"/v1/admin/merchants/{merchant['id']}/correct-contact-email",
        json={"email": "attacker@example.com"},
    )

    assert response.status_code in (401, 403)


# --- the record it leaves ---------------------------------------------------


def test_the_change_is_audit_logged(fake_client):
    merchant, _owner_id, headers = _setup(fake_client)

    _correct(merchant, headers, "hussensaid211@gmail.com")

    entries = [
        r
        for r in fake_client.table("audit_logs")._table.rows
        if r["action"] == "merchant.contact_email_corrected"
    ]
    assert len(entries) == 1
    assert entries[0]["merchant_id"] == merchant["id"]


def test_the_audit_entry_masks_both_addresses(fake_client):
    """Audit logs are readable by every Super Admin and exportable. The
    entry has to prove what happened, not carry two personal email
    addresses in clear text."""
    merchant, _owner_id, headers = _setup(fake_client)

    _correct(merchant, headers, "hussensaid211@gmail.com")

    entry = next(
        r
        for r in fake_client.table("audit_logs")._table.rows
        if r["action"] == "merchant.contact_email_corrected"
    )
    recorded = str(entry.get("metadata"))
    assert "huseinsaid211@gmail.com" not in recorded
    assert "hussensaid211@gmail.com" not in recorded
    assert "@gmail.com" in recorded


def test_the_address_never_reaches_the_logs(fake_client, caplog):
    """Same rule the push throttle follows for phone numbers: a merchant's
    email is personal data and Railway logs are not the place for it."""
    import logging

    merchant, _owner_id, headers = _setup(fake_client)
    logger = logging.getLogger("infinity.onboarding")
    # infinity.* loggers set propagate=False, so caplog sees nothing
    # unless it is attached to this logger directly - without this the
    # assertion below would pass no matter what the code logged.
    caplog.set_level(logging.INFO, logger="infinity.onboarding")
    logger.addHandler(caplog.handler)
    try:
        _correct(merchant, headers, "hussensaid211@gmail.com")
    finally:
        logger.removeHandler(caplog.handler)

    assert "merchant_contact_email_corrected" in caplog.text
    assert "hussensaid211@gmail.com" not in caplog.text
