"""Which replica runs a background sweep.

The schedulers start in app/main.py's lifespan, so they start in every
replica. With one replica that has always been fine. With two, both would
sweep the same queue at once - and deliver_event POSTs a webhook *before*
recording the outcome, so both replicas would read the same pending event
and both send it. A merchant receiving collection.success twice can
activate a customer's service twice.

So each sweep asks for a lease first and skips its turn if another
replica holds it.

**A lost lease costs one skipped tick and never a wrong answer.** Every
sweep here is idempotent and runs on a timer: a webhook not delivered
this minute is delivered next minute, a withdrawal not reconciled now is
reconciled in two minutes. That is what makes it safe for every failure
in this module to mean "skip", which is also the only thing it can mean -
nothing here raises.

Why not pg_try_advisory_lock: see the migration. Through PostgREST a
session-scoped lock leaks on a pooled connection and a transaction-scoped
one releases before the sweep it guards has started.
"""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from supabase import Client

logger = logging.getLogger("infinity.scheduler")

# Identifies this process in the table. Random per boot and purely for
# reading during an incident - nothing branches on it.
_HOLDER = f"{os.getenv('RAILWAY_REPLICA_ID') or 'local'}-{uuid.uuid4().hex[:8]}"

# How long a lease is held before it is considered abandoned.
#
# Must exceed the longest a sweep can legitimately take, or a second
# replica starts while the first is still working - the exact thing this
# prevents. The webhook sweep is the slow one: up to 50 sequential POSTs
# at an 8 second timeout each, so several minutes in the worst case.
#
# The cost of it being too long is only that a crashed replica's sweep
# pauses until the lease expires, and every sweep here is on a timer
# anyway.
_LEASE_SECONDS = 600


def _already_free() -> datetime:
    """An expiry a moment in the past, so the very next claim succeeds.

    Writing "now" would leave the lease free only strictly after this
    instant, and a claim landing in the same clock tick - which is not
    hypothetical, two datetime.now() calls in a row can return the same
    microsecond - would compare equal, fail the `<`, and skip a sweep for
    no reason.
    """
    return datetime.now(timezone.utc) - timedelta(seconds=1)


def acquire_lease(client: Client, name: str) -> bool:
    """True if this replica may run `name` now.

    Takes the lease only when the current one has expired. Postgres
    serialises the two updates, so when replicas race, the loser's WHERE
    matches no rows and it returns False.

    Never raises. A database hiccup here returns False, which skips one
    tick - strictly safer than running a sweep twice.
    """
    now = datetime.now(timezone.utc)
    try:
        if _claim(client, name, now):
            return True
        # Nothing was updated. Either another replica holds the lease -
        # the normal case, and we skip this tick - or the row does not
        # exist at all.
        #
        # That second case has to be handled rather than treated as "no",
        # because of deploy ordering: if this code ships before its
        # migration, every lease lookup matches no row, every sweep skips
        # forever, and webhook delivery stops silently. A guard whose
        # failure mode is "the platform quietly stops working" is worse
        # than no guard. So create the row and try once more.
        if _lease_row_missing(client, name):
            _seed(client, name)
            return _claim(client, name, now)
        return False
    except Exception:  # noqa: BLE001 — a skipped tick beats a double sweep
        logger.warning("scheduler_lease_unavailable name=%s", name)
        return False


def _claim(client: Client, name: str, now: datetime) -> bool:
    """The whole mechanism, in one filter: only a lease nobody currently
    holds can be taken. Postgres serialises concurrent updates, so when
    replicas race the loser matches no rows."""
    result = (
        client.table("scheduler_leases")
        .update(
            {
                "holder": _HOLDER,
                "acquired_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=_LEASE_SECONDS)).isoformat(),
                "updated_at": now.isoformat(),
            }
        )
        .eq("name", name)
        .lt("expires_at", now.isoformat())
        .execute()
    )
    return bool(result.data)


def _lease_row_missing(client: Client, name: str) -> bool:
    rows = client.table("scheduler_leases").select("name").eq("name", name).execute().data or []
    return not rows


def _seed(client: Client, name: str) -> None:
    """Create a lease already expired, so the caller can take it.

    Two replicas booting together may both try this; the primary key
    makes one of them lose, and losing is fine - the row it wanted now
    exists either way.
    """
    try:
        client.table("scheduler_leases").insert(
            {"name": name, "expires_at": _already_free().isoformat()}
        ).execute()
    except Exception:  # noqa: BLE001 — the other replica created it first
        logger.info("scheduler_lease_seed_raced name=%s", name)


def release_lease(client: Client, name: str) -> None:
    """Hand the lease back so the next tick can start promptly.

    Only the holder releases, so a replica cannot cut short a sweep
    running somewhere else - which would reintroduce exactly the double
    delivery this exists to prevent.

    Never raises, and not releasing is harmless: the lease expires on its
    own and the next tick picks it up.
    """
    now = datetime.now(timezone.utc)
    try:
        (
            client.table("scheduler_leases")
            .update({"expires_at": _already_free().isoformat(), "updated_at": now.isoformat()})
            .eq("name", name)
            .eq("holder", _HOLDER)
            .execute()
        )
    except Exception:  # noqa: BLE001 — the lease expires by itself
        logger.warning("scheduler_lease_release_failed name=%s", name)
