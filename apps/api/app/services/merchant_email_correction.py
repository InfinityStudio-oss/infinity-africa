"""Correcting the email address on a merchant account.

The other half of the duplicate-account fix (see
app/services/duplicate_signup.py). Signup now refuses to create a second
application for an identity that already has one, which only helps if
there is some way to fix the address that was wrong - otherwise a merchant
who mistypes their email is simply stuck.

That way is here, as a Super Admin action rather than a self-service one.
A merchant who cannot receive mail at the address on the account has only
their password left to prove who they are, and an unauthenticated
"change the email on this account" endpoint on a live payments platform is
a worse thing to own than a support call. At 60 merchants, every signup
is already approved by hand.

**What this does not do.** It does not touch the wallet, the ledger, any
collection or any API key. It changes one email address on one merchant
and on the Supabase Auth user behind it, and sends a fresh verification
link to the new address. The new address is left *unverified* on purpose:
the merchant still has to click the link, so a mistyped correction fails
closed rather than handing the account to whoever owns the typo.
"""

import logging
import uuid

from supabase import Client

from app.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationAPIError
from app.services.email import auth_link_for, send_email_verification_email

logger = logging.getLogger("infinity.onboarding")


def _owner_user_id(client: Client, merchant_id: uuid.UUID) -> str:
    """The Supabase Auth user whose email this is. The merchant admin from
    merchant_users - the same row signup creates - not whatever address
    happens to sit in merchants.contact_email, which is a business contact
    field and may legitimately differ from the login."""
    rows = (
        client.table("merchant_users")
        .select("user_id,role,status,created_at")
        .eq("merchant_id", str(merchant_id))
        .eq("status", "active")
        .order("created_at")
        .execute()
        .data
        or []
    )
    admins = [r for r in rows if r.get("role") == "MERCHANT_ADMIN"]
    chosen = (admins or rows)
    if not chosen:
        raise NotFoundError("This business has no active account owner to update.")
    return str(chosen[0]["user_id"])


def correct_merchant_contact_email(
    client: Client, *, merchant_id: uuid.UUID, new_email: str
) -> dict:
    """Move the account to `new_email` and send a verification link there.

    Raises ConflictError if the address already belongs to another
    Supabase Auth user - that is the one case where going ahead would do
    real damage, because two merchants would be fighting over one login.
    """
    email = (new_email or "").strip().lower()
    if not email or "@" not in email:
        raise ValidationAPIError("Enter a valid email address.")

    user_id = _owner_user_id(client, merchant_id)

    try:
        updated = client.auth.admin.update_user_by_id(
            user_id,
            # email_confirm stays False: the merchant proves they can
            # receive mail at the new address by clicking the link. A
            # Super Admin typo here must not confirm an address nobody
            # owns.
            {"email": email, "email_confirm": False},
        )
    except Exception as exc:
        message = str(exc).lower()
        if "already" in message and ("registered" in message or "exists" in message):
            raise ConflictError(
                "Another account already uses that email address."
            ) from exc
        raise ValidationAPIError("Couldn't update the email address.") from exc

    client.table("merchants").update({"contact_email": email}).eq(
        "id", str(merchant_id)
    ).execute()

    # Best-effort, exactly like signup's own verification email: the
    # address is already changed by this point, and a mail hiccup must not
    # make the Super Admin think the correction failed. They can send
    # another one.
    verification_sent = False
    try:
        settings = get_settings()
        link = client.auth.admin.generate_link(
            {
                "type": "magiclink",
                "email": email,
                "options": {
                    "redirect_to": f"{settings.app_url}/auth/callback?next=/dashboard/overview"
                },
            }
        )
        send_email_verification_email(
            client,
            email=email,
            # Our own callback route with the token as a query parameter.
            # Supabase's action_link ignores redirect_to and returns the
            # token in a URL fragment the server can never read - see
            # auth_link_for.
            action_link=auth_link_for(
                link,
                redirect_to=f"{settings.app_url}/auth/callback?next=/dashboard/overview",
                link_type="magiclink",
            ),
        )
        verification_sent = True
    except Exception:  # noqa: BLE001 — the address is corrected either way
        logger.warning("merchant_email_correction_link_failed merchant_id=%s", merchant_id)

    # Never the address itself: this logger's output lands in Railway logs
    # and a merchant's email is personal data, same rule as the phone
    # numbers in app/core/push_throttle.py.
    logger.info(
        "merchant_contact_email_corrected merchant_id=%s verification_sent=%s",
        merchant_id,
        verification_sent,
    )
    return {
        "user_id": str(getattr(getattr(updated, "user", None), "id", user_id)),
        "email": email,
        "verification_sent": verification_sent,
    }
