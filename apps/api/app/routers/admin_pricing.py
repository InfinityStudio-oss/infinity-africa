"""Super Admin withdrawal pricing-rule management —
/v1/admin/merchants/{merchant_id}/pricing-rules and
/v1/admin/pricing-rules/*. Own file, matching the established
one-file-per-review-workflow convention (admin_onboarding.py,
admin_disputes.py, admin_risk.py).

Every write here is service_role-only (merchant_pricing_rules has no
insert/update/delete RLS policy — see
supabase/migrations/20260820090000_merchant_pricing_rules.sql); this router
is the only way a rule is ever created, edited, or deactivated.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth import require_super_admin
from app.core.errors import NotFoundError
from app.core.time import utc_now_iso
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse
from app.schemas.withdrawals import (
    PricingRuleCreate,
    PricingRuleResponse,
    PricingRuleUpdate,
)
from app.services.audit import write_audit_log
from app.services.crud import get_by_id, insert_row, update_row
from app.services.security_alerts import notify_security_event

router = APIRouter(prefix="/admin", tags=["admin-pricing"])


def _list_rules(client, *, merchant_id: uuid.UUID | None) -> list[dict]:
    query = client.table("merchant_pricing_rules").select("*")
    query = query.eq("merchant_id", str(merchant_id)) if merchant_id else query.is_("merchant_id", "null")
    result = query.order("created_at", desc=True).execute()
    return result.data or []


@router.get("/pricing-rules", response_model=APIResponse[list[PricingRuleResponse]])
def list_platform_pricing_rules(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    merchant_id: Annotated[uuid.UUID | None, Query(description="Omit to list platform fallback rules")] = None,
):
    client = get_supabase_admin()
    rows = _list_rules(client, merchant_id=merchant_id)
    return APIResponse(data=[PricingRuleResponse(**row) for row in rows])


def _record_pricing_change(client, *, admin, row: dict, action: str, title: str, event: str) -> None:
    """Audit + alert for a pricing change.

    These endpoints had neither. Pricing decides what every merchant is
    charged on every transaction, so a change here moves real money over
    time -- it belongs in the audit trail at least as much as a single
    withdrawal does. Rule fields only; nothing here is sensitive."""
    merchant_id = row.get("merchant_id")
    merchant = get_by_id(client, "merchants", uuid.UUID(merchant_id)) if merchant_id else None
    scope = (merchant or {}).get("business_name") or ("Platform default" if not merchant_id else str(merchant_id))

    write_audit_log(
        client,
        actor_id=admin.id,
        merchant_id=uuid.UUID(merchant_id) if merchant_id else None,
        action=action,
        resource_type="merchant_pricing_rule",
        resource_id=uuid.UUID(row["id"]),
        metadata={
            "scope": scope,
            "method": row.get("method"),
            "percentage_fee": str(row.get("percentage_fee")),
            "flat_fee": str(row.get("flat_fee")),
            "is_active": row.get("is_active"),
        },
    )

    notify_security_event(
        client,
        event=event,
        title=title,
        actor_email=admin.email,
        actor_id=admin.id,
        merchant_name=scope,
        extra={
            "Method": row.get("method") or "—",
            "Percentage fee": str(row.get("percentage_fee")),
            "Flat fee": str(row.get("flat_fee")),
            "Active": str(row.get("is_active")),
        },
    )


@router.post("/pricing-rules/platform-fallback", response_model=APIResponse[PricingRuleResponse])
def create_platform_fallback_pricing_rule(
    payload: PricingRuleCreate,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    row = insert_row(
        client,
        "merchant_pricing_rules",
        {"merchant_id": None, "created_by": str(admin.id), **_create_rule_fields(payload)},
    )

    _record_pricing_change(
        client, admin=admin, row=row, action="pricing_rule.created",
        title="Platform pricing rule created", event="super_admin.pricing.created",
    )

    return APIResponse(data=PricingRuleResponse(**row))


@router.get("/merchants/{merchant_id}/pricing-rules", response_model=APIResponse[list[PricingRuleResponse]])
def list_merchant_pricing_rules(
    merchant_id: uuid.UUID,
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    if not get_by_id(client, "merchants", merchant_id):
        raise NotFoundError("Merchant not found")
    rows = _list_rules(client, merchant_id=merchant_id)
    return APIResponse(data=[PricingRuleResponse(**row) for row in rows])


@router.post("/merchants/{merchant_id}/pricing-rules", response_model=APIResponse[PricingRuleResponse])
def create_merchant_pricing_rule(
    merchant_id: uuid.UUID,
    payload: PricingRuleCreate,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    if not get_by_id(client, "merchants", merchant_id):
        raise NotFoundError("Merchant not found")

    row = insert_row(
        client,
        "merchant_pricing_rules",
        {"merchant_id": str(merchant_id), "created_by": str(admin.id), **_create_rule_fields(payload)},
    )

    _record_pricing_change(
        client, admin=admin, row=row, action="pricing_rule.created",
        title="Merchant pricing rule created", event="super_admin.pricing.created",
    )

    return APIResponse(data=PricingRuleResponse(**row))


@router.patch("/pricing-rules/{pricing_rule_id}", response_model=APIResponse[PricingRuleResponse])
def update_pricing_rule(
    pricing_rule_id: uuid.UUID,
    payload: PricingRuleUpdate,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    if not get_by_id(client, "merchant_pricing_rules", pricing_rule_id):
        raise NotFoundError("Pricing rule not found")

    fields = _rule_fields(payload, exclude_unset=True)
    if fields:
        row = update_row(client, "merchant_pricing_rules", pricing_rule_id, fields)
    else:
        row = get_by_id(client, "merchant_pricing_rules", pricing_rule_id)

    _record_pricing_change(
        client, admin=admin, row=row, action="pricing_rule.updated",
        title="Pricing rule updated", event="super_admin.pricing.updated",
    )

    return APIResponse(data=PricingRuleResponse(**row))


@router.post("/pricing-rules/{pricing_rule_id}/deactivate", response_model=APIResponse[PricingRuleResponse])
def deactivate_pricing_rule(
    pricing_rule_id: uuid.UUID,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
):
    client = get_supabase_admin()
    if not get_by_id(client, "merchant_pricing_rules", pricing_rule_id):
        raise NotFoundError("Pricing rule not found")

    row = update_row(client, "merchant_pricing_rules", pricing_rule_id, {"is_active": False})

    _record_pricing_change(
        client, admin=admin, row=row, action="pricing_rule.deactivated",
        title="Pricing rule deactivated", event="super_admin.pricing.deleted",
    )

    return APIResponse(data=PricingRuleResponse(**row))


def _rule_fields(payload: PricingRuleCreate | PricingRuleUpdate, *, exclude_unset: bool = False) -> dict:
    return payload.model_dump(mode="json", exclude_unset=exclude_unset)


def _create_rule_fields(payload: PricingRuleCreate) -> dict:
    """Like _rule_fields, but never sends an explicit null for
    effective_from — the column is NOT NULL DEFAULT now() in Postgres;
    omitting it (rather than nulling it out) lets that default apply,
    same as if the field had never been in the request at all."""
    fields = _rule_fields(payload)
    if fields.get("effective_from") is None:
        fields["effective_from"] = utc_now_iso()
    return fields
