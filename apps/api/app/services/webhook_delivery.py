"""Delivers the outbound merchant webhook queue.

`enqueue_webhook_event` (app/services/webhooks.py) has always written
`webhook_events` rows with `status='pending'`, and until now nothing ever
read them — its own docstring said delivery was "future work for a
background worker". This is that worker.

That gap mattered: a partner integrating against the Collections API is
told to wait for `collection.success` rather than trust the 202 from the
create call, and that event was never actually sent. Polling
GET /v1/collections/{id} was the only thing that worked.

Design notes:

**Signing is unchanged from the test-delivery endpoint.** The signature is
HMAC-SHA256 over the exact raw bytes POSTed, sent as `X-Infinity-Signature`
— identical to `POST /v1/merchant/webhook-config/test`. A partner whose
verification passes against a test delivery must not then fail against a
real one, so both paths use `sign_outbound_payload` over the same body
shape. `X-Infinity-Timestamp` is added alongside for replay windows; it is
deliberately NOT part of the signed material, because folding it in would
silently break every receiver that already verifies the test delivery.

**A merchant with no signing secret still gets delivered to.** The secret
is optional today and generating one is a separate merchant action;
refusing to deliver unsigned would turn "hasn't set a secret yet" into
"receives nothing", which is worse and harder to diagnose. Unsigned
deliveries simply carry no signature header.

**Failures back off and eventually stop.** Attempts are spaced by
`_BACKOFF_SECONDS` and capped at `_MAX_ATTEMPTS`, after which the row is
`failed` and never retried — a permanently broken endpoint must not be
retried forever against a live provider's traffic. The whole sequence
finishes in ten minutes; see `_BACKOFF_SECONDS` for why a longer tail was
measured to buy nothing.

**Delivery never blocks payment processing.** Nothing here is called from
a request path. The scheduler in app/main.py drives it, and every
exception is contained per event.

**One merchant's backlog cannot starve another's.** Two separate things
are needed for that, and the first version had neither:

*Waiting is not occupying.* The batch used to be sliced off the oldest
queued rows and only then filtered for which were actually due, so events
sitting out a retry backoff still held batch slots. One endpoint going
down was enough to fill all 50 with rows that were due in up to half an
hour, at which point the sweep delivered nothing at all — platform-wide,
to every merchant — until that cohort cleared. The scan window is now
wider than the batch and due-ness is decided before anything is taken.

*Fair share.* Even among genuinely due events, oldest-first means a
merchant with a large backlog takes the whole batch. Events are
interleaved round-robin across merchants instead, so each gets a turn.
A merchant queueing alone still gets the entire batch, since there is
nobody to interleave with.
"""

import json
import logging
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from itertools import zip_longest
from typing import Any

import httpx
from supabase import Client

from app.config import get_settings
from app.core.analytics import track
from app.core.monitoring import capture_message
from app.core.secret_box import decrypt_secret
from app.core.time import utc_now_iso
from app.services.crud import get_by_id, update_row
from app.services.security_alerts import should_alert_once
from app.services.webhooks import sign_outbound_payload

logger = logging.getLogger("infinity.webhook_delivery")

# Attempt 1 is immediate; the rest are spaced out. Five attempts, the last
# at ten minutes.
#
# It was [0, 60, 300, 900, 1800] — five attempts over 51 minutes. The long
# tail bought nothing. Measured on 2026-10-27 across 379 given-up
# deliveries: every single one failed all five times, and 96 of the day's
# 103 returned the identical status on every attempt. The failures this
# faces are deterministic — a handler that throws on a payload throws on
# it an hour later too — so the extra 41 minutes only delayed the moment
# anyone found out.
#
# Ten minutes still covers what the backoff is actually for: a receiver
# restart or a brief outage. What it stops costing is time-to-knowing. A
# merchant watching their Collections page now learns a delivery is in
# trouble in seconds and dead within ten minutes, instead of an hour.
#
# Resending stays the recovery for anything longer than that
# (POST /v1/admin/merchant-webhooks/{id}/resend), which is the right shape:
# retry briefly and automatically, recover deliberately.
_BACKOFF_SECONDS = [0, 30, 90, 180, 300]
_MAX_ATTEMPTS = len(_BACKOFF_SECONDS)

_TIMEOUT_SECONDS = 8.0

# Bounded so one sweep cannot spend unbounded time in a scheduler tick.
_BATCH_SIZE = 50

# How many queued rows a sweep will look at to find its batch. Larger than
# the batch on purpose: rows waiting out a backoff are skipped rather than
# delivered, so the scan has to be able to see past a block of them to the
# due events behind. Still bounded, so a pathological queue cannot make one
# sweep unbounded.
_SCAN_LIMIT = 500


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_due(event: dict, *, now: datetime) -> bool:
    """Whether this event's next attempt is owed yet."""
    attempts = int(event.get("attempts") or 0)
    if attempts >= _MAX_ATTEMPTS:
        return False
    last = _parse_ts(event.get("last_attempted_at"))
    if last is None:
        return True
    return now >= last + timedelta(seconds=_BACKOFF_SECONDS[attempts])


def _pending_events(client: Client) -> list[dict]:
    """The scan window, oldest first — NOT the batch. Slicing to the batch
    here is what used to let backed-off rows crowd out due ones."""
    rows = (
        client.table("webhook_events")
        .select("*")
        .in_("status", ["pending", "retrying"])
        .order("created_at", desc=False)
        .execute()
        .data
        or []
    )
    return rows[:_SCAN_LIMIT]


def _batch_fairly(due: list[dict]) -> list[dict]:
    """Round-robin the due events across merchants, then take the batch.

    `due` arrives oldest-first, so taking the head of it would hand the
    whole batch to whichever merchant queued earliest — normally the one
    with the largest backlog, which is exactly the merchant least able to
    absorb it and most likely to be failing. Interleaving gives every
    merchant with something waiting a slot in every sweep.

    Order within a merchant is preserved, so an individual receiver still
    sees its own events oldest-first. Events with no merchant_id (there
    should be none) group under one key rather than being dropped.
    """
    by_merchant: OrderedDict[str, list[dict]] = OrderedDict()
    for event in due:
        by_merchant.setdefault(str(event.get("merchant_id")), []).append(event)

    interleaved = [
        event
        for round_ in zip_longest(*by_merchant.values())
        for event in round_
        if event is not None
    ]
    return interleaved[:_BATCH_SIZE]


class SigningSecretUnavailableError(Exception):
    """A merchant has a signing secret that could not be decrypted.

    Distinct from "no secret configured", which is an ordinary state: a
    merchant who has never generated one receives unsigned deliveries by
    design. This is the other thing entirely — a merchant who *did*
    configure signing, whose receiver verifies it, and whose secret we
    cannot currently read.
    """


def _secret_for(client: Client, merchant_id: str) -> str | None:
    """The merchant's signing secret, or None if they have not set one.

    Raises SigningSecretUnavailableError if one is configured but cannot
    be decrypted.

    That distinction is the whole point. This used to swallow the failure
    and return None, which is the same value as "no secret configured" —
    so a merchant who had deliberately turned signing on would silently
    receive an **unsigned** delivery the moment decryption broke (a
    rotated or mismatched SECRET_BOX_KEY, corrupted ciphertext). Their
    receiver then either rejects it, losing a real payment notification,
    or accepts unsigned payloads — which means it would also accept a
    forged one.

    Failing the attempt instead is strictly better. The delivery retries
    on the normal schedule, the row stays visible as undelivered, and if
    the cause is a key that has been fixed in the meantime a later attempt
    simply succeeds. Nothing is silently downgraded.
    """
    merchant = get_by_id(client, "merchants", uuid.UUID(merchant_id))
    encrypted = merchant.get("webhook_secret_encrypted") if merchant else None
    if not encrypted:
        return None
    try:
        return decrypt_secret(encrypted)
    except Exception as exc:
        logger.exception("webhook secret could not be decrypted merchant_id=%s", merchant_id)
        raise SigningSecretUnavailableError(merchant_id) from exc


def deliver_event(client: Client, event: dict) -> bool:
    """POSTs one event and records the outcome. Returns True if delivered.

    Never raises: the caller is a scheduler sweeping a shared queue, and
    one merchant's unreachable endpoint must not stop the others.
    """
    event_id = uuid.UUID(event["id"])
    attempts = int(event.get("attempts") or 0) + 1
    target_url = event.get("target_url")

    if not target_url:
        update_row(
            client,
            "webhook_events",
            event_id,
            {"status": "failed", "attempts": attempts, "last_attempted_at": utc_now_iso()},
        )
        return False

    raw_body = json.dumps(event.get("payload") or {}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Infinity-Event": str(event.get("event_name") or ""),
        "X-Infinity-Delivery": str(event["id"]),
        "X-Infinity-Timestamp": str(int(datetime.now(timezone.utc).timestamp())),
    }
    try:
        secret = _secret_for(client, event["merchant_id"])
    except SigningSecretUnavailableError:
        # Configured to sign, and we cannot. Nothing is sent: an unsigned
        # delivery to a receiver that verifies signatures is either a lost
        # notification or, worse, proof that it accepts unsigned payloads.
        # The attempt is counted so this still backs off and eventually
        # stops rather than spinning, and the row stays visible as
        # undelivered. A later attempt succeeds by itself once the key is
        # fixed, because nothing about the event was changed.
        logger.error(
            "webhook delivery skipped: signing secret unavailable event=%s attempt=%s",
            event["id"],
            attempts,
        )
        if should_alert_once(
            f"signing_secret_unavailable:{event['merchant_id']}",
            window_seconds=get_settings().webhook_exhausted_alert_window_seconds,
        ):
            capture_message(
                "webhook signing secret could not be decrypted — delivery withheld",
                level="error",
                tags={"merchant_id": str(event["merchant_id"])},
            )
        update_row(
            client,
            "webhook_events",
            event_id,
            {
                "status": "failed" if attempts >= _MAX_ATTEMPTS else "retrying",
                "attempts": attempts,
                "last_attempted_at": utc_now_iso(),
                # No response_status_code: nothing was sent, so there is no
                # status to record. Writing one would invent a reply the
                # merchant's server never gave.
            },
        )
        return False

    if secret:
        headers["X-Infinity-Signature"] = sign_outbound_payload(raw_body=raw_body, secret=secret)

    status_code: int | None = None
    delivered = False
    try:
        response = httpx.post(target_url, content=raw_body, headers=headers, timeout=_TIMEOUT_SECONDS)
        status_code = response.status_code
        delivered = response.is_success
    except httpx.HTTPError as exc:
        # The receiver's URL is merchant-controlled, so the error text can
        # contain their host but never anything of ours. Logged at info:
        # an unreachable customer endpoint is an expected condition.
        logger.info(
            "webhook delivery failed event=%s attempt=%s error=%s",
            event["id"],
            attempts,
            type(exc).__name__,
        )

    if delivered:
        update_row(
            client,
            "webhook_events",
            event_id,
            {
                "status": "delivered",
                "attempts": attempts,
                "last_attempted_at": utc_now_iso(),
                "delivered_at": utc_now_iso(),
                "response_status_code": status_code,
            },
        )
        track(
            "webhook_delivered",
            merchant_id=event["merchant_id"],
            properties={"attempt": attempts, "http_status": status_code},
        )
        return True

    # Exhausted means genuinely give up; anything else is retried later.
    exhausted = attempts >= _MAX_ATTEMPTS
    update_row(
        client,
        "webhook_events",
        event_id,
        {
            "status": "failed" if exhausted else "retrying",
            "attempts": attempts,
            "last_attempted_at": utc_now_iso(),
            "response_status_code": status_code,
        },
    )
    if exhausted:
        logger.warning(
            "webhook delivery gave up event=%s merchant_id=%s attempts=%s last_status=%s",
            event["id"],
            event["merchant_id"],
            attempts,
            status_code,
        )
        # A merchant will now never receive this event, and there is no
        # replay. That is the failure this platform most wants to hear
        # about, and a warning line in Railway is easy to miss — so it
        # also goes to Sentry, where it can raise an alert. The target
        # URL is merchant-controlled text and is deliberately not included.
        #
        # Once per merchant per window, though, not once per event. A
        # single endpoint erroring 0.5% of the time produced about
        # eighteen identical alerts a day, every one of them describing
        # the same ongoing condition — which is how a genuinely new
        # failure gets lost among them. The row is still marked failed and
        # the warning above is still logged for every event; only the
        # alert is suppressed, and a merchant whose endpoint stays broken
        # still raises one every window.
        if should_alert_once(
            f"webhook_exhausted:{event['merchant_id']}",
            window_seconds=get_settings().webhook_exhausted_alert_window_seconds,
        ):
            capture_message(
                "webhook delivery exhausted — merchant will not receive this event",
                level="error",
                tags={"merchant_id": str(event["merchant_id"]), "last_status": str(status_code)},
            )
        track(
            "webhook_exhausted",
            merchant_id=event["merchant_id"],
            properties={"attempt": attempts, "http_status": status_code},
        )
    return False


def deliver_pending_webhooks(client: Client) -> dict[str, int]:
    """One sweep of the queue. Returns a small summary for the scheduler
    log — never raises, for the same reason deliver_event does not."""
    now = datetime.now(timezone.utc)
    due = _batch_fairly([event for event in _pending_events(client) if _is_due(event, now=now)])

    delivered = 0
    failed = 0
    for event in due:
        try:
            if deliver_event(client, event):
                delivered += 1
            else:
                failed += 1
        except Exception:
            failed += 1
            logger.exception("webhook delivery raised event=%s", event.get("id"))

    return {"due": len(due), "delivered": delivered, "failed": failed}
