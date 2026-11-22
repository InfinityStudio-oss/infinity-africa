"""Finding a payment by the customer's phone number.

The question this answers is the one support is asked all day: "this
person says they paid — did it go through?" The operator has a phone
number, and nothing else.

--- Why this is not just a LIKE

Numbers are STORED canonically. Every one of the last 400 collections
is `255XXXXXXXXX`. Numbers are TYPED however the person in front of you
said them: 0762474101, 255762474101, +255 762 474 101, 0762 474 101.
A naive equality filter on the typed text matches nothing and tells the
operator the payment does not exist — which is worse than no search,
because it is a confident wrong answer about someone's money.

So the term is normalised to the stored form first, using the same
normalize_tz_phone the rest of the platform writes with.

--- Partial numbers

An operator often has only the tail: "it ends 474101". A short suffix
is allowed, but with a floor. Two or three digits would match thousands
of rows across every merchant and scan the whole table to do it, so
anything under six digits is treated as not-a-phone and left to the
reference search instead.
"""

import logging
import re
import uuid

from supabase import Client

from app.core.phone import InvalidPhoneNumberError, normalize_tz_phone
from app.services.crud import fetch_all

logger = logging.getLogger("infinity.phone_search")

# Below this, a "phone" is too short to mean anything: it would match a
# large fraction of the table and scan all of it to find them.
MIN_PARTIAL_DIGITS = 6


def looks_like_phone(term: str) -> bool:
    """Is this search term a phone number rather than a reference?

    References here are TXN-20261122-ABC123, PO-4A03D6BE..., PWF-...  -
    they all carry letters and a hyphen. A phone is digits, possibly
    with +, spaces or hyphens between them. The test is therefore "what
    remains after stripping separators is all digits, and there are
    enough of them".
    """
    stripped = re.sub(r"[\s\-+()]", "", term or "")
    return stripped.isdigit() and len(stripped) >= MIN_PARTIAL_DIGITS


def canonical_or_suffix(term: str) -> tuple[str | None, str | None]:
    """(exact, suffix) for a typed phone term.

    Exactly one is set. A complete number normalises to the stored form
    and is matched exactly, which is indexed and fast. A partial cannot
    be normalised - there is no country code to anchor it - so it falls
    back to a suffix match, which is slower and deliberately floored at
    MIN_PARTIAL_DIGITS.
    """
    digits = re.sub(r"[\s\-+()]", "", term or "")
    if not digits.isdigit() or len(digits) < MIN_PARTIAL_DIGITS:
        return None, None
    try:
        return normalize_tz_phone(digits), None
    except InvalidPhoneNumberError:
        # Not a whole Tanzanian number. Treat it as the tail of one.
        return None, digits


def collection_ids_for_phone(
    client: Client, *, term: str, merchant_id: uuid.UUID | None = None, limit: int = 2000
) -> list[str]:
    """Every collection id whose customer phone matches `term`.

    Returns [] when nothing matches, which callers must treat as "no
    results" rather than "no filter" - skipping the filter on an unknown
    number would show the operator every transaction on the platform and
    let them conclude the wrong one succeeded.

    Capped. A number belonging to a very busy payer is not a reason to
    build a URL the server will reject (see crud.fetch_in_chunks for how
    that failed before), and 2000 collections for one phone is already
    far past what anyone reads.
    """
    exact, suffix = canonical_or_suffix(term)
    if not exact and not suffix:
        return []

    def query():
        # A FACTORY, not a built query: fetch_all re-ranges it per page
        # and a PostgREST query cannot be reused once executed. Passing
        # a built query with .limit() on it would also hit the server's
        # hard 1000-row cap silently - the exact failure documented on
        # fetch_all, where a .limit(5000) scan quietly read 1000 rows
        # and under-reported a merchant's customers.
        q = client.table("collections").select("id")
        if merchant_id is not None:
            q = q.eq("merchant_id", str(merchant_id))
        if exact:
            return q.eq("customer_phone", exact)
        # Suffix, not "contains": the tail of a number is what people
        # read out. `%474101` cannot use the btree index, which is why
        # the digit floor exists.
        return q.ilike("customer_phone", f"%{suffix}")

    rows = fetch_all(query, max_rows=limit)
    return [row["id"] for row in rows]
