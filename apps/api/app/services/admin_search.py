"""One box, several columns: the Super Admin list searches.

Every Super Admin list screen has a search box that promises more than
one column - "Invoice number, business, or customer", "Slug or
business". PostgREST expresses that as
`or=(a.ilike.*term*,b.ilike.*term*)`, and the two awkward parts are the
same every time:

  1. The term is interpolated into a COMMA-SEPARATED expression, so a
     term containing a comma or a bracket silently changes the query's
     shape rather than being searched for.
  2. "business" is not a column on these tables. The business name lives
     on merchants, so it has to be resolved to merchant ids first.

Both are easy to get subtly wrong once per screen, which is why they
live here instead.
"""

import logging
import re

from supabase import Client

from app.services.crud import fetch_all

logger = logging.getLogger("infinity.admin_search")

# Characters that are syntax inside an or_() expression rather than text
# to search for. A term containing a comma would split into extra
# branches; a bracket would unbalance the expression. Both change which
# rows come back, with nothing to say so.
_OR_SYNTAX = re.compile(r"[,()]")

# Runs of whitespace, collapsed after the substitution above - see
# or_search_term for why this is correctness and not neatness.
_WHITESPACE = re.compile(r"\s+")

# How many merchants a term may match before this stops adding them to
# the query. Each merchant becomes a `merchant_id.eq.<uuid>` branch, and
# the whole expression travels in the URL - see crud.fetch_in_chunks for
# what happens when a URL outgrows what the server will accept.
#
# For scale: there are 162 merchants in total today, so this is not a
# limit anyone reaches by searching for a business. A term generic
# enough to match 200 businesses is not a search, and the warning below
# says so rather than quietly returning a truncated answer.
MAX_MERCHANT_MATCHES = 200


def or_search_term(term: str) -> str:
    """A search term made safe to interpolate into an or_() expression.

    Not escaped - replaced. There is no escape for a comma inside
    PostgREST's or_() list, so a comma becomes a space and the term
    searches for what the operator almost certainly meant.

    Runs of whitespace then collapse to one. That is not tidiness: the
    substitution above turns "Kilimanjaro, Cafe" into two spaces, and
    `ilike '%Kilimanjaro  Cafe%'` does not match the business actually
    called "Kilimanjaro Cafe Ltd". Without this, sanitising the term
    would be what stopped it being found.
    """
    return _WHITESPACE.sub(" ", _OR_SYNTAX.sub(" ", term or "")).strip()


def merchant_ids_matching(client: Client, term: str) -> list[str]:
    """Merchant ids whose business name or code matches `term`.

    Business name AND code, because an operator holding a merchant code
    off a receipt and an operator who only knows the trading name are
    the same person on a different day.
    """
    safe = or_search_term(term)
    if not safe:
        return []

    def query():
        return (
            client.table("merchants")
            .select("id")
            .or_(f"business_name.ilike.%{safe}%,merchant_code.ilike.%{safe}%")
        )

    rows = fetch_all(query, max_rows=MAX_MERCHANT_MATCHES + 1)
    ids = [row["id"] for row in rows]
    if len(ids) > MAX_MERCHANT_MATCHES:
        # Said out loud rather than silently trimmed. A truncated set
        # would mean the screen answers "this business has no invoices"
        # for a business that has some.
        logger.warning(
            "admin search term matched more than %s merchants; "
            "business-name matching skipped for this term",
            MAX_MERCHANT_MATCHES,
        )
        return []
    return ids


def build_or_expression(term: str, columns: list[str], merchant_ids: list[str]) -> str | None:
    """The or_() expression for a one-box search, or None if there is
    nothing to search for.

    `columns` are text columns on the table itself, matched as a
    case-insensitive substring. `merchant_ids` are added as exact
    branches so a search for a business name reaches rows that only
    reference it by id.
    """
    safe = or_search_term(term)
    if not safe:
        return None
    branches = [f"{column}.ilike.%{safe}%" for column in columns]
    branches += [f"merchant_id.eq.{merchant_id}" for merchant_id in merchant_ids]
    return ",".join(branches)


def apply_one_box_search(
    query,
    client: Client,
    term: str | None,
    *,
    columns: list[str],
    search_merchants: bool = True,
):
    """Narrows `query` by a one-box search, or leaves it alone.

    Returns (query, searched). `searched` is False when the term was
    empty or became empty after sanitising - the caller gets back an
    unchanged query, which is right: an empty search box is not a filter
    for nothing.

    One guard, not two. An early `if not term.strip()` here was exactly
    equivalent to the expression check below, because both
    merchant_ids_matching and build_or_expression already treat an
    empty term as nothing to search - so it was a second way to express
    one rule, and mutation testing showed removing it changed no
    behaviour at all.
    """
    merchant_ids = merchant_ids_matching(client, term or "") if search_merchants else []
    expression = build_or_expression(term or "", columns, merchant_ids)
    if expression is None:
        return query, False
    return query.or_(expression), True
