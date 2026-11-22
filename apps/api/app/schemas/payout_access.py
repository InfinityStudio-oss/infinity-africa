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
    # Null means no negotiated rate: this merchant pays the platform
    # tariff. Reported as null rather than resolved to the tariff value,
    # so the screen can show "standard" instead of a number an operator
    # would read as this merchant's own deal.
    fee_flat_tzs: Decimal | None = None
    fee_percentage: Decimal | None = None
    # When the merchant asked for access, if they ever did. Null is not
    # the same as refused: it means they never asked.
    access_requested_at: datetime | None = None
    version: int
    updated_at: datetime | None = None
    # What is still committed. Pausing does not recall an in-flight
    # payout, and an operator deciding whether to pause should see that.
    wallet_available: Decimal = Decimal(0)
    wallet_reserved: Decimal = Decimal(0)
    wallet_environment: str = "sandbox"


class PayoutReleaseRequest(BaseModel):
    """Give back the reserve on a payout parked in reconciliation.

    `reason` is required and stored, because it is the only record of
    the judgement being made: somebody decided the provider did not pay.
    `acknowledge` is the deliberate step, for the same reason it exists
    on granting live access — this cannot be sent by accident.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=300)
    acknowledge: bool = False

    @field_validator("reason")
    @classmethod
    def _trim(cls, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) < 10:
            raise ValueError("Give a real reason — how do you know the provider did not pay?")
        return trimmed

    def model_post_init(self, _context) -> None:
        if not self.acknowledge:
            raise ValueError(
                "Releasing a reserve needs acknowledge=true. If the provider did pay, this "
                "returns money that already left and the platform covers the difference."
            )


class AdminPayoutRow(BaseModel):
    """One payout, as Super Admin sees it — with the merchant named,
    which the partner-facing shape has no reason to carry."""

    id: uuid.UUID
    merchant_id: uuid.UUID
    business_name: str | None = None
    merchant_code: str | None = None
    environment: str
    status: str
    amount: Decimal
    fee_amount: Decimal
    total_debit: Decimal
    currency: str
    failure_code: str | None = None
    failure_reason: str | None = None
    # Why the release button is or is not offered. A payout the provider
    # acknowledged must be settled by asking them, never by assuming,
    # so the screen has to know the difference.
    provider_acknowledged: bool = False
    dispatch_attempts: int = 0
    created_at: datetime
    completed_at: datetime | None = None


class ProviderHealthResponse(BaseModel):
    """Whether the payout provider is actually reachable, per environment.

    Worth its own endpoint because the first sandbox payout failed at
    exactly this point and the only symptom was a payout silently
    parking: the Selcom Business sandbox base URL answers 404, and
    nothing in the product said so. A deployment that cannot reach its
    provider should be able to say that out loud.
    """

    environment: str
    reachable: bool
    detail: str
    checked_at: datetime


class PayoutRequestDismiss(BaseModel):
    """Clear a pending access request without granting anything.

    The reason is required and audited, because clearing the stamp
    destroys the only evidence on the row that anybody ever asked. An
    operator looking later needs to be able to tell "declined, and here
    is why" from "nobody has ever requested this".

    Deliberately NOT a refusal the merchant is told about and NOT a
    block: they keep the same not-enabled screen they had before, and
    they can ask again. A dismissal is an inbox action, not a verdict.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = Field(gt=0)
    reason: str = Field(min_length=5, max_length=300)

    @field_validator("reason")
    @classmethod
    def _trim_reason(cls, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) < 5:
            raise ValueError("Give a short reason — it is the only record of the decision.")
        return trimmed
