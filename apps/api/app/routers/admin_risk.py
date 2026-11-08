"""Super Admin fraud/risk monitoring and document-request review —
/v1/admin/risk-alerts, /v1/admin/document-requests, /v1/admin/notifications.

Own file, not admin.py, matching that router's own stated convention
(onboarding review lives in admin_onboarding.py, not admin.py either).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth import require_super_admin
from app.core.errors import NotFoundError
from app.core.pagination import LIST_COUNT, PaginationParams, build_page_meta, pagination_params
from app.core.time import utc_now_iso
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse
from app.schemas.document_requests import AdminDocumentRequestResponse
from app.schemas.enums import NotificationType
from app.schemas.fraud import (
    AdminFraudAlertResponse,
    FraudAlertNoteCreate,
    FraudAlertStatusUpdate,
    RequestDocumentsInput,
)
from app.schemas.notifications import NotificationResponse
from app.services import document_requests_service
from app.services.admin_directory import batch_merchant_codes, batch_merchant_names
from app.services.collections import finalize_pending_review_collection
from app.services.crud import get_by_id, insert_row, update_row
from app.services.notifications_service import notify_merchant

router = APIRouter(prefix="/admin", tags=["admin-risk"])


@router.get("/risk-alerts", response_model=APIResponse[list[AdminFraudAlertResponse]])
def list_risk_alerts(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    merchant_id: Annotated[uuid.UUID | None, Query()] = None,
):
    client = get_supabase_admin()
    query = client.table("fraud_alerts").select("*", count=LIST_COUNT)
    if merchant_id is not None:
        query = query.eq("merchant_id", str(merchant_id))
    result = query.order("created_at", desc=True).range(pagination.start, pagination.end).execute()
    rows = result.data or []
    names = batch_merchant_names(client, {r["merchant_id"] for r in rows})
    codes = batch_merchant_codes(client, {r["merchant_id"] for r in rows})
    data = [
        AdminFraudAlertResponse.from_row(
            row, merchant_name=names.get(row["merchant_id"]), merchant_code=codes.get(row["merchant_id"])
        )
        for row in rows
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


@router.patch("/risk-alerts/{alert_id}/status", response_model=APIResponse[AdminFraudAlertResponse])
def update_risk_alert_status(
    alert_id: uuid.UUID,
    payload: FraudAlertStatusUpdate,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    alert = get_by_id(client, "fraud_alerts", alert_id)
    if not alert:
        raise NotFoundError("Fraud alert not found")

    updated = update_row(client, "fraud_alerts", alert_id, {"status": payload.status})
    insert_row(
        client,
        "fraud_alert_events",
        {
            "alert_id": str(alert_id),
            "actor_id": str(admin.id),
            "actor_type": "user",
            "action": "status_changed",
            "from_status": alert["status"],
            "to_status": payload.status,
            "note": payload.note,
        },
    )
    if payload.status in ("CLEARED", "CLOSED") and alert.get("transaction_id"):
        client.table("transaction_reviews").update({"status": "CLEARED", "cleared_at": utc_now_iso()}).eq(
            "transaction_id", alert["transaction_id"]
        ).execute()

    if payload.status == "CLEARED" and alert.get("rule_code") == "SELF_PAYMENT_OWN_TILL":
        # This alert is what held a collection in 'pending_review' instead
        # of crediting it (app/services/fraud_monitoring_service.py::
        # check_self_payment_risk, called from resolve_collection()) —
        # clearing it here is the only place that collection ever gets
        # credited. Idempotent: finalize_pending_review_collection() only
        # acts on a collection still 'pending_review', so re-clearing an
        # already-CLOSED alert (or clearing CLOSED after CLEARED) can't
        # double-credit.
        collection_id = (alert.get("metadata") or {}).get("collection_id")
        if collection_id:
            finalize_pending_review_collection(client, collection_id=uuid.UUID(collection_id))

    notify_merchant(
        client,
        merchant_id=uuid.UUID(alert["merchant_id"]),
        notification_type=NotificationType.FRAUD_ALERT,
        title=f"Transaction review status updated: {payload.status}",
        body=payload.note or f"Status changed to {payload.status}.",
        related_resource_type="fraud_alert",
        related_resource_id=alert_id,
    )

    row = updated or alert
    names = batch_merchant_names(client, {row["merchant_id"]})
    codes = batch_merchant_codes(client, {row["merchant_id"]})
    return APIResponse(
        data=AdminFraudAlertResponse.from_row(
            row, merchant_name=names.get(row["merchant_id"]), merchant_code=codes.get(row["merchant_id"])
        )
    )


@router.post("/risk-alerts/{alert_id}/notes", response_model=APIResponse[AdminFraudAlertResponse])
def add_risk_alert_note(
    alert_id: uuid.UUID,
    payload: FraudAlertNoteCreate,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    alert = get_by_id(client, "fraud_alerts", alert_id)
    if not alert:
        raise NotFoundError("Fraud alert not found")

    insert_row(
        client,
        "fraud_alert_events",
        {
            "alert_id": str(alert_id),
            "actor_id": str(admin.id),
            "actor_type": "user",
            "action": "note_added",
            "note": payload.note,
        },
    )
    names = batch_merchant_names(client, {alert["merchant_id"]})
    codes = batch_merchant_codes(client, {alert["merchant_id"]})
    return APIResponse(
        data=AdminFraudAlertResponse.from_row(
            alert, merchant_name=names.get(alert["merchant_id"]), merchant_code=codes.get(alert["merchant_id"])
        )
    )


@router.post("/risk-alerts/{alert_id}/request-documents", response_model=APIResponse[AdminDocumentRequestResponse])
def request_documents_for_alert(
    alert_id: uuid.UUID,
    payload: RequestDocumentsInput,
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    alert = get_by_id(client, "fraud_alerts", alert_id)
    if not alert:
        raise NotFoundError("Fraud alert not found")

    request = document_requests_service.create_document_request(
        client,
        merchant_id=uuid.UUID(alert["merchant_id"]),
        transaction_id=uuid.UUID(alert["transaction_id"]) if alert.get("transaction_id") else None,
        alert_id=alert_id,
        requested_documents=payload.requested_documents,
        reason=payload.reason,
        due_date=payload.due_date,
    )
    names = batch_merchant_names(client, {request["merchant_id"]})
    codes = batch_merchant_codes(client, {request["merchant_id"]})
    return APIResponse(
        data=AdminDocumentRequestResponse.from_row(
            request, merchant_name=names.get(request["merchant_id"]), merchant_code=codes.get(request["merchant_id"])
        )
    )


@router.get("/document-requests", response_model=APIResponse[list[AdminDocumentRequestResponse]])
def list_document_requests(_admin: Annotated[AuthenticatedUser, Depends(require_super_admin)]):
    client = get_supabase_admin()
    rows = document_requests_service.list_all_document_requests(client)
    names = batch_merchant_names(client, {r["merchant_id"] for r in rows})
    codes = batch_merchant_codes(client, {r["merchant_id"] for r in rows})
    for row in rows:
        for file in row.get("files", []):
            file["signed_url"] = document_requests_service.get_document_file_signed_url(client, file)
    return APIResponse(
        data=[
            AdminDocumentRequestResponse.from_row(
                row, merchant_name=names.get(row["merchant_id"]), merchant_code=codes.get(row["merchant_id"])
            )
            for row in rows
        ]
    )


@router.patch("/document-requests/{request_id}/approve", response_model=APIResponse[AdminDocumentRequestResponse])
def approve_document_request(
    request_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    request = document_requests_service.review_document_request(
        client, request_id=request_id, reviewer_id=admin.id, status="APPROVED"
    )
    names = batch_merchant_names(client, {request["merchant_id"]})
    codes = batch_merchant_codes(client, {request["merchant_id"]})
    return APIResponse(
        data=AdminDocumentRequestResponse.from_row(
            request, merchant_name=names.get(request["merchant_id"]), merchant_code=codes.get(request["merchant_id"])
        )
    )


@router.patch("/document-requests/{request_id}/reject", response_model=APIResponse[AdminDocumentRequestResponse])
def reject_document_request(
    request_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    request = document_requests_service.review_document_request(
        client, request_id=request_id, reviewer_id=admin.id, status="REJECTED"
    )
    names = batch_merchant_names(client, {request["merchant_id"]})
    codes = batch_merchant_codes(client, {request["merchant_id"]})
    return APIResponse(
        data=AdminDocumentRequestResponse.from_row(
            request, merchant_name=names.get(request["merchant_id"]), merchant_code=codes.get(request["merchant_id"])
        )
    )


@router.get("/notifications", response_model=APIResponse[list[NotificationResponse]])
def list_admin_notifications(_admin: Annotated[AuthenticatedUser, Depends(require_super_admin)]):
    client = get_supabase_admin()
    rows = (
        client.table("notifications")
        .select("*")
        .eq("recipient_type", "admin")
        .order("created_at", desc=True)
        .execute()
    ).data or []
    return APIResponse(data=[NotificationResponse(**row) for row in rows])
