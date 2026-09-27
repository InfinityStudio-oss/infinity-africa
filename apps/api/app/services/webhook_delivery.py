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
retried forever against a live provider's traffic.

**Delivery never blocks payment processing.** Nothing here is called from
a request path. The scheduler in app/main.py drives it, and every
exception is contained per event, so one merchant's dead endpoint cannot
stall the queue for everyone else.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from supabase import Client

from app.core.secret_box import decrypt_secret
from app.core.time import utc_now_iso
from app.services.crud import get_by_id, update_row
from app.services.webhooks import sign_outbound_payload

logger = logging.getLogger("infinity.webhook_delivery")

# Attempt 1 is immediate; the rest are spaced out. Five attempts over ~30
# minutes covers a receiver restart or a short outage without hammering an
# endpoint that is simply down.
_BACKOFF_SECONDS = [0, 60, 300, 900, 1800]
_MAX_ATTEMPTS = len(_BACKOFF_SECONDS)

_TIMEOUT_SECONDS = 8.0

# Bounded so one sweep cannot spend unbounded time in a scheduler tick.
_BATCH_SIZE = 50


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
    rows = (
        client.table("webhook_events")
        .select("*")
        .in_("status", ["pending", "retrying"])
        .order("created_at", desc=False)
        .execute()
        .data
        or []
    )
    return rows[:_BATCH_SIZE]


def _secret_for(client: Client, merchant_id: str) -> str | None:
    merchant = get_by_id(client, "merchants", uuid.UUID(merchant_id))
    encrypted = merchant.get("webhook_secret_encrypted") if merchant else None
    if not encrypted:
        return None
    try:
        return decrypt_secret(encrypted)
    except Exception:
        logger.exception("webhook secret could not be decrypted merchant_id=%s", merchant_id)
        return None


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
    secret = _secret_for(client, event["merchant_id"])
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
    return False


def deliver_pending_webhooks(client: Client) -> dict[str, int]:
    """One sweep of the queue. Returns a small summary for the scheduler
    log — never raises, for the same reason deliver_event does not."""
    now = datetime.now(timezone.utc)
    due = [event for event in _pending_events(client) if _is_due(event, now=now)]

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
