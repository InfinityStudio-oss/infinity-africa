"""Regression coverage for the 2026-08-23 live incident: a wallet-push
collection was marked "successful" and credited to the merchant wallet,
then Selcom actually reversed the underlying M-Pesa payment ("Payment
unsuccessful. You are trying to pay into your own till") — but nothing in
this codebase could act on that later signal, since
resolve_collection()'s idempotency guard treats any non-"processing"
collection as already resolved. See app/services/collections.py::
reverse_successful_collection() and app/services/checkout_reconciliation.py's
reversal routing in complete_checkout_collection_once() for the fix.

Uses the same real-fixture-setup pattern as test_checkout_reconciliation.py
(execute_wallet_push_for_payment_link() against a fake Selcom client, not
a hand-rolled collection row) so these tests exercise the true shape a
production collection has.
"""

import asyncio
import uuid
from decimal import Decimal

from app.config import get_settings
from app.services.checkout_reconciliation import complete_checkout_collection_once
from app.services.collections import (
    finalize_pending_review_collection,
    reverse_successful_collection,
)
from app.services.wallet_push import execute_wallet_push_for_payment_link
from tests.factories import create_merchant, make_merchant_member, seed_fraud_rules

WALLET_PAYMENT_PENDING_RESPONSE = {
    "reference": "0289999288",
    "resultcode": "111",
    "result": "PENDING",
    "message": "Request in progress.",
    "data": [],
}

CREATE_ORDER_SUCCESS_RESPONSE = {
    "reference": "S20690427372",
    "resultcode": "000",
    "result": "SUCCESS",
    "message": "Payment notification logged",
    "data": [{"payment_token": "TOKEN", "payment_gateway_url": "aHR0cHM6Ly9leGFtcGxlLmNvbS9wYXk=", "qr": "QR"}],
}

COMPLETED_KWARGS = {
    "payment_status": "COMPLETED",
    "result": "SUCCESS",
    "resultcode": "000",
    "reference": "S20690471578",
    "channel": "TIGOPESA",
    "raw_response": {"payment_status": "COMPLETED"},
}


class _FakeSelcomCheckoutClient:
    def __init__(self, *, credentials=None, order_response=None, payment_response=None):
        self._order_response = order_response or CREATE_ORDER_SUCCESS_RESPONSE
        self._payment_response = payment_response or WALLET_PAYMENT_PENDING_RESPONSE

    async def create_order_minimal(self, **kwargs):
        from app.services.selcom_checkout.parsing import (
            parse_create_order_minimal_response,
        )

        return parse_create_order_minimal_response(self._order_response)

    async def process_wallet_payment(self, **kwargs):
        from app.services.selcom_checkout.parsing import parse_wallet_payment_response

        return parse_wallet_payment_response(self._payment_response)


def _patch_checkout_client(monkeypatch):
    import app.services.checkout_orders as checkout_orders_module
    import app.services.wallet_push as wallet_push_module

    fake = _FakeSelcomCheckoutClient()
    monkeypatch.setattr(checkout_orders_module, "SelcomCheckoutHTTPClient", lambda **kwargs: fake)
    monkeypatch.setattr(wallet_push_module, "SelcomCheckoutHTTPClient", lambda **kwargs: fake)


def _seed_pending_collection(
    fake_client, monkeypatch, *, customer_phone="255747730270", with_invoice=False, **merchant_overrides
):
    _patch_checkout_client(monkeypatch)
    merchant = create_merchant(fake_client, **merchant_overrides)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Merchant Wallet (test)",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": "TZS",
            "balance": "0",
        },
    )
    payment_link = fake_client.seed(
        "payment_links",
        {
            "merchant_id": str(merchant_id),
            "amount": "1000.00",
            "currency": "TZS",
            "status": "ACTIVE",
            "allowed_payment_methods": ["STK_PUSH"],
            "public_slug": "test-slug-" + uuid.uuid4().hex[:8],
        },
    )
    invoice = None
    if with_invoice:
        invoice = fake_client.seed(
            "invoices",
            {
                "merchant_id": str(merchant_id),
                "payment_link_id": payment_link["id"],
                "invoice_number": "INV-TEST-" + uuid.uuid4().hex[:8],
                "total_amount": "1000.00",
                "amount_paid": "0",
                "status": "SENT",
            },
        )
    collection = asyncio.run(
        execute_wallet_push_for_payment_link(fake_client, payment_link=payment_link, buyer_phone=customer_phone)
    )
    assert collection["status"] == "processing"
    return collection, merchant_id, payment_link, invoice


def _complete(fake_client, collection, **overrides):
    kwargs = {**COMPLETED_KWARGS, "transid": collection["provider_transid"]}
    kwargs.update(overrides)
    return asyncio.run(
        complete_checkout_collection_once(fake_client, collection_id=uuid.UUID(collection["id"]), **kwargs)
    )


# --- the exact incident: credited, then reversed --------------------------------------


def test_reversed_after_completed_reverses_ledger_and_wallet(fake_client, monkeypatch):
    collection, _merchant_id, _payment_link, _invoice = _seed_pending_collection(fake_client, monkeypatch)

    resolved = _complete(fake_client, collection)
    assert resolved["status"] == "successful"
    wallet = fake_client.table("ledger_accounts")._table.rows[0]
    assert Decimal(str(wallet["balance"])) == Decimal("985.00")
    assert fake_client.table("payment_links")._table.rows[0]["status"] == "PAID"

    reversed_result = _complete(
        fake_client,
        collection,
        payment_status="REVERSED",
        result="FAIL",
        resultcode="651",
        raw_response={"payment_status": "REVERSED", "message": "Transaction reversed"},
    )

    assert reversed_result["status"] == "reversed"
    wallet = fake_client.table("ledger_accounts")._table.rows[0]
    assert Decimal(str(wallet["balance"])) == Decimal(0)  # clawed back, not left at 985
    assert fake_client.table("payment_links")._table.rows[0]["status"] == "ACTIVE"

    notification_types = {n["notification_type"] for n in fake_client.table("notifications")._table.rows}
    assert "collection_reversed" in notification_types


def test_reversal_reopens_linked_invoice_from_paid(fake_client, monkeypatch):
    collection, _merchant_id, _link, invoice = _seed_pending_collection(
        fake_client, monkeypatch, with_invoice=True
    )

    resolved = _complete(fake_client, collection)
    assert resolved["status"] == "successful"
    stored_invoice = fake_client.table("invoices")._table.rows[0]
    assert stored_invoice["id"] == invoice["id"]
    assert stored_invoice["status"] == "PAID"
    assert Decimal(str(stored_invoice["amount_paid"])) == Decimal("1000.00")

    reversed_result = _complete(
        fake_client,
        collection,
        payment_status="REVERSED",
        result="FAIL",
        resultcode="651",
        raw_response={"payment_status": "REVERSED"},
    )
    assert reversed_result["status"] == "reversed"

    stored_invoice = fake_client.table("invoices")._table.rows[0]
    assert stored_invoice["status"] == "SENT"  # reopened, not left PAID
    assert Decimal(str(stored_invoice["amount_paid"])) == Decimal(0)


def test_reversal_message_marker_triggers_reversal_even_with_ambiguous_status(fake_client, monkeypatch):
    """The live incident's own M-Pesa message ('Payment unsuccessful. You
    are trying to pay into your own till') is the kind of free-text
    reversal signal that may arrive without a clean payment_status —
    the message text alone must still trigger a real reversal."""
    collection, _merchant_id, _link, _invoice = _seed_pending_collection(fake_client, monkeypatch)
    _complete(fake_client, collection)

    reversed_result = _complete(
        fake_client,
        collection,
        payment_status="COMPLETED",
        result="FAIL",
        resultcode="651",
        raw_response={"message": "Payment unsuccessful. You are trying to pay into your own till"},
    )

    assert reversed_result["status"] == "reversed"
    wallet = fake_client.table("ledger_accounts")._table.rows[0]
    assert Decimal(str(wallet["balance"])) == Decimal(0)


def test_duplicate_reversal_signal_does_not_double_reverse(fake_client, monkeypatch):
    collection, _merchant_id, _link, _invoice = _seed_pending_collection(fake_client, monkeypatch)
    _complete(fake_client, collection)

    kwargs = {
        "payment_status": "REVERSED",
        "result": "FAIL",
        "resultcode": "651",
        "raw_response": {"payment_status": "REVERSED"},
    }
    first = _complete(fake_client, collection, **kwargs)
    second = _complete(fake_client, collection, **kwargs)

    assert first["status"] == "reversed"
    assert second["status"] == "reversed"
    wallet = fake_client.table("ledger_accounts")._table.rows[0]
    assert Decimal(str(wallet["balance"])) == Decimal(0)  # not driven negative by a repeat reversal


def test_reversal_with_insufficient_balance_marks_reversed_and_alerts_admin(fake_client, monkeypatch):
    """The merchant already withdrew the funds before the reversal
    arrived — the ledger's own atomic guard blocks the wallet from going
    negative, so the reversal can't fully claw back the money. The
    collection must still flip to 'reversed' (never keep claiming
    success) and an admin alert must be raised for manual recovery."""
    collection, _merchant_id, _link, _invoice = _seed_pending_collection(fake_client, monkeypatch)
    _complete(fake_client, collection)

    wallet_row = fake_client.table("ledger_accounts")._table.rows[0]
    wallet_row["balance"] = "0"  # simulate the merchant having already withdrawn the 985 credited

    reversed_result = reverse_successful_collection(
        fake_client, collection_id=uuid.UUID(collection["id"]), reason="Reversed by provider"
    )

    assert reversed_result["status"] == "reversed"
    admin_notifications = [
        n
        for n in fake_client.table("notifications")._table.rows
        if n["notification_type"] == "collection_reversed" and n["recipient_type"] == "admin"
    ]
    assert admin_notifications, "expected an admin notification about the reversal"
    assert "manual recovery" in admin_notifications[0]["body"].lower()


def test_reversing_an_already_reversed_collection_is_a_noop(fake_client, monkeypatch):
    collection, _merchant_id, _link, _invoice = _seed_pending_collection(fake_client, monkeypatch)
    _complete(fake_client, collection)
    reverse_successful_collection(fake_client, collection_id=uuid.UUID(collection["id"]), reason="first")
    result = reverse_successful_collection(fake_client, collection_id=uuid.UUID(collection["id"]), reason="second")
    assert result["status"] == "reversed"
    wallet = fake_client.table("ledger_accounts")._table.rows[0]
    assert Decimal(str(wallet["balance"])) == Decimal(0)


# --- self-payment / own-till ---------------------------------------------------------
#
# The rule fires on a payer phone matching the merchant's own contact
# phone. Whether that HOLDS the funds or merely records an alert now
# depends on the amount: see Settings.self_payment_hold_above_amount for
# why, and _hold_every_self_payment below for the original behaviour.
# These fixtures create a 1000 collection, so the threshold each test
# sets is what decides which path it takes.


def _hold_above(monkeypatch, amount):
    monkeypatch.setenv("SELF_PAYMENT_HOLD_ABOVE_AMOUNT", str(amount))
    get_settings.cache_clear()


def test_self_payment_phone_match_holds_pending_review_not_credited(fake_client, monkeypatch):
    _hold_above(monkeypatch, 500)  # the 1000 collection below exceeds this
    seed_fraud_rules(fake_client, "SELF_PAYMENT_OWN_TILL")
    collection, _merchant_id, _link, _invoice = _seed_pending_collection(
        fake_client, monkeypatch, customer_phone="255747730270", contact_phone="255747730270"
    )

    resolved = _complete(fake_client, collection)

    assert resolved["status"] == "pending_review"
    wallet = fake_client.table("ledger_accounts")._table.rows[0]
    assert Decimal(str(wallet["balance"])) == Decimal(0)
    assert fake_client.table("payment_links")._table.rows[0]["status"] == "ACTIVE"

    alerts = fake_client.table("fraud_alerts")._table.rows
    assert any(a["rule_code"] == "SELF_PAYMENT_OWN_TILL" for a in alerts)


def test_self_payment_holds_linked_invoice_from_being_marked_paid(fake_client, monkeypatch):
    _hold_above(monkeypatch, 500)
    seed_fraud_rules(fake_client, "SELF_PAYMENT_OWN_TILL")
    collection, _merchant_id, _link, invoice = _seed_pending_collection(
        fake_client,
        monkeypatch,
        customer_phone="255747730270",
        contact_phone="255747730270",
        with_invoice=True,
    )

    resolved = _complete(fake_client, collection)

    assert resolved["status"] == "pending_review"
    stored_invoice = fake_client.table("invoices")._table.rows[0]
    assert stored_invoice["id"] == invoice["id"]
    assert stored_invoice["status"] == "SENT"  # not PAID — held pending review
    assert Decimal(str(stored_invoice["amount_paid"])) == Decimal(0)


def test_different_phone_from_merchant_credits_normally(fake_client, monkeypatch):
    seed_fraud_rules(fake_client, "SELF_PAYMENT_OWN_TILL")
    collection, _merchant_id, _link, _invoice = _seed_pending_collection(
        fake_client, monkeypatch, customer_phone="255747730270", contact_phone="255700000000"
    )

    resolved = _complete(fake_client, collection)

    assert resolved["status"] == "successful"
    wallet = fake_client.table("ledger_accounts")._table.rows[0]
    assert Decimal(str(wallet["balance"])) == Decimal("985.00")


def test_finalizing_pending_review_collection_credits_it_exactly_once(fake_client, monkeypatch):
    _hold_above(monkeypatch, 500)
    seed_fraud_rules(fake_client, "SELF_PAYMENT_OWN_TILL")
    collection, _merchant_id, _link, _invoice = _seed_pending_collection(
        fake_client, monkeypatch, customer_phone="255747730270", contact_phone="255747730270"
    )
    resolved = _complete(fake_client, collection)
    assert resolved["status"] == "pending_review"

    finalized = finalize_pending_review_collection(fake_client, collection_id=uuid.UUID(collection["id"]))
    assert finalized["status"] == "successful"
    wallet = fake_client.table("ledger_accounts")._table.rows[0]
    assert Decimal(str(wallet["balance"])) == Decimal("985.00")
    assert fake_client.table("payment_links")._table.rows[0]["status"] == "PAID"

    # Finalizing twice must not double-credit.
    finalize_pending_review_collection(fake_client, collection_id=uuid.UUID(collection["id"]))
    wallet = fake_client.table("ledger_accounts")._table.rows[0]
    assert Decimal(str(wallet["balance"])) == Decimal("985.00")


def test_admin_clearing_self_payment_alert_finalizes_collection(fake_client, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app
    from tests.factories import TEST_JWT_SECRET, auth_headers, make_super_admin

    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    # Below this the collection would be credited outright and there would
    # be nothing for an admin to clear.
    monkeypatch.setenv("SELF_PAYMENT_HOLD_ABOVE_AMOUNT", "500")
    get_settings.cache_clear()

    seed_fraud_rules(fake_client, "SELF_PAYMENT_OWN_TILL")
    collection, _merchant_id, _link, _invoice = _seed_pending_collection(
        fake_client, monkeypatch, customer_phone="255747730270", contact_phone="255747730270"
    )
    resolved = _complete(fake_client, collection)
    assert resolved["status"] == "pending_review"

    alert = next(
        a for a in fake_client.table("fraud_alerts")._table.rows if a["rule_code"] == "SELF_PAYMENT_OWN_TILL"
    )
    admin_user_id = uuid.uuid4()
    make_super_admin(fake_client, admin_user_id)

    client = TestClient(app)
    response = client.patch(
        f"/v1/admin/risk-alerts/{alert['id']}/status",
        headers=auth_headers(admin_user_id),
        json={"status": "CLEARED", "note": "Confirmed legitimate"},
    )

    assert response.status_code == 200, response.text
    wallet = fake_client.table("ledger_accounts")._table.rows[0]
    assert Decimal(str(wallet["balance"])) == Decimal("985.00")
    assert fake_client.table("collections")._table.rows[0]["status"] == "successful"

    get_settings.cache_clear()


# --- self-payment below the hold threshold: credited, still recorded ------------------


def test_a_small_self_payment_is_credited_rather_than_held(fake_client, monkeypatch):
    """The honest case this cost. Testing a payment from your own phone is
    the first thing any integrator does, and an unconditional hold left
    their money at pending_review with nothing explaining why — a partner
    hit exactly this on 2026-10-01 and concluded the API was broken."""
    _hold_above(monkeypatch, 50000)  # the 1000 collection below is well under
    seed_fraud_rules(fake_client, "SELF_PAYMENT_OWN_TILL")
    collection, _merchant_id, _link, _invoice = _seed_pending_collection(
        fake_client, monkeypatch, customer_phone="255747730270", contact_phone="255747730270"
    )

    resolved = _complete(fake_client, collection)

    assert resolved["status"] == "successful"
    wallet = fake_client.table("ledger_accounts")._table.rows[0]
    assert Decimal(str(wallet["balance"])) == Decimal("985.00")


def test_a_credited_self_payment_still_raises_an_alert(fake_client, monkeypatch):
    """Not holding is not the same as not noticing. A merchant cycling
    money through their own account must still be visible to an admin."""
    _hold_above(monkeypatch, 50000)
    seed_fraud_rules(fake_client, "SELF_PAYMENT_OWN_TILL")
    collection, _merchant_id, _link, _invoice = _seed_pending_collection(
        fake_client, monkeypatch, customer_phone="255747730270", contact_phone="255747730270"
    )

    _complete(fake_client, collection)

    alerts = [a for a in fake_client.table("fraud_alerts")._table.rows if a["rule_code"] == "SELF_PAYMENT_OWN_TILL"]
    assert len(alerts) == 1
    assert alerts[0]["metadata"]["held"] is False
    assert "Held for review" not in alerts[0]["reason"]


def test_a_large_self_payment_is_still_held(fake_client, monkeypatch):
    """The threshold moves where the line sits; it does not remove it.
    Paying in, withdrawing, then disputing the original mobile money
    transaction only pays off at size, which is what still gets held."""
    _hold_above(monkeypatch, 500)
    seed_fraud_rules(fake_client, "SELF_PAYMENT_OWN_TILL")
    collection, _merchant_id, _link, _invoice = _seed_pending_collection(
        fake_client, monkeypatch, customer_phone="255747730270", contact_phone="255747730270"
    )

    resolved = _complete(fake_client, collection)

    assert resolved["status"] == "pending_review"
    assert Decimal(str(fake_client.table("ledger_accounts")._table.rows[0]["balance"])) == Decimal(0)
    alerts = [a for a in fake_client.table("fraud_alerts")._table.rows if a["rule_code"] == "SELF_PAYMENT_OWN_TILL"]
    assert alerts[0]["metadata"]["held"] is True


def test_a_zero_threshold_holds_every_self_payment(fake_client, monkeypatch):
    """The switch back to the original behaviour, for if this turns out to
    have been the wrong trade."""
    _hold_above(monkeypatch, 0)
    seed_fraud_rules(fake_client, "SELF_PAYMENT_OWN_TILL")
    collection, _merchant_id, _link, _invoice = _seed_pending_collection(
        fake_client, monkeypatch, customer_phone="255747730270", contact_phone="255747730270"
    )

    assert _complete(fake_client, collection)["status"] == "pending_review"


def test_the_rule_still_ignores_a_different_payer_entirely(fake_client, monkeypatch):
    """No alert at all for an ordinary customer — the threshold must not
    turn this into something that fires on every payment."""
    _hold_above(monkeypatch, 50000)
    seed_fraud_rules(fake_client, "SELF_PAYMENT_OWN_TILL")
    collection, _merchant_id, _link, _invoice = _seed_pending_collection(
        fake_client, monkeypatch, customer_phone="255747730270", contact_phone="255700000000"
    )

    assert _complete(fake_client, collection)["status"] == "successful"
    assert fake_client.table("fraud_alerts")._table.rows == []
