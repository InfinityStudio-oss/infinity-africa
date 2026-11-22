"""Request and response shapes for the Disbursement API.

The merchant-facing name is "Payouts" and the developer-facing name is
the "Disbursement API"; the route is /v1/payouts because
/v1/disbursements is the older withdrawal API and spends a different
balance.

No merchant_id anywhere in a request. A payout key already implies its
merchant and its environment, and accepting either from the body would
mean validating a client-supplied id on a money-moving call - the exact
shape of an insecure direct object reference. Both are read from the
authenticated caller instead.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PayoutCreateRequest(BaseModel):
    """Create one payout to an already-approved beneficiary."""

    # Refused, not ignored. A merchant_id in this body is the specific
    # case: Pydantic would drop it and return 201, so a partner who sent
    # one would believe they had aimed the payout at that merchant. On a
    # money-moving call the quiet version of that answer is the dangerous
    # one - say no instead.
    model_config = ConfigDict(extra="forbid")

    beneficiary_id: uuid.UUID
    amount: Decimal = Field(gt=0, description="Payout amount, exclusive of fees")
    currency: str = Field(default="TZS", pattern="^[A-Z]{3}$")
    # Free-form, echoed back and stored. Capped so a client cannot use a
    # payout record as general-purpose storage.
    metadata: dict = Field(default_factory=dict)

    @field_validator("amount")
    @classmethod
    def _at_most_two_decimals(cls, value: Decimal) -> Decimal:
        if -value.as_tuple().exponent > 2:
            raise ValueError("Amount may have at most 2 decimal places.")
        return value

    @field_validator("metadata")
    @classmethod
    def _bounded_metadata(cls, value: dict) -> dict:
        if len(value) > 20:
            raise ValueError("metadata may have at most 20 keys.")
        for key, item in value.items():
            if not isinstance(item, (str, int, float, bool)) and item is not None:
                raise ValueError(f"metadata.{key} must be a string, number, boolean or null.")
            if isinstance(item, str) and len(item) > 500:
                raise ValueError(f"metadata.{key} may be at most 500 characters.")
        return value


class PayoutResponse(BaseModel):
    """What a payout looks like to the partner.

    Deliberately excludes provider_raw_response, api_key_id and the
    beneficiary's identifier: the first is ours to debug with, the second
    is a credential reference, and the third is already known to whoever
    created the beneficiary and does not need repeating on every read.
    """

    id: uuid.UUID
    status: str
    amount: Decimal
    fee_amount: Decimal
    total_debit: Decimal
    currency: str
    environment: str
    beneficiary_id: uuid.UUID
    reference: str = Field(description="Stable InfinityPay reference for this payout")
    failure_code: str | None = None
    failure_reason: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict) -> "PayoutResponse":
        return cls(
            id=row["id"],
            status=row["status"],
            amount=Decimal(str(row["amount"])),
            fee_amount=Decimal(str(row["fee_amount"])),
            total_debit=Decimal(str(row["total_debit"])),
            currency=row["currency"],
            environment=row["environment"],
            beneficiary_id=row["beneficiary_id"],
            reference=row["provider_reference"],
            failure_code=row.get("failure_code"),
            failure_reason=row.get("failure_reason"),
            created_at=row["created_at"],
            completed_at=row.get("completed_at"),
        )


class PayoutWalletFundRequest(BaseModel):
    """Move settled funds from Collections into the Payout Wallet.

    Dashboard-only. A payout key must never be able to top up the wallet
    it spends from - that would make a leaked key self-replenishing, and
    the balance would stop being a cap on the damage.
    """

    amount: Decimal = Field(gt=0)
    currency: str = Field(default="TZS", pattern="^[A-Z]{3}$")
    environment: str = Field(default="live", pattern="^(sandbox|live)$")

    @field_validator("amount")
    @classmethod
    def _at_most_two_decimals(cls, value: Decimal) -> Decimal:
        if -value.as_tuple().exponent > 2:
            raise ValueError("Amount may have at most 2 decimal places.")
        return value


class PayoutWalletResponse(BaseModel):
    available: Decimal
    reserved: Decimal
    currency: str
    environment: str


class MerchantPayoutWalletResponse(BaseModel):
    """The wallet as the portal needs it.

    Carries the pause state and the limits alongside the balances so the
    page can render a Fund button that matches what the server will
    actually allow. `can_fund` is the role answer: staff and developers
    may read this surface, but only an admin may move money onto it, and
    the button should say so rather than discovering it on submit.
    """

    available: Decimal
    reserved: Decimal
    currency: str
    environment: str
    paused: bool = False
    paused_reason: str | None = None
    per_payout_limit_tzs: Decimal | None = None
    daily_limit_tzs: Decimal | None = None
    can_fund: bool = False
    # An outstanding funding code, if one is still usable. The code
    # itself lives on the server and the box to type it into lived only
    # in page state, so a reload left a merchant with a valid code in
    # their inbox and nowhere to put it. This is what lets the page
    # offer the box again.
    pending_funding_challenge_id: uuid.UUID | None = None
    pending_funding_masked_email: str | None = None
    pending_funding_amount: Decimal | None = None
    pending_funding_expires_at: datetime | None = None
