import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


class TransactionResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    reference: str
    provider_reference: str | None = None
    type: str
    method: str
    collection_id: uuid.UUID | None = None
    disbursement_id: uuid.UUID | None = None
    gross_amount: Decimal
    fee_amount: Decimal
    net_amount: Decimal
    currency: str
    status: str
    # Merchant-wallet balance snapshot around this transaction's most recent
    # ledger posting, and that posting's direction — null for transactions
    # created before this column existed, or with no wallet-affecting leg.
    # Never computed/guessed here: null means "not available", shown as
    # such, not backfilled with a derived number.
    balance_before: Decimal | None = None
    balance_after: Decimal | None = None
    direction: str | None = None
    # The customer who paid, resolved through collection_id rather than
    # stored here — see app/services/customer_lookup.py. Null for withdrawals
    # (no paying customer) and QR scans (no phone captured), never guessed.
    customer_phone: str | None = None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
