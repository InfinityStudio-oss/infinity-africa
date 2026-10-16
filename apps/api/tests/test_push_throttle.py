"""One customer may not be sent prompt after prompt.

From production, 2026-10-12: a single number on MAXTON'S WIFI was sent
**52 payment prompts in two hours**, all TZS 500, all expired without
being completed. Selcom reported "Wallet push successful" every time, so
the prompt was delivered and simply never answered.

Nobody gained anything from attempts 6 through 52. The customer got dead
prompts and no WiFi, the merchant got a dashboard full of failures, and
the platform spent provider calls on a request that was failing for a
reason more attempts could not change.

The tests that matter most here are the ones in the other direction: a
customer retrying in good faith must not be blocked, and one customer's
loop must not stop anybody else paying. A throttle that catches real
sales is worse than the loop it prevents.
"""

import uuid

import pytest

from app.config import get_settings
from app.core.push_throttle import assert_customer_push_allowed
from app.core.rate_limit import RateLimitExceededError, _limiter


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setenv("COLLECTION_PUSH_PER_CUSTOMER_LIMIT", "5")
    monkeypatch.setenv("COLLECTION_PUSH_PER_CUSTOMER_WINDOW_SECONDS", "600")
    get_settings.cache_clear()
    _limiter._hits.clear()
    yield
    _limiter._hits.clear()
    get_settings.cache_clear()


def _push(merchant_id, phone):
    assert_customer_push_allowed(merchant_id=merchant_id, customer_phone=phone)


def test_a_customer_retrying_in_good_faith_is_not_blocked():
    """The case the limit must never catch. A first prompt that expires
    and an immediate second attempt is an ordinary customer, and blocking
    them costs a real sale."""
    merchant, phone = uuid.uuid4(), "255797747005"

    for _ in range(5):
        _push(merchant, phone)  # no raise


def test_the_loop_is_stopped_at_the_limit():
    merchant, phone = uuid.uuid4(), "255797747005"
    for _ in range(5):
        _push(merchant, phone)

    with pytest.raises(RateLimitExceededError):
        _push(merchant, phone)


def test_the_message_tells_the_customer_what_to_do():
    """"Too many requests" tells someone retrying in good faith nothing.
    The two things they can act on are their balance and whether the
    prompt is reaching them."""
    merchant, phone = uuid.uuid4(), "255797747005"
    for _ in range(5):
        _push(merchant, phone)

    with pytest.raises(RateLimitExceededError) as exc:
        _push(merchant, phone)

    message = str(exc.value).lower()
    assert "balance" in message
    assert "try again" in message


def test_one_customers_loop_does_not_block_another_customer():
    """These pushes arrive from a partner's server, so every customer
    shares one IP. If this throttled by address instead of by number, one
    person retrying would stop an entire ISP's customers from paying."""
    merchant = uuid.uuid4()
    for _ in range(5):
        _push(merchant, "255797747005")

    _push(merchant, "255712000002")  # a different customer, unaffected


def test_the_same_customer_may_still_pay_a_different_merchant():
    """A customer buying from two ISPs is two separate relationships."""
    phone = "255797747005"
    merchant_a, merchant_b = uuid.uuid4(), uuid.uuid4()
    for _ in range(5):
        _push(merchant_a, phone)

    _push(merchant_b, phone)


def test_a_push_with_no_phone_is_never_throttled():
    """A QR scan or a hosted checkout page has no destination number yet,
    so there is no customer to throttle."""
    merchant = uuid.uuid4()
    for _ in range(50):
        _push(merchant, None)


def test_the_throttle_can_be_switched_off():
    """Ships with an escape hatch, because a limit on a payment path that
    turns out to be wrong must be removable without a deploy."""
    import os

    os.environ["COLLECTION_PUSH_PER_CUSTOMER_LIMIT"] = "0"
    get_settings.cache_clear()
    merchant, phone = uuid.uuid4(), "255797747005"
    try:
        for _ in range(60):
            _push(merchant, phone)
    finally:
        os.environ["COLLECTION_PUSH_PER_CUSTOMER_LIMIT"] = "5"
        get_settings.cache_clear()


def test_the_phone_number_never_becomes_a_readable_bucket_name():
    """A bucket key could surface in a traceback or a heap dump.
    enforce_rate_limit hashes it; this is what holds that true."""
    merchant, phone = uuid.uuid4(), "255797747005"
    _push(merchant, phone)

    assert any("collection_push_per_customer" in k for k in _limiter._hits)
    assert not any(phone in k for k in _limiter._hits)
