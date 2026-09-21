import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth import require_role
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse
from app.schemas.developer_docs import DeveloperDocsResponse, EndpointGroup
from app.schemas.enums import UserRole

router = APIRouter(prefix="/merchants/{merchant_id}/developer-docs", tags=["developer-docs"])

# The DEVELOPER role's one stated capability is "view API documentation and
# manage API keys" — MERCHANT_ADMIN gets it too since it's read-only.
_ALLOWED_ROLES = (UserRole.MERCHANT_ADMIN, UserRole.DEVELOPER)

_ENDPOINT_GROUPS = [
    EndpointGroup(
        name="Payment Links",
        base_path="/v1/payment-links",
        description="Create shareable checkout links (flat resource — merchant_id in the body, "
        "not the path); public read/collect at /public/payment-links/{public_slug}.",
    ),
    EndpointGroup(
        name="Invoices",
        base_path="/v1/invoices",
        description="Itemized bills (flat resource — merchant_id in the body/query, not the path); "
        "generate a customer-facing \"Pay Now\" payment link at "
        "/v1/invoices/{invoice_id}/payment-link, paid through /public/payment-links/{public_slug}.",
    ),
    EndpointGroup(
        name="Collections",
        base_path="/v1/collections/{ussd-push,stk-push,selcom-pesa-push,dynamic-qr}",
        description="Initiate a mock push/QR collection (flat — merchant_id in the body); "
        "always returns PROCESSING. Read back at /v1/merchants/{merchant_id}/collections.",
    ),
    EndpointGroup(
        name="Disbursements",
        base_path="/v1/disbursements/{selcom-pesa,mobile-money,bank-account}",
        description="Request a payout from your InfinityPay balance (flat — merchant_id in the body; "
        "validates available balance first). Read back at /v1/disbursements "
        "(merchant_id as a query param) or /v1/disbursements/{id}.",
    ),
    EndpointGroup(
        name="Transactions",
        base_path="/v1/merchants/{merchant_id}/transactions",
        description="Read-only unified ledger of every collection, disbursement, and fee.",
    ),
    EndpointGroup(
        name="Webhooks",
        base_path="/v1/merchants/{merchant_id}/webhooks",
        description="Delivery log for events sent to your configured webhook_url.",
    ),
    EndpointGroup(
        name="API Keys",
        base_path="/v1/merchant/api-keys",
        description="Create/list/revoke the sandbox and live keys used to authenticate these calls "
        "(self-service — resolves your own merchant from your dashboard session).",
    ),
]


@router.get("", response_model=APIResponse[DeveloperDocsResponse])
def get_developer_docs(
    merchant_id: uuid.UUID,
    _actor: Annotated[AuthenticatedUser, Depends(require_role(*_ALLOWED_ROLES))],
):
    return APIResponse(
        data=DeveloperDocsResponse(
            api_version="v1",
            swagger_ui_url="/docs",
            openapi_schema_url="/openapi.json",
            authentication={
                "dashboard": "Authorization: Bearer <Supabase Auth JWT>",
                "server_to_server": "X-API-Key: <your api key, from /v1/merchant/api-keys>",
                "idempotency": "Idempotency-Key header required on POST /payment-links, /collections, "
                "/disbursements, and /collect endpoints",
            },
            endpoint_groups=_ENDPOINT_GROUPS,
        )
    )
