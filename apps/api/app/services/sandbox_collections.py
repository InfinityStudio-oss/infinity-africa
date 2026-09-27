"""Sandbox collection simulation for the three direct server-to-server API
endpoints (POST /v1/collections/{wallet-push,selcom-pesa,qr}) — the only
collection-creation paths a sandbox-environment API key is ever routed
to. Never calls Selcom, never inserts a linked `transactions` row, so
resolve_collection()'s ledger-posting path is structurally unreachable
for anything created here — sandbox activity cannot touch a real wallet
balance by construction, not by a runtime check that could be bypassed
or forgotten elsewhere.

TODO (documented gap, not attempted here): this only covers the direct
API push/QR endpoints, the ones a merchant's own backend is expected to
call per the "integrate into your backend" business case. The "Infinity
Payment Page" flow (POST /v1/collections -> a payment_links row -> the
public customer-facing /pay/{slug} page) is NOT sandbox-aware — an
API-created payment link always goes through the real payment flow
regardless of the creating key's environment, since that page is
rendered and driven by Infinity itself, not the merchant's backend, and
extending simulation there would mean teaching the public,
unauthenticated pay endpoint to know a payment link's origin
environment. Out of scope for this pass.
"""

import logging
import uuid
from decimal import Decimal

from supabase import Client

from app.core.references import generate_reference
from app.core.time import utc_now_iso
from app.services.crud import insert_row
from app.services.webhooks import enqueue_webhook_event

logger = logging.getLogger("infinity.sandbox_collections")

# The external status vocabulary the public API reports, mirroring
# app/services/collections_api.py::to_external_status.
_INTERNAL_TO_EXTERNAL_STATUS: dict[str, str] = {
    "successful": "successful",
    "failed": "failed",
    "pending_review": "pending_clearance",
    "reversed": "reversed",
}

_SIMULATE_TO_INTERNAL_STATUS: dict[str, str] = {
    "successful": "successful",
    "failed": "failed",
    "pending_clearance": "pending_review",
    "reversed": "reversed",
}

_EXTERNAL_METHOD_TO_INTERNAL: dict[str, str] = {
    "wallet_push": "STK_PUSH",
    "selcom_pesa": "SELCOM_PESA_PUSH",
    "qr": "DYNAMIC_QR",
}

_TERMINAL_STATUSES = {"successful", "failed", "reversed"}

# The event a real collection of this status would emit (see
# app/services/collections.py::resolve_collection). A sandbox collection
# emits the same ones so a partner can exercise their real webhook handler
# without spending money — which was otherwise impossible: Send Test
# Webhook only ever sends the one fixed test payload, and a live push costs
# real TZS.
_STATUS_TO_EVENT: dict[str, str] = {
    "successful": "collection.success",
    "failed": "collection.failed",
    "pending_review": "collection.pending_review",
}


def execute_sandbox_collection(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    external_method: str,
    amount: Decimal,
    currency: str,
    customer_phone: str | None,
    customer_name: str | None,
    merchant_reference: str | None,
    description: str | None,
    api_key_id: uuid.UUID,
    source: str,
    simulate_status: str | None,
) -> dict:
    """Creates a `collections` row with its FINAL status set directly —
    defaults to "successful" (a sandbox integration test should work by
    default without needing to know a magic value first), or whatever
    `simulate_status` asked for. No Selcom call, no transactions row."""
    internal_status = _SIMULATE_TO_INTERNAL_STATUS.get(simulate_status or "successful", "successful")
    now = utc_now_iso()
    sandbox_reference = f"SANDBOX-{uuid.uuid4().hex[:12].upper()}"

    row = insert_row(
        client,
        "collections",
        {
            "merchant_id": str(merchant_id),
            "environment": "sandbox",
            "method": _EXTERNAL_METHOD_TO_INTERNAL[external_method],
            "amount": str(amount),
            "currency": currency,
            "customer_phone": customer_phone,
            "merchant_reference": merchant_reference,
            "provider": "sandbox",
            "status": internal_status,
            "source": source,
            "api_key_id": str(api_key_id),
            "provider_reference": sandbox_reference,
            "provider_transid": generate_reference("SANDBOXTXN"),
            "initiated_at": now,
            "completed_at": now if internal_status in _TERMINAL_STATUSES else None,
            "failure_reason": "Simulated failure (sandbox)" if internal_status == "failed" else None,
            "metadata": {"sandbox": True, "customer_name": customer_name, "description": description},
        },
    )

    _emit_sandbox_webhook(client, merchant_id=merchant_id, collection=row, internal_status=internal_status)

    if external_method == "qr":
        row = {
            **row,
            "payment_token": f"SANDBOX-TOKEN-{uuid.uuid4().hex[:8].upper()}",
            "qr": f"00020101021226SANDBOXQR{sandbox_reference}",
        }
    return row


def _emit_sandbox_webhook(
    client: Client, *, merchant_id: uuid.UUID, collection: dict, internal_status: str
) -> None:
    """Queues the same event a real collection of this status would.

    Deliberately marked `"sandbox": true` in the payload. A partner must
    be able to tell a simulated event from a real one — the alternative is
    a sandbox test that looks identical to money actually arriving, which
    is the same footgun the `test` flag guards on Send Test Webhook.

    Best-effort: a sandbox collection is a simulation, and failing to queue
    its notification must not turn a successful 202 into a 500.
    """
    event_name = _STATUS_TO_EVENT.get(internal_status)
    if not event_name:
        return

    payload = {
        "collection_id": collection["id"],
        "reference": collection.get("merchant_reference"),
        "merchant_reference": collection.get("merchant_reference"),
        "amount": collection["amount"],
        "currency": collection["currency"],
        "status": _INTERNAL_TO_EXTERNAL_STATUS.get(internal_status, internal_status),
        "sandbox": True,
        "timestamp": utc_now_iso(),
    }
    if internal_status == "failed":
        payload["failure_reason_code"] = "unknown_provider_error"
        payload["failure_reason_message"] = "Simulated failure (sandbox)."

    try:
        enqueue_webhook_event(
            client, merchant_id=merchant_id, event_name=event_name, payload=payload
        )
    except Exception:
        logger.exception("sandbox webhook could not be queued collection_id=%s", collection.get("id"))
