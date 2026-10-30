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

**Only an application that never got off the ground blocks a second
one.** Read the five cases again: every stray was *unverified* - nobody
ever confirmed the address, nobody ever signed in, not one took a
payment. That is the accident. It is not the same thing as one person
owning two businesses, and the first version of this guard could not
tell them apart: it keyed on identity alone, so an established merchant
opening a genuinely separate business was turned away with a message
telling him he had already applied. That happened, on 2026-10-30, to a
merchant carrying 19,968 payments.

So the lookup still finds every application on this identity, and then
only refuses on one whose owner never confirmed their email. A merchant
who verified demonstrably *received* their link, which means the
mistyped-address accident did not happen to them and a second
application is a second business. The Super Admin still reviews every
one by hand before it can take money, which is the control that actually
decides who goes live.
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


def _owner_never_verified(client: Client, merchant_id: str) -> bool:
    """Whether this account's owner never confirmed their email.

    The question the guard actually needs answered. An application whose
    owner verified is a business that received its link and got in; one
    whose owner never did is the abandoned half of a mistyped address,
    and that is the only kind worth blocking a new signup over.

    A lookup that fails answers "verified", which allows the signup. The
    whole module is built that way round: a duplicate account is tidied
    up by hand, while a real merchant turned away at the door may simply
    not come back.
    """
    try:
        rows = (
            client.table("merchant_users")
            .select("user_id,role,status,created_at")
            .eq("merchant_id", merchant_id)
            .eq("status", "active")
            .order("created_at")
            .execute()
            .data
            or []
        )
        admins = [r for r in rows if r.get("role") == "MERCHANT_ADMIN"] or rows
        if not admins:
            # No owner at all. Nothing here can have been verified, and
            # nothing can be corrected either, so it must not stand in
            # the way of a new application.
            return False
        result = client.auth.admin.get_user_by_id(str(admins[0]["user_id"]))
        return not getattr(getattr(result, "user", None), "email_confirmed_at", None)
    except Exception:  # noqa: BLE001 - see the docstring; this allows the signup
        logger.warning("duplicate_signup_owner_check_unavailable merchant_id=%s", merchant_id)
        return False


def find_existing_application(
    client: Client, *, nida: str, phone: str | None
) -> dict | None:
    """The unverified application already holding this identity, or None.

    Matches on NIDA first and falls back to the contact phone, oldest
    first - the oldest is the original application, the one whose email
    should be corrected rather than replaced.

    A match only counts if its owner never confirmed their email. Holding
    the identity is not enough: one person may legitimately run two
    businesses, and refusing that was a real cost paid by a real
    merchant. See the module docstring.

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
            for match in matches:
                if _owner_never_verified(client, str(match["id"])):
                    return match

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
            for match in matches:
                if _owner_never_verified(client, str(match["id"])):
                    return match

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


def identity_siblings(client: Client) -> dict[str, list[dict]]:
    """merchant_id -> the other businesses held by the same person.

    One person may now run several businesses (see the module docstring),
    so the Super Admin reviewing an application needs to be told when the
    ID in front of them already has others. Nothing is refused on this -
    it is a fact for the reviewer, who is the control that actually
    decides who goes live.

    Built as one index from two queries rather than a lookup per row:
    this feeds the onboarding queue, which renders every pending
    application at once, and a per-row lookup there is how the Businesses
    page came to make roughly 700 round trips for one screen.

    Keyed on NIDA where there is one and the contact phone otherwise -
    the same two keys, in the same order, the signup guard uses, so the
    screen cannot disagree with the rule.
    """
    try:
        submissions = (
            client.table("onboarding_submissions").select("merchant_id,nida_number").execute().data or []
        )
        merchants = (
            client.table("merchants")
            .select("id,business_name,merchant_code,status,contact_phone,created_at")
            .execute()
            .data
            or []
        )
    except Exception:  # noqa: BLE001 - a missing badge must not fail the queue
        logger.warning("identity_siblings_unavailable")
        return {}

    nida_by_merchant = {
        str(s["merchant_id"]): (s.get("nida_number") or "").strip()
        for s in submissions
        if s.get("merchant_id")
    }

    def key_for(merchant: dict) -> str | None:
        nida = nida_by_merchant.get(str(merchant["id"]))
        if nida:
            return f"nida:{nida}"
        phone = (merchant.get("contact_phone") or "").strip()
        return f"phone:{phone}" if phone else None

    grouped: dict[str, list[dict]] = {}
    for merchant in merchants:
        key = key_for(merchant)
        if key:
            grouped.setdefault(key, []).append(merchant)

    index: dict[str, list[dict]] = {}
    for merchant in merchants:
        key = key_for(merchant)
        if not key:
            continue
        others = [m for m in grouped[key] if str(m["id"]) != str(merchant["id"])]
        if others:
            index[str(merchant["id"])] = [
                {
                    "merchant_id": str(m["id"]),
                    "business_name": m.get("business_name") or "",
                    "merchant_code": m.get("merchant_code"),
                    "status": m.get("status"),
                }
                for m in sorted(others, key=lambda m: m.get("created_at") or "")
            ]
    return index
