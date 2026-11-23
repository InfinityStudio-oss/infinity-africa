"""What happened to one payment, from the evidence the platform records.

Built for one support conversation: "the customer paid, but my billing
system never switched their internet on". Three different questions hide
in that sentence and this module keeps them apart, because the answer to
each comes from a different place:

1. **Did the payment succeed?** - collections / transactions.
2. **Did the merchant's system hear about it?** - webhook_events, the
   outbound delivery log. A delivered event means the merchant's endpoint
   answered HTTP 2xx. That proves RECEIPT, nothing more.
3. **Did the merchant's system activate the service?** - nothing on this
   platform records that. No billing integration sends an activation
   acknowledgement back, so the honest answer is always "not confirmed",
   and the timeline says which system controls it.

Nothing here invents an event. A step with no recorded timestamp is shown
without one rather than with a guess, and the activation step can never
read as confirmed until a real, authenticated acknowledgement exists
(see docs/payment-tracking.md for what that would require).

**The shared reference is `collection_id`.** It is already returned by
every Collections API create call, by GET /v1/collections/{id}, and in
every collection.* webhook payload, so a billing system that integrated
at any point already stores it. Introducing another identifier would give
support two numbers to ask for and integrators one more to confuse.

What is deliberately NOT returned: webhook payloads, target URLs, signing
secrets, provider raw responses, provider status codes, customer details
beyond what the transaction list already shows, and anything from a
stack trace. A response status code is shown because it is the merchant's
OWN server's answer, and the one fact that tells them where to look.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from supabase import Client

from app.services.crud import get_by_id
from app.services.webhook_delivery import MAX_ATTEMPTS, next_attempt_at

logger = logging.getLogger("infinity.payment_tracking")

ACTIVATION_NOT_CONFIRMED = {
    "status": "not_confirmed",
    "label": "Service activation not confirmed",
    "detail": (
        "InfinityPay records whether your system received the payment notification, "
        "not whether it activated the customer's service. Activation is controlled by "
        "your billing system - check it using the InfinityPay Payment ID above."
    ),
}

# What each outbound delivery state means, in the words the timeline uses.
# `failed` is the worker's word for "every attempt used up" - shown as
# exhausted, because "failed" next to a successful payment reads as if the
# payment failed.
_DELIVERY_STATE = {
    "pending": "queued",
    "retrying": "retrying",
    "delivered": "delivered",
    "failed": "exhausted",
}

_DELIVERY_LABEL = {
    "queued": "Webhook queued",
    "retrying": "Webhook delivery retrying",
    "delivered": "Webhook delivered",
    "exhausted": "Webhook delivery exhausted",
}


def _iso(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _step(code: str, label: str, state: str, at: Any = None, detail: str | None = None) -> dict:
    """`state` is one of done / failed / waiting / unknown - what the UI
    colours by. `at` is only ever a timestamp the database holds."""
    return {"code": code, "label": label, "state": state, "at": _iso(at), "detail": detail}


def _money_out_source(client: Client, transaction: dict) -> dict | None:
    """The payout or withdrawal row behind a money-out transaction, pinned
    to the transaction's own merchant. None for anything else, including
    a payout-wallet top-up, which has no source row of its own.

    Read for two facts the ledger row does not carry: when the provider
    outcome was recorded (completed_at) and, for a payout, whether it was
    sandbox or live."""
    for column, table in (("payout_id", "payouts"), ("disbursement_id", "disbursements")):
        source_id = transaction.get(column)
        if not source_id:
            continue
        try:
            row = get_by_id(client, table, uuid.UUID(str(source_id)))
        except Exception:  # supplementary, never takes the panel down
            logger.warning("payment_tracking_source_unavailable table=%s", table, exc_info=True)
            return None
        if row and str(row.get("merchant_id")) == str(transaction["merchant_id"]):
            return {**row, "_table": table}
        return None
    return None


def _environment(source: dict | None) -> str | None:
    """sandbox / live, only where a row actually records it.

    Only payouts carry an environment. The transactions table has none,
    so a sandbox payout sits in the same ledger as live money and, until
    this, nothing on screen said which it was. A withdrawal or a payout-
    wallet top-up has no recorded environment and gets None - shown as no
    badge, never as a guess."""
    if source and source.get("_table") == "payouts":
        env = source.get("environment")
        return env if env in ("sandbox", "live") else None
    return None


def _payment_steps(collection: dict | None, transaction: dict, source: dict | None = None) -> list[dict]:
    if collection is None:
        # A withdrawal, payout, fee or adjustment: no customer payment
        # behind it. The ledger row, and the payout or withdrawal row it
        # points at, are the evidence there is.
        status = transaction.get("status")
        finished_at = source.get("completed_at") if source else None
        steps = [_step("initiated", "Transaction recorded", "done", transaction.get("created_at"))]
        if status == "successful":
            steps.append(_step("confirmed", "Transaction successful", "done", finished_at))
        elif status in ("failed", "cancelled", "reversed"):
            steps.append(
                _step(
                    status,
                    f"Transaction {status}",
                    "failed",
                    finished_at if source and source.get("_table") == "payouts" else None,
                )
            )
        else:
            steps.append(_step("awaiting", "Awaiting confirmation", "waiting"))
        return steps

    steps = [
        _step(
            "initiated",
            "Payment initiated",
            "done",
            collection.get("initiated_at") or collection.get("created_at"),
        )
    ]
    status = collection.get("status")
    if status == "successful":
        steps.append(_step("confirmed", "Payment confirmed", "done", collection.get("completed_at")))
    elif status == "reversed":
        steps.append(_step("confirmed", "Payment confirmed", "done", collection.get("completed_at")))
        # No reversed_at column exists, so no time is claimed for it.
        steps.append(
            _step(
                "reversed",
                "Payment reversed",
                "failed",
                detail="The provider reversed this payment after it was confirmed.",
            )
        )
    elif status == "failed":
        steps.append(
            _step(
                "failed",
                "Payment failed",
                "failed",
                collection.get("failed_at") or collection.get("completed_at"),
                # The merchant-safe sentence written for exactly this, never
                # the provider's own free text.
                detail=collection.get("failure_reason_message"),
            )
        )
    elif status == "cancelled":
        steps.append(
            _step(
                "cancelled",
                "Payment cancelled",
                "failed",
                collection.get("cancelled_at") or collection.get("failed_at"),
                detail=collection.get("failure_reason_message"),
            )
        )
    elif status == "pending_review":
        steps.append(
            _step(
                "awaiting",
                "Awaiting confirmation",
                "waiting",
                detail="Held for an InfinityPay review before it is credited.",
            )
        )
    else:
        steps.append(_step("awaiting", "Awaiting confirmation", "waiting"))
    return steps


def _deliveries(client: Client, *, merchant_id: str, collection_id: str) -> tuple[list[dict], bool]:
    """Every outbound delivery about this payment, oldest first.

    Scoped by merchant_id AND collection_id, so a caller cannot read
    another merchant's delivery history by passing a collection id they
    do not own. Returns (rows, available) - a failed lookup is reported as
    unavailable, never as "no deliveries", which would read as "you have
    no webhook".
    """
    try:
        rows = (
            client.table("webhook_events")
            .select("id, event_name, status, attempts, created_at, last_attempted_at, delivered_at, response_status_code")
            .eq("merchant_id", merchant_id)
            .eq("collection_id", collection_id)
            .order("created_at", desc=False)
            .execute()
            .data
        ) or []
    except Exception:
        logger.warning("payment_tracking_deliveries_unavailable collection_id=%s", collection_id, exc_info=True)
        return [], False

    out = []
    for row in rows:
        state = _DELIVERY_STATE.get(str(row.get("status")), "queued")
        attempts = int(row.get("attempts") or 0)
        if state == "queued" and attempts > 0:
            state = "retrying"
        out.append(
            {
                "event_name": row.get("event_name"),
                "state": state,
                "label": _DELIVERY_LABEL[state],
                "attempts": attempts,
                "max_attempts": MAX_ATTEMPTS,
                "queued_at": _iso(row.get("created_at")),
                "last_attempt_at": _iso(row.get("last_attempted_at")),
                "delivered_at": _iso(row.get("delivered_at")),
                "response_status": row.get("response_status_code"),
                "next_retry_at": _iso(next_attempt_at(row)),
            }
        )
    return out, True


def build_payment_tracking(client: Client, *, transaction: dict) -> dict:
    """The tracking view for one transaction row.

    The caller is responsible for having authorised access to
    `transaction` (merchant-scoped lookup, or Super Admin). Everything
    read here is then additionally pinned to that transaction's own
    merchant_id, so a mismatched collection or delivery row from another
    merchant can never be folded in.
    """
    merchant_id = str(transaction["merchant_id"])
    collection = None
    collection_id = transaction.get("collection_id")
    if collection_id:
        row = get_by_id(client, "collections", uuid.UUID(str(collection_id)))
        if row and str(row.get("merchant_id")) == merchant_id:
            collection = row

    source = None if collection is not None else _money_out_source(client, transaction)

    deliveries: list[dict] = []
    deliveries_available = True
    webhook_configured = False
    if collection is not None:
        merchant = get_by_id(client, "merchants", uuid.UUID(merchant_id)) or {}
        webhook_configured = bool(merchant.get("webhook_url"))
        deliveries, deliveries_available = _deliveries(
            client, merchant_id=merchant_id, collection_id=str(collection["id"])
        )

    return {
        "transaction_id": str(transaction["id"]),
        "environment": _environment(source),
        "identifiers": {
            # The one value to share with a billing system.
            "payment_id": str(collection["id"]) if collection else None,
            "merchant_reference": collection.get("merchant_reference") if collection else None,
            "transaction_reference": transaction.get("reference"),
            "provider_reference": transaction.get("provider_reference")
            or (collection.get("provider_reference") if collection else None),
        },
        "payment": _payment_steps(collection, transaction, source),
        "webhooks": {
            # Webhook delivery is only tracked for customer payments;
            # withdrawal events are not linked to a payment id.
            "applicable": collection is not None,
            "configured": webhook_configured,
            "available": deliveries_available,
            "deliveries": deliveries,
        },
        "service_activation": dict(ACTIVATION_NOT_CONFIRMED),
    }
