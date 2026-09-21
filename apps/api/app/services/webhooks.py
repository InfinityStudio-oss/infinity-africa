"""Webhook event enqueueing + incoming Selcom webhook storage.

enqueue_webhook_event only *records* an OUTBOUND event (public.webhook_events,
status='pending') — it does not deliver it. Actual HTTP delivery with
retries/signing is future work for a background worker; this is the write
side that worker would read from.

store_incoming_selcom_event is the other direction: logging an INBOUND
delivery from Selcom to POST /v1/webhooks/selcom, in public.selcom_webhook_events.
"""

import hashlib
import hmac
import uuid
from typing import Any

from supabase import Client

from app.services.crud import execute_maybe_single, get_by_id, insert_row


def last_webhook_delivery(client: Client, merchant_id: uuid.UUID) -> dict | None:
    """Most recent webhook_events row for this merchant, or None if it's
    never had one. Not .maybe_single() — that requires exactly 0 or 1 rows
    match, but a merchant can have many; order + take the first instead,
    same pattern as services/onboarding.py's list_onboarding_submissions.
    Shared by the merchant's own GET /v1/merchant/webhook-config and the
    Super Admin GET /v1/admin/merchants/{id}/webhook-config."""
    rows = (
        client.table("webhook_events")
        .select("event_name, status, created_at")
        .eq("merchant_id", str(merchant_id))
        .order("created_at", desc=True)
        .execute()
    ).data or []
    return rows[0] if rows else None


def sign_outbound_payload(*, raw_body: bytes, secret: str) -> str:
    """HMAC-SHA256 over the raw JSON body, using the merchant's own
    webhook_secret — the signature a merchant's receiving endpoint should
    recompute and compare to verify a delivery genuinely came from InfinityPay.
    Same scheme as compute_selcom_signature, just the other direction."""
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def find_selcom_webhook_event(client: Client, event_id: str, *, provider: str = "selcom") -> dict | None:
    query = (
        client.table("selcom_webhook_events")
        .select("*")
        .eq("provider", provider)
        .eq("event_id", event_id)
        .maybe_single()
    )
    return execute_maybe_single(query)


def store_incoming_selcom_event(
    client: Client,
    *,
    event_id: str,
    event_type: str,
    raw_body: str,
    signature: str | None,
    signature_valid: bool,
    provider: str = "selcom",
    raw_headers: dict | None = None,
) -> tuple[dict, bool]:
    """Records an inbound Selcom webhook delivery. Returns (row, is_duplicate).

    (provider, event_id) is the idempotency key: checked first so a retried
    delivery of an event already stored short-circuits as a duplicate
    instead of reprocessing its side effects; the DB's own unique
    constraint is the backstop against a concurrent race on the same event.

    `provider` defaults to "selcom" (the original placeholder Checkout
    product's inbound events, POST /v1/webhooks/selcom) — pass
    "selcom_checkout" for the newer, confirmed-signing-scheme product's
    events (POST /v1/webhooks/selcom/checkout), so the two never collide
    on event_id even if both happened to reuse the same value.

    `raw_headers` — the caller's job to have already filtered out
    Authorization/Cookie/etc.; this function stores whatever it's given
    verbatim. Added specifically to diagnose an unexpected/rejected
    signature scheme (see selcom_checkout_webhook's docstring) — optional
    so the older /v1/webhooks/selcom call site doesn't need updating."""
    existing = find_selcom_webhook_event(client, event_id, provider=provider)
    if existing:
        return existing, True

    try:
        row = insert_row(
            client,
            "selcom_webhook_events",
            {
                "provider": provider,
                "event_id": event_id,
                "event_type": event_type,
                "raw_body": raw_body,
                "signature": signature,
                "signature_valid": signature_valid,
                "status": "received",
                "raw_headers": raw_headers,
            },
        )
    except Exception:
        existing = find_selcom_webhook_event(client, event_id, provider=provider)
        if existing:
            return existing, True
        raise

    return row, False


def enqueue_webhook_event(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    event_name: str,
    payload: dict[str, Any],
) -> dict | None:
    """No-ops (returns None) if the merchant hasn't configured a webhook_url,
    or if they've opted into a subset of events via webhook_subscribed_events
    and this event_name isn't in it. Null/empty subscribed_events means
    "all events" — the default, unchanged behavior for merchants who never
    touch that setting.

    Stamps `event` (the event_name) and `merchant_code` onto every outbound
    payload here, in this one choke point, rather than in each of the many
    per-event payload builders scattered across the codebase — merchant_code
    is identification only (not a secret, not an auth credential), added so
    a merchant's webhook receiver can attribute a delivery without a second
    API call back to InfinityPay."""
    merchant = get_by_id(client, "merchants", merchant_id)
    target_url = merchant.get("webhook_url") if merchant else None

    if not target_url:
        return None

    subscribed = merchant.get("webhook_subscribed_events") if merchant else None
    if subscribed and event_name not in subscribed:
        return None

    enriched_payload = {
        "event": event_name,
        "merchant_code": merchant.get("merchant_code") if merchant else None,
        **payload,
    }

    return insert_row(
        client,
        "webhook_events",
        {
            "merchant_id": str(merchant_id),
            "event_name": event_name,
            "payload": enriched_payload,
            "target_url": target_url,
            "status": "pending",
            "attempts": 0,
        },
    )
