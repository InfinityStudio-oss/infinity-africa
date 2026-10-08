"""Checkout order lifecycle — currently just Step 1: create the order
shell via Selcom Checkout's Create Order - Minimal
(https://developers.selcommobile.com/#create-order-minimal). Never pulls
money — see app/services/selcom_checkout/client.py's module docstring.

order_id sent to Selcom is server-generated (generate_reference("ORD")),
never client-supplied — guarantees uniqueness rather than trusting it,
and is enforced again at the database level
(checkout_orders_merchant_order_id_key) as defense-in-depth. Callers use
merchant_reference for their own tracking value instead (same role as
collections.merchant_reference).

HTTP-level idempotency (retried requests replaying the same result
without re-calling Selcom) is handled by the router via
app.services.idempotency.run_idempotent, same as
POST /v1/merchant/withdrawals — not duplicated here.
"""

import logging
import uuid
from decimal import Decimal

from supabase import Client

from app.config import get_settings
from app.core.payment_minimums import assert_amount_allowed
from app.core.references import generate_reference
from app.core.time import utc_now_iso
from app.services.crud import execute_maybe_single, insert_row
from app.services.selcom_checkout.client import (
    SelcomCheckoutHTTPClient,
    get_selcom_checkout_credentials,
)

# Selcom requires buyer_email on every create-order-minimal call, but a
# public payment-link customer is only ever asked for a phone number
# (this task's own frontend spec) — payment_links.customer_email is
# nullable and often unset. This placeholder is a known, deliberate gap:
# it's a well-formed but non-deliverable address, never claimed to be a
# real one, used only because Selcom's API rejects a blank/missing value
# outright. Revisit if Selcom's own account settings ever make this
# field genuinely optional, or if the checkout page starts collecting a
# real email.
_PLACEHOLDER_BUYER_EMAIL_DOMAIN = "customers.infinitypay.me"

logger = logging.getLogger("infinity.checkout_orders")

# Postgres' unique-violation SQLSTATE, and the index that guards
# checkout_orders.provider_reference.
_UNIQUE_VIOLATION = "23505"
_PROVIDER_REFERENCE_INDEX = "checkout_orders_provider_reference_key"


def _is_duplicate_provider_reference(exc: Exception) -> bool:
    """True only for "Selcom gave us a reference we already hold".

    Deliberately narrow on both the SQLSTATE and the index name: any
    other unique violation — a repeated order_id of our own making, say —
    is a real bug and must keep raising rather than be quietly retried
    into a second row.
    """
    code = getattr(exc, "code", None)
    message = str(getattr(exc, "message", "") or exc)
    return code == _UNIQUE_VIOLATION and _PROVIDER_REFERENCE_INDEX in message




async def create_checkout_order_minimal(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    buyer_email: str,
    buyer_name: str,
    buyer_phone: str,
    amount: Decimal,
    currency: str,
    no_of_items: int,
    buyer_remarks: str | None = None,
    merchant_remarks: str | None = None,
    payment_link_id: uuid.UUID | None = None,
    merchant_reference: str | None = None,
) -> dict:
    """Calls Selcom, then persists the full result (success or not) to
    checkout_orders regardless of outcome — mirrors disbursements.py's
    convention of always keeping the raw provider response for
    support/reconciliation, not just on success.

    buyer_phone must already be normalized to "255XXXXXXXXX" by the
    caller's request schema (see CreateOrderMinimalRequest) — this
    function trusts it's already in that shape."""
    # Baseline floor, applied where every Selcom Checkout path
    # converges. The push services apply the network-specific rule
    # before this; this catches hosted checkout and QR, where no
    # network has been chosen yet. See app/core/payment_minimums.py.
    assert_amount_allowed(Decimal(str(amount)))

    order_id = generate_reference("ORD")
    settings = get_settings()

    checkout_client = SelcomCheckoutHTTPClient(credentials=get_selcom_checkout_credentials())
    result = await checkout_client.create_order_minimal(
        order_id=order_id,
        buyer_email=buyer_email,
        buyer_name=buyer_name,
        buyer_phone=buyer_phone,
        amount=str(amount),
        currency=currency,
        no_of_items=no_of_items,
        buyer_remarks=buyer_remarks,
        merchant_remarks=merchant_remarks,
        webhook=settings.selcom_checkout_webhook_url or None,
    )

    row = {
        "merchant_id": str(merchant_id),
        "payment_link_id": str(payment_link_id) if payment_link_id else None,
        "order_id": order_id,
        "merchant_reference": merchant_reference,
        "buyer_email": buyer_email,
        "buyer_name": buyer_name,
        "buyer_phone": buyer_phone,
        "amount": str(amount),
        "currency": currency,
        "buyer_remarks": buyer_remarks,
        "merchant_remarks": merchant_remarks,
        "no_of_items": no_of_items,
        "status": "created" if result.is_success else "failed",
        "provider": "selcom",
        "provider_reference": result.reference or None,
        "gateway_buyer_uuid": result.gateway_buyer_uuid,
        "payment_token": result.payment_token,
        "qr": result.qr,
        "payment_gateway_url": result.payment_gateway_url,
        "provider_result_code": result.resultcode,
        "provider_result": result.result,
        "provider_message": result.message,
        "raw_response": result.raw_response,
        "initiated_at": utc_now_iso(),
    }

    try:
        return insert_row(client, "checkout_orders", row)
    except Exception as exc:
        if not _is_duplicate_provider_reference(exc):
            raise
        # Selcom handed back a reference we have already stored. It is
        # their value, under our unique index, so their repeating it
        # turned into a 500 on a live payment — the merchant saw the
        # request fail even though the order had been placed.
        #
        # Our own order_id is what identifies this order everywhere that
        # matters, and Selcom's reply is kept whole in raw_response, so
        # dropping just the duplicated column loses nothing and lets the
        # payment carry on. Logged rather than alerted: it is the
        # provider's identifier, not a fault of ours to fix.
        logger.warning(
            "checkout_order_duplicate_provider_reference order_id=%s merchant_id=%s",
            order_id,
            merchant_id,
        )
        return insert_row(client, "checkout_orders", {**row, "provider_reference": None})


async def get_or_create_checkout_order_for_payment_link(client: Client, *, payment_link: dict, buyer_phone: str) -> dict:
    """"Create Selcom minimal order if one does not already exist for
    this attempt" (task instruction) — reuses the most recent still-
    `created` order for this payment link instead of creating a new
    Selcom order on every retry/page-refresh. Doesn't call Selcom at all
    when reusing.

    buyer_phone must already be normalized to "255XXXXXXXXX" by the
    caller."""
    # Baseline floor, applied where every Selcom Checkout path
    # converges. The push services apply the network-specific rule
    # before this; this catches hosted checkout and QR, where no
    # network has been chosen yet. See app/core/payment_minimums.py.
    assert_amount_allowed(Decimal(str(payment_link["amount"])))

    existing = execute_maybe_single(
        client.table("checkout_orders")
        .select("*")
        .eq("payment_link_id", payment_link["id"])
        .eq("status", "created")
        .order("created_at", desc=True)
        .range(0, 0)
        .maybe_single()
    )
    if existing:
        return existing

    buyer_email = payment_link.get("customer_email") or f"payment-link-{payment_link['id']}@{_PLACEHOLDER_BUYER_EMAIL_DOMAIN}"
    buyer_name = payment_link.get("customer_name") or "InfinityPay Customer"

    return await create_checkout_order_minimal(
        client,
        merchant_id=uuid.UUID(payment_link["merchant_id"]),
        buyer_email=buyer_email,
        buyer_name=buyer_name,
        buyer_phone=buyer_phone,
        amount=Decimal(str(payment_link["amount"])),
        currency=payment_link["currency"],
        no_of_items=1,
        payment_link_id=uuid.UUID(payment_link["id"]),
        merchant_reference=payment_link.get("merchant_reference"),
    )
