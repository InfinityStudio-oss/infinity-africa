"""Shared result types every Selcom checkout/collections client
implementation (mock_client.py, live_client.py) returns — the vocabulary
app/services/collections.py is written against, regardless of which client
is active. See client.py for the PaymentProvider interface these types
appear in.

Withdrawals/disbursements are a different Selcom product with their own
result type — see app/services/selcom_business/schemas.py.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ProviderStatus = Literal["successful", "failed", "processing"]


class CollectionResult(BaseModel):
    provider: str
    provider_reference: str
    status: ProviderStatus
    failure_reason: str | None = None
    # Provider detail carried through so resolve_collection can normalize a
    # failure into a stable reason code (app/services/failure_reasons.py)
    # instead of storing the provider's own prose. Optional: the older
    # app/services/selcom/ paths never had these, and a missing value just
    # resolves to unknown_provider_error.
    provider_payment_status: str | None = None
    provider_resultcode: str | None = None


class DynamicQrResult(BaseModel):
    provider: str
    provider_reference: str
    qr_payload: str
    qr_expires_at: datetime
