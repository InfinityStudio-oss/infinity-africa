"""Request and response shapes for the Super Admin withdrawal automation
policy. See app/services/withdrawal_policy.py for the precedence these
fields describe, and app/routers/admin_withdrawal_policy.py for the routes.

Amounts are typed ``Decimal`` throughout. Pydantic serialises Decimal to a
JSON **string**, which is what every money field on this API already does
(app/schemas/disbursements.py) and what the portal already parses — a JSON
number would hand the browser a float and put binary rounding between an
operator and a limit that decides whether money moves.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class WithdrawalAutomationPolicyUpdate(BaseModel):
    """What a Super Admin is asking the policy to become.

    ``extra="forbid"`` so a misspelled field is an error rather than a
    silently ignored instruction. An operator who types ``max_amount`` and
    gets a 200 back would reasonably believe the limit had changed.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    # No ge/le here: the real bounds depend on the platform's own
    # withdrawal minimum and caps, and are enforced in
    # withdrawal_policy._validate_amounts so that the message can name the
    # actual limit. Field(ge=0) stays as a cheap floor so a negative never
    # reaches the service.
    max_amount_tzs: Decimal = Field(ge=0)
    merchant_rolling_24h_limit_tzs: Decimal = Field(ge=0)

    # The version the administrator was looking at. Not optional: an
    # update that does not say what it is replacing cannot be checked for
    # staleness, and this policy is edited from a page two people may have
    # open at once.
    version: int = Field(gt=0)

    # Required by the backend for any change that widens what can happen
    # without a human — turning automation on, or raising either limit.
    # See withdrawal_policy.requires_confirmation. Tightening or switching
    # off never needs it.
    confirm: bool = False


class WithdrawalAutomationPolicyResponse(BaseModel):
    """The EFFECTIVE policy, which is not always the stored one.

    The portal renders this directly, including the case where a
    deployment override means the stored switch cannot take effect. Two
    separate sets of numbers are reported on purpose: what is stored, and
    what is actually in force after the deployment ceilings apply.
    """

    # What the system will do right now.
    automation_active: bool
    effective_max_amount_tzs: Decimal
    effective_rolling_24h_limit_tzs: Decimal

    # What is stored, which is what the form edits.
    enabled: bool
    max_amount_tzs: Decimal | None
    merchant_rolling_24h_limit_tzs: Decimal | None
    version: int | None
    updated_at: str | None
    updated_by: str | None
    # Resolved for display. Null when nobody has saved the policy yet, or
    # when the administrator's account no longer exists.
    updated_by_email: str | None

    # Why it is off, when it is off. Null while automation is active.
    blocked_reason_code: str | None
    blocked_explanation: str | None

    # The deployment layer, so the page can say "a deployment override is
    # preventing this" rather than showing a switch that does nothing.
    manual_only_override: bool
    deployment_automation_allowed: bool
    hard_max_amount_tzs: Decimal
    hard_rolling_24h_limit_tzs: Decimal
    policy_unavailable: bool

    # Context the page needs to explain the limits without hardcoding
    # them: the per-request threshold is meaningless next to an unknown
    # platform minimum.
    platform_min_withdrawal_amount_tzs: Decimal
    platform_max_withdrawal_amount_tzs: Decimal
    platform_rolling_24h_limit_tzs: Decimal
