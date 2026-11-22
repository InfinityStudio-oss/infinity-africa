"""Webhooks for payouts.

The Disbursement API emitted nothing at all, so every partner had to
poll, and anyone arriving from the Collections API would wait for a
callback that was never coming.

Two things these pin that are easy to get wrong:

* Only TERMINAL outcomes are announced. needs_reconciliation means "we
  do not know yet"; telling a partner about it invites exactly the retry
  that pays twice.
* The payload carries `environment`. There is one webhook URL per
  merchant with no sandbox/live separation, so a sandbox payout notifies
  the same endpoint a live one does, and a receiver that ignores the
  field will credit a customer for money that never moved.
"""

import uuid
from decimal import Decimal

import pytest

from app.services.payout_dispatch import apply_provider_result, release_parked_payout
from app.services.selcom_business.schemas import SelcomBusinessResult

CUR = "TZS"
def _result(status, *, reason=None):
    return SelcomBusinessResult(
        provider="mock_selcom_business",
        transaction_id="PRV-1",
        status=status,
        failure_reason=reason,
    )


def _world(fake_client, *, status="processing", **payout_overrides):
    merchant_id = uuid.uuid4()
    fake_client.seed(
        "merchants",
        {
            "id": str(merchant_id),
            "business_name": "Merchant",
            "merchant_code": "27413765",
            "status": "active",
            "webhook_url": "https://merchant.example.invalid/hooks",
        },
    )
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
            "beneficiary_id": str(uuid.uuid4()),
            "provider_reference": "PO-TESTREFERENCE01",
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


def _events(fake_client):
    return fake_client.table("webhook_events")._table.rows


def test_a_settled_payout_announces_success(fake_client):
    _merchant_id, payout = _world(fake_client)

    apply_provider_result(
        fake_client,
        payout=payout,
        result=_result("successful"),
    )

    events = _events(fake_client)
    assert [e["event_name"] for e in events] == ["payout.success"]
    body = events[0]["payload"]
    assert body["payout_id"] == payout["id"]
    assert body["total_debit"] == "1010.00"
    assert body["reference"] == "PO-TESTREFERENCE01"


def test_a_confirmed_failure_announces_failure(fake_client):
    _merchant_id, payout = _world(fake_client)

    apply_provider_result(
        fake_client,
        payout=payout,
        result=_result("failed", reason="Declined"),
    )

    assert [e["event_name"] for e in _events(fake_client)] == ["payout.failed"]


def test_an_unresolved_payout_announces_nothing(fake_client):
    """needs_reconciliation means we do not know. Telling a partner
    anything here invites the retry that pays twice."""
    _merchant_id, payout = _world(fake_client)

    apply_provider_result(
        fake_client,
        payout=payout,
        result=_result("processing"),
    )

    assert _events(fake_client) == []


def test_the_payload_says_which_environment_it_came_from(fake_client):
    """One webhook URL, no sandbox/live separation. A receiver that
    ignores this credits a customer for money that never moved."""
    _merchant_id, payout = _world(fake_client)

    apply_provider_result(
        fake_client,
        payout=payout,
        result=_result("successful"),
    )

    assert _events(fake_client)[0]["payload"]["environment"] == "sandbox"


def test_an_admin_release_tells_the_merchant_too(fake_client):
    """They have money back and a payout that will never complete.
    Finding that out by polling days later is not good enough."""
    _merchant_id, payout = _world(fake_client, status="needs_reconciliation")

    release_parked_payout(
        fake_client,
        payout_id=uuid.UUID(payout["id"]),
        reason="Confirmed with the provider that the request never arrived.",
        actor_id=uuid.uuid4(),
    )

    events = _events(fake_client)
    assert [e["event_name"] for e in events] == ["payout.failed"]
    assert events[0]["payload"]["failure_code"] == "released_by_admin"


def test_a_merchant_with_no_webhook_url_gets_nothing(fake_client):
    """Unchanged behaviour from every other event: no URL, no delivery,
    and certainly no error on the money path."""
    merchant_id, payout = _world(fake_client)
    fake_client.table("merchants").update({"webhook_url": None}).eq(
        "id", str(merchant_id)
    ).execute()

    apply_provider_result(
        fake_client,
        payout=payout,
        result=_result("successful"),
    )

    assert _events(fake_client) == []


def test_a_failed_webhook_never_unwinds_the_money(fake_client, monkeypatch):
    """The emit is a courier. If queueing throws, the settlement that
    already posted to the ledger must stand."""
    _merchant_id, payout = _world(fake_client)

    import app.services.payout_dispatch as module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("webhook table unavailable")

    monkeypatch.setattr(module, "enqueue_webhook_event", _boom)

    status = apply_provider_result(
        fake_client,
        payout=payout,
        result=_result("successful"),
    )

    assert status == "successful"
    balances = {
        a["purpose"]: Decimal(str(a["balance"]))
        for a in fake_client.table("ledger_accounts")._table.rows
    }
    assert balances["payout_reserved"] == Decimal(0)


@pytest.mark.parametrize("event_name", ["payout.success", "payout.failed", "payout.reversed"])
def test_every_new_event_name_is_in_the_migration(event_name):
    """The fake does not enforce the CHECK on webhook_events.event_name,
    so emitting an unlisted name passes every test above and raises an
    unhandled exception the first time it meets Postgres. This reads the
    migration."""
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[3]
        / "supabase"
        / "migrations"
        / "20261122090000_payout_webhook_events.sql"
    )
    assert f"'{event_name}'" in migration.read_text(encoding="utf-8")
