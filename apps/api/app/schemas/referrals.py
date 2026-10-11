"""Request/response shapes for the referral programme.

Two audiences with deliberately different views of the same rows.

A **merchant** sees their own code, their own link, counts, and money.
They do not see who the referred businesses are beyond a count, what those
businesses trade, or any fraud flag — that is another business's private
trading information, and a referrer's interest in it ends at "did it
qualify".

A **Super Admin** sees everything, because approving a payout without
being able to see what it was earned from is not a review.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class MerchantReferralSummaryResponse(BaseModel):
    """The merchant portal's referral panel."""

    referral_code: str | None = None
    referral_code_status: str = "active"
    referral_link: str | None = None

    total_invited: int
    approved_referrals: int
    qualified_referrals: int

    pending_commission: Decimal
    approved_commission: Decimal
    paid_commission: Decimal
    currency: str = "TZS"


class AdminReferralResponse(BaseModel):
    """One referral relationship, as Super Admin sees it."""

    id: uuid.UUID
    referrer_merchant_id: uuid.UUID
    referrer_name: str | None = None
    referrer_code: str | None = None
    referred_merchant_id: uuid.UUID
    referred_name: str | None = None
    referred_code: str | None = None

    referral_code_used: str
    status: str

    signup_at: datetime
    referred_approved_at: datetime | None = None
    referral_period_start_at: datetime | None = None
    referral_period_end_at: datetime | None = None

    qualification_volume_threshold: Decimal
    commission_rate_bps: int
    minimum_payout_amount: Decimal
    currency: str

    ineligible_reason: str | None = None
    fraud_flag_reason: str | None = None

    # The commission as it currently stands, when one has been calculated.
    commission_id: uuid.UUID | None = None
    commission_status: str | None = None
    successful_volume: Decimal | None = None
    infinitypay_net_revenue: Decimal | None = None
    commission_amount: Decimal | None = None
    payout_eligible: bool = False


class AdminReferralCommissionResponse(BaseModel):
    id: uuid.UUID
    referral_id: uuid.UUID
    referrer_merchant_id: uuid.UUID
    referred_merchant_id: uuid.UUID

    period_start_at: datetime
    period_end_at: datetime

    successful_volume: Decimal
    infinitypay_net_revenue: Decimal
    commission_rate_bps: int
    commission_amount: Decimal
    minimum_payout_amount: Decimal
    currency: str

    status: str
    reviewed_by_admin_id: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    paid_at: datetime | None = None
    rejection_reason: str | None = None
    calculation_snapshot: dict[str, Any] = Field(default_factory=dict)


class CommissionRejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class CommissionPaidRequest(BaseModel):
    """`note` is where the operator records how it was actually paid —
    this endpoint moves no money, it records that someone else did."""

    note: str | None = Field(default=None, max_length=500)


class FraudHoldRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ReferralCodeStatusRequest(BaseModel):
    status: str = Field(pattern="^(active|disabled)$")
    reason: str | None = Field(default=None, max_length=500)
