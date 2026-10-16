"""One business, one account.

From production, 2026-10-16: five businesses held eleven accounts between
them. Every single case has the same shape - a merchant mistypes their
email on the Get Started form, never receives the verification link, and
signs up again with the address spelled correctly:

    KILUNGULE  mlangalamohamedi93@kilungulesupe...  unverified, 0 collections
               mlangalamohamedi93@gmail.com         verified,   1409
    BBTECH     mabesason@gmail.com                  unverified, 0
               bbtechnology00@gmail.com             verified,   143
    ENZOH      lunguwendelini4@gmail.com            unverified, 0
               lunguwendelini6@gmail.com            verified,   23
    KISINGA    breezykicnga51@gmail.com             unverified, 0
               breezykicnga595@gmail.com            verified,   0
    BEACH      huseinsaid211 / husseinsaid211       unverified, 0
               hussensaid211@gmail.com              verified,   89

They sign up again because that is the only thing the product lets them
do: the "check your email" screen offers "Resend verification email",
which sends another link to the address that was wrong the first time.
There is no way to correct it.

The cost is not cosmetic. Each stray account is a separate merchant_id
with its own wallet, its own API keys and its own onboarding submission
for a Super Admin to review - and three of the five strays had already
been approved, so the platform was carrying duplicate approved merchants
for one real business. Support cannot tell which account a caller means.

So signup refuses to create a second application for an identity that
already has one, and tells the merchant what to do instead. Correcting
the address is a Super Admin action (admin.correct_merchant_contact_email)
rather than a self-service endpoint: at this scale every signup is
reviewed by hand anyway, and an unauthenticated "change the email on an
account" endpoint is not something this platform should grow.

**NIDA is the key that works, not the phone.** ENZOH used two different
phone numbers with one NIDA, and the one pre-existing legitimate pair
(a deactivated test account and VoxopPay) shares a phone with no NIDA on
file. Phone is still checked, because it is the only key available for
the four merchants with no NIDA on record.
"""

import logging

from supabase import Client

logger = logging.getLogger("infinity.onboarding")


def mask_email(email: str | None) -> str:
    """``husseinsaid211@gmail.com`` -> ``h••••••••••1@gmail.com``.

    Enough for the person who just mistyped their own address to
    recognise it, not enough to hand a real address to someone who
    guessed a NIDA number. The domain stays readable because that is
    usually where the typo is (``@kilungulesupe...`` for ``@gmail.com``).
    """
    if not email or "@" not in email:
        return "•••"
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        return f"{local[:1]}•@{domain}"
    return f"{local[0]}{'•' * (len(local) - 2)}{local[-1]}@{domain}"


def find_existing_application(
    client: Client, *, nida: str, phone: str | None
) -> dict | None:
    """The merchant that already holds this identity, or None.

    Matches on NIDA first and falls back to the contact phone. Returns
    the *oldest* match: that is the original application, the one whose
    email should be corrected rather than replaced.

    Never raises. A lookup failure here means signup proceeds exactly as
    it did before this guard existed - a duplicate account is a mess to
    clean up, but refusing a real merchant's signup because of a database
    hiccup is worse.
    """
    try:
        merchant_ids: list[str] = []

        if nida:
            rows = (
                client.table("onboarding_submissions")
                .select("merchant_id")
                .eq("nida_number", nida)
                .execute()
                .data
                or []
            )
            merchant_ids = [r["merchant_id"] for r in rows if r.get("merchant_id")]

        if merchant_ids:
            matches = (
                client.table("merchants")
                .select("id,business_name,merchant_code,contact_email,created_at")
                .in_("id", merchant_ids)
                .order("created_at")
                .execute()
                .data
                or []
            )
            if matches:
                return matches[0]

        if phone:
            matches = (
                client.table("merchants")
                .select("id,business_name,merchant_code,contact_email,created_at")
                .eq("contact_phone", phone)
                .order("created_at")
                .execute()
                .data
                or []
            )
            if matches:
                return matches[0]

        return None
    except Exception:  # noqa: BLE001 — never block a real signup on a lookup
        logger.warning("duplicate_signup_check_unavailable")
        return None


def duplicate_signup_message(existing: dict) -> str:
    """What the merchant reads. Three things they can act on: that the
    application exists, which address it is on, and that support can
    change it - because nothing in the product lets them do it
    themselves."""
    code = existing.get("merchant_code") or "—"
    return (
        "You have already applied with this ID number. The application is on "
        f"{mask_email(existing.get('contact_email'))} (business code {code}). "
        "If that email address is wrong, contact InfinityPay support and we will "
        "correct it and send you a new verification link — please do not create a "
        "second account."
    )
