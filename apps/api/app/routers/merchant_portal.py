"""Self-service Merchant Portal API — /v1/merchant/*.

Every endpoint here resolves the caller's merchant purely from their JWT
(app.auth.get_own_merchant / require_own_merchant_role) — unlike every
other router, the client never supplies a merchant_id at all, in the path,
query, or body. Everything below delegates to the same services the
existing /v1/payment-links, /v1/invoices, /v1/collections/{method},
/v1/disbursements/{method}, /v1/merchants/{id}/transactions, and
/v1/merchants/{id}/api-keys routers already use — no business logic is
reimplemented here, only re-exposed at merchant-scoped-by-JWT paths.

"Withdrawals" here is the same thing as "disbursements" everywhere else in
the codebase (schema, table, services) — user-facing naming only, matching
the Merchant Portal frontend's existing "Withdraw"/"Withdrawals" copy. The
existing /v1/disbursements/* routes are untouched.
"""

import logging
import secrets
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from app.auth import get_current_user, hash_api_key, require_own_merchant_role
from app.config import get_settings
from app.core.errors import APIError, ConflictError, NotFoundError, ValidationAPIError
from app.core.feature_flags import (
    require_merchant_api_keys_enabled,
    require_withdrawals_enabled,
)
from app.core.pagination import PaginationParams, build_page_meta, pagination_params
from app.core.rate_limit import rate_limit
from app.core.references import generate_reference
from app.core.request_ip import client_ip
from app.core.time import utc_now_iso
from app.database.session import get_supabase_admin
from app.schemas.api_keys import (
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyIpWhitelistUpdate,
    ApiKeyRename,
    ApiKeyResponse,
)
from app.schemas.api_logs import ApiRequestLogResponse
from app.schemas.auth import AuthenticatedUser, MerchantMembership
from app.schemas.checkout_orders import CheckoutOrderResponse
from app.schemas.collections import (
    CollectionResponse,
    DynamicQrCollectionResponse,
    HostedCheckoutCollectionResponse,
)
from app.schemas.common import APIResponse
from app.schemas.disbursements import DisbursementResponse
from app.schemas.disputes import (
    DisputeMessageCreate,
    DisputeResponse,
    RequestRefundInput,
)
from app.schemas.document_requests import DocumentRequestResponse
from app.schemas.enums import CollectionMethod, DisbursementMethod, UserRole
from app.schemas.fraud import FraudAlertResponse
from app.schemas.invoices import InvoiceItemResponse, InvoiceResponse, InvoiceUpdate
from app.schemas.ip_allowlist import IpAllowlistCreate, IpAllowlistResponse
from app.schemas.merchant_notifications import (
    MerchantNotificationSettingsResponse,
    MerchantNotificationSettingsUpdate,
)
from app.schemas.merchant_portal import (
    CreateOrderMinimalRequest,
    MerchantDynamicQrCollectionRequest,
    MerchantHostedCheckoutCollectionRequest,
    MerchantInvoiceCreate,
    MerchantOverviewResponse,
    MerchantPaymentLinkCreate,
    MerchantPaymentLinkUpdate,
    MerchantPushCollectionRequest,
    MerchantUserCreate,
    MerchantUserResponse,
    MerchantUserUpdate,
    WalletLedgerEntryResponse,
    WithdrawalCreate,
    WithdrawalOtpChallengeResponse,
    WithdrawalOtpVerify,
)
from app.schemas.merchants import MerchantResponse
from app.schemas.notifications import NotificationResponse
from app.schemas.payment_links import PaymentLinkResponse
from app.schemas.refunds import RefundResponse
from app.schemas.transactions import TransactionResponse
from app.schemas.withdrawals import FeeBreakdown, WithdrawalQuoteRequest
from app.services import disputes_service, document_requests_service
from app.services.admin_directory import batch_user_profiles, best_effort_user_profile
from app.services.api_access import (
    check_production_api_access,
    check_sandbox_api_access,
)
from app.services.audit import write_audit_log
from app.services.checkout_orders import create_checkout_order_minimal
from app.services.checkout_reconciliation import refresh_checkout_collection_status
from app.services.collections import initiate_collection, initiate_dynamic_qr_collection
from app.services.crud import (
    execute_maybe_single,
    get_by_id,
    get_for_merchant,
    insert_row,
    list_for_merchant,
    update_row,
)
from app.services.disbursements import (
    execute_disbursement,
    preflight_withdrawal,
    quote_withdrawal_fee,
)
from app.services.email import (
    send_invoice_email,
    send_payment_link_customer_email,
    send_staff_invite_email,
    send_withdrawal_otp_email,
)
from app.services.hosted_checkout import execute_hosted_checkout_collection
from app.services.idempotency import run_idempotent
from app.services.ledger import export_wallet_ledger_rows, list_wallet_ledger
from app.services.merchant_gate import require_approved_merchant
from app.services.merchant_notifications import (
    get_or_create_notification_settings,
    upsert_notification_settings,
    validate_notification_emails,
)
from app.services.merchant_overview import get_merchant_overview
from app.services.payment_links import (
    batch_collection_counts,
    build_public_url,
    generate_or_reuse_invoice_payment_link,
    generate_public_slug,
    get_with_effective_status,
    validate_payment_link_for_collection,
    with_effective_status,
)
from app.services.wallet_ledger_export import build_wallet_ledger_workbook
from app.services.wallet_push import execute_wallet_push_collection
from app.services.withdrawal_otp import (
    create_challenge,
    get_own_challenge,
    mask_email,
    rotate_otp,
    verify_otp,
)

logger = logging.getLogger("infinity.merchant_portal")

router = APIRouter(prefix="/merchant", tags=["merchant-portal"])

_ADMIN_AND_STAFF = (UserRole.MERCHANT_ADMIN, UserRole.MERCHANT_STAFF)
_ADMIN_ONLY = (UserRole.MERCHANT_ADMIN,)
_ADMIN_AND_DEVELOPER = (UserRole.MERCHANT_ADMIN, UserRole.DEVELOPER)


# --- Profile / overview ------------------------------------------------------


@router.get("/me", response_model=APIResponse[MerchantResponse])
def get_my_merchant(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role())],
):
    client = get_supabase_admin()
    row = get_by_id(client, "merchants", membership.merchant_id)
    if not row:
        raise NotFoundError("Merchant not found")
    return APIResponse(data=MerchantResponse(**row))


@router.get("/overview", response_model=APIResponse[MerchantOverviewResponse])
def get_my_overview(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role())],
):
    client = get_supabase_admin()
    overview = get_merchant_overview(client, merchant_id=membership.merchant_id)
    return APIResponse(data=MerchantOverviewResponse(**overview))


# --- Wallet -------------------------------------------------------------------


@router.get("/wallet/ledger", response_model=APIResponse[list[WalletLedgerEntryResponse]])
def list_my_wallet_ledger(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role())],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    start_date: Annotated[date | None, Query(description="Africa/Dar_es_Salaam calendar date, inclusive")] = None,
    end_date: Annotated[date | None, Query(description="Africa/Dar_es_Salaam calendar date, inclusive")] = None,
):
    """merchant_id always comes from the caller's own membership
    (require_own_merchant_role -> get_own_merchant), never from a query
    param — a merchant can only ever see their own wallet ledger."""
    client = get_supabase_admin()
    merchant = get_by_id(client, "merchants", membership.merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")
    rows, total = list_wallet_ledger(
        client,
        merchant_id=membership.merchant_id,
        currency=merchant["currency"],
        pagination=pagination,
        start_date=start_date,
        end_date=end_date,
    )
    data = [WalletLedgerEntryResponse(**row) for row in rows]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


@router.get("/wallet/ledger/export")
def export_my_wallet_ledger(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role())],
    start_date: Annotated[date, Query(description="Africa/Dar_es_Salaam calendar date, inclusive")],
    end_date: Annotated[date, Query(description="Africa/Dar_es_Salaam calendar date, inclusive")],
    format: Annotated[str, Query()] = "xlsx",
):
    """Same ownership rule as GET /wallet/ledger — merchant_id is resolved
    from the caller's own membership, never accepted from the request.
    start_date/end_date are required here (unlike the list endpoint):
    the exported filename literally encodes the range, so there must
    always be one to encode."""
    if format != "xlsx":
        raise ValidationAPIError("Only format=xlsx is supported")
    if end_date < start_date:
        raise ValidationAPIError("end_date must be on or after start_date")

    client = get_supabase_admin()
    merchant = get_by_id(client, "merchants", membership.merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")

    rows = export_wallet_ledger_rows(
        client,
        merchant_id=membership.merchant_id,
        currency=merchant["currency"],
        start_date=start_date,
        end_date=end_date,
    )
    workbook_bytes = build_wallet_ledger_workbook(merchant=merchant, rows=rows)

    filename = f"infinitypay-wallet-ledger-{start_date.isoformat()}-to-{end_date.isoformat()}.xlsx"
    return Response(
        content=workbook_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Payment links ------------------------------------------------------------


def _payment_link_response(row: dict, *, attempt_count: int = 0) -> PaymentLinkResponse:
    # customer_email_sent isn't a real payment_links column — only present
    # on `row` right after create_my_payment_link attaches it (see there),
    # so **row picks it up there and every other caller's plain DB row
    # naturally leaves it at the schema's None default.
    return PaymentLinkResponse(
        **row, public_url=build_public_url(row["public_slug"]), attempt_count=attempt_count
    )


@router.get("/payment-links", response_model=APIResponse[list[PaymentLinkResponse]])
def list_my_payment_links(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    client = get_supabase_admin()
    rows, total = list_for_merchant(client, "payment_links", merchant_id=membership.merchant_id, pagination=pagination)
    rows = [with_effective_status(client, row) for row in rows]
    counts = batch_collection_counts(client, {row["id"] for row in rows})
    data = [_payment_link_response(row, attempt_count=counts.get(row["id"], 0)) for row in rows]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


@router.post("/payment-links", response_model=APIResponse[PaymentLinkResponse], status_code=status.HTTP_201_CREATED)
async def create_my_payment_link(
    payload: MerchantPaymentLinkCreate,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="payment_link_create", limit=30, window_seconds=60))],
):
    client = get_supabase_admin()
    # An unapproved merchant can't put a payable link into the world.
    require_approved_merchant(client, membership.merchant_id)

    async def _handler() -> tuple[int, dict]:
        data = payload.model_dump(mode="json", exclude={"allowed_payment_methods", "origin"})
        data["merchant_id"] = str(membership.merchant_id)
        data["allowed_payment_methods"] = [m.value for m in payload.allowed_payment_methods]
        data["public_slug"] = generate_public_slug()
        data["status"] = "ACTIVE"
        data["created_via"] = payload.origin

        row = insert_row(client, "payment_links", data)

        write_audit_log(
            client,
            actor_id=membership.user_id,
            actor_type="user",
            merchant_id=membership.merchant_id,
            action="payment_link.created",
            resource_type="payment_link",
            resource_id=uuid.UUID(row["id"]),
            metadata={"origin": payload.origin},
        )

        # customer_email_sent isn't a payment_links column — attached here
        # only so the response (and, via run_idempotent's cache, any
        # retried request) can report the outcome; None means "no
        # customer_email, nothing was attempted" (see PaymentLinkResponse).
        if row.get("customer_email"):
            merchant = get_by_id(client, "merchants", membership.merchant_id)
            sent = merchant is not None and send_payment_link_customer_email(
                client, merchant=merchant, payment_link=row
            ) is not None
            row["customer_email_sent"] = sent

        return status.HTTP_201_CREATED, row

    _status_code, body = await run_idempotent(
        client,
        merchant_id=membership.merchant_id,
        endpoint="POST /v1/merchant/payment-links",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )
    return APIResponse(data=_payment_link_response(body))


@router.get("/payment-links/{link_id}", response_model=APIResponse[PaymentLinkResponse])
def get_my_payment_link(
    link_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    client = get_supabase_admin()
    row = get_by_id(client, "payment_links", link_id)
    if not row or uuid.UUID(row["merchant_id"]) != membership.merchant_id:
        raise NotFoundError("Payment link not found")
    row = with_effective_status(client, row)
    counts = batch_collection_counts(client, {row["id"]})
    return APIResponse(data=_payment_link_response(row, attempt_count=counts.get(row["id"], 0)))


@router.patch("/payment-links/{link_id}", response_model=APIResponse[PaymentLinkResponse])
def update_my_payment_link(
    link_id: uuid.UUID,
    payload: MerchantPaymentLinkUpdate,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    """Only an ACTIVE link may be edited — a PAID/EXPIRED/CANCELLED link's
    terms shouldn't change after the fact (a customer may have already seen
    the old terms, or already paid under them)."""
    client = get_supabase_admin()
    row = get_by_id(client, "payment_links", link_id)
    if not row or uuid.UUID(row["merchant_id"]) != membership.merchant_id:
        raise NotFoundError("Payment link not found")

    row = with_effective_status(client, row)
    if row["status"] != "ACTIVE":
        raise ConflictError(f"Only an ACTIVE payment link can be edited (status: {row['status']})")

    update_data = payload.model_dump(mode="json", exclude_unset=True, exclude={"allowed_payment_methods"})
    if payload.allowed_payment_methods is not None:
        update_data["allowed_payment_methods"] = [m.value for m in payload.allowed_payment_methods]

    if update_data:
        row = update_row(client, "payment_links", link_id, update_data) or row
        write_audit_log(
            client,
            actor_id=membership.user_id,
            actor_type="user",
            merchant_id=membership.merchant_id,
            action="payment_link.updated",
            resource_type="payment_link",
            resource_id=link_id,
            metadata={"fields": sorted(update_data.keys())},
        )

    counts = batch_collection_counts(client, {row["id"]})
    return APIResponse(data=_payment_link_response(row, attempt_count=counts.get(row["id"], 0)))


@router.patch("/payment-links/{link_id}/cancel", response_model=APIResponse[PaymentLinkResponse])
def cancel_my_payment_link(
    link_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    client = get_supabase_admin()
    row = get_by_id(client, "payment_links", link_id)
    if not row or uuid.UUID(row["merchant_id"]) != membership.merchant_id:
        raise NotFoundError("Payment link not found")

    row = with_effective_status(client, row)
    if row["status"] == "PAID":
        raise ConflictError("A paid payment link cannot be cancelled")

    if row["status"] != "CANCELLED":
        row = update_row(client, "payment_links", link_id, {"status": "CANCELLED"}) or row
        write_audit_log(
            client,
            actor_id=membership.user_id,
            actor_type="user",
            merchant_id=membership.merchant_id,
            action="payment_link.cancelled",
            resource_type="payment_link",
            resource_id=link_id,
        )
    return APIResponse(data=_payment_link_response(row))


# --- Invoices -----------------------------------------------------------------


def _fetch_invoice_items(client, invoice_id: uuid.UUID) -> list[dict]:
    result = client.table("invoice_items").select("*").eq("invoice_id", str(invoice_id)).order("sort_order").execute()
    return result.data or []


def _invoice_response(client, row: dict) -> InvoiceResponse:
    items = _fetch_invoice_items(client, uuid.UUID(row["id"]))
    return InvoiceResponse(**row, items=[InvoiceItemResponse(**item) for item in items])


@router.get("/invoices", response_model=APIResponse[list[InvoiceResponse]])
def list_my_invoices(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    client = get_supabase_admin()
    rows, total = list_for_merchant(client, "invoices", merchant_id=membership.merchant_id, pagination=pagination)
    data = [_invoice_response(client, row) for row in rows]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


@router.post("/invoices", response_model=APIResponse[InvoiceResponse], status_code=status.HTTP_201_CREATED)
def create_my_invoice(
    payload: MerchantInvoiceCreate,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    client = get_supabase_admin()
    # An unapproved merchant can't raise an invoice for collection.
    require_approved_merchant(client, membership.merchant_id)

    subtotal = sum((item.quantity * item.unit_price for item in payload.items), Decimal(0))
    total_amount = subtotal + payload.tax_amount - payload.discount_amount
    if total_amount < 0:
        raise ValidationAPIError("Total amount cannot be negative")

    invoice_data = payload.model_dump(mode="json", exclude={"items"})
    invoice_data["merchant_id"] = str(membership.merchant_id)
    invoice_data["invoice_number"] = generate_reference("INV")
    invoice_data["subtotal"] = str(subtotal)
    invoice_data["total_amount"] = str(total_amount)
    invoice_data["amount_paid"] = "0"
    invoice_data["status"] = "DRAFT"

    invoice = insert_row(client, "invoices", invoice_data)
    invoice_id = invoice["id"]

    items_data = [{**item.model_dump(mode="json"), "invoice_id": invoice_id} for item in payload.items]
    client.table("invoice_items").insert(items_data).execute()

    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="invoice.created",
        resource_type="invoice",
        resource_id=uuid.UUID(invoice_id),
    )
    return APIResponse(data=_invoice_response(client, invoice))


@router.get("/invoices/{invoice_id}", response_model=APIResponse[InvoiceResponse])
def get_my_invoice(
    invoice_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    client = get_supabase_admin()
    row = get_by_id(client, "invoices", invoice_id)
    if not row or uuid.UUID(row["merchant_id"]) != membership.merchant_id:
        raise NotFoundError("Invoice not found")
    return APIResponse(data=_invoice_response(client, row))


@router.patch("/invoices/{invoice_id}", response_model=APIResponse[InvoiceResponse])
def update_my_invoice(
    invoice_id: uuid.UUID,
    payload: InvoiceUpdate,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    client = get_supabase_admin()
    row = get_by_id(client, "invoices", invoice_id)
    if not row or uuid.UUID(row["merchant_id"]) != membership.merchant_id:
        raise NotFoundError("Invoice not found")

    if row["status"] != "DRAFT":
        raise ValidationAPIError("Only a draft invoice can be edited")

    update_data = payload.model_dump(mode="json", exclude={"items"}, exclude_unset=True)

    if payload.items is not None:
        subtotal = sum((item.quantity * item.unit_price for item in payload.items), Decimal(0))
        tax_amount = payload.tax_amount if payload.tax_amount is not None else Decimal(str(row["tax_amount"]))
        discount_amount = (
            payload.discount_amount if payload.discount_amount is not None else Decimal(str(row["discount_amount"]))
        )
        total_amount = subtotal + tax_amount - discount_amount
        if total_amount < 0:
            raise ValidationAPIError("Total amount cannot be negative")

        update_data["subtotal"] = str(subtotal)
        update_data["total_amount"] = str(total_amount)

        client.table("invoice_items").delete().eq("invoice_id", str(invoice_id)).execute()
        items_data = [{**item.model_dump(mode="json"), "invoice_id": str(invoice_id)} for item in payload.items]
        client.table("invoice_items").insert(items_data).execute()
    elif payload.tax_amount is not None or payload.discount_amount is not None:
        subtotal = Decimal(str(row["subtotal"]))
        tax_amount = payload.tax_amount if payload.tax_amount is not None else Decimal(str(row["tax_amount"]))
        discount_amount = (
            payload.discount_amount if payload.discount_amount is not None else Decimal(str(row["discount_amount"]))
        )
        total_amount = subtotal + tax_amount - discount_amount
        if total_amount < 0:
            raise ValidationAPIError("Total amount cannot be negative")
        update_data["total_amount"] = str(total_amount)

    row = update_row(client, "invoices", invoice_id, update_data) or row
    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="invoice.updated",
        resource_type="invoice",
        resource_id=invoice_id,
    )
    return APIResponse(data=_invoice_response(client, row))


@router.post("/invoices/{invoice_id}/send", response_model=APIResponse[InvoiceResponse])
def send_my_invoice(
    invoice_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    """DRAFT -> SENT — but only once the customer's payment-request email
    has actually been delivered via Resend (app/services/email.py).
    Generates/reuses the invoice's Pay Now link first, then emails it;
    the invoice stays DRAFT if either step fails, so a SENT invoice always
    means the customer was actually notified, never just "we tried."
    """
    client = get_supabase_admin()
    row = get_by_id(client, "invoices", invoice_id)
    if not row or uuid.UUID(row["merchant_id"]) != membership.merchant_id:
        raise NotFoundError("Invoice not found")

    if row["status"] != "DRAFT":
        raise ValidationAPIError("Only a draft invoice can be sent")

    if not row.get("customer_email"):
        raise ValidationAPIError("Customer email is required to send this invoice automatically.")

    merchant = get_by_id(client, "merchants", membership.merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")

    link = generate_or_reuse_invoice_payment_link(client, invoice=row, merchant_id=membership.merchant_id)
    items = (
        client.table("invoice_items").select("*").eq("invoice_id", str(invoice_id)).order("sort_order").execute()
    ).data or []

    send_invoice_email(
        client,
        merchant=merchant,
        invoice={**row, "payment_link_id": link["id"]},
        items=items,
        payment_url=build_public_url(link["public_slug"]),
    )

    row = update_row(client, "invoices", invoice_id, {"status": "SENT", "sent_at": utc_now_iso()}) or row
    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="invoice.sent",
        resource_type="invoice",
        resource_id=invoice_id,
        metadata={"customer_email": row.get("customer_email")},
    )
    return APIResponse(data=_invoice_response(client, row))


@router.post("/invoices/{invoice_id}/payment-link", response_model=APIResponse[PaymentLinkResponse])
def generate_my_invoice_payment_link(
    invoice_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    client = get_supabase_admin()
    row = get_by_id(client, "invoices", invoice_id)
    if not row or uuid.UUID(row["merchant_id"]) != membership.merchant_id:
        raise NotFoundError("Invoice not found")

    if row["status"] not in ("SENT", "PARTIALLY_PAID", "OVERDUE"):
        raise ValidationAPIError(
            f"Cannot generate a payment link for an invoice with status {row['status']}; send it first"
        )

    had_link_id = row.get("payment_link_id")
    link = generate_or_reuse_invoice_payment_link(client, invoice=row, merchant_id=membership.merchant_id)

    if had_link_id != link["id"]:
        # Only a genuinely new link is worth an audit entry — reusing an
        # already-active one is a no-op from an audit perspective.
        write_audit_log(
            client,
            actor_id=membership.user_id,
            actor_type="user",
            merchant_id=membership.merchant_id,
            action="invoice.payment_link_generated",
            resource_type="invoice",
            resource_id=invoice_id,
            metadata={"payment_link_id": link["id"]},
        )
    return APIResponse(data=_payment_link_response(link))


# --- Collections ----------------------------------------------------------


_METHOD_PATHS: dict[CollectionMethod, str] = {
    CollectionMethod.USSD_PUSH: "ussd-push",
    CollectionMethod.STK_PUSH: "stk-push",
    CollectionMethod.SELCOM_PESA_PUSH: "selcom-pesa-push",
    CollectionMethod.DYNAMIC_QR: "dynamic-qr",
}


@router.get("/collections", response_model=APIResponse[list[CollectionResponse]])
def list_my_collections(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    client = get_supabase_admin()
    rows, total = list_for_merchant(client, "collections", merchant_id=membership.merchant_id, pagination=pagination)
    data = [CollectionResponse(**row) for row in rows]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


@router.post("/collections/{collection_id}/refresh-status", response_model=APIResponse[CollectionResponse])
async def refresh_my_collection_status(
    collection_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    """Manual reconciliation for a Selcom Checkout wallet-push collection
    left "processing" — queries Selcom's order-status directly and
    applies the same completion logic the webhook uses
    (app/services/checkout_reconciliation.py). Scoped to the caller's own
    merchant via get_for_merchant, same as every other merchant-portal
    single-resource lookup."""
    client = get_supabase_admin()
    collection = get_for_merchant(client, "collections", merchant_id=membership.merchant_id, row_id=collection_id)
    if not collection:
        raise NotFoundError("Collection not found")

    resolved = await refresh_checkout_collection_status(client, collection_id=collection_id)
    write_audit_log(
        client,
        actor_id=membership.user_id,
        merchant_id=membership.merchant_id,
        action="collection.status_refreshed",
        resource_type="collection",
        resource_id=collection_id,
        metadata={"status": resolved["status"]},
    )
    return APIResponse(data=CollectionResponse(**resolved))


async def _create_my_push_collection(
    method: CollectionMethod,
    payload: MerchantPushCollectionRequest,
    membership: MerchantMembership,
    idempotency_key: str,
) -> APIResponse[CollectionResponse]:
    client = get_supabase_admin()

    await validate_payment_link_for_collection(
        client, merchant_id=membership.merchant_id, payment_link_id=payload.payment_link_id, method=method
    )

    async def _handler() -> tuple[int, dict]:
        collection = await initiate_collection(
            client,
            merchant_id=membership.merchant_id,
            method=method,
            amount=payload.amount,
            currency=payload.currency,
            customer_id=payload.customer_id,
            customer_phone=payload.customer_phone,
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            payment_link_id=payload.payment_link_id,
            invoice_id=payload.invoice_id,
            merchant_reference=payload.merchant_reference,
            description=payload.description,
            callback_url=payload.callback_url,
        )
        write_audit_log(
            client,
            actor_id=membership.user_id,
            actor_type="user",
            merchant_id=membership.merchant_id,
            action="collection.initiated",
            resource_type="collection",
            resource_id=uuid.UUID(collection["id"]),
            metadata={"method": method.value},
        )
        return status.HTTP_202_ACCEPTED, collection

    _status_code, body = await run_idempotent(
        client,
        merchant_id=membership.merchant_id,
        endpoint=f"POST /v1/merchant/collections/{_METHOD_PATHS[method]}",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )
    return APIResponse(data=CollectionResponse(**body))


@router.post(
    "/collections/ussd-push", response_model=APIResponse[CollectionResponse], status_code=status.HTTP_202_ACCEPTED
)
async def create_my_ussd_push_collection(
    payload: MerchantPushCollectionRequest,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="merchant_collection_create", limit=20, window_seconds=60))],
):
    return await _create_my_push_collection(CollectionMethod.USSD_PUSH, payload, membership, idempotency_key)


@router.post(
    "/collections/stk-push", response_model=APIResponse[CollectionResponse], status_code=status.HTTP_202_ACCEPTED
)
async def create_my_stk_push_collection(
    payload: MerchantPushCollectionRequest,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="merchant_collection_create", limit=20, window_seconds=60))],
):
    return await _create_my_push_collection(CollectionMethod.STK_PUSH, payload, membership, idempotency_key)


@router.post(
    "/collections/selcom-pesa-push",
    response_model=APIResponse[CollectionResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_my_selcom_pesa_push_collection(
    payload: MerchantPushCollectionRequest,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="merchant_collection_create", limit=20, window_seconds=60))],
):
    return await _create_my_push_collection(CollectionMethod.SELCOM_PESA_PUSH, payload, membership, idempotency_key)


@router.post(
    "/collections/dynamic-qr",
    response_model=APIResponse[DynamicQrCollectionResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_my_dynamic_qr_collection(
    payload: MerchantDynamicQrCollectionRequest,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="merchant_collection_create", limit=20, window_seconds=60))],
):
    client = get_supabase_admin()

    await validate_payment_link_for_collection(
        client,
        merchant_id=membership.merchant_id,
        payment_link_id=payload.payment_link_id,
        method=CollectionMethod.DYNAMIC_QR,
    )

    async def _handler() -> tuple[int, dict]:
        collection, qr_result = await initiate_dynamic_qr_collection(
            client,
            merchant_id=membership.merchant_id,
            amount=payload.amount,
            currency=payload.currency,
            customer_id=payload.customer_id,
            customer_phone=payload.customer_phone,
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            payment_link_id=payload.payment_link_id,
            invoice_id=payload.invoice_id,
            merchant_reference=payload.merchant_reference,
            description=payload.description,
            callback_url=payload.callback_url,
        )
        write_audit_log(
            client,
            actor_id=membership.user_id,
            actor_type="user",
            merchant_id=membership.merchant_id,
            action="collection.initiated",
            resource_type="collection",
            resource_id=uuid.UUID(collection["id"]),
            metadata={"method": "DYNAMIC_QR"},
        )
        body = {
            **collection,
            "qr_payload": qr_result.qr_payload,
            "qr_expires_at": qr_result.qr_expires_at.isoformat(),
            "expires_at": qr_result.qr_expires_at.isoformat(),
        }
        return status.HTTP_202_ACCEPTED, body

    _status_code, body = await run_idempotent(
        client,
        merchant_id=membership.merchant_id,
        endpoint="POST /v1/merchant/collections/dynamic-qr",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )
    return APIResponse(data=DynamicQrCollectionResponse(**body))


@router.post(
    "/collections/hosted-checkout",
    response_model=APIResponse[HostedCheckoutCollectionResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_my_hosted_checkout_collection(
    payload: MerchantHostedCheckoutCollectionRequest,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="merchant_collection_create", limit=20, window_seconds=60))],
):
    """"Request Collection" — no channel to pick. Creates a Selcom order
    via create-order-minimal and returns its decoded payment_gateway_url
    for the merchant to open or copy — Selcom's own hosted checkout page
    shows whichever methods are enabled on the account (card confirmed
    not enabled; no exclusion logic exists here on purpose)."""
    client = get_supabase_admin()

    async def _handler() -> tuple[int, dict]:
        collection = await execute_hosted_checkout_collection(
            client,
            merchant_id=membership.merchant_id,
            amount=payload.amount,
            currency=payload.currency,
            customer_id=payload.customer_id,
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            customer_phone=payload.customer_phone,
            merchant_reference=payload.merchant_reference,
            description=payload.description,
            invoice_id=payload.invoice_id,
        )
        write_audit_log(
            client,
            actor_id=membership.user_id,
            actor_type="user",
            merchant_id=membership.merchant_id,
            action="collection.initiated",
            resource_type="collection",
            resource_id=uuid.UUID(collection["id"]),
            metadata={"method": "HOSTED_CHECKOUT"},
        )
        return status.HTTP_202_ACCEPTED, collection

    _status_code, body = await run_idempotent(
        client,
        merchant_id=membership.merchant_id,
        endpoint="POST /v1/merchant/collections/hosted-checkout",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )
    return APIResponse(data=HostedCheckoutCollectionResponse(**body))


@router.post(
    "/collections/wallet-push",
    response_model=APIResponse[CollectionResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_my_wallet_push_collection(
    payload: MerchantPushCollectionRequest,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="merchant_collection_create", limit=20, window_seconds=60))],
):
    """TEMPORARY (2026-08-23): "Request Collection" via wallet-push —
    added back specifically because Selcom's hosted checkout is
    confirmed broken account-side (see
    docs/selcom-checkout-collections.md, "Known issue" section).
    Sends a real STK/USSD push to payload.customer_phone immediately.
    Swap back to /collections/hosted-checkout once Selcom confirms
    fixed — see app/services/wallet_push.py's module docstring."""
    client = get_supabase_admin()

    async def _handler() -> tuple[int, dict]:
        collection = await execute_wallet_push_collection(
            client,
            merchant_id=membership.merchant_id,
            amount=payload.amount,
            currency=payload.currency,
            customer_phone=payload.customer_phone,
            customer_id=payload.customer_id,
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            merchant_reference=payload.merchant_reference,
            description=payload.description,
            invoice_id=payload.invoice_id,
        )
        write_audit_log(
            client,
            actor_id=membership.user_id,
            actor_type="user",
            merchant_id=membership.merchant_id,
            action="collection.initiated",
            resource_type="collection",
            resource_id=uuid.UUID(collection["id"]),
            metadata={"method": "STK_PUSH"},
        )
        return status.HTTP_202_ACCEPTED, collection

    _status_code, body = await run_idempotent(
        client,
        merchant_id=membership.merchant_id,
        endpoint="POST /v1/merchant/collections/wallet-push",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )
    return APIResponse(data=CollectionResponse(**body))


@router.post(
    "/collections/create-order-minimal",
    response_model=APIResponse[CheckoutOrderResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_my_checkout_order_minimal(
    payload: CreateOrderMinimalRequest,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="merchant_collection_create", limit=20, window_seconds=60))],
):
    """Selcom Checkout's Create Order - Minimal
    (https://developers.selcommobile.com/#create-order-minimal) — Step 1
    for STK/USSD/wallet push, payment-link checkout, and dynamic QR/token
    display. Never pulls money: no wallet-payment call happens here or
    anywhere in app/services/selcom_checkout/ yet.

    A 202 with status="created" means the order shell exists on Selcom's
    side and a payment_token/qr/gateway URL are available — it does not
    mean anything has been paid. A 202 with status="failed" means Selcom
    rejected the order itself (see provider_message); either way this
    endpoint's own HTTP response is 202, since the order attempt was
    still recorded — check `status` in the body for the real outcome,
    same convention as the push-collection endpoints above."""
    client = get_supabase_admin()

    if payload.payment_link_id is not None:
        # Not validate_payment_link_for_collection() — that also checks
        # the link accepts one *specific* collection method, which
        # doesn't apply here: this order shell doesn't commit to
        # STK/USSD/wallet/QR yet, so there's no single method to check
        # against. Ownership + ACTIVE status is all that's meaningful at
        # this stage.
        link = get_with_effective_status(client, payload.payment_link_id)
        if not link or uuid.UUID(link["merchant_id"]) != membership.merchant_id:
            raise ValidationAPIError("payment_link_id does not belong to this merchant")
        if link["status"] != "ACTIVE":
            raise ConflictError(f"This payment link cannot accept a collection (status: {link['status']})")

    async def _handler() -> tuple[int, dict]:
        order = await create_checkout_order_minimal(
            client,
            merchant_id=membership.merchant_id,
            buyer_email=payload.buyer_email,
            buyer_name=payload.buyer_name,
            buyer_phone=payload.buyer_phone,
            amount=payload.amount,
            currency=payload.currency,
            no_of_items=payload.no_of_items,
            buyer_remarks=payload.buyer_remarks,
            merchant_remarks=payload.merchant_remarks,
            payment_link_id=payload.payment_link_id,
            merchant_reference=payload.merchant_reference,
        )
        write_audit_log(
            client,
            actor_id=membership.user_id,
            actor_type="user",
            merchant_id=membership.merchant_id,
            action="checkout_order.created",
            resource_type="checkout_order",
            resource_id=uuid.UUID(order["id"]),
            metadata={"status": order["status"]},
        )
        return status.HTTP_202_ACCEPTED, order

    _status_code, body = await run_idempotent(
        client,
        merchant_id=membership.merchant_id,
        endpoint="POST /v1/merchant/collections/create-order-minimal",
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
        handler=_handler,
    )
    return APIResponse(data=CheckoutOrderResponse(**body))


# --- Withdrawals (disbursements) --------------------------------------------


@router.post("/withdrawals/quote", response_model=APIResponse[FeeBreakdown])
def quote_my_withdrawal(
    payload: WithdrawalQuoteRequest,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    """Read-only fee calculation — no withdrawal is created, no funds are
    reserved, Selcom is never called. Lets the merchant see the full charge
    breakdown before submitting (POST /withdrawals below), which
    recalculates and freezes the same breakdown server-side rather than
    trusting whatever this call returned."""
    client = get_supabase_admin()
    breakdown = quote_withdrawal_fee(
        client,
        merchant_id=membership.merchant_id,
        amount=payload.amount,
        method=payload.method,
        destination_code=payload.destination_code,
    )
    return APIResponse(data=breakdown)


@router.get("/withdrawals", response_model=APIResponse[list[DisbursementResponse]])
def list_my_withdrawals(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    client = get_supabase_admin()
    rows, total = list_for_merchant(client, "disbursements", merchant_id=membership.merchant_id, pagination=pagination)
    data = [DisbursementResponse(**row) for row in rows]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


@router.post(
    "/withdrawals",
    response_model=APIResponse[WithdrawalOtpChallengeResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_my_withdrawal(
    payload: WithdrawalCreate,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_ONLY))],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="withdrawal_otp_request", limit=5, window_seconds=300))
    ],
):
    """Merchant-admin only — a deliberate tightening vs. the existing
    /v1/disbursements/{method} routes, which also allow MERCHANT_STAFF.

    **This no longer creates a withdrawal.** It validates the request, then
    emails a 6-digit code to the merchant's own registered contact address
    and returns a challenge. The disbursement is only created by
    POST /withdrawals/{challenge_id}/verify, and even then as
    PENDING_ADMIN_APPROVAL — the provider is still reached only from a
    Super Admin's approval, and the balance/standing/fraud gates still
    re-run there.

    Nothing is written to disbursements, nothing is reserved, and no CEO
    notification is sent until the code verifies. An abandoned challenge is
    therefore inert: it holds no funds and is invisible to every approval,
    payout, sweep and reconciliation path.

    Validation deliberately runs here rather than at verify time so a
    merchant learns about an unverified account, a blocked balance or a bad
    destination immediately, instead of after fetching a code from their
    inbox."""
    require_withdrawals_enabled()
    client = get_supabase_admin()

    merchant = require_approved_merchant(client, membership.merchant_id)
    recipient_email = (merchant.get("contact_email") or "").strip()
    if not recipient_email:
        raise ValidationAPIError(
            "No contact email is set for this business, so we can't send a verification code. "
            "Add one in Settings first."
        )

    # The same gates execute_disbursement applies, run now so the merchant
    # is not sent a code for a request that could never succeed. They are
    # NOT trusted to still hold at verify time — execute_disbursement runs
    # every one of them again, and a Super Admin's approval re-runs them a
    # third time before any money moves.
    preflight_withdrawal(
        client,
        merchant_id=membership.merchant_id,
        amount=payload.amount,
        currency=payload.currency,
        method=payload.method,
        destination_code=payload.destination_code,
    )

    stored_payload = {
        "method": payload.method.value,
        "amount": str(payload.amount),
        "currency": payload.currency,
        "destination_name": payload.resolved_destination_name,
        "destination_identifier": payload.destination_identifier,
        "destination_code": payload.destination_code,
        "bank_name": payload.bank_name if payload.method.value == "BANK_ACCOUNT" else None,
        "network": payload.network if payload.method.value == "MOBILE_MONEY" else None,
        "description": payload.description,
        # Carried so the eventual withdrawal inherits the caller's key —
        # replaying the same key cannot create two withdrawals.
        "idempotency_key": idempotency_key,
    }

    challenge, code = create_challenge(
        client,
        merchant_id=membership.merchant_id,
        requested_by=membership.user_id,
        payload=stored_payload,
    )

    # Raises if it cannot send. The merchant must never be shown a code
    # entry box for a code that was never delivered.
    send_withdrawal_otp_email(
        client,
        merchant=merchant,
        recipient_email=recipient_email,
        code=code,
        expires_minutes=get_settings().withdrawal_otp_expires_minutes,
    )

    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="withdrawal.otp_requested",
        resource_type="withdrawal_otp_challenge",
        resource_id=uuid.UUID(challenge["id"]),
        # Amount and method only — never the code, and never the full
        # destination identifier.
        metadata={"method": payload.method.value, "amount": str(payload.amount)},
    )

    settings = get_settings()
    return APIResponse(
        data=WithdrawalOtpChallengeResponse(
            challenge_id=uuid.UUID(challenge["id"]),
            masked_email=mask_email(recipient_email),
            expires_at=challenge["expires_at"],
            resend_cooldown_seconds=settings.withdrawal_otp_resend_cooldown_seconds,
            max_attempts=settings.withdrawal_otp_max_attempts,
        )
    )


@router.post(
    "/withdrawals/{challenge_id}/verify",
    response_model=APIResponse[DisbursementResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def verify_my_withdrawal_otp(
    challenge_id: uuid.UUID,
    payload: WithdrawalOtpVerify,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_ONLY))],
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="withdrawal_otp_verify", limit=10, window_seconds=300))
    ],
):
    """Verifies the emailed code and, only then, creates the withdrawal.

    The withdrawal is built from the payload stored on the challenge, never
    from anything re-sent now, so the amount and destination that were
    validated and emailed are exactly the ones created — there is no window
    in which a verified code could be applied to a different request.

    The result is a normal PENDING_ADMIN_APPROVAL disbursement. No provider
    is called here; that still happens only from a Super Admin's approval.
    """
    require_withdrawals_enabled()
    client = get_supabase_admin()

    challenge = get_own_challenge(client, challenge_id=challenge_id, merchant_id=membership.merchant_id)
    # A challenge belongs to the person who raised it, not to the merchant
    # at large — a second admin on the same account cannot complete someone
    # else's withdrawal using a code sent to the shared mailbox.
    if str(challenge.get("requested_by")) != str(membership.user_id):
        raise NotFoundError("Verification request not found")

    try:
        verified = verify_otp(client, challenge=challenge, submitted_code=payload.code)
    except APIError:
        write_audit_log(
            client,
            actor_id=membership.user_id,
            actor_type="user",
            merchant_id=membership.merchant_id,
            action="withdrawal.otp_verify_failed",
            resource_type="withdrawal_otp_challenge",
            resource_id=challenge_id,
            metadata={"attempts": int(challenge.get("attempts") or 0) + 1},
        )
        raise

    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="withdrawal.otp_verified",
        resource_type="withdrawal_otp_challenge",
        resource_id=challenge_id,
    )

    stored = verified.get("withdrawal_payload") or challenge.get("withdrawal_payload") or {}
    method = DisbursementMethod(stored["method"])

    async def _handler() -> tuple[int, dict]:
        disbursement = await execute_disbursement(
            client,
            merchant_id=membership.merchant_id,
            method=method,
            amount=Decimal(str(stored["amount"])),
            currency=stored.get("currency") or "TZS",
            destination_name=stored.get("destination_name"),
            destination_identifier=stored["destination_identifier"],
            destination_code=stored["destination_code"],
            bank_name=stored.get("bank_name"),
            network=stored.get("network"),
            description=stored.get("description"),
        )
        write_audit_log(
            client,
            actor_id=membership.user_id,
            actor_type="user",
            merchant_id=membership.merchant_id,
            action="withdrawal.submitted_after_otp",
            resource_type="disbursement",
            resource_id=uuid.UUID(disbursement["id"]),
            metadata={"method": stored["method"], "challenge_id": str(challenge_id)},
        )
        return status.HTTP_202_ACCEPTED, disbursement

    # Reuses the idempotency key from the original request, carried on the
    # challenge. A repeated verify therefore returns the first withdrawal
    # rather than creating a second, on top of used_at already making the
    # challenge single-use.
    _status_code, body = await run_idempotent(
        client,
        merchant_id=membership.merchant_id,
        endpoint="POST /v1/merchant/withdrawals",
        idempotency_key=str(stored.get("idempotency_key") or challenge_id),
        request_payload={k: v for k, v in stored.items() if k != "idempotency_key"},
        handler=_handler,
    )

    # The Super Admin notification is sent by execute_disbursement, which
    # owns it for every withdrawal route — not duplicated here.

    return APIResponse(data=DisbursementResponse(**body))


@router.post(
    "/withdrawals/{challenge_id}/resend",
    response_model=APIResponse[WithdrawalOtpChallengeResponse],
)
async def resend_my_withdrawal_otp(
    challenge_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_ONLY))],
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="withdrawal_otp_resend", limit=5, window_seconds=600))
    ],
):
    """Issues a fresh code on the same challenge, replacing the previous one.

    The stored payload is untouched, so a resend cannot change the amount or
    destination the code was bound to. rotate_otp enforces the cooldown and
    resets the attempt counter — the new code gets its own budget, since
    being locked out of a code you have not seen yet would be nonsense."""
    require_withdrawals_enabled()
    client = get_supabase_admin()

    challenge = get_own_challenge(client, challenge_id=challenge_id, merchant_id=membership.merchant_id)
    if str(challenge.get("requested_by")) != str(membership.user_id):
        raise NotFoundError("Verification request not found")
    if challenge.get("used_at") or challenge.get("locked_at"):
        raise ValidationAPIError("This request can no longer be verified. Start a new withdrawal.")

    merchant = require_approved_merchant(client, membership.merchant_id)
    recipient_email = (merchant.get("contact_email") or "").strip()
    if not recipient_email:
        raise ValidationAPIError("No contact email is set for this business.")

    code = rotate_otp(client, challenge=challenge)
    send_withdrawal_otp_email(
        client,
        merchant=merchant,
        recipient_email=recipient_email,
        code=code,
        expires_minutes=get_settings().withdrawal_otp_expires_minutes,
    )

    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="withdrawal.otp_resent",
        resource_type="withdrawal_otp_challenge",
        resource_id=challenge_id,
        metadata={"resend_count": int(challenge.get("resend_count") or 0) + 1},
    )

    settings = get_settings()
    refreshed = get_own_challenge(client, challenge_id=challenge_id, merchant_id=membership.merchant_id)
    return APIResponse(
        data=WithdrawalOtpChallengeResponse(
            challenge_id=challenge_id,
            masked_email=mask_email(recipient_email),
            expires_at=refreshed["expires_at"],
            resend_cooldown_seconds=settings.withdrawal_otp_resend_cooldown_seconds,
            max_attempts=settings.withdrawal_otp_max_attempts,
        )
    )


# --- Transactions ---------------------------------------------------------


@router.get("/transactions", response_model=APIResponse[list[TransactionResponse]])
def list_my_transactions(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    client = get_supabase_admin()
    rows, total = list_for_merchant(client, "transactions", merchant_id=membership.merchant_id, pagination=pagination)
    data = [TransactionResponse(**row) for row in rows]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


@router.get("/transactions/{reference}", response_model=APIResponse[TransactionResponse])
def get_my_transaction_by_reference(
    reference: str,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    """By the human-readable reference (TXN-...), not the internal UUID id
    — the existing /v1/merchants/{id}/transactions/{transaction_id} route
    only supports lookup by id; this is new."""
    client = get_supabase_admin()
    row = execute_maybe_single(
        client.table("transactions")
        .select("*")
        .eq("merchant_id", str(membership.merchant_id))
        .eq("reference", reference)
        .maybe_single()
    )
    if not row:
        raise NotFoundError("Transaction not found")
    return APIResponse(data=TransactionResponse(**row))


# --- API keys ---------------------------------------------------------------


def _generate_api_key(environment: str) -> tuple[str, str, str]:
    token = secrets.token_urlsafe(24)
    plaintext = f"inf_{environment}_{token}"
    prefix = plaintext[: len(f"inf_{environment}_") + 6]
    last4 = plaintext[-4:]
    return plaintext, prefix, last4


def _insert_ip_allowlist_entries(
    client,
    *,
    merchant_id: uuid.UUID,
    api_key_id: uuid.UUID,
    environment: str,
    entries: list,
    created_by: uuid.UUID,
    status_value: str = "pending",
) -> list[dict]:
    """Inline "Allowed server IPs" list submitted alongside key creation —
    each row is scoped to this specific key (api_key_id set, not null), and
    starts `pending` like every other merchant-added IP: the existing
    Super Admin approval rule is unchanged, this only removes the "leave
    the form, go add IPs on a different page" round trip."""
    rows = []
    for entry in entries:
        rows.append(
            insert_row(
                client,
                "api_ip_allowlist",
                {
                    "merchant_id": str(merchant_id),
                    "api_key_id": str(api_key_id),
                    "environment": environment,
                    # api_ip_allowlist.label is NOT NULL while the API schema
                    # leaves it optional, so an unlabelled row reaches PostgREST
                    # as a null and 500s -- surfacing in the portal as the
                    # generic "Couldn't reach InfinityPay". Fall back to the IP
                    # itself, which is what ApiKeyAllowedIp already documents
                    # ("falls back to the IP itself for display").
                    "label": (entry.label or "").strip() or entry.ip_address_or_cidr,
                    "ip_address_or_cidr": entry.ip_address_or_cidr,
                    "notes": None,
                    "status": status_value,
                    "created_by": str(created_by),
                },
            )
        )
    return rows


@router.get("/api-keys", response_model=APIResponse[list[ApiKeyResponse]])
def list_my_api_keys(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_DEVELOPER))],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    client = get_supabase_admin()
    rows, total = list_for_merchant(client, "api_keys", merchant_id=membership.merchant_id, pagination=pagination)
    data = [ApiKeyResponse(**row) for row in rows]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


@router.post("/api-keys", response_model=APIResponse[ApiKeyCreateResponse], status_code=status.HTTP_201_CREATED)
def create_my_api_key(
    payload: ApiKeyCreate,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_DEVELOPER))],
    request: Request,
    _rate_limit: Annotated[None, Depends(rate_limit(scope="api_key_create", limit=10, window_seconds=60))],
):
    """Sandbox keys are self-service for any non-suspended merchant.
    Production (`live`) keys are ALSO self-service — no per-key Super Admin
    approval — but only once the merchant is approved/verified/priced (see
    app.services.api_access.check_production_api_access)."""
    require_merchant_api_keys_enabled()
    client = get_supabase_admin()
    # Pending/unapproved merchants can't mint any API key (sandbox or
    # live) — see app/services/merchant_gate.py. Production keys have the
    # stricter check_production_api_access gate on top of this.
    merchant = require_approved_merchant(client, membership.merchant_id)
    if payload.environment == "live":
        check_production_api_access(client, merchant)
    else:
        check_sandbox_api_access(merchant)

    plaintext, prefix, last4 = _generate_api_key(payload.environment)

    row = insert_row(
        client,
        "api_keys",
        {
            "merchant_id": str(membership.merchant_id),
            "name": payload.name,
            "environment": payload.environment,
            "key_prefix": prefix,
            "key_last4": last4,
            "hashed_key": hash_api_key(plaintext),
            "scopes": payload.scopes,
            "status": "active",
            "ip_whitelist_enabled": payload.ip_whitelist_enabled,
            "continue_without_ip_whitelist": payload.continue_without_ip_whitelist,
            "created_by": str(membership.user_id),
        },
    )
    if payload.ip_whitelist_enabled and payload.allowed_ips:
        _insert_ip_allowlist_entries(
            client,
            merchant_id=membership.merchant_id,
            api_key_id=uuid.UUID(row["id"]),
            environment=payload.environment,
            entries=payload.allowed_ips,
            created_by=membership.user_id,
        )

    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="api_key.created",
        resource_type="api_key",
        resource_id=uuid.UUID(row["id"]),
        metadata={
            "environment": payload.environment,
            "scopes": payload.scopes,
            "ip_whitelist_enabled": payload.ip_whitelist_enabled,
            "allowed_ip_count": len(payload.allowed_ips),
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse(
        data=ApiKeyCreateResponse(
            id=row["id"],
            name=row["name"],
            environment=row["environment"],
            key_prefix=row["key_prefix"],
            key_last4=row["key_last4"],
            scopes=row["scopes"],
            ip_whitelist_enabled=row["ip_whitelist_enabled"],
            continue_without_ip_whitelist=row["continue_without_ip_whitelist"],
            plaintext_key=plaintext,
            created_at=row["created_at"],
        )
    )


@router.patch("/api-keys/{api_key_id}", response_model=APIResponse[ApiKeyResponse])
def rename_my_api_key(
    api_key_id: uuid.UUID,
    payload: ApiKeyRename,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_DEVELOPER))],
):
    client = get_supabase_admin()
    row = update_row(client, "api_keys", api_key_id, {"name": payload.name}, merchant_id=membership.merchant_id)
    if not row:
        raise NotFoundError("API key not found")

    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="api_key.renamed",
        resource_type="api_key",
        resource_id=api_key_id,
        metadata={"name": payload.name},
    )
    return APIResponse(data=ApiKeyResponse(**row))


@router.patch("/api-keys/{api_key_id}/revoke", response_model=APIResponse[ApiKeyResponse])
def revoke_my_api_key(
    api_key_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_DEVELOPER))],
    request: Request,
):
    """A revoked key can never authenticate again (app.auth.dependencies.
    verify_api_key only matches status='active'). This is also the only
    recovery path if a merchant loses their secret — there's no reveal, so
    "I lost it" means revoke (or rotate) it, never retrieve it."""
    client = get_supabase_admin()
    row = update_row(
        client,
        "api_keys",
        api_key_id,
        {"status": "revoked", "revoked_at": datetime.now(timezone.utc).isoformat()},
        merchant_id=membership.merchant_id,
    )
    if not row:
        raise NotFoundError("API key not found")

    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="api_key.revoked",
        resource_type="api_key",
        resource_id=api_key_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse(data=ApiKeyResponse(**row))


@router.post(
    "/api-keys/{api_key_id}/rotate", response_model=APIResponse[ApiKeyCreateResponse], status_code=status.HTTP_201_CREATED
)
def rotate_my_api_key(
    api_key_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_DEVELOPER))],
    request: Request,
    _rate_limit: Annotated[None, Depends(rate_limit(scope="api_key_create", limit=10, window_seconds=60))],
):
    """Revokes the named key and creates a fresh one with the same
    name/environment/scopes/IP-whitelist choice in a single action — the
    "rotate" a developer reaches for on a schedule, after a suspected leak,
    or simply because they lost the secret (there's no reveal — rotating is
    the only way to get a usable key back). The new key's plaintext is
    returned exactly once, same rule as create_my_api_key — copy it now, it
    can never be retrieved again."""
    require_merchant_api_keys_enabled()
    client = get_supabase_admin()
    old_row = get_by_id(client, "api_keys", api_key_id)
    if not old_row or uuid.UUID(old_row["merchant_id"]) != membership.merchant_id:
        raise NotFoundError("API key not found")
    if old_row["status"] == "revoked":
        raise ConflictError("This key was already revoked")

    merchant = get_by_id(client, "merchants", membership.merchant_id) or {}
    if old_row["environment"] == "live":
        check_production_api_access(client, merchant)
    else:
        check_sandbox_api_access(merchant)

    update_row(
        client,
        "api_keys",
        api_key_id,
        {"status": "revoked", "revoked_at": datetime.now(timezone.utc).isoformat()},
        merchant_id=membership.merchant_id,
    )

    plaintext, prefix, last4 = _generate_api_key(old_row["environment"])
    new_row = insert_row(
        client,
        "api_keys",
        {
            "merchant_id": str(membership.merchant_id),
            "name": old_row["name"],
            "environment": old_row["environment"],
            "key_prefix": prefix,
            "key_last4": last4,
            "hashed_key": hash_api_key(plaintext),
            "scopes": old_row["scopes"],
            "status": "active",
            "ip_whitelist_enabled": old_row.get("ip_whitelist_enabled", False),
            "continue_without_ip_whitelist": old_row.get("continue_without_ip_whitelist", True),
            "created_by": str(membership.user_id),
        },
    )

    if old_row.get("ip_whitelist_enabled"):
        # Carry the old key's linked allowlist entries forward to the new
        # key id, preserving their status — otherwise IP protection would
        # silently lapse the moment a whitelisted key is rotated, since
        # is_ip_allowed() only matches rows scoped to this exact key id (or
        # merchant-wide null rows, which need no copying). The old,
        # revoked key's rows are left as-is, as a historical record.
        old_entries = (
            client.table("api_ip_allowlist")
            .select("*")
            .eq("api_key_id", str(api_key_id))
            .neq("status", "rejected")
            .execute()
        ).data or []
        for entry in old_entries:
            insert_row(
                client,
                "api_ip_allowlist",
                {
                    "merchant_id": str(membership.merchant_id),
                    "api_key_id": new_row["id"],
                    "environment": entry["environment"],
                    "label": entry.get("label"),
                    "ip_address_or_cidr": entry["ip_address_or_cidr"],
                    "notes": entry.get("notes"),
                    "status": entry["status"],
                    "created_by": str(membership.user_id),
                    "approved_by": entry.get("approved_by"),
                },
            )

    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="api_key.rotated",
        resource_type="api_key",
        resource_id=uuid.UUID(new_row["id"]),
        metadata={"replaced_api_key_id": str(api_key_id)},
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse(
        data=ApiKeyCreateResponse(
            id=new_row["id"],
            name=new_row["name"],
            environment=new_row["environment"],
            key_prefix=new_row["key_prefix"],
            key_last4=new_row["key_last4"],
            scopes=new_row["scopes"],
            ip_whitelist_enabled=new_row["ip_whitelist_enabled"],
            continue_without_ip_whitelist=new_row["continue_without_ip_whitelist"],
            plaintext_key=plaintext,
            created_at=new_row["created_at"],
        )
    )


@router.patch("/api-keys/{api_key_id}/ip-whitelist", response_model=APIResponse[ApiKeyResponse])
def update_my_api_key_ip_whitelist(
    api_key_id: uuid.UUID,
    payload: ApiKeyIpWhitelistUpdate,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_DEVELOPER))],
):
    """Switch a key between "Enable IP whitelisting" and "Continue without
    IP whitelisting" after it already exists — from the API key detail
    panel. Switching to enabled requires at least one non-rejected linked
    entry to already exist (add one first via POST .../ip-allowlist with
    this key's id)."""
    client = get_supabase_admin()
    row = get_by_id(client, "api_keys", api_key_id)
    if not row or uuid.UUID(row["merchant_id"]) != membership.merchant_id:
        raise NotFoundError("API key not found")

    if payload.ip_whitelist_enabled:
        linked = (
            client.table("api_ip_allowlist")
            .select("id")
            .eq("api_key_id", str(api_key_id))
            .neq("status", "rejected")
            .execute()
        ).data or []
        if not linked:
            raise ValidationAPIError(
                "Add at least one allowed server IP or choose Continue without IP whitelisting."
            )

    updated = update_row(
        client,
        "api_keys",
        api_key_id,
        {
            "ip_whitelist_enabled": payload.ip_whitelist_enabled,
            "continue_without_ip_whitelist": not payload.ip_whitelist_enabled,
        },
        merchant_id=membership.merchant_id,
    )
    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="api_key.ip_whitelist_updated",
        resource_type="api_key",
        resource_id=api_key_id,
        metadata={"ip_whitelist_enabled": payload.ip_whitelist_enabled},
    )
    return APIResponse(data=ApiKeyResponse(**updated))


# --- IP allowlist -------------------------------------------------------------
# Merchant-provided server IPs — Infinity never generates these. Only ever
# enforced for `live` traffic, and only once at least one `active` row
# exists (see app/services/ip_allowlist.py). New rows start `pending`
# until a Super Admin approves them (PATCH /v1/admin/ip-allowlist/*).


@router.get("/ip-allowlist", response_model=APIResponse[list[IpAllowlistResponse]])
def list_my_ip_allowlist(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_DEVELOPER))],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    api_key_id: Annotated[uuid.UUID | None, Query(description="Filter to entries linked to one API key")] = None,
):
    """Also used by the API key detail panel — GET .../ip-allowlist?api_key_id=...
    to show/manage the IPs linked to one specific key."""
    client = get_supabase_admin()
    filters = {"api_key_id": str(api_key_id)} if api_key_id else None
    rows, total = list_for_merchant(
        client, "api_ip_allowlist", merchant_id=membership.merchant_id, pagination=pagination, filters=filters
    )
    data = [IpAllowlistResponse(**row) for row in rows]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


@router.post("/ip-allowlist", response_model=APIResponse[IpAllowlistResponse], status_code=status.HTTP_201_CREATED)
def create_my_ip_allowlist_entry(
    payload: IpAllowlistCreate,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_DEVELOPER))],
):
    client = get_supabase_admin()
    if payload.api_key_id is not None:
        key = get_by_id(client, "api_keys", payload.api_key_id)
        if not key or uuid.UUID(key["merchant_id"]) != membership.merchant_id:
            raise NotFoundError("API key not found")

    row = insert_row(
        client,
        "api_ip_allowlist",
        {
            "merchant_id": str(membership.merchant_id),
            "api_key_id": str(payload.api_key_id) if payload.api_key_id else None,
            "environment": payload.environment,
            "label": payload.label,
            "ip_address_or_cidr": payload.ip_address_or_cidr,
            "notes": payload.notes,
            "status": "pending",
            "created_by": str(membership.user_id),
        },
    )
    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="ip_allowlist.created",
        resource_type="api_ip_allowlist",
        resource_id=uuid.UUID(row["id"]),
        metadata={"environment": payload.environment, "ip_address_or_cidr": payload.ip_address_or_cidr},
    )
    return APIResponse(data=IpAllowlistResponse(**row))


@router.delete("/ip-allowlist/{entry_id}", response_model=APIResponse[dict])
def delete_my_ip_allowlist_entry(
    entry_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_DEVELOPER))],
):
    client = get_supabase_admin()
    row = get_by_id(client, "api_ip_allowlist", entry_id)
    if not row or uuid.UUID(row["merchant_id"]) != membership.merchant_id:
        raise NotFoundError("IP allowlist entry not found")

    client.table("api_ip_allowlist").delete().eq("id", str(entry_id)).execute()
    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="ip_allowlist.deleted",
        resource_type="api_ip_allowlist",
        resource_id=entry_id,
    )
    return APIResponse(data={"deleted": True})


# --- API logs -------------------------------------------------------------


@router.get("/api-logs", response_model=APIResponse[list[ApiRequestLogResponse]])
def list_my_api_logs(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_DEVELOPER))],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    client = get_supabase_admin()
    rows, total = list_for_merchant(client, "api_request_logs", merchant_id=membership.merchant_id, pagination=pagination)
    data = [ApiRequestLogResponse(**row) for row in rows]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


# --- Risk monitoring ---------------------------------------------------------


@router.get("/risk-alerts", response_model=APIResponse[list[FraudAlertResponse]])
def list_my_risk_alerts(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    client = get_supabase_admin()
    rows, total = list_for_merchant(client, "fraud_alerts", merchant_id=membership.merchant_id, pagination=pagination)
    data = [FraudAlertResponse(**row) for row in rows]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


# --- Document requests --------------------------------------------------------


@router.get("/document-requests", response_model=APIResponse[list[DocumentRequestResponse]])
def list_my_document_requests(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    client = get_supabase_admin()
    rows = document_requests_service.list_document_requests_for_merchant(client, membership.merchant_id)
    return APIResponse(data=[DocumentRequestResponse(**row) for row in rows])


@router.post("/document-requests/{request_id}/submit", response_model=APIResponse[DocumentRequestResponse])
async def submit_document_request(
    request_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
    document_label: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
):
    client = get_supabase_admin()
    request = get_by_id(client, "merchant_document_requests", request_id)
    if not request or request["merchant_id"] != str(membership.merchant_id):
        raise NotFoundError("Document request not found")

    await document_requests_service.register_document_request_file(
        client,
        request_id=request_id,
        merchant_id=membership.merchant_id,
        document_label=document_label,
        file=file,
        uploaded_by=membership.user_id,
    )
    updated = document_requests_service.mark_document_request_submitted(
        client, request_id=request_id, merchant_id=membership.merchant_id
    )
    return APIResponse(data=DocumentRequestResponse(**updated))


# --- Disputes ------------------------------------------------------------------


@router.get("/disputes", response_model=APIResponse[list[DisputeResponse]])
def list_my_disputes(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    client = get_supabase_admin()
    rows = disputes_service.list_disputes_for_merchant(client, membership.merchant_id)
    return APIResponse(data=[DisputeResponse(**row) for row in rows])


@router.get("/disputes/{dispute_id}", response_model=APIResponse[dict])
def get_my_dispute(
    dispute_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    client = get_supabase_admin()
    dispute = get_by_id(client, "disputes", dispute_id)
    if not dispute or dispute.get("merchant_id") != str(membership.merchant_id):
        raise NotFoundError("Dispute not found")
    return APIResponse(data=disputes_service.get_dispute_with_messages(client, dispute_id))


@router.post("/disputes/{dispute_id}/respond", response_model=APIResponse[dict])
def respond_to_my_dispute(
    dispute_id: uuid.UUID,
    payload: DisputeMessageCreate,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    client = get_supabase_admin()
    result = disputes_service.respond_to_dispute(
        client, dispute_id=dispute_id, merchant_id=membership.merchant_id, sender_id=membership.user_id, body=payload.body
    )
    return APIResponse(data=result)


@router.post("/disputes/{dispute_id}/accept-refund", response_model=APIResponse[RefundResponse])
def accept_refund_for_my_dispute(
    dispute_id: uuid.UUID,
    payload: RequestRefundInput,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_ONLY))],
):
    client = get_supabase_admin()
    refund = disputes_service.accept_refund(
        client, dispute_id=dispute_id, merchant_id=membership.merchant_id, amount=payload.amount
    )
    return APIResponse(data=RefundResponse(**refund))


# --- Notifications ---------------------------------------------------------


@router.get("/notifications", response_model=APIResponse[list[NotificationResponse]])
def list_my_notifications(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_AND_STAFF))],
):
    client = get_supabase_admin()
    rows = (
        client.table("notifications")
        .select("*")
        .eq("merchant_id", str(membership.merchant_id))
        .order("created_at", desc=True)
        .execute()
    ).data or []
    return APIResponse(data=[NotificationResponse(**row) for row in rows])


# --- Notification settings (collection emails) --------------------------------
# Where THIS merchant wants collection transaction notifications emailed —
# distinct from the /notifications above (in-app notification feed) and
# from a customer's payment receipt email (never configurable, always the
# customer's own address). See app/services/email.py::
# send_merchant_collection_notification_email and
# app/services/merchant_notifications.py.


@router.get("/notification-settings", response_model=APIResponse[MerchantNotificationSettingsResponse])
def get_my_notification_settings(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_ONLY))],
):
    client = get_supabase_admin()
    row = get_or_create_notification_settings(client, membership.merchant_id)
    return APIResponse(data=MerchantNotificationSettingsResponse(**row))


@router.patch("/notification-settings", response_model=APIResponse[MerchantNotificationSettingsResponse])
def update_my_notification_settings(
    payload: MerchantNotificationSettingsUpdate,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_ONLY))],
):
    client = get_supabase_admin()
    emails = validate_notification_emails(
        [payload.primary_notification_email, payload.secondary_notification_email],
        enabled=payload.collection_notifications_enabled,
    )
    row = upsert_notification_settings(
        client,
        membership.merchant_id,
        primary_notification_email=emails[0] if len(emails) > 0 else None,
        secondary_notification_email=emails[1] if len(emails) > 1 else None,
        collection_notifications_enabled=payload.collection_notifications_enabled,
        updated_by=membership.user_id,
    )
    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="notification_settings.updated",
        resource_type="merchant_notification_settings",
        resource_id=uuid.UUID(row["id"]),
        metadata={
            "collection_notifications_enabled": payload.collection_notifications_enabled,
            "notification_email_count": len(emails),
        },
    )
    return APIResponse(data=MerchantNotificationSettingsResponse(**row))


# --- Team / Users -------------------------------------------------------------


def _merchant_user_response(client, row: dict) -> MerchantUserResponse:
    profile = best_effort_user_profile(client, row["user_id"])
    return MerchantUserResponse(
        id=row["id"],
        user_id=row["user_id"],
        merchant_id=row["merchant_id"],
        full_name=profile.get("full_name"),
        email=profile.get("email"),
        role=row["role"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/users/me", response_model=APIResponse[MerchantUserResponse])
def get_my_membership(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role())],
):
    """Any active member, any role — no admin gate — since this is what the
    Merchant Portal's own topbar account menu reads its signed-in name,
    email, and role from."""
    client = get_supabase_admin()
    row = execute_maybe_single(
        client.table("merchant_users")
        .select("*")
        .eq("merchant_id", str(membership.merchant_id))
        .eq("user_id", str(membership.user_id))
        .maybe_single()
    )
    if not row:
        raise NotFoundError("Membership not found")
    return APIResponse(data=_merchant_user_response(client, row))


@router.post("/users/me/accept-invite", response_model=APIResponse[MerchantUserResponse])
def accept_my_merchant_invite(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
):
    """Called once, right after a newly-invited staff member sets their
    password on the frontend's /dashboard/invite/accept page — flips their
    merchant_users row from 'invited' to 'active' so require_own_merchant_role
    (which only recognizes 'active') starts letting them into the portal.

    Deliberately depends on get_current_user, not require_own_merchant_role:
    the whole point is that this runs *before* the caller has an active
    membership — require_own_merchant_role would 404 every legitimate call.
    merchant_id is never taken from the request; it's resolved purely from
    the merchant_users row create_my_merchant_user already created at
    invite-send time, keyed by this caller's own user_id from their JWT.

    Idempotent: calling this again after already being active just returns
    the existing membership rather than erroring — a staff member re-opening
    an old invite email/tab after already accepting shouldn't see a failure."""
    client = get_supabase_admin()
    rows = (
        client.table("merchant_users")
        .select("*")
        .eq("user_id", str(user.id))
        .in_("status", ["invited", "active"])
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    if not rows:
        raise NotFoundError("No pending invitation found for your account")

    row = rows[0]
    if row["status"] == "invited":
        row = update_row(client, "merchant_users", uuid.UUID(row["id"]), {"status": "active"}) or row
        write_audit_log(
            client,
            actor_id=user.id,
            actor_type="user",
            merchant_id=uuid.UUID(row["merchant_id"]),
            action="merchant_user.invite_accepted",
            resource_type="merchant_user",
            resource_id=uuid.UUID(row["id"]),
        )

    return APIResponse(data=_merchant_user_response(client, row))


@router.get("/users", response_model=APIResponse[list[MerchantUserResponse]])
def list_my_merchant_users(
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_ONLY))],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    client = get_supabase_admin()
    rows, total = list_for_merchant(
        client, "merchant_users", merchant_id=membership.merchant_id, pagination=pagination
    )
    profiles = batch_user_profiles(client, {row["user_id"] for row in rows})
    data = [
        MerchantUserResponse(
            id=row["id"],
            user_id=row["user_id"],
            merchant_id=row["merchant_id"],
            full_name=profiles.get(row["user_id"], {}).get("full_name"),
            email=profiles.get(row["user_id"], {}).get("email"),
            role=row["role"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


@router.post("/users", response_model=APIResponse[MerchantUserResponse], status_code=status.HTTP_201_CREATED)
def create_my_merchant_user(
    payload: MerchantUserCreate,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_ONLY))],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="staff_invite", limit=10, window_seconds=60))],
):
    """Invites a brand new Supabase Auth user by email (never reuses or
    silently attaches an already-registered account to this merchant) and
    links it to the caller's merchant with the requested role.

    Uses auth.admin.generate_link(type="invite") rather than
    invite_user_by_email — generate_link creates the same kind of Supabase
    Auth user + invite token, but does NOT send Supabase's own unbranded
    email; this endpoint sends a branded one via Resend instead
    (app/services/email.py::send_staff_invite_email), carrying the same
    action_link. Raises (fails the whole invite) if that email doesn't go
    out — an admin needs to know the invite didn't actually reach anyone,
    the same fail-closed reasoning as invoice sending."""
    client = get_supabase_admin()
    settings = get_settings()

    merchant = get_by_id(client, "merchants", membership.merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")

    try:
        result = client.auth.admin.generate_link(
            {
                "type": "invite",
                "email": payload.email,
                "options": {
                    "data": {"full_name": payload.full_name},
                    # Must land on the password-setup page, not
                    # /dashboard/login — an invited staff member has no
                    # password yet, so sending them to the login form
                    # leaves them stuck with no way in.
                    "redirect_to": f"{settings.public_app_url}/dashboard/invite/accept",
                },
            }
        )
    except Exception as exc:
        # supabase-py raises a generic AuthApiError for every rejection
        # (duplicate email, invalid email, rate limit, etc) with no stable
        # subclass to catch narrowly.
        raise ConflictError(
            f"Couldn't invite this person — the email may already be registered with InfinityPay. ({exc})"
        ) from exc

    invited_user = result.user
    if not invited_user or not invited_user.id:
        raise ConflictError("Couldn't invite this person — no user was returned by Supabase Auth")

    row = insert_row(
        client,
        "merchant_users",
        {
            "merchant_id": str(membership.merchant_id),
            "user_id": invited_user.id,
            "role": payload.role.value,
            "status": "invited",
            "invited_by": str(membership.user_id),
        },
    )

    send_staff_invite_email(
        client,
        merchant=merchant,
        invited_email=payload.email,
        invited_role=payload.role.value,
        accept_url=result.properties.action_link,
    )

    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="merchant_user.invited",
        resource_type="merchant_user",
        resource_id=uuid.UUID(row["id"]),
        metadata={"role": payload.role.value, "email": payload.email},
    )

    return APIResponse(
        data=MerchantUserResponse(
            id=row["id"],
            user_id=row["user_id"],
            merchant_id=row["merchant_id"],
            full_name=payload.full_name,
            email=payload.email,
            role=row["role"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    )


@router.post("/users/{user_row_id}/resend-invite", response_model=APIResponse[MerchantUserResponse])
def resend_my_merchant_user_invite(
    user_row_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_ONLY))],
):
    """Covers the gap where the original invite email failed to send after
    the Supabase Auth user + merchant_users row were already created
    (POST /users fails closed in that case, but the invited account still
    exists — a second POST /users for the same address would just 409).
    Uses generate_link(type="recovery") rather than "invite" — the
    Supabase Auth user already exists from the original invite, and
    "invite" only works for brand-new users. The resulting action link
    still lands on /dashboard/invite/accept, and
    accept-invite-form.tsx's supabase.auth.updateUser({password}) works
    identically regardless of whether the underlying link type was
    invite or recovery."""
    client = get_supabase_admin()
    row = get_by_id(client, "merchant_users", user_row_id)
    if not row or uuid.UUID(row["merchant_id"]) != membership.merchant_id:
        raise NotFoundError("Merchant user not found")

    if row["status"] != "invited":
        raise ConflictError("This person has already accepted their invite — nothing to resend")

    merchant = get_by_id(client, "merchants", membership.merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")

    profile = best_effort_user_profile(client, row["user_id"])
    invited_email = profile.get("email")
    if not invited_email:
        raise ConflictError("Couldn't find this person's email to resend the invite")

    settings = get_settings()
    try:
        result = client.auth.admin.generate_link(
            {
                "type": "recovery",
                "email": invited_email,
                "options": {"redirect_to": f"{settings.public_app_url}/dashboard/invite/accept"},
            }
        )
    except Exception as exc:
        raise ConflictError(f"Couldn't resend the invite. ({exc})") from exc

    send_staff_invite_email(
        client,
        merchant=merchant,
        invited_email=invited_email,
        invited_role=row["role"],
        accept_url=result.properties.action_link,
    )

    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="merchant_user.invite_resent",
        resource_type="merchant_user",
        resource_id=user_row_id,
        metadata={"role": row["role"]},
    )

    return APIResponse(
        data=MerchantUserResponse(
            id=row["id"],
            user_id=row["user_id"],
            merchant_id=row["merchant_id"],
            full_name=profile.get("full_name"),
            email=invited_email,
            role=row["role"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    )


@router.patch("/users/{user_row_id}", response_model=APIResponse[MerchantUserResponse])
def update_my_merchant_user(
    user_row_id: uuid.UUID,
    payload: MerchantUserUpdate,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_ONLY))],
):
    client = get_supabase_admin()
    row = get_by_id(client, "merchant_users", user_row_id)
    if not row or uuid.UUID(row["merchant_id"]) != membership.merchant_id:
        raise NotFoundError("Merchant user not found")

    if row["user_id"] == str(membership.user_id):
        raise ConflictError("Use your own account settings to change your role or status")

    update_data = payload.model_dump(mode="json", exclude_unset=True)
    if not update_data:
        raise ValidationAPIError("No fields to update")

    row = update_row(client, "merchant_users", user_row_id, update_data, merchant_id=membership.merchant_id) or row

    write_audit_log(
        client,
        actor_id=membership.user_id,
        actor_type="user",
        merchant_id=membership.merchant_id,
        action="merchant_user.updated",
        resource_type="merchant_user",
        resource_id=user_row_id,
        metadata={"fields": sorted(update_data.keys())},
    )
    return APIResponse(data=_merchant_user_response(client, row))


@router.post("/users/{user_row_id}/deactivate", response_model=APIResponse[MerchantUserResponse])
def deactivate_my_merchant_user(
    user_row_id: uuid.UUID,
    membership: Annotated[MerchantMembership, Depends(require_own_merchant_role(*_ADMIN_ONLY))],
):
    client = get_supabase_admin()
    row = get_by_id(client, "merchant_users", user_row_id)
    if not row or uuid.UUID(row["merchant_id"]) != membership.merchant_id:
        raise NotFoundError("Merchant user not found")

    if row["user_id"] == str(membership.user_id):
        raise ConflictError("You cannot deactivate your own account")

    if row["status"] != "suspended":
        row = (
            update_row(client, "merchant_users", user_row_id, {"status": "suspended"}, merchant_id=membership.merchant_id)
            or row
        )
        write_audit_log(
            client,
            actor_id=membership.user_id,
            actor_type="user",
            merchant_id=membership.merchant_id,
            action="merchant_user.deactivated",
            resource_type="merchant_user",
            resource_id=user_row_id,
        )
    return APIResponse(data=_merchant_user_response(client, row))
