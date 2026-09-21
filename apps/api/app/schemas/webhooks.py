import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class WebhookEventResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    event_name: str
    payload: dict[str, Any]
    target_url: str
    status: str
    attempts: int
    last_attempted_at: datetime | None = None
    delivered_at: datetime | None = None
    response_status_code: int | None = None
    created_at: datetime
    updated_at: datetime


class SelcomWebhookPayload(BaseModel):
    """Body of an inbound POST /v1/webhooks/selcom delivery. Selcom only
    ever reports on its own domain events — collections and disbursements —
    since it has no concept of InfinityPay's payment_link/invoice entities;
    payment_link.paid/invoice.paid are separate, *outbound* events InfinityPay
    enqueues as a consequence of resolving a linked collection, not
    something Selcom itself sends. A real Selcom callback has its own
    documented shape — this is a reasonable placeholder the mock provider's
    design already fits."""

    event_id: str
    event_type: Literal[
        "collection.success",
        "collection.failed",
        "disbursement.success",
        "disbursement.failed",
        # "withdrawal.*" accepted as an alias of "disbursement.*" — the
        # client-facing name this task asked for on the incoming callback
        # literal. Both route through the same resolution path in
        # app/routers/webhooks.py; kept alongside "disbursement.*" (not a
        # replacement) since existing tests already send that name and it's
        # the real, working value.
        "withdrawal.success",
        "withdrawal.failed",
        "withdrawal.reversed",
    ]
    provider_reference: str
    failure_reason: str | None = None
