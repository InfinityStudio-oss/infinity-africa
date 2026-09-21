"""Gates whether a merchant may create/rotate a `live` API key, and whether
a merchant may authenticate with an API key at all (any environment).

Business decision (amended 2026-08-26): production API keys are
self-service — once a merchant is approved, they create their own `live`
keys with no per-key or per-merchant Super Admin approval step. The gate is
purely automatic eligibility:
  - merchant status == 'active'        (Super Admin approved onboarding)
  - kyc_status == 'verified'
  - a pricing rule resolves for them    (their own, or the platform fallback)
  - api_access_suspended is false       (Super Admin abuse/fraud kill switch)

"Wallet exists" from the task brief isn't a separate check: this codebase
has no standalone wallet-creation record — get_wallet_balance derives the
balance from the transactions ledger, which is always queryable (0 for a
merchant with no transactions yet), so a wallet effectively always "exists"
the moment a merchant row does.

Sandbox keys are gated only on api_access_suspended — every non-suspended
merchant, regardless of approval state, can always create/use a sandbox key
(that's the whole point of a sandbox letting integrators build ahead of
approval).
"""

import uuid

from supabase import Client

from app.core.errors import ProductionAccessRestrictedError
from app.services.withdrawals.fee_calculator import find_pricing_rule


def is_merchant_api_access_suspended(merchant: dict) -> bool:
    return bool(merchant.get("api_access_suspended"))


def has_resolvable_pricing_rule(client: Client, merchant_id: uuid.UUID) -> bool:
    return find_pricing_rule(client, merchant_id=merchant_id, channel=None, destination_code=None) is not None


def is_production_api_access_allowed(client: Client, merchant: dict) -> bool:
    if is_merchant_api_access_suspended(merchant):
        return False
    if merchant.get("status") != "active" or merchant.get("kyc_status") != "verified":
        return False
    return has_resolvable_pricing_rule(client, uuid.UUID(merchant["id"]))


def check_production_api_access(client: Client, merchant: dict) -> None:
    if is_merchant_api_access_suspended(merchant):
        raise ProductionAccessRestrictedError(
            "This merchant's API access has been suspended. Contact InfinityPay support."
        )
    if merchant.get("status") != "active" or merchant.get("kyc_status") != "verified":
        raise ProductionAccessRestrictedError(
            "Production API keys are available after your business account is approved."
        )
    if not has_resolvable_pricing_rule(client, uuid.UUID(merchant["id"])):
        raise ProductionAccessRestrictedError(
            "Production API access isn't available yet — no pricing has been assigned to your account. "
            "Contact InfinityPay support."
        )


def check_sandbox_api_access(merchant: dict) -> None:
    if is_merchant_api_access_suspended(merchant):
        raise ProductionAccessRestrictedError(
            "This merchant's API access has been suspended. Contact InfinityPay support."
        )
