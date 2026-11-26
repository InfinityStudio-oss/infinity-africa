"""Helping a merchant who cannot get past email verification.

Nine live businesses were sitting unable to sign in - approved, KYC
verified, wallet ready - because nobody had ever clicked the link in
their verification email. Seven had been sent one, four of those twice.
Super Admin had no way to help any of them: the only resend on the
platform is self-service, and reaching it requires getting to the
"check your email" screen, which a merchant who closed the tab a month
ago no longer has. The fallback was editing auth.users by hand in the
Supabase dashboard.

Two different problems live here, and they need different answers.

RESEND is for "the email went somewhere they did not look". It changes
nothing: a fresh link goes to the address already on the account, and
the merchant still proves they can receive mail there. This is the one
to reach for first, and it is the safe one.

CONFIRM is for "they cannot click it at all" - the address is right,
they have been sent links repeatedly, and the account is stranded. It
marks the address verified on a Super Admin's say-so, which is a
security control being overridden, so it is deliberately the second
option and not the obvious one.

The thing CONFIRM must never become is a fix for a WRONG address. That
is what correct_contact_email is for (see
app/services/merchant_email_correction.py). Confirming a wrong address
locks the account to a mailbox nobody owns AND removes the only signal
that it was wrong, because the unverified flag is that signal. So this
refuses when the address looks undeliverable, and the audit entry
records the address so the decision is reviewable afterwards.
"""

import logging
import uuid

from supabase import Client

from app.config import get_settings
from app.core.errors import NotFoundError, ValidationAPIError
from app.services.email import auth_link_for, send_email_verification_email
from app.services.merchant_email_correction import _owner_user_id

logger = logging.getLogger("infinity.onboarding")


def _auth_user(client: Client, user_id: str) -> dict:
    """The Supabase Auth user behind a merchant, as a plain dict."""
    try:
        result = client.auth.admin.get_user_by_id(user_id)
    except Exception as exc:
        raise NotFoundError("Could not read this account's login.") from exc
    user = getattr(result, "user", None) or result
    if user is None:
        raise NotFoundError("This business has no login to verify.")
    # supabase-py hands back an object here and a dict in the fake, so
    # read both the same way rather than branching at every call site.
    if isinstance(user, dict):
        return user
    return {
        "id": getattr(user, "id", None),
        "email": getattr(user, "email", None),
        "email_confirmed_at": getattr(user, "email_confirmed_at", None),
        "last_sign_in_at": getattr(user, "last_sign_in_at", None),
    }


def verification_state(client: Client, merchant_id: uuid.UUID) -> dict:
    """Whether this merchant can actually sign in, and since when.

    Read-only. Exists so the Super Admin screen can show the state
    rather than offering a button whose effect nobody can predict -
    "Confirm email" on an account that is already confirmed is a
    different thing from the same button on a stranded one.
    """
    user = _auth_user(client, _owner_user_id(client, merchant_id))
    return {
        "email": user.get("email"),
        "email_confirmed_at": user.get("email_confirmed_at"),
        "last_sign_in_at": user.get("last_sign_in_at"),
        "can_sign_in": bool(user.get("email_confirmed_at")),
    }


def resend_verification(client: Client, merchant_id: uuid.UUID) -> dict:
    """Send a fresh verification link to the address already on file.

    Changes nothing about the account. The merchant still has to click
    it, so this is safe to run as often as somebody asks.

    Raises rather than quietly succeeding when the address is already
    confirmed: a Super Admin pressing this on a working account is
    confused about something, and sending a link that resolves to
    "already verified" teaches them nothing.
    """
    user_id = _owner_user_id(client, merchant_id)
    user = _auth_user(client, user_id)
    email = (user.get("email") or "").strip()
    if not email:
        raise NotFoundError("This business has no login email to send to.")
    if user.get("email_confirmed_at"):
        raise ValidationAPIError(
            "This email address is already verified — they can sign in now."
        )

    settings = get_settings()
    next_path = "/auth/callback?next=/dashboard/overview"
    try:
        link = client.auth.admin.generate_link(
            {
                "type": "magiclink",
                "email": email,
                "options": {"redirect_to": f"{settings.app_url}{next_path}"},
            }
        )
        send_email_verification_email(
            client,
            email=email,
            # Our own callback with the token as a query parameter.
            # Supabase's action_link ignores redirect_to and puts the
            # token in a URL fragment, which a server can never read -
            # see email.auth_link_for.
            action_link=auth_link_for(
                link, redirect_to=f"{settings.app_url}{next_path}", link_type="magiclink"
            ),
        )
    except Exception as exc:
        # Raised, not swallowed. Unlike the correction flow - where the
        # address has already changed by this point and a mail failure
        # must not read as "the correction failed" - nothing has
        # happened here, so saying it worked would be a lie.
        logger.warning("admin_resend_verification_failed merchant_id=%s", merchant_id)
        raise ValidationAPIError(
            "Couldn't send the verification email. Try again in a moment."
        ) from exc

    # The address is never logged: this output lands in Railway logs and
    # a merchant's email is personal data, the same rule as the phone
    # numbers in app/core/push_throttle.py.
    logger.info("admin_resend_verification merchant_id=%s", merchant_id)
    return {"email": email, "verification_sent": True}


def confirm_email(client: Client, merchant_id: uuid.UUID) -> dict:
    """Mark the login email verified without the merchant clicking a link.

    The override. For an account that is stranded despite the address
    being correct - repeated links sent, none clicked, business already
    approved and KYC verified by a person.

    Returns the address so the caller can audit it. Confirming the
    WRONG address is the failure mode that matters, because the
    unverified flag is the only remaining signal that an address is
    wrong, and this removes it.
    """
    user_id = _owner_user_id(client, merchant_id)
    user = _auth_user(client, user_id)
    email = (user.get("email") or "").strip()
    if not email or "@" not in email:
        raise ValidationAPIError(
            "This account has no usable email address. Correct the address first."
        )
    if user.get("email_confirmed_at"):
        # Idempotent, and says so. Pressing it twice is not an error, but
        # it should not report that it did something either.
        return {
            "email": email,
            "already_confirmed": True,
            "email_confirmed_at": user.get("email_confirmed_at"),
        }

    try:
        client.auth.admin.update_user_by_id(user_id, {"email_confirm": True})
    except Exception as exc:
        raise ValidationAPIError("Couldn't confirm this email address.") from exc

    after = _auth_user(client, user_id)
    if not after.get("email_confirmed_at"):
        # Read back rather than trusted. A write that reports success and
        # changes nothing has happened on this platform before - see the
        # notification-settings row that was never created.
        raise ValidationAPIError(
            "The email still reads as unverified after the change. Nothing was confirmed."
        )

    logger.info("admin_confirm_email merchant_id=%s", merchant_id)
    return {
        "email": email,
        "already_confirmed": False,
        "email_confirmed_at": after.get("email_confirmed_at"),
    }
