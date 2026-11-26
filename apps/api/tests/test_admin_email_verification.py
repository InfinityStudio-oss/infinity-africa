"""Helping a merchant who cannot get past email verification.

Nine live businesses were stranded unable to sign in - approved, KYC
verified, wallet ready - because nobody had clicked the link in their
verification email. Super Admin had no way to help: the only resend is
self-service, reached from a "check your email" screen a merchant who
closed the tab a month ago cannot get back to. The fallback was hand
edits to auth.users in the Supabase dashboard.

Two actions, deliberately different:

  RESEND  changes nothing. A fresh link to the address already on file;
          the merchant still proves they can receive mail there.
  CONFIRM overrides the check. For an account stranded despite a
          correct address.

Pinned here:

1. Resend does not confirm anything - the merchant still has to click.
2. Confirm actually confirms, and is idempotent.
3. Both are Super Admin only.
4. Confirming is audited with the address IN FULL, unlike every other
   entry here, because the mistake that matters is confirming the WRONG
   address and a masked entry cannot be reviewed for that.
5. Neither touches the wallet, the ledger or anything else.
"""

import uuid

import pytest
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
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _admin(fake_client):
    user_id = uuid.uuid4()
    make_super_admin(fake_client, user_id)
    return auth_headers(user_id, aal="aal2")


def _stranded(fake_client, *, confirmed=False, email="owner@business.co.tz"):
    """A merchant whose owner has never confirmed their email."""
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    owner = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, owner, "MERCHANT_ADMIN")
    fake_client.auth.admin.seed_user(
        str(owner),
        email=email,
        email_confirmed_at="2026-11-01T09:00:00+00:00" if confirmed else None,
    )
    return merchant_id, owner


def _audits(fake_client, action):
    return [r for r in fake_client.table("audit_logs")._table.rows if r.get("action") == action]


# --- who may reach any of this -----------------------------------------------


def test_a_merchant_admin_cannot_confirm_their_own_email(fake_client):
    """The whole point of the check is that the account holder cannot
    tick it themselves."""
    merchant_id, owner = _stranded(fake_client)

    response = client.post(
        f"/v1/admin/merchants/{merchant_id}/confirm-email", headers=auth_headers(owner)
    )

    assert response.status_code in (401, 403)


def test_an_anonymous_caller_cannot_resend(fake_client):
    merchant_id, _ = _stranded(fake_client)

    assert client.post(f"/v1/admin/merchants/{merchant_id}/resend-verification").status_code in (
        401,
        403,
    )


# --- reading the state -------------------------------------------------------


def test_the_state_says_a_stranded_merchant_cannot_sign_in(fake_client):
    headers = _admin(fake_client)
    merchant_id, _ = _stranded(fake_client)

    response = client.get(f"/v1/admin/merchants/{merchant_id}/email-verification", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["can_sign_in"] is False
    assert data["email_confirmed_at"] is None


def test_the_state_says_a_working_merchant_can_sign_in(fake_client):
    headers = _admin(fake_client)
    merchant_id, _ = _stranded(fake_client, confirmed=True)

    data = client.get(
        f"/v1/admin/merchants/{merchant_id}/email-verification", headers=headers
    ).json()["data"]

    assert data["can_sign_in"] is True


# --- resend ------------------------------------------------------------------


def test_resending_does_not_confirm_anything(fake_client):
    """The safe action stays safe.

    If resend ever confirmed the address, the careful distinction
    between the two buttons would be gone and the override would be
    happening by accident.
    """
    headers = _admin(fake_client)
    merchant_id, _ = _stranded(fake_client)

    response = client.post(
        f"/v1/admin/merchants/{merchant_id}/resend-verification", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["data"]["can_sign_in"] is False
    assert response.json()["data"]["email_confirmed_at"] is None


def test_resending_to_an_already_verified_account_is_refused(fake_client):
    # A Super Admin pressing this on a working account has misread
    # something; a link that resolves to "already verified" teaches
    # them nothing.
    headers = _admin(fake_client)
    merchant_id, _ = _stranded(fake_client, confirmed=True)

    response = client.post(
        f"/v1/admin/merchants/{merchant_id}/resend-verification", headers=headers
    )

    assert response.status_code == 422
    assert "already verified" in response.text.lower()


def test_resending_is_audited_with_the_address_masked(fake_client):
    headers = _admin(fake_client)
    merchant_id, _ = _stranded(fake_client, email="owner@business.co.tz")

    client.post(f"/v1/admin/merchants/{merchant_id}/resend-verification", headers=headers)

    entries = _audits(fake_client, "merchant.verification_resent")
    assert len(entries) == 1
    # An audit log is readable by every Super Admin and exportable.
    assert entries[0]["metadata"]["to"] != "owner@business.co.tz"


# --- confirm -----------------------------------------------------------------


def test_confirming_lets_the_merchant_sign_in(fake_client):
    headers = _admin(fake_client)
    merchant_id, _ = _stranded(fake_client)

    response = client.post(f"/v1/admin/merchants/{merchant_id}/confirm-email", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["can_sign_in"] is True
    assert data["email_confirmed_at"] is not None


def test_confirming_twice_is_not_an_error_and_does_not_re_audit(fake_client):
    headers = _admin(fake_client)
    merchant_id, _ = _stranded(fake_client)

    first = client.post(f"/v1/admin/merchants/{merchant_id}/confirm-email", headers=headers)
    second = client.post(f"/v1/admin/merchants/{merchant_id}/confirm-email", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["can_sign_in"] is True
    # One override happened, so one entry. A second entry would claim a
    # decision nobody took.
    assert len(_audits(fake_client, "merchant.email_confirmed_by_admin")) == 1


def test_confirming_records_the_address_IN_FULL(fake_client):
    """The deliberate exception to masking.

    Every other entry in this log masks the address. This one does not,
    because the mistake that matters is confirming the WRONG address -
    the unverified flag is the only remaining signal that an address is
    wrong, and this removes it. A masked entry cannot be reviewed for
    that afterwards.
    """
    headers = _admin(fake_client)
    merchant_id, _ = _stranded(fake_client, email="owner@business.co.tz")

    client.post(f"/v1/admin/merchants/{merchant_id}/confirm-email", headers=headers)

    entry = _audits(fake_client, "merchant.email_confirmed_by_admin")[0]
    assert entry["metadata"]["email"] == "owner@business.co.tz"
    assert "bypassed" in entry["metadata"]["note"]


def test_confirming_an_account_with_no_usable_address_is_refused(fake_client):
    # Nothing to confirm, and confirming an empty address would strand
    # the account with the signal removed.
    headers = _admin(fake_client)
    merchant_id, _ = _stranded(fake_client, email="")

    response = client.post(f"/v1/admin/merchants/{merchant_id}/confirm-email", headers=headers)

    assert response.status_code == 422
    assert "correct the address" in response.text.lower()


def test_neither_action_touches_the_wallet_or_the_ledger(fake_client):
    headers = _admin(fake_client)
    merchant_id, _ = _stranded(fake_client)
    before_txns = len(fake_client.table("transactions")._table.rows)

    client.post(f"/v1/admin/merchants/{merchant_id}/resend-verification", headers=headers)
    client.post(f"/v1/admin/merchants/{merchant_id}/confirm-email", headers=headers)

    assert len(fake_client.table("transactions")._table.rows) == before_txns


def test_a_missing_merchant_is_a_404_not_a_confirm(fake_client):
    headers = _admin(fake_client)

    assert (
        client.post(f"/v1/admin/merchants/{uuid.uuid4()}/confirm-email", headers=headers).status_code
        == 404
    )


def test_a_confirm_that_silently_changes_nothing_is_reported_as_a_failure(fake_client, monkeypatch):
    """The guard mutation testing found untested.

    A write that returns success and changes nothing has happened on
    this platform before - a notification-settings row that was never
    created, and a payout retry that reported done. So confirm_email
    reads the user back and refuses to claim success if the flag is
    still empty.

    Forced here by making the update a no-op: without the read-back,
    this returns 200 and a Super Admin tells a merchant to go and log
    in to an account that is still locked.
    """
    headers = _admin(fake_client)
    merchant_id, _ = _stranded(fake_client)

    def _does_nothing(user_id, attributes):  # noqa: ARG001
        return None

    monkeypatch.setattr(fake_client.auth.admin, "update_user_by_id", _does_nothing)

    response = client.post(f"/v1/admin/merchants/{merchant_id}/confirm-email", headers=headers)

    assert response.status_code == 422
    assert "still reads as unverified" in response.text.lower()
    # And nothing was audited, because nothing happened.
    assert _audits(fake_client, "merchant.email_confirmed_by_admin") == []
