"""One retry when Selcom's edge answers 502/503/504 — and never on the
call that moves money.

Measured on 2026-11-01: a handful of customer payments a day die before
they start because create-order-minimal gets an HTTP 502 from Selcom's
gateway. The order is never created, nothing is charged, and the
customer simply sees a failure. The 502s arrive in bursts of seconds, so
a single retry a moment later usually lands.

The danger in adding retries to a payments client is not the retry that
fails — it is the retry of a request that already succeeded invisibly.
`_signed_request` is the one choke point every endpoint shares,
including process_wallet_payment, which pulls money out of a customer's
wallet. These tests exist mostly to hold the line that the money-moving
calls never opt in.
"""

import json
from typing import ClassVar

import pytest

import app.services.selcom_checkout.client as selcom_checkout_client_module
from app.services.selcom.outbound_guard import reset_outbound_guard
from app.services.selcom_checkout.client import (
    _GATEWAY_RETRY_ATTEMPTS,
    _RETRYABLE_GATEWAY_STATUSES,
    SelcomCheckoutHTTPClient,
)
from app.services.selcom_checkout.errors import SelcomCheckoutError
from app.services.selcom_checkout.schemas import SelcomCheckoutCredentials

CREATE_ORDER_OK = {
    "reference": "0289999288",
    "resultcode": "000",
    "result": "SUCCESS",
    "message": "Payment notification logged",
    "data": [
        {
            "gateway_buyer_uuid": "12344321",
            "payment_token": "80008000",
            "qr": "QR",
            "payment_gateway_url": "aHR0cDpleGFtcGxlLmNvbS9wZy90MTIyMjI=",
        }
    ],
}

ORDER_STATUS_OK = {
    "resultcode": "000",
    "result": "SUCCESS",
    "message": "Order fetch successful",
    "data": [
        {
            "order_id": "ORD-1",
            "creation_date": "2026-11-01 20:12:00",
            "amount": "1000",
            "payment_status": "COMPLETED",
            "transid": "TX1",
            "channel": "TIGOPESATZ",
            "reference": "REF1",
            "msisdn": "255712000000",
        }
    ],
}

WALLET_PAYMENT_OK = {
    "reference": "0289999288",
    "resultcode": "000",
    "result": "SUCCESS",
    "message": "Payment request accepted",
    "data": [],
}


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict):
        self.status_code = status_code
        self.content = json.dumps(json_body).encode("utf-8")


class _FakeAsyncClient:
    """Serves a scripted sequence of responses so a test can say "502,
    then 200" and assert on what the client did in between. Unlike the
    fake in test_selcom_checkout_client.py this accepts `params` as well
    as `json`, because order-status is a GET."""

    responses: ClassVar[list[_FakeResponse]] = []
    calls: ClassVar[list[dict]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, *, json=None, params=None, headers=None):
        _FakeAsyncClient.calls.append({"method": method, "url": url, "json": json, "params": params})
        index = min(len(_FakeAsyncClient.calls) - 1, len(_FakeAsyncClient.responses) - 1)
        return _FakeAsyncClient.responses[index]


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch):
    monkeypatch.setattr(selcom_checkout_client_module.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.responses = [_FakeResponse(200, CREATE_ORDER_OK)]
    # The guard is a module-level singleton; one test's rate window would
    # otherwise leak into the next and make a retry look slow.
    reset_outbound_guard()
    yield
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.responses = []


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch):
    """The backoff is real time in production and dead weight in a test.
    Recorded rather than skipped, so a test can assert the client paused
    at all."""
    slept: list[float] = []

    async def _fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(selcom_checkout_client_module.asyncio, "sleep", _fake_sleep)
    return slept


def _client() -> SelcomCheckoutHTTPClient:
    return SelcomCheckoutHTTPClient(
        credentials=SelcomCheckoutCredentials(
            base_url="https://checkout.example.selcommobile.com",
            api_key="test-key",
            api_secret="test-secret",
            digest_method="HS256",
            vendor="VENDORTEST",
            timeout_seconds=30,
        )
    )


async def _create_order():
    return await _client().create_order_minimal(
        order_id="ORD-1",
        buyer_email="john@example.com",
        buyer_name="John Doe",
        buyer_phone="255712000000",
        amount="1000",
        no_of_items=1,
    )


# --- the fix: a 502 no longer fails the customer ------------------------------------


@pytest.mark.asyncio
async def test_create_order_retries_once_after_a_502_and_succeeds():
    _FakeAsyncClient.responses = [
        _FakeResponse(502, {}),
        _FakeResponse(200, CREATE_ORDER_OK),
    ]

    result = await _create_order()

    assert result.payment_token == "80008000"
    assert len(_FakeAsyncClient.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", sorted(_RETRYABLE_GATEWAY_STATUSES))
async def test_every_gateway_status_is_retried(status_code):
    _FakeAsyncClient.responses = [
        _FakeResponse(status_code, {}),
        _FakeResponse(200, CREATE_ORDER_OK),
    ]

    await _create_order()

    assert len(_FakeAsyncClient.calls) == 2


@pytest.mark.asyncio
async def test_the_retry_reuses_the_same_order_id():
    """The whole safety argument rests on this. A retry carrying a fresh
    order_id would be a second order, and two orders is how one customer
    pays twice."""
    _FakeAsyncClient.responses = [
        _FakeResponse(502, {}),
        _FakeResponse(200, CREATE_ORDER_OK),
    ]

    await _create_order()

    first, second = _FakeAsyncClient.calls
    assert first["json"]["order_id"] == second["json"]["order_id"] == "ORD-1"
    assert first["json"] == second["json"]


@pytest.mark.asyncio
async def test_it_pauses_between_attempts(_no_real_sleeping):
    _FakeAsyncClient.responses = [
        _FakeResponse(502, {}),
        _FakeResponse(200, CREATE_ORDER_OK),
    ]

    await _create_order()

    assert len(_no_real_sleeping) == 1
    assert _no_real_sleeping[0] > 0


@pytest.mark.asyncio
async def test_it_gives_up_after_the_configured_attempts():
    """A provider that is genuinely down must not be hammered. The
    customer still gets a clear failure, just one attempt later."""
    _FakeAsyncClient.responses = [_FakeResponse(502, {})]

    with pytest.raises(SelcomCheckoutError) as exc_info:
        await _create_order()

    assert exc_info.value.provider_status_code == 502
    assert len(_FakeAsyncClient.calls) == _GATEWAY_RETRY_ATTEMPTS


@pytest.mark.asyncio
async def test_a_successful_first_attempt_is_not_repeated():
    _FakeAsyncClient.responses = [_FakeResponse(200, CREATE_ORDER_OK)]

    await _create_order()

    assert len(_FakeAsyncClient.calls) == 1


# --- what must NOT be retried --------------------------------------------------------


@pytest.mark.asyncio
async def test_wallet_payment_is_never_retried():
    """process_wallet_payment pulls money from a customer's wallet. A 502
    here is ambiguous — the push may already be on its way to the
    customer's handset — so the only safe number of attempts is one.
    If this test ever fails, a customer is about to be charged twice."""
    _FakeAsyncClient.responses = [_FakeResponse(502, {})]

    with pytest.raises(SelcomCheckoutError):
        await _client().process_wallet_payment(
            transid="TX-1", order_id="ORD-1", msisdn="255712000000"
        )

    assert len(_FakeAsyncClient.calls) == 1


@pytest.mark.asyncio
async def test_selcompesa_payment_is_never_retried():
    """The other money-moving call, for the same reason."""
    _FakeAsyncClient.responses = [_FakeResponse(502, {})]

    with pytest.raises(SelcomCheckoutError):
        await _client().selcompesa_payment(
            transid="TX-1", order_id="ORD-1", msisdn="255712000000"
        )

    assert len(_FakeAsyncClient.calls) == 1


@pytest.mark.asyncio
async def test_a_500_is_not_retried():
    """500 means Selcom's application was reached and threw, so the work
    may have been done. 502/503/504 come from the proxy in front of it
    and say the request never got that far. Only the latter is safe to
    repeat blindly."""
    _FakeAsyncClient.responses = [_FakeResponse(500, {})]

    with pytest.raises(SelcomCheckoutError):
        await _create_order()

    assert len(_FakeAsyncClient.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
async def test_client_errors_are_not_retried(status_code):
    """Selcom rejected this on its merits. Sending it again just fails
    twice and doubles the load for nothing."""
    _FakeAsyncClient.responses = [_FakeResponse(status_code, {})]

    with pytest.raises(SelcomCheckoutError):
        await _create_order()

    assert len(_FakeAsyncClient.calls) == 1


@pytest.mark.asyncio
async def test_a_transport_failure_is_not_retried(monkeypatch):
    """A timeout is ambiguous in a way a 502 is not: the request may be
    being processed right now. Left alone deliberately."""

    class _TimingOutClient(_FakeAsyncClient):
        async def request(self, method, url, **kwargs):
            _FakeAsyncClient.calls.append({"method": method, "url": url})
            raise selcom_checkout_client_module.httpx.TimeoutException("too slow")

    monkeypatch.setattr(selcom_checkout_client_module.httpx, "AsyncClient", _TimingOutClient)

    with pytest.raises(SelcomCheckoutError):
        await _create_order()

    assert len(_FakeAsyncClient.calls) == 1


# --- the read path -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_status_retries_a_502():
    """Read-only, so repeating it cannot do harm. Worth retrying because
    a failed status read leaves a real payment unresolved."""
    _FakeAsyncClient.responses = [
        _FakeResponse(502, {}),
        _FakeResponse(200, ORDER_STATUS_OK),
    ]

    result = await _client().get_order_status(order_id="ORD-1")

    assert result.payment_status == "COMPLETED"
    assert len(_FakeAsyncClient.calls) == 2


# --- the guard that outlives this change ---------------------------------------------


def test_only_known_safe_calls_opt_into_retrying():
    """A new endpoint method must not pick up retries by accident. The
    default is off; this pins the exact set of callers that turn it on,
    so adding one is a deliberate edit to this list with a reason beside
    it in the source."""
    import inspect

    source = inspect.getsource(selcom_checkout_client_module)
    opted_in = source.count("retry_on_gateway_error=True")

    assert opted_in == 2, (
        "Exactly two calls may retry: create_order_minimal (no money moves, same "
        "order_id) and get_order_status (a read). If you added a third, prove it is "
        "safe to send twice before changing this number."
    )
