"""Shared "is this merchant allowed to move money yet?" gate.

A merchant may collect payments, issue payment links / invoices, and mint
API keys only once a Super Admin has approved their onboarding submission —
which is the moment app/services/onboarding.py::approve_onboarding_submission
sets ``merchants.status = 'active'`` (together with ``kyc_status =
'verified'``).

Withdrawals already enforce this via
app/services/disbursements.py::_check_merchant_is_verified (raising
WithdrawalRestrictedError). This module is the same rule for the money-in
and money-enabling paths, in one place, so every entry point checks it
identically instead of each router re-deriving it.
"""

import uuid

from supabase import Client

from app.core.errors import MerchantNotApprovedError
from app.services.crud import get_by_id

_PENDING_MESSAGE = (
    "Your merchant account is still pending verification. You'll be able to collect "
    "payments and manage credentials once an InfinityPay reviewer approves your account."
)


def require_approved_merchant(client: Client, merchant_id: uuid.UUID) -> dict:
    """Return the merchant row if their account is approved and active;
    raise MerchantNotApprovedError (403) otherwise.

    'active' is the single source of truth here — it's set only by Super
    Admin approval and cleared by suspension, so it already covers both
    "never approved" and "approval revoked"."""
    merchant = get_by_id(client, "merchants", merchant_id)
    if not merchant or merchant.get("status") != "active":
        raise MerchantNotApprovedError(_PENDING_MESSAGE)
    return merchant
