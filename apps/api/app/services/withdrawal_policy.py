"""The one place that decides whether withdrawal automation is in force.

Four things could each answer "is automation on?" and they used to be read
in two different places: two environment flags, two environment amount
caps, and - as of
supabase/migrations/20261031010000_withdrawal_automation_policy.sql - a
database policy row the Super Admin portal owns. Spreading that across the
payout path and the portal is how a platform ends up with a switch that
says OFF while money is still moving, so every caller resolves it here and
nowhere else.

PRECEDENCE, in order. Each step can only ever be more conservative than
the one before it:

1. ``REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS`` (default **True**) is the
   emergency manual-only override. While it is set, automation cannot run
   whatever the policy row says, and the portal shows the switch as locked
   by the deployment rather than offering a control that would do nothing.
2. ``AUTO_WITHDRAWALS_ENABLED`` (default **False**) is the deployment's
   permission for automation to exist at all. Both flags must be set
   before the portal switch has any effect - the belt-and-suspenders pair
   that already existed, with its meaning unchanged, so that a single
   mis-set variable cannot enable real-money automation.
3. ``withdrawal_automation_policy.enabled`` is the routine ON/OFF a Super
   Admin operates within that permission. Default False.
4. ``AUTO_WITHDRAWAL_MAX_AMOUNT_TZS`` and
   ``AUTO_WITHDRAWAL_DAILY_LIMIT_TZS`` are HARD CEILINGS. The effective
   limit is ``min(policy, env)``, so a policy row can tighten a limit but
   never raise it past what the deployment allows.
5. Every other control applies to automatic and manual withdrawals alike
   and none of them are reachable from this module: merchant verification
   and active status, the withdrawal OTP, open high-risk fraud alerts,
   available balance, the per-request minimum and maximum, the hard
   rolling 24h limit, and destination validation.

**Unreadable means manual.** A missing row, a malformed amount, a dropped
connection - all of them resolve to automation off with the reason code
``AUTO_POLICY_UNAVAILABLE``. There is no failure of this module that can
let a payout past a human, which is the only direction the uncertainty is
allowed to fall.

**Never cached.** ``resolve_effective_policy`` reads the row on every call,
including the call on the payout path. The dashboard cache
(app/services/cache.py) deliberately has no entry for this: a stale ON is
money leaving after an operator believed they had stopped it. The cost is
one indexed single-row read per withdrawal request.
"""

import logging
import uuid
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from supabase import Client

from app.config import get_settings
from app.core.errors import ConflictError, ValidationAPIError

logger = logging.getLogger("infinity.withdrawal_policy")

TABLE = "withdrawal_automation_policy"

# Written onto disbursements.auto_decision_code. Merchant-safe by
# construction: a code says which limit or switch stopped automation, never
# anything about fraud scoring or another merchant.
CODE_ELIGIBLE = "AUTO_ELIGIBLE"
CODE_POLICY_DISABLED = "AUTO_POLICY_DISABLED"
CODE_AMOUNT_LIMIT = "AUTO_AMOUNT_LIMIT_EXCEEDED"
CODE_ROLLING_LIMIT = "AUTO_ROLLING_LIMIT_EXCEEDED"
CODE_POLICY_UNAVAILABLE = "AUTO_POLICY_UNAVAILABLE"
CODE_RISK_REVIEW = "AUTO_RISK_REVIEW_REQUIRED"

# The statuses that mean an automatically authorized payout actually
# reached Selcom.
#
# auto_approved alone does NOT mean that. The flag is written inside the
# advisory lock the instant eligibility is decided, which is before the
# provider is called - so a row can carry auto_approved=true while the
# payout is still in flight, or while it has already failed. Both
# operator notifications are gated on this, and they are gated on the
# same tuple rather than on two copies of it, because a message telling
# an operator money went out when it did not is the one failure this
# whole alert exists to prevent.
#
# It lives here rather than beside either caller because both need it and
# neither may import the other: app/services/disbursements.py already
# imports this module, and app/services/sms_messages.py cannot import
# disbursements without a cycle.
PAYOUT_REACHED_PROVIDER_STATUSES = ("PROCESSING", "SUCCESS", "NEEDS_RECONCILIATION")


@dataclass(frozen=True)
class DeploymentAutomationLimits:
    """What the deployment permits, with no database in the answer.

    This is the half of the decision that cannot be read inside a
    transaction, because it lives in this process's environment rather
    than in Postgres. It is passed to finalize_withdrawal_limits as a
    ceiling and a permission; that function reads the live policy itself
    and combines the two with AND and LEAST, so runtime can only tighten.

    Keeping it separate from EffectiveWithdrawalPolicy matters: the
    effective policy is a *display* answer assembled from two
    transactions, and handing it to the payout path is exactly the race
    that migration 20261031040000 closed.
    """

    automation_allowed: bool
    max_amount_tzs: Decimal
    rolling_24h_limit_tzs: Decimal


def deployment_automation_limits() -> DeploymentAutomationLimits:
    """The deployment ceiling and permission, for the payout path.

    Both env flags must agree before automation is permitted at all —
    unchanged, and still deliberately two, so one mis-set variable cannot
    start unattended payouts. ROUND_DOWN on the ceilings for the same
    reason as everywhere else here: a ceiling nudged down lets less money
    through unattended.
    """
    settings = get_settings()
    allowed = settings.auto_withdrawals_enabled and not settings.require_admin_approval_for_all_withdrawals
    return DeploymentAutomationLimits(
        automation_allowed=allowed,
        max_amount_tzs=settings.auto_withdrawal_max_amount_tzs.quantize(MONEY, rounding=ROUND_DOWN),
        rolling_24h_limit_tzs=settings.auto_withdrawal_daily_limit_tzs.quantize(MONEY, rounding=ROUND_DOWN),
    )


@dataclass(frozen=True)
class EffectiveWithdrawalPolicy:
    """What the running system will actually do, not what any one layer was
    configured with.

    ``automation_active`` is the only field the payout path branches on.
    The rest exist so the portal can explain the state - in particular why
    a switch is off when the policy row says it is on.
    """

    automation_active: bool
    max_amount_tzs: Decimal
    merchant_rolling_24h_limit_tzs: Decimal

    # The stored row, for display and for optimistic concurrency.
    policy_enabled: bool
    policy_version: int | None
    policy_max_amount_tzs: Decimal | None
    policy_rolling_24h_limit_tzs: Decimal | None
    updated_at: str | None
    updated_by: str | None

    # The deployment layer.
    manual_only_override: bool
    deployment_automation_allowed: bool
    hard_max_amount_tzs: Decimal
    hard_rolling_24h_limit_tzs: Decimal

    # True when the policy row could not be read or made sense of. The
    # portal must say so rather than render zeros as if they were settings.
    policy_unavailable: bool

    @property
    def blocked_reason_code(self) -> str | None:
        """Why automation is not active, as a code, or None when it is."""
        if self.automation_active:
            return None
        if self.policy_unavailable:
            return CODE_POLICY_UNAVAILABLE
        return CODE_POLICY_DISABLED

    @property
    def blocked_explanation(self) -> str | None:
        """The same thing in a sentence an operator can act on."""
        if self.automation_active:
            return None
        if self.policy_unavailable:
            return (
                "The automation policy could not be read, so every withdrawal is going to "
                "manual approval. This is the safe fallback, not a configuration you chose."
            )
        if self.manual_only_override:
            return (
                "A deployment override (REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS) is forcing "
                "manual approval for every withdrawal. The switch below cannot take effect until "
                "that variable is cleared in the deployment environment."
            )
        if not self.deployment_automation_allowed:
            return (
                "This deployment has not enabled withdrawal automation "
                "(AUTO_WITHDRAWALS_ENABLED), so the switch below cannot take effect yet."
            )
        return "Automatic processing is switched off. Every withdrawal is waiting for manual approval."


MONEY = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """A TZS amount at the two decimal places every money column uses.

    PostgREST serialises a ``numeric`` column as a JSON *number*, so
    ``500000.00`` arrives as the float ``500000.0`` and, left alone, goes
    back out of the API as the string ``"500000.0"``. The portal then
    rendered "TZS 500,000.0 or less may process automatically" on the one
    field where mistaking 500 for 500,000 is the whole hazard — a trailing
    single zero is noise exactly where the number has to be read at a
    glance.

    Lossless for anything that came out of ``numeric(14, 2)``, which
    cannot hold a third decimal place in the first place.
    """
    return value.quantize(MONEY)


def _decimal_or_none(value: object) -> Decimal | None:
    """A money column that will not parse is a reason to fall back to
    manual, not a reason to guess. Never float(): a binary float cannot
    hold 0.01, and this value decides whether real money moves."""
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if parsed < 0:
        return None
    return parsed


def load_stored_policy(client: Client) -> dict | None:
    """The policy row, or None if it cannot be read or does not make sense.

    Deliberately total: every failure mode - no row, several rows, a
    non-numeric amount, a dead connection, a PostgREST error envelope -
    collapses to None, and None means manual approval upstream. The one
    thing this must never do is raise into a withdrawal request, because a
    merchant's payout request failing is a worse outcome than that payout
    waiting for a human.
    """
    try:
        rows = client.table(TABLE).select(
            "enabled, max_amount_tzs, merchant_rolling_24h_limit_tzs, version, updated_at, updated_by"
        ).limit(2).execute().data
    except Exception:  # noqa: BLE001 - see the docstring; this falls back to manual
        logger.warning("withdrawal_policy_unreadable")
        return None

    # A select that failed can come back as PostgREST's error dict rather
    # than a list, and iterating that yields its string keys - which counts
    # like rows and reads like data. Checked explicitly.
    if not isinstance(rows, list) or len(rows) != 1:
        logger.warning("withdrawal_policy_unexpected_shape rows=%s", len(rows) if isinstance(rows, list) else "n/a")
        return None

    row = rows[0]
    max_amount = _decimal_or_none(row.get("max_amount_tzs"))
    rolling = _decimal_or_none(row.get("merchant_rolling_24h_limit_tzs"))
    version = row.get("version")
    if max_amount is None or rolling is None or not isinstance(version, int):
        logger.warning("withdrawal_policy_malformed")
        return None

    return {
        "enabled": bool(row.get("enabled")),
        "max_amount_tzs": money(max_amount),
        "merchant_rolling_24h_limit_tzs": money(rolling),
        "version": version,
        "updated_at": row.get("updated_at"),
        "updated_by": row.get("updated_by"),
    }


def resolve_effective_policy(client: Client) -> EffectiveWithdrawalPolicy:
    """Collapse the deployment layer and the stored policy into one answer.

    Called on the payout path and by the portal, so both are looking at the
    same thing - the portal cannot show OFF while a withdrawal is being
    auto-authorized, or ON while every request is going to a human.
    """
    settings = get_settings()
    manual_only = settings.require_admin_approval_for_all_withdrawals
    deployment_allows = settings.auto_withdrawals_enabled and not manual_only
    # Normalised here rather than at the response, so the limit the RPC is
    # given, the limit the portal shows and the limit the audit trail
    # records are the same text. ROUND_DOWN because these are ceilings: a
    # ceiling nudged down lets less money through unattended, and that is
    # the only direction a rounding choice is allowed to err.
    hard_max = settings.auto_withdrawal_max_amount_tzs.quantize(MONEY, rounding=ROUND_DOWN)
    hard_rolling = settings.auto_withdrawal_daily_limit_tzs.quantize(MONEY, rounding=ROUND_DOWN)

    stored = load_stored_policy(client)

    if stored is None:
        return EffectiveWithdrawalPolicy(
            automation_active=False,
            max_amount_tzs=Decimal(0),
            merchant_rolling_24h_limit_tzs=Decimal(0),
            policy_enabled=False,
            policy_version=None,
            policy_max_amount_tzs=None,
            policy_rolling_24h_limit_tzs=None,
            updated_at=None,
            updated_by=None,
            manual_only_override=manual_only,
            deployment_automation_allowed=deployment_allows,
            hard_max_amount_tzs=hard_max,
            hard_rolling_24h_limit_tzs=hard_rolling,
            policy_unavailable=True,
        )

    # The ceilings bite here, once, so that nothing downstream has to
    # remember to apply them.
    effective_max = min(stored["max_amount_tzs"], hard_max)
    effective_rolling = min(stored["merchant_rolling_24h_limit_tzs"], hard_rolling)
    active = deployment_allows and stored["enabled"] and effective_max > 0 and effective_rolling > 0

    return EffectiveWithdrawalPolicy(
        automation_active=active,
        max_amount_tzs=effective_max,
        merchant_rolling_24h_limit_tzs=effective_rolling,
        policy_enabled=stored["enabled"],
        policy_version=stored["version"],
        policy_max_amount_tzs=stored["max_amount_tzs"],
        policy_rolling_24h_limit_tzs=stored["merchant_rolling_24h_limit_tzs"],
        updated_at=stored["updated_at"],
        updated_by=str(stored["updated_by"]) if stored["updated_by"] else None,
        manual_only_override=manual_only,
        deployment_automation_allowed=deployment_allows,
        hard_max_amount_tzs=hard_max,
        hard_rolling_24h_limit_tzs=hard_rolling,
        policy_unavailable=False,
    )


# --- Writing the policy ----------------------------------------------------

_MAX_EXPONENT = 2


def _validate_amounts(*, enabled: bool, max_amount: Decimal, rolling: Decimal) -> None:
    """Server-side, always - the portal's own checks are a convenience and
    this is the only enforcement. Messages name the real limit, because an
    operator who gets "invalid value" has no way to find the right one."""
    settings = get_settings()

    for label, value in (
        ("Maximum automatic withdrawal amount", max_amount),
        ("Rolling 24-hour automatic limit", rolling),
    ):
        if value < 0:
            raise ValidationAPIError(f"{label} cannot be negative.")
        if -value.as_tuple().exponent > _MAX_EXPONENT:
            raise ValidationAPIError(f"{label} may have at most 2 decimal places.")

    if not enabled:
        # Limits are still stored and still validated for shape, so that
        # turning the switch on later cannot surface a value that was never
        # checked. The "must be positive" and platform-cap rules below are
        # about a policy that is actually in force.
        return

    if max_amount <= 0 or rolling <= 0:
        raise ValidationAPIError(
            "Both limits must be greater than zero to enable automatic processing. "
            "To stop automatic processing, switch it off instead."
        )

    if max_amount < settings.min_withdrawal_amount_tzs:
        raise ValidationAPIError(
            f"The maximum automatic withdrawal amount ({max_amount} TZS) is below the platform's "
            f"minimum withdrawal amount ({settings.min_withdrawal_amount_tzs} TZS), so no withdrawal "
            "could ever qualify. Set it to at least the minimum, or switch automatic processing off."
        )

    if max_amount > settings.max_withdrawal_amount_tzs:
        raise ValidationAPIError(
            f"The maximum automatic withdrawal amount cannot exceed the platform's per-request "
            f"withdrawal cap of {settings.max_withdrawal_amount_tzs} TZS."
        )

    if rolling > settings.daily_withdrawal_limit_tzs:
        raise ValidationAPIError(
            f"The rolling 24-hour automatic limit cannot exceed the platform's rolling 24-hour "
            f"withdrawal limit of {settings.daily_withdrawal_limit_tzs} TZS."
        )

    if rolling < max_amount:
        raise ValidationAPIError(
            "The rolling 24-hour automatic limit cannot be lower than the per-request maximum - "
            "the first withdrawal of the day would exhaust it and nothing would ever process "
            "automatically."
        )


def requires_confirmation(
    current: EffectiveWithdrawalPolicy, *, enabled: bool, max_amount: Decimal, rolling: Decimal
) -> bool:
    """Whether this change widens what can happen without a human.

    Turning automation on, or raising either limit, is the direction that
    lets more money move unattended, so the caller must say explicitly that
    it meant to. Tightening or switching off never needs confirming: an
    operator reaching for the brake must not be asked twice.
    """
    if enabled and not current.policy_enabled:
        return True
    if not enabled:
        return False
    if current.policy_max_amount_tzs is None or current.policy_rolling_24h_limit_tzs is None:
        return True
    return max_amount > current.policy_max_amount_tzs or rolling > current.policy_rolling_24h_limit_tzs


def update_policy(
    client: Client,
    *,
    enabled: bool,
    max_amount_tzs: Decimal,
    merchant_rolling_24h_limit_tzs: Decimal,
    expected_version: int,
    actor_id: uuid.UUID,
    correlation_id: str,
    confirmed: bool,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """Write the policy AND its audit row, together or not at all.

    Both used to be separate requests: the update committed, then the
    router wrote the audit row. If that second write failed, the control
    over unattended payouts had changed, nothing recorded that anybody
    changed it, and the administrator who had in fact succeeded was shown
    an error. All three are bad, and the third is the kind of thing that
    gets a change made twice.

    update_withdrawal_automation_policy (migration 20261031040000) does
    both under ``for update`` on the single policy row, so they commit
    together, the version check and the write are one decision rather than
    two, and the before/after values in the audit row come from the row
    this transaction locked rather than from an earlier read that may
    already be stale.

    ``actor_id`` is the authenticated admin from the request context, never
    the request body — a client-supplied administrator id would make the
    audit trail worthless.

    Raises ValidationAPIError for a value that cannot be stored and
    ConflictError for a stale version. Returns the stored row.
    """
    _validate_amounts(enabled=enabled, max_amount=max_amount_tzs, rolling=merchant_rolling_24h_limit_tzs)
    deployment = deployment_automation_limits()

    try:
        result = client.rpc(
            "update_withdrawal_automation_policy",
            {
                "p_enabled": enabled,
                "p_max_amount": str(max_amount_tzs),
                "p_rolling_limit": str(merchant_rolling_24h_limit_tzs),
                "p_expected_version": expected_version,
                "p_actor_id": str(actor_id),
                "p_correlation_id": correlation_id,
                "p_confirmed": confirmed,
                # Recorded in the audit row, not enforced here —
                # enforcement is finalize_withdrawal_limits' job, at the
                # moment a payout is authorised.
                "p_deployment_allows": deployment.automation_allowed,
                "p_deployment_max": str(deployment.max_amount_tzs),
                "p_deployment_rolling": str(deployment.rolling_24h_limit_tzs),
                "p_ip": ip_address,
                "p_user_agent": user_agent,
            },
        ).execute()
    except Exception as exc:  # narrowed below, re-raised otherwise
        raise ConflictError(
            "The automation policy could not be saved. Nothing was changed. "
            "Reload the current settings and try again."
        ) from exc

    data = result.data if isinstance(result.data, dict) else {}
    outcome = data.get("outcome")

    if outcome == "conflict":
        raise ConflictError(
            "This policy was changed by someone else while you were editing it. "
            "Reload the current settings and apply your change again."
        )
    if outcome != "ok":
        # 'unavailable', or a shape this code does not recognise. Either
        # way nothing was written, and saying so is the only honest
        # answer available.
        raise ConflictError(
            "The automation policy could not be read, so it was not changed. "
            "Withdrawals are going to manual approval in the meantime. Reload and try again."
        )

    return {
        "enabled": data["enabled"],
        "max_amount_tzs": data["max_amount_tzs"],
        "merchant_rolling_24h_limit_tzs": data["merchant_rolling_24h_limit_tzs"],
        "version": data["version"],
        "updated_at": data.get("updated_at"),
        "updated_by": str(actor_id),
    }
