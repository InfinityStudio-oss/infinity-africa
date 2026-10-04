"""Simulates the Selcom Business Disbursement API — local development
only. Reachable exclusively when SELCOM_BUSINESS_MODE=mock (see
client.py::get_selcom_business_client()); never constructed when the mode
is "sandbox" or "live". Mirrors app/services/selcom/mock_client.py's shape
and reuses the same MOCK_PROVIDER_FAILURE_RATE/MOCK_PROVIDER_LATENCY_SECONDS
settings rather than inventing a second set of mock-tuning knobs.
"""

import asyncio
import random
import uuid

from app.services.selcom_business.schemas import SelcomBusinessResult

_PROVIDER_NAME = "mock_selcom_business"


class MockSelcomBusinessClient:
    def __init__(self, *, failure_rate: float = 0.1, latency_seconds: float = 0.3):
        self.failure_rate = failure_rate
        self.latency_seconds = latency_seconds

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
    ) -> SelcomBusinessResult:
        await asyncio.sleep(self.latency_seconds)

        if random.random() < self.failure_rate:
            return SelcomBusinessResult(
                provider=_PROVIDER_NAME,
                transaction_id=trans_id,
                status="failed",
                failure_reason=random.choice(
                    ["Invalid recipient account", "Provider network timeout", "Payout limit exceeded"]
                ),
            )

        return SelcomBusinessResult(
            provider=_PROVIDER_NAME,
            transaction_id=trans_id,
            status="successful",
            receipt=f"MOCK-RECEIPT-{uuid.uuid4().hex[:10].upper()}",
        )

    async def query_transaction(self, *, trans_id: str) -> SelcomBusinessResult:
        await asyncio.sleep(self.latency_seconds)
        return SelcomBusinessResult(provider=_PROVIDER_NAME, transaction_id=trans_id, status="successful")

    async def balance(self, *, account_number: str) -> dict:
        """A fixed, obviously-round float figure.

        Deliberately large enough that mock payouts are never blocked by
        it, and deliberately not a number anyone would mistake for a real
        balance. Only reachable when SELCOM_BUSINESS_MODE=mock.
        """
        await asyncio.sleep(self.latency_seconds)
        return {
            "success": True,
            "result": "SUCCESS",
            "resultcode": "000",
            "data": {"account_number": account_number, "balance": "1000000.00", "currency": "TZS"},
        }

    async def account_lookup(
        self,
        *,
        recipient_fi_code: str,
        recipient_account: str,
        trans_id: str,
        amount: str | None = None,
    ) -> dict:
        """A deterministic stand-in shaped like a real Selcom envelope.

        The name is deliberately obviously fake. This runs only when
        SELCOM_BUSINESS_MODE=mock, which is never production, and a
        plausible-looking invented name on a withdrawal confirmation is
        exactly the thing that must not be mistaken for a verified one.
        """
        await asyncio.sleep(self.latency_seconds)
        return {
            "success": True,
            "result": "SUCCESS",
            "resultcode": "000",
            "data": {
                "accountName": f"MOCK ACCOUNT HOLDER ({recipient_account[-4:]})",
                "account": recipient_account,
                "bank": recipient_fi_code,
            },
        }
