"""Platform-wide Super Admin dashboard reads — /v1/admin/*.

Every route here is `require_super_admin`-gated and reads across ALL
merchants (no merchant_id scoping) — distinct from the existing
merchant-scoped routers (payment_links.py, invoices.py, collections.py,
transactions.py, disbursements.py) which stay as they are. List endpoints
follow routers/merchants.py::list_merchants' exact pattern: inline
`.select("*", count="exact").order(...).range(...)`, not services/crud.py's
merchant-scoped helpers (these queries have no merchant_id to scope by).

Onboarding review (GET/POST /v1/admin/onboarding/*) lives in
routers/admin_onboarding.py, not here — untouched by this router.
"""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth import require_super_admin
from app.core.errors import NotFoundError
from app.core.pagination import PaginationParams, build_page_meta, pagination_params
from app.core.time import utc_now_iso
from app.database.session import get_supabase_admin
from app.schemas.admin import (
    AdminApiKeyResponse,
    AdminAuditLogResponse,
    AdminCollectionResponse,
    AdminCustomerResponse,
    AdminInquiryResponse,
    AdminInvoiceResponse,
    AdminMerchantResponse,
    AdminMerchantUserResponse,
    AdminOverviewResponse,
    AdminPayByLinkResponse,
    AdminPaymentLinkResponse,
    AdminTransactionResponse,
    AdminWebhookEventResponse,
    AdminWithdrawalResponse,
)
from app.schemas.api_keys import ApiKeyResponse
from app.schemas.api_logs import AdminApiRequestLogResponse
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse
from app.schemas.ip_allowlist import AdminIpAllowlistResponse
from app.schemas.merchant_notifications import (
    AdminMerchantNotificationSettingsResponse,
    MerchantNotificationSettingsUpdate,
)
from app.schemas.pay_by_link import PayByLinkResponse
from app.schemas.webhook_config import WebhookConfigResponse
from app.services.admin_customers import list_admin_customers
from app.services.admin_directory import (
    batch_api_key_prefixes,
    batch_merchant_codes,
    batch_merchant_names,
    batch_user_profiles,
    batch_wallet_balances,
)
from app.services.admin_overview import get_admin_overview
from app.services.api_access import is_production_api_access_allowed
from app.services.audit import write_audit_log
from app.services.checkout_reconciliation import refresh_checkout_collection_status
from app.services.crud import execute_maybe_single, get_by_id, update_row
from app.services.email import batch_latest_email_deliveries
from app.services.ledger import get_wallet_balance
from app.services.merchant_notifications import (
    get_or_create_notification_settings,
    notification_delivery_summary,
    upsert_notification_settings,
    validate_notification_emails,
)
from app.services.pay_by_link import get_own_pay_link
from app.services.payment_links import build_public_url
from app.services.webhooks import last_webhook_delivery

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=APIResponse[AdminOverviewResponse])
def get_overview(_admin: Annotated[AuthenticatedUser, Depends(require_super_admin)]):
    client = get_supabase_admin()
    return APIResponse(data=AdminOverviewResponse(**get_admin_overview(client)))


@router.get("/merchants", response_model=APIResponse[list[AdminMerchantResponse]])
def list_admin_merchants(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    client = get_supabase_admin()
    result = (
        client.table("merchants")
        .select("*", count="exact")
        .order("created_at", desc=True)
        .range(pagination.start, pagination.end)
        .execute()
    )
    merchants = result.data or []
    merchant_ids = {m["id"] for m in merchants}

    submissions: list[dict] = []
    owner_user_id_by_merchant: dict[str, str] = {}
    if merchant_ids:
        submissions = (
            client.table("onboarding_submissions")
            .select("merchant_id, nature_of_business, physical_address")
            .in_("merchant_id", list(merchant_ids))
            .execute()
        ).data or []

        memberships = (
            client.table("merchant_users")
            .select("merchant_id, user_id")
            .in_("merchant_id", list(merchant_ids))
            .eq("role", "MERCHANT_ADMIN")
            .eq("status", "active")
            .execute()
        ).data or []
        owner_user_id_by_merchant = {m["merchant_id"]: m["user_id"] for m in memberships}

    submission_by_merchant = {s["merchant_id"]: s for s in submissions}
    profiles = batch_user_profiles(client, set(owner_user_id_by_merchant.values()))

    data = []
    for merchant in merchants:
        submission = submission_by_merchant.get(merchant["id"])
        owner_user_id = owner_user_id_by_merchant.get(merchant["id"])
        profile = profiles.get(owner_user_id, {}) if owner_user_id else {}
        data.append(
            AdminMerchantResponse(
                merchant_id=merchant["id"],
                merchant_code=merchant.get("merchant_code"),
                business_name=merchant["business_name"],
                owner_name=profile.get("full_name"),
                email=merchant["contact_email"],
                contact_phone=merchant.get("contact_phone"),
                nature_of_business=submission["nature_of_business"] if submission else None,
                physical_address=submission["physical_address"] if submission else None,
                account_status=merchant["status"],
                kyc_status=merchant["kyc_status"],
                api_access_suspended=bool(merchant.get("api_access_suspended")),
                production_api_eligible=is_production_api_access_allowed(client, merchant),
                available_balance=get_wallet_balance(
                    client, merchant_id=uuid.UUID(merchant["id"]), currency=merchant["currency"]
                ),
                created_at=merchant["created_at"],
            )
        )
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


@router.get("/merchants/{merchant_id}", response_model=APIResponse[AdminMerchantResponse])
def get_admin_merchant(
    merchant_id: uuid.UUID,
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    merchant = get_by_id(client, "merchants", merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")

    submission = (
        client.table("onboarding_submissions")
        .select("nature_of_business, physical_address")
        .eq("merchant_id", str(merchant_id))
        .execute()
    ).data or []
    membership = (
        client.table("merchant_users")
        .select("user_id")
        .eq("merchant_id", str(merchant_id))
        .eq("role", "MERCHANT_ADMIN")
        .eq("status", "active")
        .execute()
    ).data or []
    profile = batch_user_profiles(client, {m["user_id"] for m in membership}).get(
        membership[0]["user_id"] if membership else None, {}
    )

    return APIResponse(
        data=AdminMerchantResponse(
            merchant_id=merchant["id"],
            merchant_code=merchant.get("merchant_code"),
            business_name=merchant["business_name"],
            owner_name=profile.get("full_name"),
            email=merchant["contact_email"],
            contact_phone=merchant.get("contact_phone"),
            nature_of_business=submission[0]["nature_of_business"] if submission else None,
            physical_address=submission[0]["physical_address"] if submission else None,
            account_status=merchant["status"],
            kyc_status=merchant["kyc_status"],
            api_access_suspended=bool(merchant.get("api_access_suspended")),
            production_api_eligible=is_production_api_access_allowed(client, merchant),
            available_balance=get_wallet_balance(
                client, merchant_id=merchant_id, currency=merchant["currency"]
            ),
            created_at=merchant["created_at"],
        )
    )


@router.post("/merchants/{merchant_id}/api-access/suspend", response_model=APIResponse[AdminMerchantResponse])
def suspend_merchant_api_access(
    merchant_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Abuse/fraud kill switch — blocks ALL API key authentication for this
    merchant (sandbox and live both, see app.auth.dependencies.verify_api_key)
    regardless of approval status. Does not revoke any existing key
    (revoke those explicitly via PATCH /v1/admin/api-keys/{id}/revoke if
    that's also intended) — it blocks *authentication*, so a suspended
    merchant's keys simply stop working until reinstated."""
    client = get_supabase_admin()
    merchant = get_by_id(client, "merchants", merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")

    update_row(
        client,
        "merchants",
        merchant_id,
        {
            "api_access_suspended": True,
            "api_access_suspended_at": utc_now_iso(),
            "api_access_suspended_by": str(admin.id),
        },
    )
    write_audit_log(
        client,
        actor_id=admin.id,
        actor_type="user",
        merchant_id=merchant_id,
        action="merchant.api_access_suspended",
        resource_type="merchant",
        resource_id=merchant_id,
    )
    return get_admin_merchant(merchant_id, admin)


@router.post("/merchants/{merchant_id}/api-access/reinstate", response_model=APIResponse[AdminMerchantResponse])
def reinstate_merchant_api_access(
    merchant_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Lifts a suspension. Production self-service eligibility still
    depends on the merchant's own approval/KYC/pricing state — this only
    clears the Super Admin override, it doesn't itself grant production
    access to a merchant who wasn't otherwise eligible."""
    client = get_supabase_admin()
    merchant = get_by_id(client, "merchants", merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")

    update_row(client, "merchants", merchant_id, {"api_access_suspended": False})
    write_audit_log(
        client,
        actor_id=admin.id,
        actor_type="user",
        merchant_id=merchant_id,
        action="merchant.api_access_reinstated",
        resource_type="merchant",
        resource_id=merchant_id,
    )
    return get_admin_merchant(merchant_id, admin)


@router.get("/merchants/{merchant_id}/api-keys", response_model=APIResponse[list[ApiKeyResponse]])
def list_admin_merchant_api_keys(
    merchant_id: uuid.UUID,
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    if not get_by_id(client, "merchants", merchant_id):
        raise NotFoundError("Merchant not found")
    rows = (
        client.table("api_keys")
        .select("*")
        .eq("merchant_id", str(merchant_id))
        .order("created_at", desc=True)
        .execute()
    ).data or []
    return APIResponse(data=[ApiKeyResponse(**row) for row in rows])


@router.get("/merchants/{merchant_id}/pay-by-link", response_model=APIResponse[PayByLinkResponse | None])
def get_admin_merchant_pay_by_link(
    merchant_id: uuid.UUID,
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Super Admin visibility into a merchant's permanent Pay by Link
    page — slug and active/disabled status (feature brief Part 10). See
    GET /pay-by-link below for the platform-wide equivalent of this same
    row. Payments created through it already show up in the regular
    collections/transactions endpoints with source="PAY_BY_LINK"
    (app/services/collection_source.py); slug create/update/enable/
    disable events already show up in the regular audit-log endpoint
    below (action starting "pay_by_link.") — nothing extra needed for
    either. Null (not 404) when the merchant hasn't created one."""
    client = get_supabase_admin()
    if not get_by_id(client, "merchants", merchant_id):
        raise NotFoundError("Merchant not found")
    row = get_own_pay_link(client, merchant_id=merchant_id)
    return APIResponse(data=PayByLinkResponse(**row, public_url=build_public_url(row["slug"])) if row else None)


@router.get("/pay-by-link", response_model=APIResponse[list[AdminPayByLinkResponse]])
def list_admin_pay_by_links(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    merchant_id: Annotated[uuid.UUID | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
):
    """Platform-wide view of every merchant's permanent Pay by Link page —
    separate from GET /payment-links above (which lists the payments
    created through them, alongside every other payment link, tagged
    created_via="pay_by_link"). This is the pages themselves: how many
    exist, how many are active, which merchant owns which slug."""
    client = get_supabase_admin()
    query = client.table("merchant_pay_links").select("*", count="exact")
    if merchant_id is not None:
        query = query.eq("merchant_id", str(merchant_id))
    if is_active is not None:
        query = query.eq("is_active", is_active)
    result = query.order("created_at", desc=True).range(pagination.start, pagination.end).execute()
    rows = result.data or []
    merchant_names = batch_merchant_names(client, {r["merchant_id"] for r in rows})
    merchant_codes = batch_merchant_codes(client, {r["merchant_id"] for r in rows})

    data = [
        AdminPayByLinkResponse(
            pay_by_link_id=row["id"],
            merchant_id=row["merchant_id"],
            merchant_name=merchant_names.get(row["merchant_id"], ""),
            merchant_code=merchant_codes.get(row["merchant_id"]),
            slug=row["slug"],
            display_name=row["display_name"],
            is_active=row["is_active"],
            created_at=row["created_at"],
            last_used_at=row.get("last_used_at"),
        )
        for row in rows
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


@router.get("/api-keys", response_model=APIResponse[list[AdminApiKeyResponse]])
def list_admin_api_keys(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    merchant_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[str | None, Query(description="active | revoked")] = None,
    environment: Annotated[str | None, Query(description="sandbox | live")] = None,
):
    """Platform-wide view across every merchant's API keys — never the
    hashed_key column (ApiKeyResponse/AdminApiKeyResponse both omit it),
    same as the merchant-scoped GET .../api-keys above."""
    client = get_supabase_admin()
    query = client.table("api_keys").select("*", count="exact")
    if merchant_id is not None:
        query = query.eq("merchant_id", str(merchant_id))
    if status is not None:
        query = query.eq("status", status)
    if environment is not None:
        query = query.eq("environment", environment)
    result = query.order("created_at", desc=True).range(pagination.start, pagination.end).execute()
    rows = result.data or []
    merchant_names = batch_merchant_names(client, {r["merchant_id"] for r in rows})
    merchant_codes = batch_merchant_codes(client, {r["merchant_id"] for r in rows})

    data = [
        AdminApiKeyResponse(
            id=row["id"],
            merchant_id=row["merchant_id"],
            merchant_name=merchant_names.get(row["merchant_id"], ""),
            merchant_code=merchant_codes.get(row["merchant_id"]),
            name=row["name"],
            environment=row["environment"],
            key_prefix=row["key_prefix"],
            key_last4=row.get("key_last4"),
            scopes=row["scopes"],
            status=row["status"],
            ip_whitelist_enabled=bool(row.get("ip_whitelist_enabled")),
            last_used_at=row.get("last_used_at"),
            last_used_ip=row.get("last_used_ip"),
            revoked_at=row.get("revoked_at"),
            created_at=row["created_at"],
        )
        for row in rows
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


@router.patch("/api-keys/{api_key_id}/revoke", response_model=APIResponse[AdminApiKeyResponse])
def revoke_admin_api_key(
    api_key_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Super Admin equivalent of the merchant's own PATCH
    .../api-keys/{id}/revoke (merchant_portal.py) — not scoped to any one
    merchant, since a platform admin may need to revoke a key regardless
    of which merchant owns it (e.g. responding to a reported leak)."""
    client = get_supabase_admin()
    row = get_by_id(client, "api_keys", api_key_id)
    if not row:
        raise NotFoundError("API key not found")

    updated = update_row(client, "api_keys", api_key_id, {"status": "revoked", "revoked_at": utc_now_iso()})
    merchant_id = uuid.UUID(row["merchant_id"])

    write_audit_log(
        client,
        actor_id=admin.id,
        actor_type="user",
        merchant_id=merchant_id,
        action="api_key.revoked_by_admin",
        resource_type="api_key",
        resource_id=api_key_id,
    )

    result = updated or row
    merchant_names = batch_merchant_names(client, {result["merchant_id"]})
    merchant_codes = batch_merchant_codes(client, {result["merchant_id"]})
    return APIResponse(
        data=AdminApiKeyResponse(
            id=result["id"],
            merchant_id=result["merchant_id"],
            merchant_name=merchant_names.get(result["merchant_id"], ""),
            merchant_code=merchant_codes.get(result["merchant_id"]),
            name=result["name"],
            environment=result["environment"],
            key_prefix=result["key_prefix"],
            key_last4=result.get("key_last4"),
            scopes=result["scopes"],
            status=result["status"],
            ip_whitelist_enabled=bool(result.get("ip_whitelist_enabled")),
            last_used_at=result.get("last_used_at"),
            last_used_ip=result.get("last_used_ip"),
            revoked_at=result.get("revoked_at"),
            created_at=result["created_at"],
        )
    )


@router.get("/customers", response_model=APIResponse[list[AdminCustomerResponse]])
def list_admin_customers_route(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    merchant_id: Annotated[uuid.UUID | None, Query()] = None,
):
    client = get_supabase_admin()
    data, total = list_admin_customers(client, merchant_id=merchant_id, pagination=pagination)
    return APIResponse(
        data=[AdminCustomerResponse(**row) for row in data], meta=build_page_meta(pagination, total)
    )


@router.get("/merchants/{merchant_id}/webhook-config", response_model=APIResponse[WebhookConfigResponse])
def get_admin_merchant_webhook_config(
    merchant_id: uuid.UUID,
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Read-only Super Admin view of a merchant's webhook config — same
    shape as the merchant's own GET /v1/merchant/webhook-config, still
    never exposing the actual signing secret (has_secret is a bool)."""
    client = get_supabase_admin()
    merchant = get_by_id(client, "merchants", merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")
    return APIResponse(
        data=WebhookConfigResponse(
            webhook_url=merchant.get("webhook_url"),
            subscribed_events=merchant.get("webhook_subscribed_events"),
            has_secret=bool(merchant.get("webhook_secret_encrypted")),
            last_delivery=last_webhook_delivery(client, merchant_id),
        )
    )


@router.get(
    "/merchants/{merchant_id}/notification-settings",
    response_model=APIResponse[AdminMerchantNotificationSettingsResponse],
)
def get_admin_merchant_notification_settings(
    merchant_id: uuid.UUID,
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Super Admin's Notification Details view for one merchant — settings
    plus the delivery summary (feature brief Part 7). Never exposes
    RESEND_API_KEY or any other provider secret; email_deliveries itself
    never stores one."""
    client = get_supabase_admin()
    merchant = get_by_id(client, "merchants", merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")

    row = get_or_create_notification_settings(client, merchant_id)
    summary = notification_delivery_summary(client, merchant_id)
    return APIResponse(
        data=AdminMerchantNotificationSettingsResponse(
            **row,
            merchant_name=merchant.get("business_name", ""),
            merchant_code=merchant.get("merchant_code"),
            **summary,
        )
    )


@router.patch(
    "/merchants/{merchant_id}/notification-settings",
    response_model=APIResponse[AdminMerchantNotificationSettingsResponse],
)
def update_admin_merchant_notification_settings(
    merchant_id: uuid.UUID,
    payload: MerchantNotificationSettingsUpdate,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Super Admin editing a merchant's notification settings — same
    validation (format, max 2, no duplicates, at least 1 required while
    enabled) as the merchant's own PUT, via the same shared validator.
    Always audit-logged with the admin's own user id as actor, distinct
    from the merchant-actor audit entry the merchant's own PATCH writes."""
    client = get_supabase_admin()
    merchant = get_by_id(client, "merchants", merchant_id)
    if not merchant:
        raise NotFoundError("Merchant not found")

    emails = validate_notification_emails(
        [payload.primary_notification_email, payload.secondary_notification_email],
        enabled=payload.collection_notifications_enabled,
    )
    row = upsert_notification_settings(
        client,
        merchant_id,
        primary_notification_email=emails[0] if len(emails) > 0 else None,
        secondary_notification_email=emails[1] if len(emails) > 1 else None,
        collection_notifications_enabled=payload.collection_notifications_enabled,
        updated_by=admin.id,
    )
    write_audit_log(
        client,
        actor_id=admin.id,
        actor_type="user",
        merchant_id=merchant_id,
        action="notification_settings.updated_by_admin",
        resource_type="merchant_notification_settings",
        resource_id=uuid.UUID(row["id"]),
        metadata={
            "collection_notifications_enabled": payload.collection_notifications_enabled,
            "notification_email_count": len(emails),
        },
    )
    summary = notification_delivery_summary(client, merchant_id)
    return APIResponse(
        data=AdminMerchantNotificationSettingsResponse(
            **row,
            merchant_name=merchant.get("business_name", ""),
            merchant_code=merchant.get("merchant_code"),
            **summary,
        )
    )


@router.get("/merchant-users", response_model=APIResponse[list[AdminMerchantUserResponse]])
def list_admin_merchant_users(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    client = get_supabase_admin()
    result = (
        client.table("merchant_users")
        .select("*", count="exact")
        .order("created_at", desc=True)
        .range(pagination.start, pagination.end)
        .execute()
    )
    rows = result.data or []
    merchant_names = batch_merchant_names(client, {r["merchant_id"] for r in rows})
    merchant_codes = batch_merchant_codes(client, {r["merchant_id"] for r in rows})
    profiles = batch_user_profiles(client, {r["user_id"] for r in rows})

    data = [
        AdminMerchantUserResponse(
            user_id=row["user_id"],
            merchant_id=row["merchant_id"],
            merchant_name=merchant_names.get(row["merchant_id"], ""),
            merchant_code=merchant_codes.get(row["merchant_id"]),
            full_name=profiles.get(row["user_id"], {}).get("full_name"),
            email=profiles.get(row["user_id"], {}).get("email"),
            role=row["role"],
            status=row["status"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


@router.get("/payment-links", response_model=APIResponse[list[AdminPaymentLinkResponse]])
def list_admin_payment_links(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    merchant_id: Annotated[uuid.UUID | None, Query()] = None,
):
    client = get_supabase_admin()
    query = client.table("payment_links").select("*", count="exact")
    if merchant_id is not None:
        query = query.eq("merchant_id", str(merchant_id))
    result = query.order("created_at", desc=True).range(pagination.start, pagination.end).execute()
    rows = result.data or []
    merchant_names = batch_merchant_names(client, {r["merchant_id"] for r in rows})
    merchant_codes = batch_merchant_codes(client, {r["merchant_id"] for r in rows})

    data = [
        AdminPaymentLinkResponse(
            link_id=row["id"],
            merchant_id=row["merchant_id"],
            merchant_name=merchant_names.get(row["merchant_id"], ""),
            merchant_code=merchant_codes.get(row["merchant_id"]),
            customer_name=row.get("customer_name"),
            customer_phone=row.get("customer_phone"),
            amount=row["amount"],
            currency=row["currency"],
            status=row["status"],
            expires_at=row.get("expires_at"),
            created_at=row["created_at"],
            created_via=row.get("created_via", "payment_link"),
        )
        for row in rows
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


@router.get("/invoices", response_model=APIResponse[list[AdminInvoiceResponse]])
def list_admin_invoices(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    merchant_id: Annotated[uuid.UUID | None, Query()] = None,
):
    client = get_supabase_admin()
    query = client.table("invoices").select("*", count="exact")
    if merchant_id is not None:
        query = query.eq("merchant_id", str(merchant_id))
    result = query.order("created_at", desc=True).range(pagination.start, pagination.end).execute()
    rows = result.data or []
    merchant_names = batch_merchant_names(client, {r["merchant_id"] for r in rows})
    merchant_codes = batch_merchant_codes(client, {r["merchant_id"] for r in rows})
    email_deliveries = batch_latest_email_deliveries(
        client, related_resource_type="invoice", related_resource_ids={r["id"] for r in rows}
    )

    data = [
        AdminInvoiceResponse(
            invoice_id=row["id"],
            invoice_number=row["invoice_number"],
            merchant_id=row["merchant_id"],
            merchant_name=merchant_names.get(row["merchant_id"], ""),
            merchant_code=merchant_codes.get(row["merchant_id"]),
            customer_name=row.get("customer_name"),
            customer_phone=row.get("customer_phone"),
            customer_email=row.get("customer_email"),
            total_amount=row["total_amount"],
            status=row["status"],
            due_date=row["due_date"],
            created_at=row["created_at"],
            sent_at=row.get("sent_at"),
            email_status=email_deliveries.get(row["id"], {}).get("status"),
            email_provider_message_id=email_deliveries.get(row["id"], {}).get("provider_message_id"),
            email_failed_reason=email_deliveries.get(row["id"], {}).get("error_message"),
        )
        for row in rows
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


@router.get("/collections", response_model=APIResponse[list[AdminCollectionResponse]])
def list_admin_collections(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    merchant_id: Annotated[uuid.UUID | None, Query()] = None,
    source: Annotated[str | None, Query()] = None,
    method: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    date_from: Annotated[str | None, Query(description="ISO timestamp, inclusive")] = None,
    date_to: Annotated[str | None, Query(description="ISO timestamp, inclusive")] = None,
    customer_phone: Annotated[str | None, Query()] = None,
    merchant_reference: Annotated[str | None, Query()] = None,
    api_key_id: Annotated[uuid.UUID | None, Query()] = None,
    payment_link_id: Annotated[uuid.UUID | None, Query()] = None,
    invoice_id: Annotated[uuid.UUID | None, Query()] = None,
):
    client = get_supabase_admin()
    query = client.table("collections").select("*", count="exact")
    if merchant_id is not None:
        query = query.eq("merchant_id", str(merchant_id))
    if source is not None:
        query = query.eq("source", source)
    if method is not None:
        query = query.eq("method", method)
    if status is not None:
        query = query.eq("status", status)
    if date_from is not None:
        query = query.gte("created_at", date_from)
    if date_to is not None:
        query = query.lte("created_at", date_to)
    if customer_phone is not None:
        query = query.eq("customer_phone", customer_phone)
    if merchant_reference is not None:
        query = query.eq("merchant_reference", merchant_reference)
    if api_key_id is not None:
        query = query.eq("api_key_id", str(api_key_id))
    if payment_link_id is not None:
        query = query.eq("payment_link_id", str(payment_link_id))
    if invoice_id is not None:
        query = query.eq("invoice_id", str(invoice_id))

    result = query.order("created_at", desc=True).range(pagination.start, pagination.end).execute()
    rows = result.data or []
    merchant_names = batch_merchant_names(client, {r["merchant_id"] for r in rows})
    merchant_codes = batch_merchant_codes(client, {r["merchant_id"] for r in rows})

    # Selcom Checkout wallet-push collections carry their own order_id on
    # the *linked* checkout_orders row, not on collections itself —
    # batched in one query rather than N+1 per row.
    checkout_order_ids = {r["checkout_order_id"] for r in rows if r.get("checkout_order_id")}
    order_ids_by_checkout_order_id: dict[str, str] = {}
    if checkout_order_ids:
        orders_result = (
            client.table("checkout_orders").select("id,order_id").in_("id", list(checkout_order_ids)).execute()
        )
        order_ids_by_checkout_order_id = {o["id"]: o["order_id"] for o in orders_result.data or []}

    # Fee/net amounts live on the linked transactions row (written only
    # once a collection actually clears — see create_processing_transaction
    # in app/services/collections.py), not on collections itself.
    collection_ids = [r["id"] for r in rows]
    fee_net_by_collection_id: dict[str, tuple[Decimal, Decimal]] = {}
    if collection_ids:
        txn_result = (
            client.table("transactions")
            .select("collection_id,fee_amount,net_amount")
            .in_("collection_id", collection_ids)
            .execute()
        )
        for txn in txn_result.data or []:
            if txn.get("collection_id"):
                fee_net_by_collection_id[txn["collection_id"]] = (txn["fee_amount"], txn["net_amount"])

    data = [
        AdminCollectionResponse(
            collection_id=row["id"],
            merchant_id=row["merchant_id"],
            merchant_name=merchant_names.get(row["merchant_id"], ""),
            merchant_code=merchant_codes.get(row["merchant_id"]),
            source=row.get("source"),
            method=row["method"],
            amount=row["amount"],
            currency=row["currency"],
            fee_amount=fee_net_by_collection_id.get(row["id"], (None, None))[0],
            net_amount=fee_net_by_collection_id.get(row["id"], (None, None))[1],
            phone=row.get("customer_phone"),
            merchant_reference=row.get("merchant_reference"),
            provider_reference=row.get("provider_reference"),
            api_key_id=row.get("api_key_id"),
            payment_link_id=row.get("payment_link_id"),
            invoice_id=row.get("invoice_id"),
            status=row["status"],
            created_at=row["created_at"],
            order_id=order_ids_by_checkout_order_id.get(row.get("checkout_order_id")),
            provider_transid=row.get("provider_transid"),
            channel=row.get("channel"),
            provider_payment_status=row.get("provider_payment_status"),
            failure_reason=row.get("failure_reason"),
        )
        for row in rows
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


@router.post("/collections/{collection_id}/refresh-status", response_model=APIResponse[AdminCollectionResponse])
async def refresh_admin_collection_status(
    collection_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    """Super Admin equivalent of
    POST /v1/merchant/collections/{id}/refresh-status — not scoped to any
    one merchant, since this router reads across all of them (see module
    docstring)."""
    client = get_supabase_admin()
    collection = get_by_id(client, "collections", collection_id)
    if not collection:
        raise NotFoundError("Collection not found")

    resolved = await refresh_checkout_collection_status(client, collection_id=collection_id)

    write_audit_log(
        client,
        actor_id=admin.id,
        merchant_id=uuid.UUID(resolved["merchant_id"]),
        action="collection.status_refreshed",
        resource_type="collection",
        resource_id=collection_id,
        metadata={"status": resolved["status"]},
    )

    merchant_names = batch_merchant_names(client, {resolved["merchant_id"]})
    merchant_codes = batch_merchant_codes(client, {resolved["merchant_id"]})
    order_id = None
    if resolved.get("checkout_order_id"):
        order = get_by_id(client, "checkout_orders", uuid.UUID(resolved["checkout_order_id"]))
        order_id = order["order_id"] if order else None

    return APIResponse(
        data=AdminCollectionResponse(
            collection_id=resolved["id"],
            merchant_id=resolved["merchant_id"],
            merchant_name=merchant_names.get(resolved["merchant_id"], ""),
            merchant_code=merchant_codes.get(resolved["merchant_id"]),
            method=resolved["method"],
            amount=resolved["amount"],
            currency=resolved["currency"],
            phone=resolved.get("customer_phone"),
            provider_reference=resolved.get("provider_reference"),
            status=resolved["status"],
            created_at=resolved["created_at"],
            order_id=order_id,
            provider_transid=resolved.get("provider_transid"),
            channel=resolved.get("channel"),
            provider_payment_status=resolved.get("provider_payment_status"),
            failure_reason=resolved.get("failure_reason"),
        )
    )


@router.get("/withdrawals", response_model=APIResponse[list[AdminWithdrawalResponse]])
def list_admin_withdrawals(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    status: Annotated[str | None, Query(description="Filter by disbursement status, e.g. PENDING_ADMIN_APPROVAL")] = None,
    requires_approval: Annotated[bool | None, Query()] = None,
    merchant_id: Annotated[uuid.UUID | None, Query()] = None,
):
    client = get_supabase_admin()
    query = client.table("disbursements").select("*", count="exact")
    if status is not None:
        query = query.eq("status", status)
    if requires_approval is not None:
        query = query.eq("requires_approval", requires_approval)
    if merchant_id is not None:
        query = query.eq("merchant_id", str(merchant_id))
    result = query.order("created_at", desc=True).range(pagination.start, pagination.end).execute()
    rows = result.data or []
    merchant_names = batch_merchant_names(client, {r["merchant_id"] for r in rows})
    merchant_codes = batch_merchant_codes(client, {r["merchant_id"] for r in rows})
    wallet_balances = batch_wallet_balances(client, {r["merchant_id"] for r in rows})
    resource_ids = {r["id"] for r in rows}
    request_emails = batch_latest_email_deliveries(
        client,
        related_resource_type="disbursement",
        related_resource_ids=resource_ids,
        email_type="withdrawal_request_notification",
    )
    success_emails = batch_latest_email_deliveries(
        client, related_resource_type="disbursement", related_resource_ids=resource_ids, email_type="withdrawal_success"
    )

    data = [
        AdminWithdrawalResponse(
            withdrawal_id=row["id"],
            merchant_id=row["merchant_id"],
            merchant_name=merchant_names.get(row["merchant_id"], ""),
            merchant_code=merchant_codes.get(row["merchant_id"]),
            method=row["method"],
            amount=row["amount"],
            currency=row["currency"],
            destination=row["destination_name"],
            destination_code=row.get("destination_code"),
            destination_identifier=row["destination_identifier"],
            status=row["status"],
            requires_approval=row["requires_approval"],
            auto_approved=row.get("auto_approved") or False,
            auto_decision_reason=row.get("auto_decision_reason"),
            provider_reference=row.get("provider_reference"),
            total_charges=row.get("total_charges") or Decimal(0),
            total_reserved_amount=row.get("total_reserved_amount"),
            recipient_net_amount=row.get("recipient_net_amount"),
            available_balance=wallet_balances.get(row["merchant_id"], "0"),
            pricing_rule_id=row.get("pricing_rule_id"),
            rejection_reason=row.get("rejection_reason"),
            admin_status_reason=row.get("admin_status_reason"),
            created_at=row["created_at"],
            request_email_status=request_emails.get(row["id"], {}).get("status"),
            success_email_status=success_emails.get(row["id"], {}).get("status"),
        )
        for row in rows
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


@router.get("/transactions", response_model=APIResponse[list[AdminTransactionResponse]])
def list_admin_transactions(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    merchant_id: Annotated[uuid.UUID | None, Query()] = None,
    merchant_code: Annotated[str | None, Query(description="8-digit Merchant ID, e.g. 27048391")] = None,
    type: Annotated[str | None, Query(description="collection | disbursement | fee | refund | reversal | adjustment")] = None,
    status: Annotated[str | None, Query()] = None,
    provider_reference: Annotated[str | None, Query()] = None,
    transaction_id: Annotated[uuid.UUID | None, Query(description="Exact transactions.id")] = None,
    date_from: Annotated[str | None, Query(description="ISO timestamp, inclusive")] = None,
    date_to: Annotated[str | None, Query(description="ISO timestamp, inclusive")] = None,
):
    client = get_supabase_admin()
    query = client.table("transactions").select("*", count="exact")
    if merchant_id is not None:
        query = query.eq("merchant_id", str(merchant_id))
    if merchant_code is not None:
        merchant_row = execute_maybe_single(
            client.table("merchants").select("id").eq("merchant_code", merchant_code).maybe_single()
        )
        # An unknown code must return zero rows, not "no filter at all" —
        # filter on an id nothing can match rather than skipping the filter.
        query = query.eq("merchant_id", merchant_row["id"] if merchant_row else "00000000-0000-0000-0000-000000000000")
    if type is not None:
        query = query.eq("type", type)
    if status is not None:
        query = query.eq("status", status)
    if provider_reference is not None:
        query = query.eq("provider_reference", provider_reference)
    if transaction_id is not None:
        query = query.eq("id", str(transaction_id))
    if date_from is not None:
        query = query.gte("created_at", date_from)
    if date_to is not None:
        query = query.lte("created_at", date_to)
    result = query.order("created_at", desc=True).range(pagination.start, pagination.end).execute()
    rows = result.data or []
    merchant_names = batch_merchant_names(client, {r["merchant_id"] for r in rows})
    merchant_codes = batch_merchant_codes(client, {r["merchant_id"] for r in rows})

    data = [
        AdminTransactionResponse(
            transaction_id=row["id"],
            merchant_id=row["merchant_id"],
            merchant_name=merchant_names.get(row["merchant_id"], ""),
            merchant_code=merchant_codes.get(row["merchant_id"]),
            reference=row["reference"],
            provider_reference=row.get("provider_reference"),
            type=row["type"],
            method=row["method"],
            gross_amount=row["gross_amount"],
            fee_amount=row["fee_amount"],
            net_amount=row["net_amount"],
            currency=row["currency"],
            status=row["status"],
            balance_before=row.get("balance_before"),
            balance_after=row.get("balance_after"),
            direction=row.get("direction"),
            created_at=row["created_at"],
        )
        for row in rows
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


@router.get("/webhooks", response_model=APIResponse[list[AdminWebhookEventResponse]])
def list_admin_webhooks(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    """Inbound provider callback log (selcom_webhook_events) — NOT the
    outbound merchant webhook deliveries table, which already has its own
    per-merchant view at GET /v1/merchants/{merchant_id}/webhooks."""
    client = get_supabase_admin()
    result = (
        client.table("selcom_webhook_events")
        .select("*", count="exact")
        .order("created_at", desc=True)
        .range(pagination.start, pagination.end)
        .execute()
    )
    data = [
        AdminWebhookEventResponse(
            webhook_event_id=row["id"],
            provider=row["provider"],
            event_type=row["event_type"],
            reference=row["event_id"],
            processed_at=row.get("processed_at"),
            created_at=row["created_at"],
            status=row["status"],
            processing_error=row.get("processing_error"),
        )
        for row in (result.data or [])
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


# --- IP allowlist -------------------------------------------------------------


@router.get("/ip-allowlist", response_model=APIResponse[list[AdminIpAllowlistResponse]])
def list_admin_ip_allowlist(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    merchant_id: Annotated[uuid.UUID | None, Query()] = None,
    environment: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="pending | active | rejected")] = None,
):
    client = get_supabase_admin()
    query = client.table("api_ip_allowlist").select("*", count="exact")
    if merchant_id is not None:
        query = query.eq("merchant_id", str(merchant_id))
    if environment is not None:
        query = query.eq("environment", environment)
    if status is not None:
        query = query.eq("status", status)
    result = query.order("created_at", desc=True).range(pagination.start, pagination.end).execute()
    rows = result.data or []
    merchant_names = batch_merchant_names(client, {r["merchant_id"] for r in rows})
    merchant_codes = batch_merchant_codes(client, {r["merchant_id"] for r in rows})
    key_prefixes = batch_api_key_prefixes(client, {r["api_key_id"] for r in rows if r.get("api_key_id")})

    data = [
        AdminIpAllowlistResponse(
            **row,
            merchant_name=merchant_names.get(row["merchant_id"], ""),
            merchant_code=merchant_codes.get(row["merchant_id"]),
            key_prefix=key_prefixes.get(row["api_key_id"]) if row.get("api_key_id") else None,
        )
        for row in rows
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


def _review_ip_allowlist_entry(
    entry_id: uuid.UUID, admin: AuthenticatedUser, new_status: str, action: str
) -> AdminIpAllowlistResponse:
    client = get_supabase_admin()
    row = get_by_id(client, "api_ip_allowlist", entry_id)
    if not row:
        raise NotFoundError("IP allowlist entry not found")

    updated = update_row(client, "api_ip_allowlist", entry_id, {"status": new_status, "approved_by": str(admin.id)})
    merchant_id = uuid.UUID(row["merchant_id"])
    write_audit_log(
        client,
        actor_id=admin.id,
        actor_type="user",
        merchant_id=merchant_id,
        action=action,
        resource_type="api_ip_allowlist",
        resource_id=entry_id,
    )
    result = updated or row
    merchant_names = batch_merchant_names(client, {result["merchant_id"]})
    merchant_codes = batch_merchant_codes(client, {result["merchant_id"]})
    key_prefix = None
    if result.get("api_key_id"):
        key_prefix = batch_api_key_prefixes(client, {result["api_key_id"]}).get(result["api_key_id"])
    return AdminIpAllowlistResponse(
        **result,
        merchant_name=merchant_names.get(result["merchant_id"], ""),
        merchant_code=merchant_codes.get(result["merchant_id"]),
        key_prefix=key_prefix,
    )


@router.post("/ip-allowlist/{entry_id}/approve", response_model=APIResponse[AdminIpAllowlistResponse])
def approve_ip_allowlist_entry(
    entry_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    return APIResponse(data=_review_ip_allowlist_entry(entry_id, admin, "active", "ip_allowlist.approved"))


@router.post("/ip-allowlist/{entry_id}/reject", response_model=APIResponse[AdminIpAllowlistResponse])
def reject_ip_allowlist_entry(
    entry_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    return APIResponse(data=_review_ip_allowlist_entry(entry_id, admin, "rejected", "ip_allowlist.rejected"))


# --- API logs -------------------------------------------------------------


@router.get("/api-logs", response_model=APIResponse[list[AdminApiRequestLogResponse]])
def list_admin_api_logs(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    merchant_id: Annotated[uuid.UUID | None, Query()] = None,
    environment: Annotated[str | None, Query()] = None,
):
    client = get_supabase_admin()
    query = client.table("api_request_logs").select("*", count="exact")
    if merchant_id is not None:
        query = query.eq("merchant_id", str(merchant_id))
    if environment is not None:
        query = query.eq("environment", environment)
    result = query.order("created_at", desc=True).range(pagination.start, pagination.end).execute()
    rows = result.data or []
    merchant_names = batch_merchant_names(client, {r["merchant_id"] for r in rows})
    merchant_codes = batch_merchant_codes(client, {r["merchant_id"] for r in rows})

    data = [
        AdminApiRequestLogResponse(
            **row,
            merchant_name=merchant_names.get(row["merchant_id"], ""),
            merchant_code=merchant_codes.get(row["merchant_id"]),
        )
        for row in rows
    ]
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


@router.get("/audit-logs", response_model=APIResponse[list[AdminAuditLogResponse]])
def list_admin_audit_logs(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    client = get_supabase_admin()
    result = (
        client.table("audit_logs")
        .select("*", count="exact")
        .order("created_at", desc=True)
        .range(pagination.start, pagination.end)
        .execute()
    )
    rows = result.data or []
    actor_ids = {r["actor_id"] for r in rows if r.get("actor_id")}
    profiles = batch_user_profiles(client, actor_ids)

    data = []
    for row in rows:
        profile = profiles.get(row.get("actor_id"), {})
        actor = profile.get("full_name") or profile.get("email")
        data.append(
            AdminAuditLogResponse(
                audit_id=row["id"],
                actor=actor,
                action=row["action"],
                entity_type=row["resource_type"],
                entity_id=row.get("resource_id"),
                metadata=row.get("metadata") or {},
                ip_address=row.get("ip_address"),
                created_at=row["created_at"],
            )
        )
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))


@router.get("/inquiries", response_model=APIResponse[list[AdminInquiryResponse]])
def list_admin_inquiries(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    """Read-only view of POST /v1/public/inquiries submissions (the
    marketing site's Contact form) — the CEO also gets each one by email
    as it arrives (send_inquiry_notification_email); this is just so
    they're browsable/searchable afterward too, not a replacement for
    that notification."""
    client = get_supabase_admin()
    result = (
        client.table("inquiries")
        .select("*", count="exact")
        .order("created_at", desc=True)
        .range(pagination.start, pagination.end)
        .execute()
    )
    data = [AdminInquiryResponse(**row) for row in (result.data or [])]
    return APIResponse(data=data, meta=build_page_meta(pagination, result.count or 0))
