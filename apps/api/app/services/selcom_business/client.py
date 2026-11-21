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

Two callers reach this.

app/services/disbursements.py — withdrawals — calls it with no argument
and follows SELCOM_BUSINESS_MODE as described above, either from a Super
Admin's manual approval or from execute_disbursement's auto-processing
branch when withdrawal automation is enabled (off by default; see
Settings.auto_withdrawals_enabled).

app/services/payout_dispatch.py — the Disbursement API — passes the
payout's own `environment`, which OVERRIDES the mode. It has to: a
deployment that pays real withdrawals necessarily runs this client in
`live`, so following the global mode sent `sandbox` payouts to Selcom
production and real money to a real phone number. A payout's environment
is the only thing that may decide which Selcom it reaches.
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

    async def account_lookup(
        self,
        *,
        recipient_fi_code: str,
        recipient_account: str,
        trans_id: str,
        amount: str | None = None,
    ) -> dict: ...

    async def balance(self, *, account_number: str) -> dict: ...


@lru_cache
def get_selcom_business_client(environment: str | None = None) -> SelcomBusinessProvider:
    """Cached like get_selcom_client() — constructing either client is
    cheap and stateless; tests that flip SELCOM_BUSINESS_MODE between cases
    must call get_selcom_business_client.cache_clear().

    `environment` is how a PAYOUT says which Selcom it means, and it wins
    over SELCOM_BUSINESS_MODE.

    Without it, a payout marked `sandbox` was dispatched to whatever the
    global mode pointed at — and in production that is `live`, because
    real withdrawals go through this same client. A sandbox payout
    therefore sent real money to a real phone number. The environment
    column was honoured by the ledger and by the enablement flags, and
    ignored by the one step that actually moves money.

    None keeps the original behaviour for withdrawals, which have no
    environment of their own and have always followed the global mode.
    """
    settings = get_settings()

    if environment is not None and environment not in ("sandbox", "live"):
        raise SelcomBusinessMisconfiguredError(
            f"Unknown Selcom Business environment {environment!r} — refusing to guess "
            "which Selcom to send real money to."
        )

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

    if environment is None:
        # Withdrawals. Unchanged: the deployment-wide mode decides.
        base_url = (
            settings.selcom_business_production_base_url
            if settings.selcom_business_mode == "live"
            else settings.selcom_business_sandbox_base_url
        )
    else:
        # Payouts. The payout's own environment decides, so a sandbox
        # payout cannot reach production however the deployment is
        # configured, and a live payout cannot be quietly answered by a
        # sandbox that reports COMPLETED for money nobody sent.
        base_url = (
            settings.selcom_business_production_base_url
            if environment == "live"
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
