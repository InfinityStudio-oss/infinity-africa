"""Gives an abandoned mobile money push a terminal answer.

A customer who dismisses the prompt, walks away, or mistypes their PIN
leaves the collection `processing` with Selcom reporting `PENDING`, and
nothing has ever changed that. The oldest such row on this platform is
from 2026-08-16. Three separate things went wrong because of it:

- An integrator told to wait for `collection.success` or
  `collection.failed` waited forever. For a billing platform that is the
  worst possible answer: a subscriber's payment neither succeeds nor
  fails, so the account sits in limbo and no human is ever prompted.
- `reconcile_pending_checkout_collections` re-polls every `processing`
  collection on every pass with no age limit, so each abandoned push
  permanently consumes a slice of a shared, rate-limited provider budget
  that real payments need.
- `expired` already existed in the failure-reason vocabulary
  (app/services/failure_reasons.py), was documented to partners, and
  nothing ever set it.

## Why this is careful rather than a one-line status update

`resolve_collection()` no-ops on any collection that is not `processing`.
So marking an abandoned push `failed` also makes it permanently
un-creditable: if the provider later reports it paid, the debit has left
the customer's wallet and the merchant will never be paid. That is a real
money loss, caused by us, on a payment that actually succeeded.

Two things guard against it, in order:

1. **A live check before expiring.** Every candidate gets one final
   authenticated status call, through the same
   `refresh_checkout_collection_status` path the manual Refresh Status
   button uses. A collection the provider has quietly settled resolves
   normally and is never expired.

2. **A grace window after expiring.** For
   `collection_push_expiry_grace_hours` afterwards we keep asking. If the
   provider changes its mind, the collection is put back to `processing`
   and settled through the ordinary path, which credits the wallet and
   emits `collection.success`. Only once the window closes do we stop
   asking, which is what bounds the polling cost.

A partner can therefore see `collection.failed` followed later by
`collection.success` for one collection. That is rare and it is the
honest ordering: we said what we believed at the time, and corrected it
when the provider told us otherwise. The alternative is keeping quiet for
24 hours, which helps nobody.

Set `collection_push_expiry_minutes` to 0 to turn expiry off entirely.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from supabase import Client

from app.config.settings import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.services.checkout_reconciliation import (
    map_checkout_status_to_provider_status,
    refresh_checkout_collection_status,
)
from app.services.collections import resolve_collection
from app.services.crud import get_by_id, update_row
from app.services.selcom.schemas import CollectionResult
from app.services.selcom_checkout.client import (
    SelcomCheckoutHTTPClient,
    get_selcom_checkout_credentials,
)

logger = logging.getLogger("infinity.collection_expiry")

# The reason this platform decided on its own, with no provider status
# behind it. normalize_failure_reason()'s `internal_reason` hook maps it
# to the documented `expired` code and its merchant-safe sentence —
# deliberately NOT by passing provider_payment_status="EXPIRED", which
# would record that Selcom said something it never said.
_INTERNAL_REASON = "expired"


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _parse_ts(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    # A naive timestamp compares as UTC rather than raising, which is what
    # the column actually holds.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _expiry_candidates(client: Client, *, cutoff: datetime, limit: int) -> list[dict]:
    """Pushes old enough to have been abandoned. Oldest first, so a long
    backlog drains in a stable order across sweeps instead of the same
    rows being retried while newer ones are never reached."""
    rows = (
        client.table("collections")
        .select("id, merchant_id, status, created_at, checkout_order_id, provider, provider_reference")
        .eq("status", "processing")
        .lt("created_at", _iso(cutoff))
        .order("created_at", desc=False)
        .execute()
        .data
        or []
    )
    return rows[:limit]


def _recheck_candidates(client: Client, *, since: datetime, until: datetime, limit: int) -> list[dict]:
    """Expired collections still inside the grace window, and expired long
    enough ago to be worth asking about again.

    `until` matters: without it, a collection expired moments earlier in
    this very sweep would be re-queried immediately, spending a second
    provider call to be told what we were just told. Waiting one expiry
    window between the two questions costs nothing — the grace window is
    measured in hours.
    """
    rows = (
        client.table("collections")
        .select("id, merchant_id, status, failed_at, checkout_order_id, failure_reason_code")
        .eq("status", "failed")
        .eq("failure_reason_code", _INTERNAL_REASON)
        .gt("failed_at", _iso(since))
        .lt("failed_at", _iso(until))
        .order("failed_at", desc=False)
        .execute()
        .data
        or []
    )
    return [row for row in rows if row.get("checkout_order_id")][:limit]


def _mark_expired(client: Client, collection: dict) -> None:
    """Routed through resolve_collection rather than a direct update so an
    expiry is indistinguishable from any other failure: the transaction
    row moves too, a linked payment link or invoice is updated, and
    `collection.failed` is enqueued by the same code path every other
    failure uses."""
    resolve_collection(
        client,
        collection_id=uuid.UUID(collection["id"]),
        result=CollectionResult(
            provider=collection.get("provider") or "selcom_checkout",
            provider_reference=collection.get("provider_reference") or "",
            status="failed",
            failure_reason=_INTERNAL_REASON,
        ),
    )


async def _provider_now_reports_paid(collection: dict) -> bool:
    """Read-only. Nothing is written until we know the answer, so a
    collection is never briefly reopened on the strength of a call that
    then fails."""
    order_id = collection.get("checkout_order_id")
    if not order_id:
        return False
    checkout_client = SelcomCheckoutHTTPClient(credentials=get_selcom_checkout_credentials())
    status_result = await checkout_client.get_order_status(order_id=str(order_id))
    outcome = map_checkout_status_to_provider_status(
        payment_status=status_result.payment_status,
        result=status_result.result,
        resultcode=status_result.resultcode,
    )
    return outcome == "successful"


async def expire_stale_pushes(client: Client) -> dict[str, int]:
    """One sweep. Never raises: it runs on a scheduler alongside payment
    traffic, and one malformed row must not stop the rest."""
    settings = get_settings()
    window_minutes = settings.collection_push_expiry_minutes
    summary = {"candidates": 0, "expired": 0, "resolved_instead": 0, "recovered": 0, "errors": 0}
    if window_minutes <= 0:
        return summary

    now = datetime.now(timezone.utc)
    limit = max(1, settings.collection_push_expiry_batch_size)

    candidates = _expiry_candidates(client, cutoff=now - timedelta(minutes=window_minutes), limit=limit)
    summary["candidates"] = len(candidates)

    stuck_cutoff = now - timedelta(hours=max(1, settings.collection_push_expiry_grace_hours))

    for row in candidates:
        collection_id = uuid.UUID(row["id"])
        try:
            # The last word before we call it dead. A collection with no
            # linked checkout order cannot be asked about at all, so it is
            # expired on age alone.
            if row.get("checkout_order_id"):
                refreshed = await refresh_checkout_collection_status(client, collection_id=collection_id)
                if refreshed and refreshed.get("status") != "processing":
                    summary["resolved_instead"] += 1
                    continue
        except (NotFoundError, ConflictError) as exc:
            logger.warning("collection_expiry_skipped collection_id=%s reason=%s", collection_id, exc)
            continue
        except Exception:
            # The check itself failed, so we have no provider answer at
            # all. Usually transient (their API is down, we are rate
            # limited), and the right response to that is to wait.
            #
            # But it is not always transient. A collection whose
            # Selcom-reported provider_reference collides with another
            # row's raises here on EVERY attempt and can never be
            # resolved — confirmed live 2026-08-28, and the row that
            # found it was still erroring a month later, polled every
            # tick, its merchant never told anything. Unresolvable is
            # exactly what expiry is for.
            #
            # Age is what separates the two. A provider outage makes every
            # check fail at once, including on pushes minutes old, and
            # those are left alone. Only a push that has been failing this
            # check for longer than the grace window is closed on a
            # failure, by which point "transient" no longer describes it.
            if not _parse_ts(row.get("created_at")) or _parse_ts(row["created_at"]) > stuck_cutoff:
                summary["errors"] += 1
                logger.exception("collection_expiry_check_failed collection_id=%s", collection_id)
                continue
            logger.warning(
                "collection_expiry_closing_unresolvable collection_id=%s created_at=%s "
                "reason=provider_check_has_failed_since_before_grace_window",
                collection_id,
                row.get("created_at"),
            )

        try:
            current = get_by_id(client, "collections", collection_id)
            if not current or current.get("status") != "processing":
                summary["resolved_instead"] += 1
                continue

            _mark_expired(client, current)
            summary["expired"] += 1
            logger.info(
                "collection_expired collection_id=%s created_at=%s age_minutes=%s",
                collection_id,
                row.get("created_at"),
                window_minutes,
            )
        except (NotFoundError, ConflictError) as exc:
            logger.warning("collection_expiry_skipped collection_id=%s reason=%s", collection_id, exc)
        except Exception:
            summary["errors"] += 1
            logger.exception("collection_expiry_failed collection_id=%s", collection_id)

    summary["recovered"] = await _recover_late_payments(
        client, now=now, limit=limit, quiet_period=timedelta(minutes=window_minutes)
    )
    return summary


async def _recover_late_payments(
    client: Client, *, now: datetime, limit: int, quiet_period: timedelta
) -> int:
    """The half that protects the customer. See this module's docstring
    for why an expired collection cannot simply be re-resolved in place."""
    grace_hours = get_settings().collection_push_expiry_grace_hours
    if grace_hours <= 0:
        return 0

    candidates = _recheck_candidates(
        client, since=now - timedelta(hours=grace_hours), until=now - quiet_period, limit=limit
    )
    recovered = 0
    for row in candidates:
        collection_id = uuid.UUID(row["id"])
        try:
            if not await _provider_now_reports_paid(row):
                continue
            # Reopened only now that the provider has actually said paid.
            # If this process dies between here and the refresh below, the
            # collection is back in its original `processing` state and the
            # next sweep expires it again — no state is stranded.
            update_row(client, "collections", collection_id, {"status": "processing"})
            await refresh_checkout_collection_status(client, collection_id=collection_id)
            recovered += 1
            logger.warning(
                "collection_expiry_recovered_late_payment collection_id=%s merchant_id=%s",
                collection_id,
                row.get("merchant_id"),
            )
        except (NotFoundError, ConflictError) as exc:
            logger.warning("collection_expiry_recheck_skipped collection_id=%s reason=%s", collection_id, exc)
        except Exception:
            logger.exception("collection_expiry_recheck_failed collection_id=%s", collection_id)
    return recovered
