"""The Selcom checkout/collections adapter interface, and the one place
mock vs. live is decided.

`PaymentProvider` is the contract both mock_client.py (MockSelcomClient) and
live_client.py (LiveSelcomClient) implement identically — nothing above this
layer (routers, app/services/collections.py) constructs a client itself or
needs to know which one is active; they all call get_selcom_client() and
use it through this interface.

SELCOM_MODE controls which one that is: "mock" (the default — every
collection is simulated, no network call ever reaches Selcom) or "live"
(calls app/services/selcom/live_client.py, which talks to Selcom's real API
— see docs/selcom-live-go-live.md before ever setting this in a deployed
environment; live traffic will fail until Selcom has whitelisted the
backend's static outbound IP).

Withdrawals/disbursements are a different Selcom product — see
app/services/selcom_business/client.py::get_selcom_business_client().
"""

from decimal import Decimal
from functools import lru_cache
from typing import Protocol

from app.config import get_settings
from app.services.selcom.schemas import (
    CollectionResult,
    DynamicQrResult,
)


class PaymentProvider(Protocol):
    async def initiate_collection(
        self,
        *,
        method: str,
        amount: Decimal,
        currency: str,
        customer_phone: str | None,
        reference: str,
    ) -> CollectionResult:
        """Push a collection request to the customer (USSD/STK/Selcom Pesa).
        Real push-payment APIs acknowledge the push near-instantly — the
        customer's approval (or lack of it) is what actually determines the
        outcome, discovered later via check_collection_status (or, for a
        live client, its own async callback to /v1/webhooks/selcom).
        Always returns status="processing"."""
        ...

    async def check_collection_status(self, *, provider_reference: str) -> CollectionResult:
        """Polls for the outcome of a previously-initiated collection. A
        live client would likely expose an equivalent status-check
        endpoint alongside its webhook, for reconciliation."""
        ...

    async def generate_dynamic_qr(
        self,
        *,
        amount: Decimal,
        currency: str,
        reference: str,
    ) -> DynamicQrResult:
        """Generates a scannable QR payload for a collection. Also always
        "processing" until scanned and approved — resolved the same way as
        a push (check_collection_status / callback)."""
        ...

class SelcomMisconfiguredError(RuntimeError):
    """SELCOM_MODE would hand out a simulated collection client somewhere
    that is not development. Deliberately a RuntimeError rather than an
    APIError: this is a deployment mistake, not something a caller did,
    and it should reach the logs and Sentry as an unhandled 500 rather
    than being dressed up as a tidy 4xx the caller might retry.

    Named and raised to match SelcomBusinessMisconfiguredError on the
    payouts side, which has always refused the same way.
    """


@lru_cache
def get_selcom_client() -> PaymentProvider:
    """FastAPI-callable (and plain function) returning the active Selcom
    client. Branches on SELCOM_MODE — "mock" (default) returns
    MockSelcomClient, "live" constructs LiveSelcomClient from the
    SELCOM_BASE_URL/SELCOM_API_KEY/SELCOM_API_SECRET/SELCOM_VENDOR_ID env
    vars. Cached because constructing either client is cheap and stateless,
    but repeated per-request construction is pointless — tests that flip
    SELCOM_MODE between cases must call get_selcom_client.cache_clear()."""
    settings = get_settings()
    if settings.selcom_mode == "live":
        from app.services.selcom.live_client import LiveSelcomClient, SelcomHTTPClient

        return LiveSelcomClient(
            client=SelcomHTTPClient(
                base_url=settings.selcom_base_url,
                api_key=settings.selcom_api_key,
                api_secret=settings.selcom_api_secret,
                vendor_id=settings.selcom_vendor_id,
            )
        )

    # Mirrors get_selcom_business_client()'s refusal, for the reason that
    # matters more on this side: MockSelcomClient resolves a collection to
    # "successful" most of the time, and execute_collection() resolves one
    # the moment it is created — so a mocked production credits merchant
    # wallets for money nobody ever paid, silently, with no error anywhere.
    #
    # Raised here rather than blocking startup. Refusing to boot took the
    # whole API down once already; this costs only the requests that would
    # have been simulated, and leaves health, auth, dashboards and the
    # Checkout money path serving normally.
    if settings.environment != "development":
        raise SelcomMisconfiguredError(
            f"SELCOM_MODE={settings.selcom_mode!r} is only allowed when ENVIRONMENT=development — "
            f"refusing to simulate collections in a '{settings.environment}' environment, because a "
            "simulated collection credits a real merchant wallet. Set SELCOM_MODE=live."
        )

    from app.services.selcom.mock_client import MockSelcomClient

    return MockSelcomClient(
        failure_rate=settings.mock_provider_failure_rate,
        latency_seconds=settings.mock_provider_latency_seconds,
        qr_expiry_seconds=settings.dynamic_qr_expiry_seconds,
    )


__all__ = [
    "CollectionResult",
    "DynamicQrResult",
    "PaymentProvider",
    "SelcomMisconfiguredError",
    "get_selcom_client",
]
