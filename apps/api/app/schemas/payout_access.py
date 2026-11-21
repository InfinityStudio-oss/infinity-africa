"""Super Admin payout-access shapes.

Every write model is `extra="forbid"`. On a control over who may move
money programmatically, a field that is silently dropped is worse than a
422: the operator is told their change applied.

`live_enabled` used to be absent from every write model, so granting
live payouts was impossible through the API at all and could only be
done by editing the database. That is not safer - it just moved the act
somewhere with no validation, no audit entry and no record of who did
it. It now has its own model and its own route, separate from the
sandbox switch and carrying an explicit acknowledgement, so it is a
deliberate act that leaves a trail rather than a forbidden one that
happens anyway.
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


class PayoutLiveAccessUpdate(BaseModel):
    """Grant or withdraw LIVE payout access - real money, sent by an API
    key, with nobody approving each request.

    Its own model and its own route, rather than a second boolean on
    PayoutAccessUpdate. Granting live is not the same kind of act as
    switching the sandbox on, and a screen that could do both with one
    field is a screen where it happens by accident.

    `acknowledge` is the deliberate step. It is not ceremony: it is what
    makes the request impossible to send by replaying a sandbox call with
    one value flipped.
    """

    model_config = ConfigDict(extra="forbid")

    live_enabled: bool
    version: int = Field(gt=0)
    # Required to turn live ON, ignored when turning it off - withdrawing
    # access should never be harder than granting it.
    acknowledge: bool = False

    def model_post_init(self, _context) -> None:
        if self.live_enabled and not self.acknowledge:
            raise ValueError(
                "Granting live payout access needs acknowledge=true. A live payout key "
                "sends real money with no human approving each request."
            )


class PayoutFeeUpdate(BaseModel):
    """This merchant's negotiated payout fee.

    Null on both fields clears the negotiated rate and puts the merchant
    back on the platform tariff. That is why they are optional and why
    null is meaningful here rather than "leave unchanged": "charge them
    the standard rate" has to be expressible, and it is the normal state.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = Field(gt=0)
    fee_flat_tzs: Decimal | None = Field(default=None, ge=0)
    fee_percentage: Decimal | None = Field(default=None, ge=0, le=100)

    @field_validator("fee_flat_tzs")
    @classmethod
    def _two_decimals(cls, value: Decimal | None) -> Decimal | None:
        return _at_most_two_decimals(value)


class PlatformPayoutTariffUpdate(BaseModel):
    """The default every merchant without a negotiated rate pays."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(gt=0)
    percentage_fee: Decimal = Field(ge=0, le=100)
    flat_fee: Decimal = Field(default=Decimal(0), ge=0)


class PlatformPayoutTariffResponse(BaseModel):
    percentage_fee: Decimal
    flat_fee: Decimal
    version: int
    updated_at: datetime | None = None


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
