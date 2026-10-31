"""Super Admin read/write for the withdrawal automation policy.

Own file, matching the one-file-per-admin-workflow convention already used
by admin_onboarding.py / admin_disputes.py / admin_risk.py /
admin_withdrawals.py. Its own prefix rather than hanging off
``/admin/withdrawals`` so that a policy route can never be confused with a
route that acts on one withdrawal.

What guards these two routes:

* ``require_super_admin`` on both, which is this codebase's sensitive-action
  convention: it refuses a non-admin AND enforces the second factor
  (``aal2``) for every ``/v1/admin`` call, reads included, raising
  MfaRequiredError otherwise. There is no separate step-up dependency to
  add — see app/auth/dependencies.py::require_super_admin. A merchant
  session and an API key cannot reach either route: API keys are only
  accepted by the handful of flat merchant endpoints that opt into
  ``get_authenticated_caller``, and this router does not.
* Bearer-token auth, so there is no cookie and no CSRF surface to preserve
  here. apps/web calls these from a Server Action holding the admin's own
  Supabase session.
* The actor is taken from the verified token. The request body cannot name
  an administrator, and ``extra="forbid"`` means trying to is a 422.
* Every value is validated server-side in
  app/services/withdrawal_policy.py, which is also what the payout path
  reads. The portal's own checks are a convenience, never the enforcement.

Reading is rate-limited gently and writing tightly: the page polls the
first on load, while the second moves a control over real money.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth import require_super_admin
from app.config import get_settings
from app.core.errors import ValidationAPIError
from app.core.rate_limit import rate_limit
from app.core.request_ip import client_ip
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse
from app.schemas.withdrawal_policy import (
    WithdrawalAutomationPolicyResponse,
    WithdrawalAutomationPolicyUpdate,
)
from app.services.admin_directory import best_effort_user_profile
from app.services.audit import write_audit_log
from app.services.security_alerts import notify_security_event
from app.services.withdrawal_policy import (
    EffectiveWithdrawalPolicy,
    requires_confirmation,
    resolve_effective_policy,
    update_policy,
)

logger = logging.getLogger("infinity.admin.withdrawal_policy")

router = APIRouter(prefix="/admin/withdrawal-automation", tags=["admin-withdrawal-automation"])


def _response(client, policy: EffectiveWithdrawalPolicy) -> WithdrawalAutomationPolicyResponse:
    settings = get_settings()
    return WithdrawalAutomationPolicyResponse(
        automation_active=policy.automation_active,
        effective_max_amount_tzs=policy.max_amount_tzs,
        effective_rolling_24h_limit_tzs=policy.merchant_rolling_24h_limit_tzs,
        enabled=policy.policy_enabled,
        max_amount_tzs=policy.policy_max_amount_tzs,
        merchant_rolling_24h_limit_tzs=policy.policy_rolling_24h_limit_tzs,
        version=policy.policy_version,
        updated_at=policy.updated_at,
        updated_by=policy.updated_by,
        # Never fails the read: a deleted administrator or an Auth hiccup
        # degrades to no name, not to a page that cannot render the switch.
        updated_by_email=best_effort_user_profile(client, policy.updated_by).get("email"),
        blocked_reason_code=policy.blocked_reason_code,
        blocked_explanation=policy.blocked_explanation,
        manual_only_override=policy.manual_only_override,
        deployment_automation_allowed=policy.deployment_automation_allowed,
        hard_max_amount_tzs=policy.hard_max_amount_tzs,
        hard_rolling_24h_limit_tzs=policy.hard_rolling_24h_limit_tzs,
        policy_unavailable=policy.policy_unavailable,
        platform_min_withdrawal_amount_tzs=settings.min_withdrawal_amount_tzs,
        platform_max_withdrawal_amount_tzs=settings.max_withdrawal_amount_tzs,
        platform_rolling_24h_limit_tzs=settings.daily_withdrawal_limit_tzs,
    )


@router.get("/policy", response_model=APIResponse[WithdrawalAutomationPolicyResponse])
def read_withdrawal_automation_policy(
    _admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    _rate_limit: Annotated[None, Depends(rate_limit(scope="admin_withdrawal_policy_read", limit=60, window_seconds=60))],
):
    """The effective policy, read fresh.

    Not cached, and deliberately not served from the dashboard cache: this
    is the screen an operator looks at to confirm they have turned
    automation off, and a cached ON or a cached OFF are both lies that
    cost money. See app/services/withdrawal_policy.py's module docstring.
    """
    client = get_supabase_admin()
    return APIResponse(data=_response(client, resolve_effective_policy(client)))


@router.put("/policy", response_model=APIResponse[WithdrawalAutomationPolicyResponse])
def update_withdrawal_automation_policy(
    payload: WithdrawalAutomationPolicyUpdate,
    request: Request,
    admin: Annotated[AuthenticatedUser, Depends(require_super_admin)],
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="admin_withdrawal_policy_write", limit=10, window_seconds=300))
    ],
):
    """Change the switch or the limits.

    Order matters and is not incidental:

    1. Read the current effective policy, because both the staleness check
       and the confirmation rule are relative to it.
    2. Refuse a widening change that did not say it meant to.
    3. Validate and write under the version filter, which is what makes
       two administrators safe.
    4. Audit, then alert.

    The audit row is written with the raising ``write_audit_log``, not the
    best-effort variant: this is a change to a control over money leaving
    the platform, and a change nobody can prove happened is worse than a
    change that failed. The alert afterwards is best-effort — an email
    provider must not be able to undo a committed policy change.

    **What this does NOT do.** Turning automation ON never touches a
    withdrawal that is already waiting for manual approval: those rows
    have had their decision taken and recorded, and nothing here re-runs
    it, so a queue of pending requests is not drained by flipping the
    switch. Turning it OFF never cancels, reverses or refunds a payout
    already submitted to Selcom — those continue through the existing
    reconciliation path and the response says so. OFF applies to payout
    authorizations taken after it commits.
    """
    client = get_supabase_admin()
    correlation_id = str(uuid.uuid4())
    before = resolve_effective_policy(client)

    if before.policy_unavailable or before.policy_version is None:
        # Editing a policy we could not read would mean writing a version
        # we are guessing at. The page reloads and shows the real state.
        raise ValidationAPIError(
            "The current automation policy could not be read, so it cannot be changed safely. "
            "Withdrawals are going to manual approval in the meantime. Reload and try again."
        )

    if requires_confirmation(
        before,
        enabled=payload.enabled,
        max_amount=payload.max_amount_tzs,
        rolling=payload.merchant_rolling_24h_limit_tzs,
    ) and not payload.confirm:
        raise ValidationAPIError(
            "This change would allow more money to be paid out without a Super Admin approving it. "
            "Confirm the effective limits to continue: automatic processing "
            f"{'ON' if payload.enabled else 'OFF'}, up to {payload.max_amount_tzs} TZS per withdrawal "
            f"(inclusive), {payload.merchant_rolling_24h_limit_tzs} TZS per merchant per rolling 24 hours."
        )

    # Raises ConflictError (409) on a stale version and ValidationAPIError
    # on a value that must not be stored.
    update_policy(
        client,
        enabled=payload.enabled,
        max_amount_tzs=payload.max_amount_tzs,
        merchant_rolling_24h_limit_tzs=payload.merchant_rolling_24h_limit_tzs,
        expected_version=payload.version,
        actor_id=uuid.UUID(str(admin.id)),
    )

    after = resolve_effective_policy(client)

    # Amounts as strings: this metadata is read back during an incident and
    # a float would be the wrong record of a money limit. No token, no OTP,
    # no credential, no provider payload — only what changed.
    write_audit_log(
        client,
        action="withdrawal_automation_policy.updated",
        resource_type="withdrawal_automation_policy",
        actor_id=uuid.UUID(str(admin.id)),
        actor_type="user",
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        metadata={
            "correlation_id": correlation_id,
            "previous": {
                "version": before.policy_version,
                "enabled": before.policy_enabled,
                "max_amount_tzs": str(before.policy_max_amount_tzs),
                "merchant_rolling_24h_limit_tzs": str(before.policy_rolling_24h_limit_tzs),
                "automation_active": before.automation_active,
            },
            "new": {
                "version": after.policy_version,
                "enabled": after.policy_enabled,
                "max_amount_tzs": str(after.policy_max_amount_tzs),
                "merchant_rolling_24h_limit_tzs": str(after.policy_rolling_24h_limit_tzs),
                "automation_active": after.automation_active,
            },
            # What the deployment ceilings made of it. A policy raised to a
            # number the deployment caps is a real source of confusion
            # later, so the record says what actually took effect.
            "effective": {
                "max_amount_tzs": str(after.max_amount_tzs),
                "rolling_24h_limit_tzs": str(after.merchant_rolling_24h_limit_tzs),
            },
            "confirmed": payload.confirm,
        },
    )

    logger.info(
        "withdrawal_automation_policy_updated correlation_id=%s enabled=%s active=%s version=%s->%s",
        correlation_id,
        after.policy_enabled,
        after.automation_active,
        before.policy_version,
        after.policy_version,
    )

    # Never deduplicated, same reasoning as _alert_withdrawal in
    # admin_withdrawals.py: each change to who may move money unattended is
    # its own decision and deserves its own notice. Best-effort.
    try:
        notify_security_event(
            client,
            event="withdrawal_automation_policy.updated",
            title=(
                "Withdrawal automation turned ON"
                if after.automation_active and not before.automation_active
                else "Withdrawal automation turned OFF"
                if before.automation_active and not after.automation_active
                else "Withdrawal automation limits changed"
            ),
            actor_email=admin.email,
            actor_id=admin.id,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
            extra={
                "Automatic processing": "ON" if after.automation_active else "OFF",
                "Per withdrawal (inclusive)": f"{after.max_amount_tzs} TZS",
                "Per merchant / rolling 24h": f"{after.merchant_rolling_24h_limit_tzs} TZS",
                "Policy version": str(after.policy_version),
                "Correlation ID": correlation_id,
            },
        )
    except Exception:  # noqa: BLE001 - the policy is already committed
        logger.warning("withdrawal_automation_policy_alert_failed correlation_id=%s", correlation_id)

    return APIResponse(data=_response(client, after))
