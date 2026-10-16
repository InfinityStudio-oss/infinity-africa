"""The merchant SMS, through the real payment path.

tests/test_sms_collection_alerts.py exercises enqueue_collection_alert
directly, which proves the message is composed correctly from values
handed to it. It cannot prove that resolve_collection hands it the right
values - and that seam is where a wrong closing balance would actually
come from, silently, long after anybody looked at this code.

So these run a payment end to end against the fake Supabase client: a
payment link, a wallet push, a provider completion, a real ledger
posting. The number the merchant is texted is then checked against the
wallet balance the posting actually produced.

The same harness as tests/test_collection_reversal.py, which covers the
2026-08-23 credit-then-reverse incident over this identical path.
"""

import asyncio
import uuid
from decimal import Decimal

import pytest

from app.config import get_settings
from app.services.checkout_reconciliation import complete_checkout_collection_once
from app.services.collections import finalize_pending_review_collection
from app.services.wallet_push import execute_wallet_push_for_payment_link
from tests.factories import create_merchant, make_merchant_member

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
    "data": [],
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
    async def create_order_minimal(self, **kwargs):
        from app.services.selcom_checkout.parsing import parse_create_order_minimal_response

        return parse_create_order_minimal_response(CREATE_ORDER_SUCCESS_RESPONSE)

    async def process_wallet_payment(self, **kwargs):
        from app.services.selcom_checkout.parsing import parse_wallet_payment_response

        return parse_wallet_payment_response(WALLET_PAYMENT_PENDING_RESPONSE)


@pytest.fixture(autouse=True)
def _sms_on(monkeypatch):
    monkeypatch.setenv("OASIS_SMS_ENABLED", "true")
    monkeypatch.setenv("OASIS_SMS_SENDER_ID", "INFINITYPAY")
    monkeypatch.setenv("OASIS_SMS_API_KEY", "test-key-not-real")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _checkout(monkeypatch):
    import app.services.checkout_orders as checkout_orders_module
    import app.services.wallet_push as wallet_push_module

    fake = _FakeSelcomCheckoutClient()
    monkeypatch.setattr(checkout_orders_module, "SelcomCheckoutHTTPClient", lambda **kwargs: fake)
    monkeypatch.setattr(wallet_push_module, "SelcomCheckoutHTTPClient", lambda **kwargs: fake)


def _seed(fake_client, *, sms_enabled=True, merchant_phone="255713000001", opening="0"):
    # A webhook URL on purpose: enqueue_webhook_event no-ops without one,
    # so the "SMS failure does not block the merchant webhook" assertion
    # below would otherwise pass against a merchant who was never going
    # to receive a webhook either way.
    merchant = create_merchant(
        fake_client, contact_phone=merchant_phone, webhook_url="https://merchant.example/hook"
    )
    merchant_id = uuid.UUID(merchant["id"])
    make_merchant_member(fake_client, merchant_id, uuid.uuid4(), "MERCHANT_ADMIN")
    fake_client.seed(
        "merchant_notification_settings",
        {
            "merchant_id": str(merchant_id),
            "collection_sms_enabled": sms_enabled,
            "announcement_sms_enabled": True,
        },
    )
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Merchant Wallet (test)",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": "TZS",
            "balance": opening,
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
            "public_slug": "sms-test-" + uuid.uuid4().hex[:8],
        },
    )
    collection = asyncio.run(
        execute_wallet_push_for_payment_link(
            fake_client, payment_link=payment_link, buyer_phone="255747730270"
        )
    )
    assert collection["status"] == "processing"
    return collection, merchant_id


def _complete(fake_client, collection, **overrides):
    kwargs = {**COMPLETED_KWARGS, "transid": collection["provider_transid"], **overrides}
    return asyncio.run(
        complete_checkout_collection_once(
            fake_client, collection_id=uuid.UUID(collection["id"]), **kwargs
        )
    )


def _sms(fake_client):
    return fake_client.table("sms_messages")._table.rows


def _wallet_balance(fake_client):
    wallet = next(
        r
        for r in fake_client.table("ledger_accounts")._table.rows
        if r.get("purpose") == "merchant_wallet"
    )
    return Decimal(str(wallet["balance"]))


# --- the seam ----------------------------------------------------------


def test_a_real_payment_texts_the_merchant_the_balance_it_produced(fake_client):
    """The whole point of this file.

    The wallet goes 0 -> 985.00 on a 1000 payment with a 15 fee. The SMS
    must quote 985, read from the ledger posting - not recomputed, not
    looked up afterwards.
    """
    collection, _merchant_id = _seed(fake_client)

    resolved = _complete(fake_client, collection)

    assert resolved["status"] == "successful"
    balance = _wallet_balance(fake_client)
    assert balance == Decimal("985.00")

    message = _sms(fake_client)[0]
    assert message["status"] == "queued"
    assert message["closing_balance"] == "985.00"
    assert f"Salio baada ya muamala: TZS {balance:,.0f}." in message["body"]


def test_the_texted_figures_match_the_transaction_row(fake_client):
    collection, _merchant_id = _seed(fake_client)

    _complete(fake_client, collection)

    transaction = fake_client.table("transactions")._table.rows[0]
    message = _sms(fake_client)[0]
    assert message["gross_amount"] == transaction["gross_amount"]
    assert message["fee_amount"] == transaction["fee_amount"]
    assert message["net_amount"] == transaction["net_amount"]
    assert message["reference"] == transaction["reference"]
    assert transaction["reference"] in message["body"]


def test_the_balance_is_this_payments_not_the_wallet_total(fake_client):
    """A merchant who already had money must be told the balance after
    *this* payment. If the code ever read the wallet instead of the
    posting, a wallet opening at 0 would hide it - so this one opens at
    50,000."""
    collection, _merchant_id = _seed(fake_client, opening="50000.00")

    _complete(fake_client, collection)

    message = _sms(fake_client)[0]
    assert message["closing_balance"] == "50985.00"
    assert "Salio baada ya muamala: TZS 50,985." in message["body"]


def test_a_second_payment_does_not_change_the_first_message(fake_client):
    """The frozen snapshot, over the real path. The first merchant alert
    must still say 985 after the wallet has moved on."""
    first, merchant_id = _seed(fake_client)
    _complete(fake_client, first)
    first_body = _sms(fake_client)[0]["body"]

    second_link = fake_client.seed(
        "payment_links",
        {
            "merchant_id": str(merchant_id),
            "amount": "2000.00",
            "currency": "TZS",
            "status": "ACTIVE",
            "allowed_payment_methods": ["STK_PUSH"],
            "public_slug": "sms-test-" + uuid.uuid4().hex[:8],
        },
    )
    second = asyncio.run(
        execute_wallet_push_for_payment_link(
            fake_client, payment_link=second_link, buyer_phone="255747730270"
        )
    )
    _complete(fake_client, second)

    assert _wallet_balance(fake_client) > Decimal("985.00")
    assert _sms(fake_client)[0]["body"] == first_body
    assert "985" in first_body


# --- the payer is never the recipient ----------------------------------


def test_the_payers_number_is_never_the_destination(fake_client):
    """255747730270 pays; 255713000001 is the merchant. Over the real
    path, where the payer's number is on the collection row."""
    collection, _merchant_id = _seed(fake_client, merchant_phone="255713000001")

    _complete(fake_client, collection)

    message = _sms(fake_client)[0]
    assert message["recipient_phone"] == "255713000001"
    assert "255747730270" not in message["recipient_phone"]
    assert "255747730270" not in message["body"]


# --- only a real success, and only once --------------------------------


def test_a_failed_payment_texts_nobody(fake_client):
    collection, _merchant_id = _seed(fake_client)

    _complete(
        fake_client,
        collection,
        payment_status="FAILED",
        result="FAIL",
        resultcode="911",
        raw_response={"payment_status": "FAILED"},
    )

    assert _sms(fake_client) == []


def test_a_still_processing_payment_texts_nobody(fake_client):
    """An accepted push is not a payment. This is the mistake the brief
    calls out by name."""
    collection, _merchant_id = _seed(fake_client)

    assert _sms(fake_client) == [], "the push itself must not queue an alert"


def test_the_callback_and_the_sweep_together_produce_one_alert(fake_client):
    """Both signals routinely arrive for the same collection. The second
    is a no-op for the money, and must be a no-op for the SMS too."""
    collection, _merchant_id = _seed(fake_client)

    _complete(fake_client, collection)
    _complete(fake_client, collection)

    assert len(_sms(fake_client)) == 1
    assert _wallet_balance(fake_client) == Decimal("985.00")


def test_a_held_payment_alerts_when_a_super_admin_releases_it(fake_client):
    """The second crediting path: finalize_pending_review_collection. A
    held payment is a real payment once released."""
    collection, merchant_id = _seed(fake_client)
    collection_id = uuid.UUID(collection["id"])
    fake_client.table("collections").update({"status": "pending_review"}).eq(
        "id", collection["id"]
    ).execute()

    finalize_pending_review_collection(fake_client, collection_id=collection_id)

    messages = _sms(fake_client)
    assert len(messages) == 1
    assert messages[0]["closing_balance"] == "985.00"


# --- SMS must never be able to hurt the payment ------------------------


def test_an_sms_failure_does_not_affect_the_payment_or_the_webhook(fake_client, monkeypatch):
    """The isolation the brief asks for, demonstrated rather than
    asserted: break the SMS enqueue outright and confirm the money, the
    payment link and the merchant webhook are all untouched."""
    import app.services.collections as collections_module

    def _explode(*_args, **_kwargs):
        raise RuntimeError("sms subsystem down")

    monkeypatch.setattr(collections_module, "enqueue_collection_alert", _explode)
    collection, _merchant_id = _seed(fake_client)

    resolved = _complete(fake_client, collection)

    assert resolved["status"] == "successful"
    assert _wallet_balance(fake_client) == Decimal("985.00")
    assert fake_client.table("payment_links")._table.rows[0]["status"] == "PAID"
    events = [
        e
        for e in fake_client.table("webhook_events")._table.rows
        if e["event_name"] == "collection.success"
    ]
    assert len(events) == 1, "the merchant webhook must still be queued"


def test_sms_being_off_changes_nothing_about_the_payment(fake_client, monkeypatch):
    monkeypatch.setenv("OASIS_SMS_ENABLED", "false")
    get_settings.cache_clear()
    collection, _merchant_id = _seed(fake_client)

    resolved = _complete(fake_client, collection)

    assert resolved["status"] == "successful"
    assert _wallet_balance(fake_client) == Decimal("985.00")
    assert _sms(fake_client) == []
