"""Batch-lookup helpers shared by the /v1/admin/* list endpoints
(app/routers/admin.py) — joining a merchant_name or a person's display name
onto rows from tables that don't store them directly.

No table stores a person's full name; only Supabase Auth's
user_metadata.full_name does. best_effort_user_profile/batch_user_profiles
resolve it via the service-role client's Auth admin API, deliberately
swallowing any failure (user deleted, network hiccup, malformed metadata)
and returning None rather than failing the whole list — a missing name is
a cosmetic gap, not a reason to break a dashboard page.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor

from supabase import Client


def batch_merchant_names(client: Client, merchant_ids: set[str]) -> dict[str, str]:
    if not merchant_ids:
        return {}
    rows = (
        client.table("merchants").select("id, business_name").in_("id", list(merchant_ids)).execute()
    ).data or []
    return {row["id"]: row["business_name"] for row in rows}


def batch_merchant_codes(client: Client, merchant_ids: set[str]) -> dict[str, str]:
    """id -> merchant_code (the human-friendly 27****** Merchant ID), for
    join-on-display on every Super Admin page that lists merchant-owned
    rows — same shape/usage as batch_merchant_names, kept as its own
    function (not merged into it) so every existing `.get(id, "")` caller
    of batch_merchant_names is unaffected."""
    if not merchant_ids:
        return {}
    rows = (
        client.table("merchants").select("id, merchant_code").in_("id", list(merchant_ids)).execute()
    ).data or []
    return {row["id"]: row["merchant_code"] for row in rows}


def batch_wallet_balances(client: Client, merchant_ids: set[str]) -> dict[str, str]:
    """id -> current merchant_wallet balance (as a string, matching every
    other Decimal-shaped field these batch helpers return), for the Super
    Admin withdrawal approval queue (app/routers/admin.py::list_admin_withdrawals) —
    lets a reviewer see whether a merchant can actually cover a pending
    request without a separate lookup. Deliberately read-only: unlike
    app/services/ledger.py::get_wallet_balance, this never creates a
    ledger_accounts row for a merchant that doesn't have one yet — a GET
    endpoint must not have that side effect. A merchant with no
    merchant_wallet row simply doesn't appear in the returned dict; callers
    should treat a missing key as a balance of 0, same convention as
    get_wallet_balance's own documented behavior for that case."""
    if not merchant_ids:
        return {}
    rows = (
        client.table("ledger_accounts")
        .select("merchant_id, balance")
        .in_("merchant_id", list(merchant_ids))
        .eq("purpose", "merchant_wallet")
        .execute()
    ).data or []
    return {row["merchant_id"]: str(row["balance"]) for row in rows}


def batch_api_key_prefixes(client: Client, api_key_ids: set[str]) -> dict[str, str]:
    """id -> key_prefix, for join-on-display only — never selects hashed_key."""
    if not api_key_ids:
        return {}
    rows = (
        client.table("api_keys").select("id, key_prefix").in_("id", list(api_key_ids)).execute()
    ).data or []
    return {row["id"]: row["key_prefix"] for row in rows}


def best_effort_user_profile(client: Client, user_id: str | uuid.UUID | None) -> dict:
    if not user_id:
        return {"full_name": None, "email": None, "last_sign_in_at": None}
    try:
        result = client.auth.admin.get_user_by_id(str(user_id))
        user = result.user
        full_name = (user.user_metadata or {}).get("full_name") if user.user_metadata else None
        # last_sign_in_at answers the question the Super Admin roster
        # exists to answer: whether a backup admin has ever actually been
        # used. An account that has never signed in satisfies "two admins
        # exist" on paper while being unproven in practice, which is the
        # failure docs/SUPER_ADMIN_MFA_RUNBOOK.md's precondition is for.
        last_sign_in = getattr(user, "last_sign_in_at", None)
        return {
            "full_name": full_name,
            "email": user.email,
            "last_sign_in_at": str(last_sign_in) if last_sign_in else None,
        }
    except Exception:  # noqa: BLE001 - deliberately broad: a deleted user, a
        # network hiccup, or malformed metadata should all degrade to "no
        # name" rather than break the enclosing admin list request.
        return {"full_name": None, "email": None, "last_sign_in_at": None}


# Supabase Auth has no "get these N users" call, so a display name costs
# one request per user. Twelve at a time turns a 100-row admin page from a
# hundred round trips end to end into about nine, which is the difference
# between a page that feels broken and one that does not. Higher is not
# obviously better: these all hit the same Auth endpoint, and the ceiling
# is there to stay a good citizen of it rather than to pace this process.
_PROFILE_FETCH_WORKERS = 12


def batch_user_profiles(client: Client, user_ids: set[str]) -> dict[str, dict]:
    """user_id -> profile, for joining display names onto an admin list.

    This used to be a dict comprehension calling best_effort_user_profile
    once per id, which read as a batch helper but was a plain N+1: every
    Super Admin list page paid one sequential network round trip per row
    it displayed. At a hundred rows that was most of a page load, and it
    got worse as the platform grew — the Business Users page was the one
    where it showed first.

    Threads rather than async because the Supabase client is synchronous
    and these call sites are sync FastAPI routes; making them async would
    mean changing every caller. The work is pure network wait, so threads
    cost nothing to have and the GIL is not involved.

    Failure is still per-user and still silent: best_effort_user_profile
    swallows its own errors, so one deleted account cannot fail the list
    or poison the pool.
    """
    ids = [str(user_id) for user_id in user_ids if user_id]
    if not ids:
        return {}
    if len(ids) == 1:
        # Not worth a pool, and keeps the common single-row path identical.
        return {ids[0]: best_effort_user_profile(client, ids[0])}

    with ThreadPoolExecutor(max_workers=min(_PROFILE_FETCH_WORKERS, len(ids))) as pool:
        profiles = pool.map(lambda user_id: best_effort_user_profile(client, user_id), ids)
        return dict(zip(ids, profiles, strict=True))
