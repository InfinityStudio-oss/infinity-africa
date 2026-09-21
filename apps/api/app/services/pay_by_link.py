"""Pay by Link: a merchant's permanent public checkout page
(/pay/{slug}) — e.g. https://infinitypay.me/pay/paul-masanja — that a
merchant shares once and reuses forever (WhatsApp, Instagram, a poster
QR, ...), distinct from payment_links' one-off generated/shareable links
(a fixed amount, a random 128-bit public_slug, created per-transaction).

This module only ever manages the permanent page's own identity (slug,
display name, active/disabled) — see
supabase/migrations/20260830020000_merchant_pay_links.sql. A customer
submitting the page's form creates an entirely ordinary payment_links row
(execute_pay_by_link_checkout below) tagged created_via="pay_by_link", so
every existing collection-creation, reconciliation, wallet-credit, and
receipt-email safety guarantee already proven for payment links applies
here completely unchanged — nothing in this module ever touches a
collection, a ledger entry, or a wallet balance.
"""

import re
import secrets
import uuid
from decimal import Decimal

from supabase import Client

from app.core.errors import ConflictError, ValidationAPIError
from app.core.time import utc_now_iso
from app.schemas.enums import LEGACY_ALLOWED_PAYMENT_METHODS_DEFAULT
from app.services.crud import execute_maybe_single, get_by_id, insert_row, update_row
from app.services.payment_links import build_public_url, generate_public_slug

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MIN_SLUG_LENGTH = 3
MAX_SLUG_LENGTH = 60

# Path segments already meaningful elsewhere on infinitypay.me (or
# that would be confusing/risky as a merchant's own permanent public
# URL) — checked before a slug is ever offered as a default or accepted
# from a merchant's own edit. Deliberately a plain Python set, not a DB
# constraint (see the migration's column comment) — this list is
# expected to grow as the app grows new top-level routes.
RESERVED_SLUGS = frozenset(
    {
        "admin",
        "merchant",
        "api",
        "auth",
        "login",
        "signup",
        "dashboard",
        "invoices",
        "collections",
        "payment-links",
        "support",
        "contact",
        "settings",
        "webhook",
        "webhooks",
    }
)


def slugify(value: str) -> str:
    """Lowercase, ASCII letters/digits only, single hyphens between
    words — "Paul Masanja" -> "paul-masanja". Can return an empty string
    for input with no alphanumeric characters at all (e.g. all emoji/
    punctuation) — callers that need a guaranteed-nonempty default use
    generate_default_slug below, not this directly."""
    lowered = value.strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")


def is_slug_reserved(slug: str) -> bool:
    return slug in RESERVED_SLUGS


def _slug_taken(client: Client, slug: str, *, exclude_pay_link_id: uuid.UUID | None = None) -> bool:
    """Checked against BOTH tables sharing the /pay/{slug} namespace — a
    merchant-chosen slug must not collide with an existing generated
    payment_links.public_slug (vanishingly unlikely in practice, since
    those are 128-bit random tokens, but the feature brief calls this out
    explicitly and it costs one cheap extra lookup) nor another
    merchant's own Pay by Link page. `slug` must already be lowercase —
    callers always validate format first (validate_slug_format).

    payment_links.public_slug is generated case-sensitively
    (secrets.token_urlsafe) while a Pay by Link slug is always lowercase,
    so the two can't be compared with a plain case-sensitive `eq` — an
    `ilike` match against the escaped literal (never a real wildcard
    pattern) makes the comparison case-insensitive without opening it up
    to `%`/`_` being treated as wildcards if a token happens to contain
    them (token_urlsafe's alphabet includes `_`)."""
    pay_link_query = client.table("merchant_pay_links").select("id").eq("slug", slug)
    if exclude_pay_link_id:
        pay_link_query = pay_link_query.neq("id", str(exclude_pay_link_id))
    if execute_maybe_single(pay_link_query.maybe_single()):
        return True

    escaped = slug.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return bool(
        execute_maybe_single(client.table("payment_links").select("id").ilike("public_slug", escaped).maybe_single())
    )


def validate_slug_format(slug: str) -> None:
    """Raises ValidationAPIError for anything that isn't lowercase
    letters/digits/single-hyphens, 3-60 characters, and not a reserved
    word — the same three rules the database's own check constraint
    enforces for format/length (belt-and-suspenders: this gives a
    specific, actionable message instead of a raw constraint-violation
    error) plus the reserved-word check the database can't."""
    if not _SLUG_PATTERN.match(slug) or not (MIN_SLUG_LENGTH <= len(slug) <= MAX_SLUG_LENGTH):
        raise ValidationAPIError(
            f"Slug must be lowercase letters, numbers, and single hyphens only "
            f"({MIN_SLUG_LENGTH}-{MAX_SLUG_LENGTH} characters)."
        )
    if is_slug_reserved(slug):
        raise ValidationAPIError(f'"{slug}" is a reserved word and can\'t be used as a Pay by Link slug.')


def check_slug_available(client: Client, slug: str, *, exclude_pay_link_id: uuid.UUID | None = None) -> None:
    """Raises for an invalid or already-taken slug. The taken-slug message
    ("This slug is already taken.") is the exact copy the feature brief
    specifies for the frontend — returned as the backend error message
    directly so the UI can show it unmodified."""
    validate_slug_format(slug)
    if _slug_taken(client, slug, exclude_pay_link_id=exclude_pay_link_id):
        raise ConflictError("This slug is already taken.")


def generate_default_slug(client: Client, base_name: str) -> str:
    """The default slug for a brand-new Pay by Link page, derived from
    the merchant's own business name — "Paul Masanja" -> "paul-masanja",
    "paul-masanja-2" if that's taken, and so on. Falls back to a random
    suffix if the name slugifies to nothing usable (e.g. a business name
    that's entirely emoji/punctuation) or happens to be a reserved word —
    a merchant can always rename it afterwards via check_slug_available."""
    base = slugify(base_name)
    if len(base) < MIN_SLUG_LENGTH or is_slug_reserved(base):
        base = f"merchant-{secrets.token_hex(3)}"
    base = base[:MAX_SLUG_LENGTH]

    candidate = base
    suffix = 2
    while _slug_taken(client, candidate):
        candidate = f"{base}-{suffix}"[:MAX_SLUG_LENGTH]
        suffix += 1
        if suffix > 500:
            # Should never happen in practice (500 consecutive
            # collisions on one base name) — a random suffix guarantees
            # termination rather than looping forever if it somehow did.
            candidate = f"{base}-{secrets.token_hex(4)}"
            break
    return candidate


def get_own_pay_link(client: Client, *, merchant_id: uuid.UUID) -> dict | None:
    return execute_maybe_single(
        client.table("merchant_pay_links").select("*").eq("merchant_id", str(merchant_id)).maybe_single()
    )


def ensure_merchant_accepts_payments(client: Client, *, merchant_id: uuid.UUID) -> dict:
    """A merchant must be status="active" to accept a Pay by Link
    payment — re-checked here, at submission time, every time, since a
    merchant can be suspended after their permanent page was already
    created and shared (same "never trust stale state" rule as
    disbursements' _check_merchant_is_verified). Deliberately a plain
    ConflictError with generic copy — a public customer-facing page must
    never reveal a merchant's internal compliance status."""
    merchant = get_by_id(client, "merchants", merchant_id)
    if not merchant or merchant.get("status") != "active":
        raise ConflictError("This merchant isn't currently accepting payments.")
    return merchant


async def execute_pay_by_link_checkout(
    client: Client,
    *,
    pay_link: dict,
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
    amount: Decimal,
    currency: str,
    description: str | None,
) -> dict:
    """Creates a fresh, entirely ordinary payment_links row for this Pay
    by Link page's merchant and returns it — the customer's browser does
    a full-page redirect to its public_url next, landing on the exact
    same "Choose how you want to pay" flow every other payment link
    already uses (app/routers/payment_links.py's public_router). No
    collection, ledger entry, or wallet credit happens here — this only
    ever creates the payment_links row a collection will later be
    resolved against, via the same path (and the same safety guarantees)
    as every other payment_links creation call site in this codebase."""
    merchant_id = uuid.UUID(pay_link["merchant_id"])
    customer_name = f"{first_name} {last_name}".strip()

    link_data = {
        "merchant_id": str(merchant_id),
        "amount": str(amount),
        "currency": currency,
        "customer_name": customer_name,
        "customer_phone": phone,
        "customer_email": email,
        "description": description,
        "allowed_payment_methods": [m.value for m in LEGACY_ALLOWED_PAYMENT_METHODS_DEFAULT],
        "public_slug": generate_public_slug(),
        "status": "ACTIVE",
        "created_via": "pay_by_link",
    }
    link = insert_row(client, "payment_links", link_data)

    update_row(client, "merchant_pay_links", uuid.UUID(pay_link["id"]), {"last_used_at": utc_now_iso()})

    return {"payment_link": link, "public_url": build_public_url(link["public_slug"])}
