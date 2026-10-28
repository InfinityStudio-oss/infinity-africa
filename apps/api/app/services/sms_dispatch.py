"""The worker that actually sends queued SMS.

Runs as a sweep on a timer, like every other background job here, and
holds the 'sms_dispatch' scheduler lease so exactly one replica is
dispatching at any moment. That single fact is what makes two other things
correct: the in-process rate limiter is genuinely the account-wide limiter,
and row claiming does not have to contend with a second worker.

**Nothing in this module can affect a payment.** It reads sms_messages,
calls the provider and writes sms_messages. It never touches a ledger
table, a transaction, a collection status or a webhook event. A provider
outage leaves rows queued and nothing else.

**Recovering from a crash.** A row claimed and then abandoned (the worker
died mid-send) has its lock expire and returns to the queue. It is then
retried with the same idempotency key it was first sent with - the key
lives on the row, written before the first attempt - so the provider
recognises the replay and nothing is sent twice. A crash between the
provider accepting and us saving the result is therefore recoverable
rather than a duplicate, which is the specific hazard the brief names.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from supabase import Client

from app.config import get_settings
from app.core.time import utc_now_iso
from app.services.sms_provider import (
    RateLimitExceededError,
    SmsNotConfigured,
    SmsResult,
    reserve_send_slot,
    send_sms,
)

logger = logging.getLogger("infinity.sms")

# Every purpose the worker will dispatch, most urgent first, paired with
# the budget it draws from. Must stay in step with the purposes
# app/services/sms_messages.py enqueues and the check constraint in
# 20261017140000 - a purpose missing from here is a message that queues
# and is never sent.
#
# This is deliberately the ONLY list. It was two: this constant and a
# second copy inside dispatch_pending_sms, and the Super Admin alerts
# added on 2026-10-28 were put in neither. Both alerts enqueued
# correctly, the row appeared in the Super Admin screen with its real
# recipient, and nothing ever claimed it - the first live withdrawal
# alert sat queued while the queue reported itself healthy. The same
# failure had already happened once, to welcome and withdrawal_complete,
# which is what the paragraph below was written about.
#
# The operator alerts come first: their whole purpose is to shorten the
# time a withdrawal waits for a human, so they must not queue behind a
# merchant announcement.
#
# 'collection_alert' is absent deliberately: retired 2026-10-17, and the
# migration cancels what was queued. Historical rows stay readable.
_DISPATCH_ORDER = (
    ("admin_withdrawal_request", "alerts"),
    ("admin_new_merchant", "alerts"),
    ("welcome", "alerts"),
    ("withdrawal_complete", "alerts"),
    ("announcement", "announcements"),
)
DISPATCHED_PURPOSES = tuple(purpose for purpose, _ in _DISPATCH_ORDER)

_WORKER = f"sms-{uuid.uuid4().hex[:8]}"

# Long enough for the provider's own 180s timeout plus room to save the
# result. Shorter than this and a slow-but-healthy send would have its row
# reclaimed while still in flight.
_LOCK_SECONDS = 300

# Stops at 5 attempts. Past that a message about a payment is too old to
# be worth sending, and the row stays visible in the Super Admin screen
# with its last error rather than retrying forever.
MAX_ATTEMPTS = 5

# Backoff per attempt. Deliberately short: a payment alert that arrives an
# hour late has lost most of its value.
_BACKOFF_SECONDS = {1: 60, 2: 300, 3: 900, 4: 3600}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _release_expired_claims(client: Client) -> int:
    """Return abandoned rows to the queue.

    A row in 'sending' whose lock has expired belongs to a worker that is
    no longer running. Retrying it is safe because the idempotency key is
    unchanged.
    """
    rows = (
        client.table("sms_messages")
        .update({"status": "queued", "locked_by": None, "locked_until": None})
        .eq("status", "sending")
        .lt("locked_until", _now().isoformat())
        .execute()
        .data
        or []
    )
    if rows:
        logger.info("sms_reclaimed_abandoned count=%d", len(rows))
    return len(rows)


def _claimable(client: Client, purpose: str, limit: int) -> list[dict]:
    now = _now().isoformat()
    return (
        client.table("sms_messages")
        .select("*")
        .eq("purpose", purpose)
        .in_("status", ["queued", "failed"])
        .lt("attempts", MAX_ATTEMPTS)
        .lte("next_attempt_at", now)
        .order("created_at")
        .limit(limit)
        .execute()
        .data
        or []
    )


def _claim(client: Client, row: dict) -> bool:
    """Take one row, or discover somebody already has it.

    The conditional update is the claim: filtering on the status we read
    means a row that changed underneath us matches nothing and we move on.
    Same mechanism as scheduler_lease._claim.
    """
    claimed = (
        client.table("sms_messages")
        .update(
            {
                "status": "sending",
                "locked_by": _WORKER,
                "locked_until": (_now() + timedelta(seconds=_LOCK_SECONDS)).isoformat(),
                "attempts": row.get("attempts", 0) + 1,
            }
        )
        .eq("id", row["id"])
        .eq("status", row["status"])
        .execute()
        .data
        or []
    )
    return bool(claimed)


def _record(client: Client, row: dict, result: SmsResult) -> None:
    """Write the outcome back.

    The row is unlocked in every branch: leaving a lock on a row whose
    outcome we already know would hold it out of the queue until the lock
    expired for no reason.
    """
    attempts = row.get("attempts", 0) + 1
    update: dict = {
        "locked_by": None,
        "locked_until": None,
        "provider_status": result.provider_status,
        "last_error": result.error,
    }
    if result.provider_sms_log_id:
        update["provider_sms_log_id"] = result.provider_sms_log_id
    if result.provider_ref:
        update["provider_ref"] = result.provider_ref
    if result.credits_used is not None:
        update["credits_used"] = result.credits_used

    if result.outcome in ("sent", "duplicate"):
        update["status"] = "sent"
        update["sent_at"] = utc_now_iso()
        update["last_error"] = None
    elif result.outcome == "pending":
        # Documented as most likely sent and charged. Terminal for us:
        # resending would be the duplicate we are trying to avoid. A
        # provider callback may later move it on.
        update["status"] = "pending"
    elif result.outcome in ("config", "no_credits"):
        # Visibly stuck rather than quietly churning. Neither improves by
        # being retried, and a retry storm against a 402 is exactly what
        # the brief warns about.
        update["status"] = "failed"
        update["next_attempt_at"] = (_now() + timedelta(days=3650)).isoformat()
        update["attempts"] = MAX_ATTEMPTS
    elif result.outcome == "throttled":
        update["status"] = "queued"
        # Does not count as an attempt: the provider refused to look at
        # it, and a documented 429 does not consume the idempotency key.
        update["attempts"] = row.get("attempts", 0)
        update["next_attempt_at"] = (
            _now() + timedelta(seconds=result.retry_after_seconds or 60)
        ).isoformat()
    elif result.outcome == "unknown":
        # We do not know whether it was sent. Retried with the same key,
        # never a new one - which is what makes retrying it safe.
        update["status"] = "unknown" if attempts >= MAX_ATTEMPTS else "queued"
        update["next_attempt_at"] = _next_attempt(attempts)
    else:  # failed
        update["status"] = "failed"
        update["next_attempt_at"] = _next_attempt(attempts)

    try:
        client.table("sms_messages").update(update).eq("id", row["id"]).execute()
    except Exception:  # noqa: BLE001 — the lock expires and the row returns
        logger.warning("sms_result_not_saved id=%s outcome=%s", row["id"], result.outcome)


def _next_attempt(attempts: int) -> str:
    """When this row becomes due again.

    Past the last backoff step the row has also hit MAX_ATTEMPTS, so the
    claim query excludes it on attempts alone; the far-future time is
    belt and braces rather than the mechanism.
    """
    delay = _BACKOFF_SECONDS.get(attempts)
    if delay is None:
        return (_now() + timedelta(days=3650)).isoformat()
    return (_now() + timedelta(seconds=delay)).isoformat()


def _dispatch_one(client: Client, row: dict) -> str:
    try:
        reserve_send_slot()
    except RateLimitExceededError:
        # Our own budget, not the provider's. Put it straight back.
        client.table("sms_messages").update(
            {
                "status": "queued",
                "locked_by": None,
                "locked_until": None,
                "attempts": row.get("attempts", 0),
            }
        ).eq("id", row["id"]).execute()
        return "rate_limited"

    result = send_sms(
        to=row["recipient_phone"],
        sender=row["sender_id"],
        message=row["body"],
        idempotency_key=row["idempotency_key"],
    )
    _record(client, row, result)
    return result.outcome


def dispatch_pending_sms(client: Client) -> dict:
    """One sweep. Returns a summary for the log line.

    Collection alerts are drained before announcements and get the larger
    share of the batch, so a 60-merchant announcement cannot leave a
    merchant's payment alert waiting behind it.
    """
    settings = get_settings()
    summary = {"reclaimed": 0, "alerts": 0, "announcements": 0, "outcomes": {}}

    if not settings.oasis_sms_enabled:
        return summary

    summary["reclaimed"] = _release_expired_claims(client)

    alert_budget = settings.oasis_sms_batch_size
    announcement_budget = min(
        settings.oasis_sms_announcement_batch_size, settings.oasis_sms_batch_size
    )

    # Transactional messages first, announcements after, so a bulk send
    # can never leave a merchant's payout confirmation waiting behind it.
    #
    # The order comes from _DISPATCH_ORDER rather than a copy kept here.
    # A copy is how two purposes have now been missed: the worker only
    # ever asks the database for the purposes it is told about, so one
    # left out of the list is not a message that fails, it is a message
    # nobody ever looks for. Adding a purpose means adding it to
    # _DISPATCH_ORDER, and test_sms_lifecycle asserts every purpose the
    # enqueue layer can write is in it.
    budgets = {"alerts": alert_budget, "announcements": announcement_budget}
    for purpose, key in _DISPATCH_ORDER:
        budget = budgets[key]
        if budget <= 0:
            continue
        for row in _claimable(client, purpose, budget):
            if not _claim(client, row):
                continue
            try:
                outcome = _dispatch_one(client, row)
            except SmsNotConfigured:
                # A deployment fault, not a per-message one. Stop the whole
                # sweep rather than marking everything failed.
                logger.error("sms_dispatch_not_configured")
                return summary
            except Exception:  # noqa: BLE001 — one bad row must not end the sweep
                logger.warning("sms_dispatch_error id=%s", row["id"])
                _record(client, row, SmsResult(outcome="unknown", error="Dispatcher error"))
                outcome = "unknown"
            summary[key] += 1
            summary["outcomes"][outcome] = summary["outcomes"].get(outcome, 0) + 1
            if outcome == "rate_limited":
                # Budget spent; the rest keep until the next sweep.
                return summary

    return summary
