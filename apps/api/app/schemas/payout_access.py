"""Super Admin payout-access shapes.

Every write model is `extra="forbid"`. On a control over who may move
money programmatically, a field that is silently dropped is worse than a
422: the operator is told their change applied. `live_enabled` is the
case that matters - it is deliberately absent from both write models, so
an attempt to grant live payouts from this screen is refused rather than
accepted and ignored.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _at_most_two_decimals(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if -value.as_tuple().exponent > 2:
        raise ValueError("Amount may have at most 2 decimal places.")
    return value


class PayoutAccessUpdate(BaseModel):
    """Turn the sandbox on or off, optionally with limits."""

    model_config = ConfigDict(extra="forbid")

    sandbox_enabled: bool
    # Optimistic concurrency. Required, not optional: two administrators
    # on the same page must not be able to overwrite each other silently.
    version: int = Field(gt=0)
    per_payout_limit_tzs: Decimal | None = Field(default=None, gt=0)
    daily_limit_tzs: Decimal | None = Field(default=None, gt=0)

    @field_validator("per_payout_limit_tzs", "daily_limit_tzs")
    @classmethod
    def _two_decimals(cls, value: Decimal | None) -> Decimal | None:
        return _at_most_two_decimals(value)


class PayoutPauseUpdate(BaseModel):
    """Pause or resume a merchant's ability to create payouts."""

    model_config = ConfigDict(extra="forbid")

    paused: bool
    version: int = Field(gt=0)
    # Required when pausing. A pause with no stated reason is one the next
    # operator cannot safely lift, and the merchant is shown this text.
    reason: str | None = Field(default=None, max_length=300)

    @field_validator("reason")
    @classmethod
    def _trim(cls, value: str | None) -> str | None:
        return value.strip() if value else None

    def model_post_init(self, _context) -> None:
        if self.paused and not self.reason:
            raise ValueError("A reason is required when pausing payouts.")


class MerchantPayoutAccessResponse(BaseModel):
    merchant_id: uuid.UUID
    business_name: str | None = None
    merchant_code: str | None = None
    enabled: bool
    sandbox_enabled: bool
    live_enabled: bool
    paused: bool
    paused_reason: str | None = None
    per_payout_limit_tzs: Decimal | None = None
    daily_limit_tzs: Decimal | None = None
    version: int
    updated_at: datetime | None = None
    # What is still committed. Pausing does not recall an in-flight
    # payout, and an operator deciding whether to pause should see that.
    wallet_available: Decimal = Decimal(0)
    wallet_reserved: Decimal = Decimal(0)
    wallet_environment: str = "sandbox"
