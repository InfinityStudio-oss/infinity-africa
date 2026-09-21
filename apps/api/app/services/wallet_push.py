"""Orchestrates the two-step Selcom Checkout wallet-push flow
(create_order_minimal -> process_wallet_payment) for a customer paying a
public payment link via mobile money push (STK/USSD/wallet pull) —
execute_wallet_push_for_payment_link() — plus a standalone variant for
the Merchant Portal's own "Request Collection" — execute_wallet_push_collection(),
added back 2026-08-23 (TEMPORARY) because Selcom's hosted checkout
(payment_gateway_url) is confirmed broken account-side — see
docs/selcom-checkout-collections.md, "Known issue" section — while
wallet-push itself is proven working (two real successful payments this
session). Swap the customer-facing/Request-Collection UI back to hosted
checkout once Selcom confirms it's fixed; nothing here needs to change
to do that, this module just needs to stop being called.

**This module never credits a merchant, posts a ledger entry, or marks a
payment_link PAID.** Selcom's wallet-payment response is normally
PENDING (resultcode 111) — the real outcome is only known later, via
the webhook or a manual status refresh
(app/services/checkout_reconciliation.py, app/routers/webhooks.py).
Even in the rare case Selcom responds SUCCESS synchronously, this module
still only records that in `collections.provider_result`/
`provider_resultcode` for audit — the collection's own aggregate
`status` never advances past "processing" here, matching every other
push-based collection method's existing convention in this codebase
(see app/services/collections.py's LiveSelcomClient.initiate_collection
docstring: "A push always acks as processing — real resolution comes
from check_collection_status... or the webhook callback, never
synchronously from the push call itself"). Reaching collections.status
== "successful" anywhere else in this codebase implies ledger entries
were already posted (see resolve_collection()'s docstring) — this module
deliberately never creates that state, to avoid a collection that claims
success without any money having actually been credited.

Every collection left "processing" here gets a linked `transactions` row
(create_processing_transaction, shared with the older push/QR
collection flow) — resolve_collection() needs exactly one to post ledger
entries against once the webhook/refresh path resolves this collection;
skipping this would crash the first time that resolution actually
happens, not at push time.
"""

import uuid
from decimal import Decimal

from supabase import Client

from app.core.references import generate_reference
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
from app.services.selcom_checkout.client import (
    SelcomCheckoutHTTPClient,
    get_selcom_checkout_credentials,
)

# collections.method must be one of USSD_PUSH/STK_PUSH/SELCOM_PESA_PUSH/
# DYNAMIC_QR (DB CHECK constraint) — Selcom's wallet-payment call itself
# takes no method/channel parameter at all (only transid/order_id/msisdn;
# confirmed against the real endpoint contract), so Selcom picks the
# actual push channel server-side based on the msisdn's carrier. STK_PUSH
# is the closest existing label and matches this flow's own "approve
# using your PIN" customer-facing copy; it's a labeling simplification,
# not a claim that Selcom always uses STK specifically — worth revisiting
# if collections.method ever needs a genuinely channel-agnostic value.
_WALLET_PUSH_METHOD_LABEL = "STK_PUSH"


async def execute_wallet_push_for_payment_link(client: Client, *, payment_link: dict, buyer_phone: str) -> dict:
    """The one call site allowed to reach
    SelcomCheckoutHTTPClient.process_wallet_payment() — see that
    method's own docstring for why it must never be called
    speculatively or automatically.

    Idempotent beyond the router's Idempotency-Key header: if a push is
    already in flight or resolved for this payment link, returns that
    existing collection instead of triggering a second real push
    ("Do not allow duplicate credits" / "duplicate attempt does not
    double-credit" — the task's own requirement). buyer_phone must
    already be normalized to "255XXXXXXXXX" by the caller.
    """
    payment_link_id = payment_link["id"]

    existing_collection = execute_maybe_single(
        client.table("collections")
        .select("*")
        .eq("payment_link_id", payment_link_id)
        .in_("status", ["processing", "successful"])
        .order("created_at", desc=True)
        .range(0, 0)
        .maybe_single()
    )
    if existing_collection:
        return existing_collection

    order = await get_or_create_checkout_order_for_payment_link(
        client, payment_link=payment_link, buyer_phone=buyer_phone
    )

    merchant_id = uuid.UUID(payment_link["merchant_id"])
    base_row = {
        "merchant_id": str(merchant_id),
        "payment_link_id": payment_link_id,
        "checkout_order_id": order["id"],
        "method": _WALLET_PUSH_METHOD_LABEL,
        "amount": str(payment_link["amount"]),
        "currency": payment_link["currency"],
        "customer_phone": buyer_phone,
        "provider": "selcom",
        "initiated_at": utc_now_iso(),
        "source": resolve_payment_link_collection_source(client, payment_link=payment_link).value,
        "api_key_id": payment_link.get("api_key_id"),
        "invoice_id": resolve_invoice_id_for_payment_link(client, payment_link_id=payment_link_id),
        "merchant_reference": payment_link.get("merchant_reference"),
    }

    if order["status"] != "created":
        # The order shell itself failed at Selcom — nothing to push
        # against. Recorded as a failed collection attempt (not raised
        # as an error) so the customer sees a clear pending->failed
        # transition rather than a bare 500, and so this attempt is
        # visible for support/reconciliation like any other.
        return insert_row(
            client,
            "collections",
            {
                **base_row,
                "status": "failed",
                "failure_reason": "Could not create the payment order with the provider",
                "checkout_order_id": order["id"],
                "provider_resultcode": order.get("provider_result_code"),
                "provider_result": order.get("provider_result"),
                "provider_message": order.get("provider_message"),
                "raw_response": order.get("raw_response") or {},
            },
        )

    transid = generate_reference("TXN")
    checkout_client = SelcomCheckoutHTTPClient(credentials=get_selcom_checkout_credentials())
    result = await checkout_client.process_wallet_payment(
        transid=transid, order_id=order["order_id"], msisdn=buyer_phone
    )

    # "successful"/"ambiguous" both stay "processing" here deliberately
    # — see module docstring. Only Selcom's own clearly-failed codes move
    # this to "failed"; anything else (including an immediate SUCCESS)
    # waits for the not-yet-implemented webhook/reconciliation step.
    collection_status = "failed" if result.status == "failed" else "processing"

    collection = insert_row(
        client,
        "collections",
        {
            **base_row,
            "status": collection_status,
            "failure_reason": result.message if collection_status == "failed" else None,
            "provider_reference": result.reference or None,
            "provider_transid": transid,
            "provider_resultcode": result.resultcode,
            "provider_result": result.result,
            "provider_message": result.message,
            "raw_response": result.raw_response,
        },
    )

    if collection_status == "processing":
        # resolve_collection() (called later by the webhook or a manual
        # refresh) needs exactly one linked transaction to post ledger
        # entries against — see module docstring. Not needed for the
        # "failed" branches above (order-creation failure, or an outright
        # wallet-payment failure): a collection that's already terminal
        # never reaches resolve_collection() at all.
        create_processing_transaction(
            client,
            merchant_id=merchant_id,
            method=_WALLET_PUSH_METHOD_LABEL,
            collection_id=collection["id"],
            provider_reference=result.reference or transid,
            amount=Decimal(str(payment_link["amount"])),
            currency=payment_link["currency"],
        )

    return collection


_PLACEHOLDER_BUYER_EMAIL_DOMAIN = "customers.infinitypay.me"


async def execute_wallet_push_collection(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    amount: Decimal,
    currency: str,
    customer_phone: str,
    customer_name: str | None = None,
    customer_email: str | None = None,
    customer_id: uuid.UUID | None = None,
    merchant_reference: str | None = None,
    description: str | None = None,
    invoice_id: uuid.UUID | None = None,
    source: str = "DASHBOARD_REQUEST",
    api_key_id: uuid.UUID | None = None,
) -> dict:
    """TEMPORARY (2026-08-23): Merchant Portal "Request Collection" —
    standalone wallet-push, not tied to any payment link. Added back
    specifically because Selcom's hosted checkout (payment_gateway_url)
    is confirmed broken account-side (see
    docs/selcom-checkout-collections.md, "Known issue" section) — this
    is the proven-working alternative while that's escalated with
    Selcom. Mirrors execute_wallet_push_for_payment_link's two-step
    flow, but always creates a fresh Selcom order (no existing-attempt
    reuse — there's no persistent payment-link resource to reuse
    against here, only the router's own Idempotency-Key replay).

    customer_phone is required (unlike hosted_checkout_collection's
    optional one) — a push has nowhere to go without one.

    Shared by two call sites with different provenance —
    app/routers/collections_api.py::create_wallet_push_collection
    (source=API_WALLET_PUSH, api_key_id set when the caller
    authenticated with one) and the legacy Merchant Portal dashboard
    push endpoint (source defaults to DASHBOARD_REQUEST) — `source`
    always reflects which one actually called this, never guessed here."""
    buyer_name = customer_name or "InfinityPay Customer"
    buyer_email = customer_email or f"collection-{uuid.uuid4()}@{_PLACEHOLDER_BUYER_EMAIL_DOMAIN}"

    order = await create_checkout_order_minimal(
        client,
        merchant_id=merchant_id,
        buyer_email=buyer_email,
        buyer_name=buyer_name,
        buyer_phone=customer_phone,
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
        "method": _WALLET_PUSH_METHOD_LABEL,
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

    transid = generate_reference("TXN")
    checkout_client = SelcomCheckoutHTTPClient(credentials=get_selcom_checkout_credentials())
    result = await checkout_client.process_wallet_payment(
        transid=transid, order_id=order["order_id"], msisdn=customer_phone
    )

    collection_status = "failed" if result.status == "failed" else "processing"

    collection = insert_row(
        client,
        "collections",
        {
            **base_row,
            "status": collection_status,
            "failure_reason": result.message if collection_status == "failed" else None,
            "provider_reference": result.reference or None,
            "provider_transid": transid,
            "provider_resultcode": result.resultcode,
            "provider_result": result.result,
            "provider_message": result.message,
            "raw_response": result.raw_response,
        },
    )

    if collection_status == "processing":
        create_processing_transaction(
            client,
            merchant_id=merchant_id,
            method=_WALLET_PUSH_METHOD_LABEL,
            collection_id=collection["id"],
            provider_reference=result.reference or transid,
            amount=amount,
            currency=currency,
        )

    return collection
