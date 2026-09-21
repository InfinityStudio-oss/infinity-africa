"""Public, unauthenticated dispute/chargeback reporting —
POST /v1/public/disputes/report. A customer reports an issue with a
merchant's product/service or a payment they didn't authorize; InfinityPay
notifies the merchant and reviews. Mirrors payment_links.py's public_router
pattern (no auth dependency at all — this is deliberately open to anyone).
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import ValidationError

from app.core.errors import ValidationAPIError
from app.core.rate_limit import rate_limit
from app.database.session import get_supabase_admin
from app.schemas.common import APIResponse
from app.schemas.disputes import DisputeResponse, PublicDisputeReportCreate
from app.services.disputes_service import create_public_dispute

router = APIRouter(prefix="/public/disputes", tags=["disputes (public)"])


@router.post("/report", response_model=APIResponse[DisputeResponse])
async def report_transaction(
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="public_dispute_report", limit=5, window_seconds=60))
    ],
    customer_name: Annotated[str, Form()],
    customer_phone: Annotated[str, Form()],
    reason_category: Annotated[str, Form()],
    description: Annotated[str, Form()],
    customer_email: Annotated[str | None, Form()] = None,
    transaction_reference: Annotated[str | None, Form()] = None,
    merchant_name: Annotated[str | None, Form()] = None,
    amount: Annotated[str | None, Form()] = None,
    payment_date: Annotated[str | None, Form()] = None,
    evidence: Annotated[list[UploadFile] | None, File()] = None,
):
    try:
        payload = PublicDisputeReportCreate(
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_email=customer_email,
            transaction_reference=transaction_reference,
            merchant_name=merchant_name,
            amount=Decimal(amount) if amount else None,
            payment_date=date.fromisoformat(payment_date) if payment_date else None,
            reason_category=reason_category,
            description=description,
        )
    except (ValidationError, ValueError) as exc:
        raise ValidationAPIError(str(exc)) from exc

    client = get_supabase_admin()
    files = [f for f in (evidence or []) if f.filename]
    dispute = await create_public_dispute(
        client,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        customer_email=payload.customer_email,
        transaction_reference=payload.transaction_reference,
        amount=payload.amount,
        reason_category=payload.reason_category,
        description=payload.description,
        evidence_files=files,
    )
    return APIResponse(data=DisputeResponse(**dispute))
