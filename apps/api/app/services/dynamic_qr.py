"""Selcom Checkout Dynamic QR for a public payment link — reuses the
exact same create-order-minimal order shell wallet_push.py uses
(get_or_create_checkout_order_for_payment_link), but there is no
wallet-payment push step: the order's own `payment_gateway_url` (Selcom's
hosted payment page) is what the customer scans or opens directly, so
this module's ceiling is even lower than wallet_push.py's — it never
calls anything beyond create-order-minimal.

**This module never credits a merchant, posts a ledger entry, or marks a
payment_link PAID.** Same as wallet_push.py: the collection stays
"processing" until a webhook or manual refresh
(app/services/checkout_reconciliation.py) confirms
payment_status=COMPLETED — see docs/selcom-checkout-collections.md.

Every collection left "processing" here gets a linked `transactions` row
(create_processing_transaction, shared with wallet_push.py) for the same
reason: resolve_collection() needs exactly one to post ledger entries
against once resolution actually happens.
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

# collections.method must be one of USSD_PUSH/STK_PUSH/SELCOM_PESA_PUSH/
# DYNAMIC_QR (DB CHECK constraint) — DYNAMIC_QR is the correct, literal
# label here, unlike wallet_push.py's STK_PUSH simplification, since this
# really is the QR method.
_METHOD_LABEL = "DYNAMIC_QR"

# Selcom's create-order-minimal requires *a* buyer_phone even though a QR
# customer is never pushed to or texted — nothing in this module ever
# sends anything to this number. Used only when the payment link has no
# customer_phone on file (the customer never had to type one for QR).
# Mirrors app/services/checkout_orders.py's placeholder buyer_email
# convention: a well-formed but inert value, never claimed to be real.
_PLACEHOLDER_BUYER_PHONE = "255700000000"
_PLACEHOLDER_BUYER_EMAIL_DOMAIN = "customers.infinitypay.me"


async def execute_dynamic_qr_for_payment_link(client: Client, *, payment_link: dict, customer_phone: str | None) -> dict:
    """Idempotent beyond the router's Idempotency-Key header, same as
    execute_wallet_push_for_payment_link: re-requesting a QR for a
    payment link that already has one in flight or resolved returns that
    existing collection rather than creating a second Selcom order."""
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
        "merchant_reference": payment_link.get("merchant_reference"),
    }

    if order["status"] != "created":
        # The order shell itself failed at Selcom — no QR to show.
        # Recorded as a failed collection attempt, same convention as
        # wallet_push.py's equivalent branch.
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

    # resolve_collection() (called later by the webhook or a manual
    # refresh) needs exactly one linked transaction to post ledger
    # entries against — see module docstring.
    create_processing_transaction(
        client,
        merchant_id=merchant_id,
        method=_METHOD_LABEL,
        collection_id=collection["id"],
        provider_reference=order.get("provider_reference") or order["order_id"],
        amount=Decimal(str(payment_link["amount"])),
        currency=payment_link["currency"],
    )

    return {
        **collection,
        "payment_gateway_url": order.get("payment_gateway_url"),
        "qr": order.get("qr"),
        "payment_token": order.get("payment_token"),
    }


async def execute_qr_collection(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    amount: Decimal,
    currency: str,
    customer_phone: str | None = None,
    customer_name: str | None = None,
    customer_email: str | None = None,
    customer_id: uuid.UUID | None = None,
    merchant_reference: str | None = None,
    description: str | None = None,
    invoice_id: uuid.UUID | None = None,
    source: str = "API_TANQR",
    api_key_id: uuid.UUID | None = None,
) -> dict:
    """Standalone Scan QR / TanQR collection, not tied to any payment
    link — for a developer/merchant creating a QR collection directly
    (POST /v1/collections/qr, e.g. a POS/counter or delivery scan-to-pay
    flow) rather than through a payment link's public page. Mirrors
    execute_dynamic_qr_for_payment_link's shape but always creates a
    fresh Selcom order.

    **Never generates a QR payload itself** — `qr`/`payment_token` in the
    returned dict are exactly what Selcom's create-order-minimal
    response contained (app/services/checkout_orders.py), passed through
    unaltered. customer_phone is optional (unlike the push methods) —
    Selcom's create-order-minimal still requires *a* value, so a
    well-formed placeholder is used when none is given, same convention
    as execute_dynamic_qr_for_payment_link."""
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
        "source": source,
        "api_key_id": str(api_key_id) if api_key_id else None,
    }

    if order["status"] != "created":
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

    return {
        **collection,
        "payment_gateway_url": order.get("payment_gateway_url"),
        "qr": order.get("qr"),
        "payment_token": order.get("payment_token"),
    }
