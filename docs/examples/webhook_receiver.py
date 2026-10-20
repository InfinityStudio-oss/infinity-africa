"""Reference InfinityPay webhook receiver - for partner developers.

This file is an example for the *receiving* side, not part of the
InfinityPay API. Copy it, translate it, or read it and write your own. It
is deliberately dependency-free (standard library only) and
framework-agnostic: `handle_delivery` takes the raw bytes and the headers
your web framework gives you and returns an HTTP status code.

It is exercised by apps/api/tests/test_webhook_receiver_reference.py, so
the properties claimed below are tested rather than asserted. **That tests
this example - it does not test your integration.** Nobody should describe
a receiver as verified until their own code has been tested against these
same cases.

What InfinityPay sends
----------------------
POST, with a JSON body and these headers:

    Content-Type: application/json
    X-Infinity-Event: collection.successful
    X-Infinity-Delivery: 6f1c... (UUID; the stable identifier for this delivery)
    X-Infinity-Timestamp: 1792486252 (unix seconds)
    X-Infinity-Signature: <64 hex chars>   # only when a signing secret is configured

The signature is HMAC-SHA256 over the **raw request body bytes**, keyed
with your webhook signing secret, hex-encoded lowercase.

Four things worth knowing before you write the verification
-----------------------------------------------------------
1. **Sign the bytes you received, not the JSON you parsed.** Parsing and
   re-serialising changes key order and whitespace, and the signature will
   not match. Capture the raw body before any JSON middleware touches it.

2. **The timestamp is not covered by the signature.** Only the body is. So
   `X-Infinity-Timestamp` tells you when we think we sent it, but an
   attacker replaying a captured delivery can also replay the timestamp
   unchanged. Use it to discard obviously stale deliveries if you like,
   but **your real replay protection is deduplication on
   X-Infinity-Delivery**, which is inside your own records and cannot be
   forged into looking new.

3. **A delivery with no signature header is not trustworthy.** If your
   secret is configured, treat a missing signature as a rejection. Do not
   accept unsigned deliveries "for now" - that is the state this whole
   exercise is closing.

4. **Retries are normal and will repeat the same X-Infinity-Delivery.**
   InfinityPay retries on any non-2xx response and on timeouts. Return 2xx
   once you have *durably recorded* the event; do the slow work afterwards.
   If you fail after recording, return 2xx anyway and recover from your own
   records - otherwise a retry arrives and you must be certain you will not
   act twice.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Callable, Mapping, Protocol

# Reject deliveries older than this, if you choose to check at all. Generous
# on purpose: our retry schedule backs off, so a legitimate retry of an
# event we first tried hours ago is normal, and a tight window would throw
# away real payments.
MAX_AGE_SECONDS = 24 * 60 * 60


def verify_signature(*, raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    """True only if `signature_header` is the HMAC-SHA256 of these exact bytes.

    `compare_digest` rather than `==`: a plain comparison returns as soon
    as two bytes differ, and that timing difference leaks the expected
    value one character at a time to anyone who can measure it.
    """
    if not signature_header or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_header.strip().lower(), expected)


def is_fresh(timestamp_header: str | None, *, now: float | None = None) -> bool:
    """Advisory only - see point 2 in the module docstring. A missing or
    unparsable timestamp is not treated as a failure, because the signature
    does not cover it and rejecting on it would gain nothing."""
    if not timestamp_header:
        return True
    try:
        sent_at = int(timestamp_header)
    except (TypeError, ValueError):
        return True
    return abs((now if now is not None else time.time()) - sent_at) <= MAX_AGE_SECONDS


class DeliveryStore(Protocol):
    """Your database. Both methods must be durable before you return 2xx.

    `mark_seen` must be atomic and must return False if this delivery id
    was already recorded - a unique constraint on the delivery id is the
    simplest correct implementation:

        insert into infinitypay_deliveries (delivery_id) values (%s)
        on conflict (delivery_id) do nothing
        returning delivery_id

    and treat "no row returned" as already-seen. Checking first and
    inserting second is a race: two concurrent retries both read "not
    seen" and both activate service.
    """

    def mark_seen(self, delivery_id: str) -> bool: ...


def handle_delivery(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    secret: str,
    store: DeliveryStore,
    activate: Callable[[dict[str, Any]], None],
    expected_merchant_id: str,
    now: float | None = None,
) -> int:
    """Verify, deduplicate and act on one delivery. Returns an HTTP status.

    Return values and what InfinityPay does with them:

        200  accepted - we stop retrying this event
        400  malformed - we record the failure; retried per the schedule
        401  signature missing or wrong - treat as hostile
        200  duplicate - accepted, because a retry has succeeded already
    """
    # 1. Authenticate before parsing. A body that fails verification should
    #    never reach your JSON parser, let alone your business logic.
    if not verify_signature(
        raw_body=raw_body,
        signature_header=headers.get("X-Infinity-Signature"),
        secret=secret,
    ):
        return 401

    if not is_fresh(headers.get("X-Infinity-Timestamp"), now=now):
        return 400

    try:
        payload = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        return 400
    if not isinstance(payload, dict):
        return 400

    delivery_id = (headers.get("X-Infinity-Delivery") or "").strip()
    if not delivery_id:
        # Without it you cannot deduplicate, so you cannot safely act.
        return 400

    # 2. Only act on what you are expecting. An authentic event for another
    #    merchant, a different currency, or a payment that has not actually
    #    succeeded must not activate anything.
    if headers.get("X-Infinity-Event") != "collection.successful":
        # Authentic, just not an event this handler acts on.
        return 200
    if str(payload.get("merchant_id") or "") != expected_merchant_id:
        return 400
    if str(payload.get("status") or "").lower() != "successful":
        return 200
    if str(payload.get("currency") or "") != "TZS":
        return 400
    reference = str(payload.get("reference") or "").strip()
    if not reference:
        return 400
    try:
        amount = float(payload["amount"])
    except (KeyError, TypeError, ValueError):
        return 400
    if amount <= 0:
        return 400

    # 3. Claim the delivery id, then act. This ordering is what makes a
    #    retry safe: the second arrival loses the race to claim and returns
    #    without activating anything.
    if not store.mark_seen(delivery_id):
        return 200

    activate(
        {
            "reference": reference,
            "amount": amount,
            "currency": payload.get("currency"),
            "merchant_id": payload.get("merchant_id"),
        }
    )
    return 200
