"""The Selcom Business Disbursement API adapter interface, and the one
place mock vs. sandbox vs. live is decided — mirrors
app/services/selcom/client.py's role for the (unrelated, differently-signed)
checkout/collections API.

SELCOM_BUSINESS_MODE controls which client get_selcom_business_client()
returns:
  - "mock"    -> MockSelcomBusinessClient. Local development ONLY — refused
                 with a RuntimeError unless ENVIRONMENT=development, so a
                 stray SELCOM_BUSINESS_MODE=mock in Railway can never
                 silently fake a real payout as "successful" (a merchant
                 would believe they were paid; they weren't). There is no
                 code path that falls back to the mock client from
                 "sandbox" or "live" either way.
  - "sandbox" -> SelcomBusinessClient pointed at
                 SELCOM_BUSINESS_SANDBOX_BASE_URL. Real HTTP calls to
                 Selcom's sandbox environment.
  - "live"    -> SelcomBusinessClient pointed at
                 SELCOM_BUSINESS_PRODUCTION_BASE_URL. Real HTTP calls to
                 Selcom's production environment — only use once a real
                 sandbox round-trip has verified the request/response shapes
                 in app/services/selcom_business/signing.py and parsing.py.

Only app/services/disbursements.py reaches this, and only through
_reserve_and_run_disbursement_provider — either from a Super Admin's
manual approval, or from execute_disbursement's auto-processing branch
when withdrawal automation is enabled (off by default; see
Settings.auto_withdrawals_enabled). Both go through that one function, so
there is no second, less-tested payout path into this client.
"""

from functools import lru_cache
from typing import Protocol

from app.config import get_settings
from app.services.selcom_business.schemas import SelcomBusinessResult


class SelcomBusinessMisconfiguredError(RuntimeError):
    """SELCOM_BUSINESS_MODE=mock outside a development environment — refused
    outright rather than silently faking a real merchant payout. If a
    deployed environment needs withdrawal approval paused, do that at the
    Super Admin workflow level (stop approving), not by mocking Selcom."""


class SelcomBusinessProvider(Protocol):
    async def process_transaction(
        self,
        *,
        trans_id: str,
        recipient_fi_code: str,
        recipient_account: str,
        recipient_name: str,
        amount: str,
        purpose: str,
        remarks: str | None = None,
    ) -> SelcomBusinessResult: ...

    async def query_transaction(self, *, trans_id: str) -> SelcomBusinessResult: ...


@lru_cache
def get_selcom_business_client() -> SelcomBusinessProvider:
    """Cached like get_selcom_client() — constructing either client is
    cheap and stateless; tests that flip SELCOM_BUSINESS_MODE between cases
    must call get_selcom_business_client.cache_clear()."""
    settings = get_settings()

    if settings.selcom_business_mode == "mock":
        if settings.environment != "development":
            raise SelcomBusinessMisconfiguredError(
                "SELCOM_BUSINESS_MODE=mock is only allowed when ENVIRONMENT=development — "
                f"refusing to fake real withdrawal payouts in a '{settings.environment}' environment."
            )

        from app.services.selcom_business.mock_client import MockSelcomBusinessClient

        return MockSelcomBusinessClient(
            failure_rate=settings.mock_provider_failure_rate,
            latency_seconds=settings.mock_provider_latency_seconds,
        )

    from app.services.selcom_business.live_client import SelcomBusinessClient

    base_url = (
        settings.selcom_business_production_base_url
        if settings.selcom_business_mode == "live"
        else settings.selcom_business_sandbox_base_url
    )
    return SelcomBusinessClient(
        base_url=base_url,
        api_key=settings.selcom_business_api_key,
        private_key_base64=settings.selcom_business_private_key_base64,
        timeout_seconds=settings.selcom_business_timeout_seconds,
    )


__all__ = [
    "SelcomBusinessMisconfiguredError",
    "SelcomBusinessProvider",
    "SelcomBusinessResult",
    "get_selcom_business_client",
]
