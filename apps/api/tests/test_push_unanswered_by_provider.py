"""A push Selcom never answers must still leave a collection behind.

From production, 2026-10-19. Selcom slowed down and **30 payment starts
across seven merchants** timed out after about 33 seconds each - GodyNet,
UTETE INTERNET, Quicknet, Kitonga_WiFi, KILUNGULE SUPER WiFi, BBTECH and
MAXTON'S WIFI. 4.7% of that day's API requests, against 0.1% two days
earlier.

The order of operations is what made it dangerous:

    create order (Selcom)     -> succeeded, order exists on their side
    process_wallet_payment    -> timed out, raised
    insert_collection         -> never reached

So the exception escaped the request, the partner got a 502, and we were
left holding **37 Selcom orders with no collection row**. Reconciliation
sweeps collections, not orders, so nothing would ever ask Selcom what
became of them. The push is the call that sends the prompt, so a timeout
on it means we do not know whether the customer was asked to pay.

Nobody lost money that day - all 37 were still `created`. That was luck.
A customer who approved a prompt for an order we were not tracking would
have paid into silence: no wallet credit, no webhook, no record.

The fix records the ambiguity instead of losing it. These tests hold the
property that matters: **whatever Selcom does or does not say, a
collection row exists afterwards**, linked to the order, in a state
reconciliation will chase.
"""

import asyncio
import uuid

import pytest

from app.config import get_settings
from app.services.selcom_checkout.client import SelcomCheckoutError
from app.services.wallet_push import execute_wallet_push_for_payment_link
from tests.factories import create_merchant

CREATE_ORDER_OK = {
    "reference": "S20690427372",
    "resultcode": "000",
    "result": "SUCCESS",
    "message": "Payment notification logged",
    "data": [],
}
PUSH_PENDING = {
    "reference": "0289999288",
    "resultcode": "111",
    "result": "PENDING",
    "message": "Request in progress.",
    "data": [],
}


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret-do-not-use")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _Client:
    """A Selcom that creates the order, then fails the push - exactly the
    shape of the 2026-10-19 incident."""

    def __init__(self, push_error: Exception | None):
        self._push_error = push_error

    async def create_order_minimal(self, **kwargs):
        from app.services.selcom_checkout.parsing import parse_create_order_minimal_response

        return parse_create_order_minimal_response(CREATE_ORDER_OK)

    async def process_wallet_payment(self, **kwargs):
        if self._push_error:
            raise self._push_error
        from app.services.selcom_checkout.parsing import parse_wallet_payment_response

        return parse_wallet_payment_response(PUSH_PENDING)


def _patch(monkeypatch, push_error):
    import app.services.checkout_orders as orders_module
    import app.services.wallet_push as push_module

    client = _Client(push_error)
    monkeypatch.setattr(orders_module, "SelcomCheckoutHTTPClient", lambda **kw: client)
    monkeypatch.setattr(push_module, "SelcomCheckoutHTTPClient", lambda **kw: client)


def _link(fake_client):
    merchant = create_merchant(fake_client)
    return fake_client.seed(
        "payment_links",
        {
            "merchant_id": merchant["id"],
            "amount": "1000.00",
            "currency": "TZS",
            "status": "ACTIVE",
            "allowed_payment_methods": ["STK_PUSH"],
            "public_slug": "unanswered-" + uuid.uuid4().hex[:8],
        },
    )


def _push(fake_client, link):
    return asyncio.run(
        execute_wallet_push_for_payment_link(
            fake_client, payment_link=link, buyer_phone="255747730270"
        )
    )


# --- the incident ------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        SelcomCheckoutError("Could not reach Selcom Checkout (ReadTimeout)"),
        SelcomCheckoutError("Could not reach Selcom Checkout (ConnectError)"),
    ],
)
def test_a_push_selcom_never_answers_still_records_a_collection(fake_client, monkeypatch, error):
    """The property the whole file exists for. Before the fix this raised
    and wrote nothing."""
    _patch(monkeypatch, error)
    link = _link(fake_client)

    collection = _push(fake_client, link)

    assert collection is not None
    assert fake_client.table("collections")._table.rows, "the order would be untracked"


def test_the_collection_is_linked_to_the_order_so_reconciliation_finds_it(
    fake_client, monkeypatch
):
    """An order with no collection is invisible: the sweep reads
    collections. The link is what makes the ambiguity recoverable."""
    _patch(monkeypatch, SelcomCheckoutError("ReadTimeout"))
    link = _link(fake_client)

    collection = _push(fake_client, link)

    assert collection["checkout_order_id"], "unsweepable without this"
    assert collection["status"] == "processing"


def test_an_unanswered_push_is_never_recorded_as_failed(fake_client, monkeypatch):
    """We do not know whether the customer was prompted. Calling that a
    failure would close a payment that may yet succeed - and the customer
    could still approve it."""
    _patch(monkeypatch, SelcomCheckoutError("ReadTimeout"))
    link = _link(fake_client)

    collection = _push(fake_client, link)

    assert collection["status"] != "failed"
    assert collection["status"] == "processing"


def test_an_unanswered_push_is_never_recorded_as_successful(fake_client, monkeypatch):
    """The other direction, and the more expensive one. Silence is not
    payment, and nothing may credit a wallet off it."""
    _patch(monkeypatch, SelcomCheckoutError("ReadTimeout"))
    link = _link(fake_client)

    collection = _push(fake_client, link)

    assert collection["status"] != "successful"
    assert fake_client.table("ledger_entries")._table.rows == [], "no credit may be posted"


def test_the_partner_gets_a_collection_id_rather_than_a_500(fake_client, monkeypatch):
    """The partner-facing half. They received a 502 and had nothing to
    poll; now they get an id and can ask us what happened to it."""
    _patch(monkeypatch, SelcomCheckoutError("ReadTimeout"))
    link = _link(fake_client)

    collection = _push(fake_client, link)

    assert collection["id"]


def test_a_transaction_is_created_so_the_payment_is_reconcilable(fake_client, monkeypatch):
    _patch(monkeypatch, SelcomCheckoutError("ReadTimeout"))
    link = _link(fake_client)

    _push(fake_client, link)

    txs = fake_client.table("transactions")._table.rows
    assert len(txs) == 1
    assert txs[0]["status"] == "processing"


# --- the normal paths must be unchanged --------------------------------


def test_a_push_selcom_answers_normally_is_untouched(fake_client, monkeypatch):
    _patch(monkeypatch, None)
    link = _link(fake_client)

    collection = _push(fake_client, link)

    assert collection["status"] == "processing"
    assert collection["provider_reference"] == "0289999288"


def test_only_provider_errors_are_absorbed(fake_client, monkeypatch):
    """The guard is narrow on purpose. A bug in our own code must still
    surface rather than be recorded as "Selcom did not answer"."""
    _patch(monkeypatch, RuntimeError("a real bug in our code"))
    link = _link(fake_client)

    with pytest.raises(RuntimeError):
        _push(fake_client, link)
