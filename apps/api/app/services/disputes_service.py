"""Customer-reported disputes/chargebacks and the refund workflow they can
lead to.

Refunds are a manual workflow — no live payment-provider refund API is
integrated yet (see the PROCESSING -> SUCCESS/FAILED note on
update_refund_status below). Reaching SUCCESS posts a real type='refund'
ledger transaction via app/services/ledger.py's post_refund_entry(), debiting
the merchant's wallet exactly like a disbursement does.
"""

import mimetypes
import uuid
from decimal import Decimal

from fastapi import UploadFile
from supabase import Client

from app.core.errors import NotFoundError, ValidationAPIError
from app.core.references import generate_reference
from app.schemas.enums import NotificationType
from app.services.crud import execute_maybe_single, get_by_id, insert_row, update_row
from app.services.ledger import post_refund_entry
from app.services.notifications_service import notify_admin, notify_merchant
from app.services.webhooks import enqueue_webhook_event

_ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}
_BUCKET = "dispute-evidence"


def _extension_for(file: UploadFile) -> str:
    if file.filename and "." in file.filename:
        return "." + file.filename.rsplit(".", 1)[-1].lower()
    return mimetypes.guess_extension(file.content_type or "") or ""


async def _upload_evidence(client: Client, *, dispute_id: uuid.UUID, files: list[UploadFile]) -> list[dict]:
    uploaded = []
    for file in files:
        if file.content_type not in _ALLOWED_MIME_TYPES:
            raise ValidationAPIError("Evidence files must be PDF, JPG, or PNG")
        content = await file.read()
        if not content:
            continue
        path = f"{dispute_id}/{uuid.uuid4().hex}{_extension_for(file)}"
        client.storage.from_(_BUCKET).upload(
            path, content, {"content-type": file.content_type or "application/octet-stream", "upsert": "true"}
        )
        uploaded.append({"file_path": path, "original_filename": file.filename or "evidence"})
    return uploaded


def _match_transaction(client: Client, *, transaction_reference: str | None) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Best-effort: a customer reporting via the public form may not have
    (or may mistype) the exact reference. Never rejects the report over a
    mismatch — just leaves merchant_id/transaction_id unset for admin
    triage."""
    if not transaction_reference:
        return None, None
    txn = execute_maybe_single(
        client.table("transactions").select("id, merchant_id").eq("reference", transaction_reference).maybe_single()
    )
    if not txn:
        return None, None
    return uuid.UUID(txn["merchant_id"]), uuid.UUID(txn["id"])


async def create_public_dispute(
    client: Client,
    *,
    customer_name: str,
    customer_phone: str,
    customer_email: str | None,
    transaction_reference: str | None,
    amount: Decimal | None,
    reason_category: str,
    description: str,
    evidence_files: list[UploadFile],
) -> dict:
    merchant_id, transaction_id = _match_transaction(client, transaction_reference=transaction_reference)

    dispute = insert_row(
        client,
        "disputes",
        {
            "merchant_id": str(merchant_id) if merchant_id else None,
            "transaction_id": str(transaction_id) if transaction_id else None,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "customer_email": customer_email,
            "transaction_reference": transaction_reference,
            "amount": str(amount) if amount is not None else None,
            "reason_category": reason_category,
            "description": description,
            "status": "MERCHANT_NOTIFIED" if merchant_id else "SUBMITTED",
            "evidence_files": [],
        },
    )
    dispute_id = uuid.UUID(dispute["id"])

    uploaded = await _upload_evidence(client, dispute_id=dispute_id, files=evidence_files)
    if uploaded:
        dispute = update_row(client, "disputes", dispute_id, {"evidence_files": uploaded}) or dispute

    insert_row(
        client,
        "dispute_messages",
        {
            "dispute_id": str(dispute_id),
            "merchant_id": str(merchant_id) if merchant_id else None,
            "sender_type": "system",
            "body": "Dispute submitted by customer via the public report-transaction form.",
        },
    )

    notify_admin(
        client,
        notification_type=NotificationType.DISPUTE_RECEIVED,
        title="New customer dispute reported",
        body=f"{customer_name} reported: {reason_category}.",
        related_resource_type="dispute",
        related_resource_id=dispute_id,
    )
    if merchant_id:
        notify_merchant(
            client,
            merchant_id=merchant_id,
            notification_type=NotificationType.DISPUTE_RECEIVED,
            title="A customer reported an issue with a transaction",
            body=description,
            related_resource_type="dispute",
            related_resource_id=dispute_id,
        )
        enqueue_webhook_event(
            client, merchant_id=merchant_id, event_name="chargeback.opened", payload={"dispute_id": str(dispute_id)}
        )

    return dispute


def list_disputes_for_merchant(client: Client, merchant_id: uuid.UUID) -> list[dict]:
    return (
        client.table("disputes")
        .select("*")
        .eq("merchant_id", str(merchant_id))
        .order("created_at", desc=True)
        .execute()
    ).data or []


def list_all_disputes(client: Client) -> list[dict]:
    return (client.table("disputes").select("*").order("created_at", desc=True).execute()).data or []


def _get_dispute_for_merchant(client: Client, *, dispute_id: uuid.UUID, merchant_id: uuid.UUID) -> dict:
    dispute = get_by_id(client, "disputes", dispute_id)
    if not dispute or dispute.get("merchant_id") != str(merchant_id):
        raise NotFoundError("Dispute not found")
    return dispute


def get_dispute_with_messages(client: Client, dispute_id: uuid.UUID) -> dict:
    dispute = get_by_id(client, "disputes", dispute_id)
    if not dispute:
        raise NotFoundError("Dispute not found")
    messages = (
        client.table("dispute_messages").select("*").eq("dispute_id", str(dispute_id)).order("created_at").execute()
    ).data or []
    return {**dispute, "messages": messages}


def respond_to_dispute(
    client: Client, *, dispute_id: uuid.UUID, merchant_id: uuid.UUID, sender_id: uuid.UUID, body: str
) -> dict:
    dispute = _get_dispute_for_merchant(client, dispute_id=dispute_id, merchant_id=merchant_id)

    insert_row(
        client,
        "dispute_messages",
        {
            "dispute_id": str(dispute_id),
            "merchant_id": str(merchant_id),
            "sender_type": "merchant",
            "sender_id": str(sender_id),
            "body": body,
        },
    )

    if dispute["status"] in ("SUBMITTED", "MERCHANT_NOTIFIED"):
        update_row(client, "disputes", dispute_id, {"status": "UNDER_REVIEW"})
        notify_admin(
            client,
            notification_type=NotificationType.DISPUTE_STATUS_UPDATED,
            title="Merchant responded to a dispute",
            body=body,
            related_resource_type="dispute",
            related_resource_id=dispute_id,
        )

    return get_dispute_with_messages(client, dispute_id)


def update_dispute_status(
    client: Client, *, dispute_id: uuid.UUID, status: str, note: str | None, admin_id: uuid.UUID
) -> dict:
    dispute = get_by_id(client, "disputes", dispute_id)
    if not dispute:
        raise NotFoundError("Dispute not found")

    updated = update_row(client, "disputes", dispute_id, {"status": status})

    insert_row(
        client,
        "dispute_messages",
        {
            "dispute_id": str(dispute_id),
            "merchant_id": dispute.get("merchant_id"),
            "sender_type": "admin",
            "sender_id": str(admin_id),
            "body": note or f"Status changed to {status}.",
        },
    )

    if dispute.get("merchant_id"):
        notify_merchant(
            client,
            merchant_id=uuid.UUID(dispute["merchant_id"]),
            notification_type=NotificationType.DISPUTE_STATUS_UPDATED,
            title=f"Dispute status updated: {status}",
            body=note or f"Your dispute status was updated to {status}.",
            related_resource_type="dispute",
            related_resource_id=dispute_id,
        )
        if status in ("REFUNDED", "REJECTED", "CLOSED"):
            enqueue_webhook_event(
                client,
                merchant_id=uuid.UUID(dispute["merchant_id"]),
                event_name="chargeback.resolved",
                payload={"dispute_id": str(dispute_id), "status": status},
            )

    return updated or dispute


def accept_refund(client: Client, *, dispute_id: uuid.UUID, merchant_id: uuid.UUID, amount: Decimal) -> dict:
    dispute = _get_dispute_for_merchant(client, dispute_id=dispute_id, merchant_id=merchant_id)
    if not dispute.get("transaction_id"):
        raise ValidationAPIError("This dispute has no matched transaction to refund")

    refund = insert_row(
        client,
        "refunds",
        {
            "dispute_id": str(dispute_id),
            "transaction_id": dispute["transaction_id"],
            "merchant_id": str(merchant_id),
            "amount": str(amount),
            "currency": "TZS",
            "status": "REQUESTED",
            "requested_by": "merchant",
            "evidence_files": [],
        },
    )
    update_row(client, "disputes", dispute_id, {"status": "REFUND_REQUESTED"})
    notify_admin(
        client,
        notification_type=NotificationType.REFUND_REQUESTED,
        title="Merchant accepted a refund request",
        body=f"Merchant accepted a refund of {amount} for dispute {dispute_id}.",
        related_resource_type="refund",
        related_resource_id=uuid.UUID(refund["id"]),
    )
    return refund


def admin_request_refund(client: Client, *, dispute_id: uuid.UUID, amount: Decimal) -> dict:
    dispute = get_by_id(client, "disputes", dispute_id)
    if not dispute:
        raise NotFoundError("Dispute not found")
    if not dispute.get("transaction_id"):
        raise ValidationAPIError("This dispute has no matched transaction to refund")
    if not dispute.get("merchant_id"):
        raise ValidationAPIError("This dispute has no matched merchant to request a refund from")

    merchant_id = uuid.UUID(dispute["merchant_id"])
    refund = insert_row(
        client,
        "refunds",
        {
            "dispute_id": str(dispute_id),
            "transaction_id": dispute["transaction_id"],
            "merchant_id": str(merchant_id),
            "amount": str(amount),
            "currency": "TZS",
            "status": "REQUESTED",
            "requested_by": "admin",
            "evidence_files": [],
        },
    )
    update_row(client, "disputes", dispute_id, {"status": "REFUND_REQUESTED"})
    notify_merchant(
        client,
        merchant_id=merchant_id,
        notification_type=NotificationType.REFUND_REQUESTED,
        title="InfinityPay requested a refund for a dispute",
        body=f"Please review and process a refund of {amount}.",
        related_resource_type="refund",
        related_resource_id=uuid.UUID(refund["id"]),
    )
    return refund


def update_refund_status(
    client: Client, *, refund_id: uuid.UUID, status: str, provider_reference: str | None
) -> dict:
    """Admin marks a refund's outcome based on provider/manual confirmation
    — there is no live payment-provider refund API integrated yet.
    PROCESSING -> SUCCESS posts a real type='refund' ledger transaction."""
    refund = get_by_id(client, "refunds", refund_id)
    if not refund:
        raise NotFoundError("Refund not found")

    update_data: dict = {"status": status}
    if provider_reference:
        update_data["provider_reference"] = provider_reference
    refund = update_row(client, "refunds", refund_id, update_data) or refund

    merchant_id = uuid.UUID(refund["merchant_id"])

    if status == "SUCCESS":
        amount = Decimal(str(refund["amount"]))
        txn = insert_row(
            client,
            "transactions",
            {
                "merchant_id": str(merchant_id),
                "reference": generate_reference("TXN"),
                "type": "refund",
                "method": "INTERNAL",
                "gross_amount": str(amount),
                "fee_amount": "0",
                "net_amount": str(amount),
                "currency": refund["currency"],
                "status": "successful",
                "metadata": {"refund_id": str(refund_id), "original_transaction_id": refund["transaction_id"]},
            },
        )
        post_refund_entry(
            client,
            transaction_id=uuid.UUID(txn["id"]),
            merchant_id=merchant_id,
            amount=amount,
            currency=refund["currency"],
        )
        update_row(client, "disputes", uuid.UUID(refund["dispute_id"]), {"status": "REFUNDED"})
        enqueue_webhook_event(
            client,
            merchant_id=merchant_id,
            event_name="refund.succeeded",
            payload={"refund_id": str(refund_id), "amount": str(amount)},
        )
        notify_merchant(
            client,
            merchant_id=merchant_id,
            notification_type=NotificationType.DISPUTE_STATUS_UPDATED,
            title="Refund completed",
            body=f"A refund of {amount} {refund['currency']} has been completed.",
            related_resource_type="refund",
            related_resource_id=refund_id,
        )

    elif status == "FAILED":
        enqueue_webhook_event(
            client, merchant_id=merchant_id, event_name="refund.failed", payload={"refund_id": str(refund_id)}
        )
        notify_merchant(
            client,
            merchant_id=merchant_id,
            notification_type=NotificationType.DISPUTE_STATUS_UPDATED,
            title="Refund attempt failed",
            body="A refund attempt failed — InfinityPay will follow up.",
            related_resource_type="refund",
            related_resource_id=refund_id,
        )

    return refund
