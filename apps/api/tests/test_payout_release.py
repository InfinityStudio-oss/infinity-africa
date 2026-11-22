"""Giving back the reserve on a payout stuck in reconciliation.

This is the most dangerous operation in the payout code. Everything else
that releases funds does so because the provider said it did not pay;
this releases on a human's judgement. If that judgement is wrong, the
money went out AND went back to the merchant, and the platform covers
the difference.

It exists because the alternative was worse: a payout can park forever —
ours did, against a sandbox endpoint that 404s — and the only way out
was editing the database by hand, with no validation, no audit entry and
no record of who decided.

So the tests are mostly about what it REFUSES.
"""

import uuid
from decimal import Decimal

import pytest

from app.core.errors import ConflictError, NotFoundError
from app.services.payout_dispatch import release_parked_payout

CUR = "TZS"


def _world(fake_client, *, status="needs_reconciliation", **payout_overrides):
    merchant_id = uuid.uuid4()
    transaction_id = fake_client.seed(
        "transactions",
        {
            "merchant_id": str(merchant_id),
            "type": "payout",
            "status": "processing",
            "currency": CUR,
            "gross_amount": "1010.00",
            "net_amount": "1000.00",
        },
    )["id"]
    payout = fake_client.seed(
        "payouts",
        {
            "merchant_id": str(merchant_id),
            "environment": "sandbox",
            "status": status,
            "amount": "1000.00",
            "fee_amount": "10.00",
            "total_debit": "1010.00",
            "currency": CUR,
            "provider_reference": f"PO-{uuid.uuid4().hex[:12].upper()}",
            "failure_code": "provider_unreachable",
            **payout_overrides,
        },
    )
    fake_client.table("transactions").update({"payout_id": payout["id"]}).eq(
        "id", transaction_id
    ).execute()
    for purpose, balance in (("payout_available", "8990.00"), ("payout_reserved", "1010.00")):
        fake_client.seed(
            "ledger_accounts",
            {
                "merchant_id": str(merchant_id),
                "name": f"{purpose} (test)",
                "account_type": "liability",
                "purpose": purpose,
                "currency": CUR,
                "environment": "sandbox",
                "balance": balance,
            },
        )
    return merchant_id, payout


def _balances(fake_client, merchant_id):
    return {
        a["purpose"]: Decimal(str(a["balance"]))
        for a in fake_client.table("ledger_accounts")._table.rows
        if a.get("merchant_id") == str(merchant_id)
    }


def test_a_parked_payout_gives_its_reserve_back(fake_client):
    merchant_id, payout = _world(fake_client)

    release_parked_payout(
        fake_client,
        payout_id=uuid.UUID(payout["id"]),
        reason="Dispatched at a sandbox endpoint that 404s; the provider never saw it.",
        actor_id=uuid.uuid4(),
    )

    after = _balances(fake_client, merchant_id)
    assert after["payout_available"] == Decimal("10000.00")
    assert after["payout_reserved"] == Decimal("0")


def test_a_processing_payout_is_refused(fake_client):
    """It may be at the provider this second."""
    _merchant_id, payout = _world(fake_client, status="processing")

    with pytest.raises(ConflictError):
        release_parked_payout(
            fake_client,
            payout_id=uuid.UUID(payout["id"]),
            reason="I think it failed, probably, more or less.",
            actor_id=uuid.uuid4(),
        )


def test_a_payout_the_provider_acknowledged_is_refused(fake_client):
    """A provider_transid means they took it. It may well have been paid,
    and that is resolved by asking them - never by assuming."""
    _merchant_id, payout = _world(fake_client, provider_transid="SELCOM-123")

    with pytest.raises(ConflictError) as excinfo:
        release_parked_payout(
            fake_client,
            payout_id=uuid.UUID(payout["id"]),
            reason="Support says it did not go through, honest.",
            actor_id=uuid.uuid4(),
        )
    assert "acknowledged" in str(excinfo.value).lower()


def test_a_raw_response_also_blocks_release(fake_client):
    """The other half of the same guard: a stored provider response means
    they answered, whatever the answer was."""
    _merchant_id, payout = _world(fake_client, provider_raw_response={"status": "PENDING"})

    with pytest.raises(ConflictError):
        release_parked_payout(
            fake_client,
            payout_id=uuid.UUID(payout["id"]),
            reason="Looks stuck to me, releasing it now.",
            actor_id=uuid.uuid4(),
        )


def test_releasing_twice_does_not_pay_the_merchant_twice(fake_client):
    """The compare-and-set. Without it a double click would post the
    reserve back twice and invent 1,010 shillings."""
    merchant_id, payout = _world(fake_client)
    reason = "Confirmed with Selcom that the request never reached them."

    release_parked_payout(
        fake_client, payout_id=uuid.UUID(payout["id"]), reason=reason, actor_id=uuid.uuid4()
    )
    with pytest.raises(ConflictError):
        release_parked_payout(
            fake_client, payout_id=uuid.UUID(payout["id"]), reason=reason, actor_id=uuid.uuid4()
        )

    assert _balances(fake_client, merchant_id)["payout_available"] == Decimal("10000.00")


def test_an_unknown_payout_is_a_404(fake_client):
    with pytest.raises(NotFoundError):
        release_parked_payout(
            fake_client,
            payout_id=uuid.uuid4(),
            reason="Releasing a payout that does not exist.",
            actor_id=uuid.uuid4(),
        )


def test_the_release_is_audited_with_the_reason(fake_client):
    """The reason is the only record of the judgement being made."""
    _merchant_id, payout = _world(fake_client)
    reason = "Selcom confirmed by email that the request never reached them."

    release_parked_payout(
        fake_client, payout_id=uuid.UUID(payout["id"]), reason=reason, actor_id=uuid.uuid4()
    )

    entries = [
        r
        for r in fake_client.table("audit_logs")._table.rows
        if r.get("action") == "payout.reserve_released"
    ]
    assert len(entries) == 1
    assert entries[0]["metadata"]["reason"] == reason
    assert entries[0]["metadata"]["total_debit"] == "1010.00"
