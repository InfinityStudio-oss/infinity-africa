"""Merchant document requests: a super admin (directly, or via a fraud
alert's "Request Documents" action) asks a merchant to submit supporting
evidence for a specific transaction. File handling mirrors
app/services/onboarding.py's register_onboarding_document() exactly —
validate -> read -> upload -> upsert a metadata row — against the private
"document-requests" bucket instead of "merchant-documents".
"""

import mimetypes
import uuid

from fastapi import UploadFile
from supabase import Client

from app.core.errors import NotFoundError, ValidationAPIError
from app.schemas.enums import NotificationType
from app.services.crud import get_by_id, insert_row, update_row
from app.services.notifications_service import notify_admin, notify_merchant

_ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}
_BUCKET = "document-requests"


def _extension_for(file: UploadFile) -> str:
    if file.filename and "." in file.filename:
        return "." + file.filename.rsplit(".", 1)[-1].lower()
    return mimetypes.guess_extension(file.content_type or "") or ""


def _with_files(client: Client, request: dict) -> dict:
    files = (
        client.table("document_request_files").select("*").eq("request_id", request["id"]).execute()
    ).data or []
    return {**request, "files": files}


def list_document_requests_for_merchant(client: Client, merchant_id: uuid.UUID) -> list[dict]:
    rows = (
        client.table("merchant_document_requests")
        .select("*")
        .eq("merchant_id", str(merchant_id))
        .order("created_at", desc=True)
        .execute()
    ).data or []
    return [_with_files(client, row) for row in rows]


def list_all_document_requests(client: Client) -> list[dict]:
    rows = (
        client.table("merchant_document_requests").select("*").order("created_at", desc=True).execute()
    ).data or []
    return [_with_files(client, row) for row in rows]


def get_document_request(client: Client, request_id: uuid.UUID) -> dict:
    request = get_by_id(client, "merchant_document_requests", request_id)
    if not request:
        raise NotFoundError("Document request not found")
    return _with_files(client, request)


def create_document_request(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    transaction_id: uuid.UUID | None,
    alert_id: uuid.UUID | None,
    requested_documents: list[str],
    reason: str,
    due_date: str | None,
) -> dict:
    request = insert_row(
        client,
        "merchant_document_requests",
        {
            "merchant_id": str(merchant_id),
            "transaction_id": str(transaction_id) if transaction_id else None,
            "alert_id": str(alert_id) if alert_id else None,
            "requested_documents": requested_documents,
            "reason": reason,
            "status": "PENDING",
            "due_date": due_date,
        },
    )
    if alert_id:
        update_row(client, "fraud_alerts", alert_id, {"status": "DOCUMENTS_REQUESTED"})
    notify_merchant(
        client,
        merchant_id=merchant_id,
        notification_type=NotificationType.DOCUMENT_REQUEST,
        title="Supporting documents required for this transaction.",
        body=reason,
        related_resource_type="document_request",
        related_resource_id=uuid.UUID(request["id"]),
    )
    return _with_files(client, request)


async def register_document_request_file(
    client: Client,
    *,
    request_id: uuid.UUID,
    merchant_id: uuid.UUID,
    document_label: str,
    file: UploadFile,
    uploaded_by: uuid.UUID,
) -> dict:
    if file.content_type not in _ALLOWED_MIME_TYPES:
        raise ValidationAPIError(f"{document_label} must be a PDF, JPG, or PNG file")

    content = await file.read()
    if not content:
        raise ValidationAPIError(f"{document_label} file is empty")

    path = f"{merchant_id}/{request_id}/{uuid.uuid4().hex}{_extension_for(file)}"
    client.storage.from_(_BUCKET).upload(
        path, content, {"content-type": file.content_type or "application/octet-stream", "upsert": "true"}
    )

    return insert_row(
        client,
        "document_request_files",
        {
            "request_id": str(request_id),
            "merchant_id": str(merchant_id),
            "document_label": document_label,
            "file_path": path,
            "original_filename": file.filename or document_label,
            "mime_type": file.content_type or "application/octet-stream",
            "size_bytes": len(content),
            "uploaded_by": str(uploaded_by),
        },
    )


def mark_document_request_submitted(client: Client, *, request_id: uuid.UUID, merchant_id: uuid.UUID) -> dict:
    request = update_row(client, "merchant_document_requests", request_id, {"status": "SUBMITTED"})
    notify_admin(
        client,
        notification_type=NotificationType.DOCUMENT_REQUEST,
        title="Merchant submitted requested documents",
        body=f"Merchant {merchant_id} submitted documents for review.",
        related_resource_type="document_request",
        related_resource_id=request_id,
    )
    return _with_files(client, request) if request else request


def get_document_file_signed_url(client: Client, file_row: dict, *, expires_in: int = 300) -> str | None:
    try:
        result = client.storage.from_(_BUCKET).create_signed_url(file_row["file_path"], expires_in)
    except Exception:  # noqa: BLE001 — StorageException or transient failure, either way no URL
        return None
    return result.get("signedURL") or result.get("signedUrl")


def review_document_request(
    client: Client, *, request_id: uuid.UUID, reviewer_id: uuid.UUID, status: str
) -> dict:
    request = get_by_id(client, "merchant_document_requests", request_id)
    if not request:
        raise NotFoundError("Document request not found")

    updated = update_row(client, "merchant_document_requests", request_id, {"status": status})
    notify_merchant(
        client,
        merchant_id=uuid.UUID(request["merchant_id"]),
        notification_type=NotificationType.DOCUMENT_REQUEST,
        title=f"Document request {status.lower()}",
        body=f"Your submitted documents were {status.lower()} by InfinityPay.",
        related_resource_type="document_request",
        related_resource_id=request_id,
    )
    return _with_files(client, updated) if updated else request
