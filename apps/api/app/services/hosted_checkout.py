"""Selcom Checkout hosted-checkout collections — the default path as of
2026-08-23: Infinity no longer asks a merchant or customer to choose a
channel (USSD_PUSH/STK_PUSH/SELCOM_PESA_PUSH/DYNAMIC_QR); every
collection now sends the customer straight to Selcom's own hosted
checkout page (`payment_gateway_url` from create-order-minimal), which
shows whichever methods are enabled on the merchant's Selcom account —
some methods are confirmed not enabled on the account, and nothing here
(or anywhere else) filters or excludes anything based on that: it's
Selcom's hosted page's job to show only what's enabled, never ours.

Two entry points:
- execute_hosted_checkout_collection(): the Merchant Portal's own
  "Request Collection" — a standalone collection, not necessarily tied
  to any payment link.
- execute_hosted_checkout_for_payment_link(): the customer-facing "Pay
  securely" button on a public payment link — reuses the same
  create-order-minimal order shell wallet_push.py/dynamic_qr.py use,
  idempotent the same way.

**Neither function ever credits a merchant, posts a ledger entry, or
marks a payment_link PAID.** The collection stays "processing" until a
webhook or manual refresh (app/services/checkout_reconciliation.py)
confirms payment_status=COMPLETED — see
docs/selcom-checkout-collections.md. Every collection left "processing"
here gets a linked `transactions` row (create_processing_transaction),
same reason wallet_push.py/dynamic_qr.py need one: resolve_collection()
requires exactly one to post ledger entries against once resolution
happens.
"""

import uuid
from decimal import Decimal

from supabase import Client

from app.core.phone import normalize_tz_phone
from app.core.time import utc_now_iso
from app.services.checkout_orders import (
    create_checkout_order_minimal,
    get_or_create_checkout_order_for_payment_link,
)
from app.services.collection_source import (
    resolve_invoice_id_for_payment_link,
    resolve_payment_link_collection_source,
)
from app.services.collections import create_processing_transaction
from app.services.crud import execute_maybe_single, insert_row

_METHOD_LABEL = "HOSTED_CHECKOUT"

# Selcom's create-order-minimal requires *a* buyer_phone even when the
# customer/merchant never supplied one for this flow — nothing here ever
# sends anything to this number. Mirrors app/services/dynamic_qr.py's
# identical placeholder convention (and checkout_orders.py's placeholder
# buyer_email).
_PLACEHOLDER_BUYER_PHONE = "255700000000"
_PLACEHOLDER_BUYER_EMAIL_DOMAIN = "customers.infinitypay.me"


def _insert_failed_order_collection(client: Client, base_row: dict, order: dict) -> dict:
    return insert_row(
        client,
        "collections",
        {
            **base_row,
            "status": "failed",
            "failure_reason": "Could not create the payment order with the provider",
            "provider_resultcode": order.get("provider_result_code"),
            "provider_result": order.get("provider_result"),
            "provider_message": order.get("provider_message"),
            "raw_response": order.get("raw_response") or {},
        },
    )


async def execute_hosted_checkout_collection(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    amount: Decimal,
    currency: str,
    customer_id: uuid.UUID | None = None,
    customer_name: str | None = None,
    customer_email: str | None = None,
    customer_phone: str | None = None,
    merchant_reference: str | None = None,
    description: str | None = None,
    invoice_id: uuid.UUID | None = None,
) -> dict:
    """Merchant Portal "Request Collection" — a standalone collection, not
    tied to any payment link. Always creates a fresh Selcom order (no
    existing-attempt reuse the way a persistent payment link has, since
    there's no persistent resource here to reuse against beyond the
    router's own Idempotency-Key replay)."""
    buyer_phone = normalize_tz_phone(customer_phone) if customer_phone else _PLACEHOLDER_BUYER_PHONE
    buyer_name = customer_name or "InfinityPay Customer"
    buyer_email = customer_email or f"collection-{uuid.uuid4()}@{_PLACEHOLDER_BUYER_EMAIL_DOMAIN}"

    order = await create_checkout_order_minimal(
        client,
        merchant_id=merchant_id,
        buyer_email=buyer_email,
        buyer_name=buyer_name,
        buyer_phone=buyer_phone,
        amount=amount,
        currency=currency,
        no_of_items=1,
        merchant_reference=merchant_reference,
    )

    base_row = {
        "merchant_id": str(merchant_id),
        "customer_id": str(customer_id) if customer_id else None,
        "invoice_id": str(invoice_id) if invoice_id else None,
        "merchant_reference": merchant_reference,
        "checkout_order_id": order["id"],
        "method": _METHOD_LABEL,
        "amount": str(amount),
        "currency": currency,
        "customer_phone": customer_phone,
        "provider": "selcom",
        "initiated_at": utc_now_iso(),
    }

    if order["status"] != "created":
        return _insert_failed_order_collection(client, base_row, order)

    collection = insert_row(
        client,
        "collections",
        {
            **base_row,
            "status": "processing",
            "provider_reference": order.get("provider_reference"),
            "provider_result": order.get("provider_result"),
            "provider_resultcode": order.get("provider_result_code"),
            "raw_response": order.get("raw_response") or {},
        },
    )

    create_processing_transaction(
        client,
        merchant_id=merchant_id,
        method=_METHOD_LABEL,
        collection_id=collection["id"],
        provider_reference=order.get("provider_reference") or order["order_id"],
        amount=amount,
        currency=currency,
    )

    return {**collection, "payment_gateway_url": order.get("payment_gateway_url")}


async def execute_hosted_checkout_for_payment_link(
    client: Client, *, payment_link: dict, customer_phone: str | None
) -> dict:
    """The customer-facing "Pay securely" button. Idempotent beyond the
    router's Idempotency-Key header, same as wallet_push.py/dynamic_qr.py:
    re-requesting checkout for a payment link that already has an attempt
    in flight or resolved returns that existing collection rather than
    creating a second Selcom order."""
    payment_link_id = payment_link["id"]

    existing_collection = execute_maybe_single(
        client.table("collections")
        .select("*")
        .eq("payment_link_id", payment_link_id)
        .eq("method", _METHOD_LABEL)
        .in_("status", ["processing", "successful"])
        .order("created_at", desc=True)
        .range(0, 0)
        .maybe_single()
    )
    if existing_collection:
        return existing_collection

    real_phone = customer_phone or payment_link.get("customer_phone")
    buyer_phone = normalize_tz_phone(real_phone) if real_phone else _PLACEHOLDER_BUYER_PHONE

    order = await get_or_create_checkout_order_for_payment_link(
        client, payment_link=payment_link, buyer_phone=buyer_phone
    )

    merchant_id = uuid.UUID(payment_link["merchant_id"])
    base_row = {
        "merchant_id": str(merchant_id),
        "payment_link_id": payment_link_id,
        "checkout_order_id": order["id"],
        "method": _METHOD_LABEL,
        "amount": str(payment_link["amount"]),
        "currency": payment_link["currency"],
        "customer_phone": real_phone,
        "provider": "selcom",
        "initiated_at": utc_now_iso(),
        "source": resolve_payment_link_collection_source(client, payment_link=payment_link).value,
        "api_key_id": payment_link.get("api_key_id"),
        "invoice_id": resolve_invoice_id_for_payment_link(client, payment_link_id=payment_link_id),
    }

    if order["status"] != "created":
        return _insert_failed_order_collection(client, base_row, order)

    collection = insert_row(
        client,
        "collections",
        {
            **base_row,
            "status": "processing",
            "provider_reference": order.get("provider_reference"),
            "provider_result": order.get("provider_result"),
            "provider_resultcode": order.get("provider_result_code"),
            "raw_response": order.get("raw_response") or {},
        },
    )

    create_processing_transaction(
        client,
        merchant_id=merchant_id,
        method=_METHOD_LABEL,
        collection_id=collection["id"],
        provider_reference=order.get("provider_reference") or order["order_id"],
        amount=Decimal(str(payment_link["amount"])),
        currency=payment_link["currency"],
    )

    return {**collection, "payment_gateway_url": order.get("payment_gateway_url")}
