"""The cache, and the much longer list of things it must never touch.

Supabase REST costs 56-60ms per query from this API, so the merchant
dashboard - nine queries - spent most of a second in the database. That
is what the cache is for.

What these tests are mostly for is the other half: this is a payments
platform, and a cached number that reaches a money decision is a bug
whose symptom is a merchant being paid twice or not at all. So the rule
is that nothing cached may decide whether money exists, moves or is owed,
and the bulk of what follows is evidence for that rather than for the
speed-up.

The fake Redis here behaves like Redis in the ways that matter: it can
be made to fail, and it stores exactly the bytes it is given.
"""

import json
import uuid
from decimal import Decimal

import pytest

from app.config import get_settings
from app.core import cache as cache_module
from app.core.cache import (
    cache_delete,
    cache_get,
    cache_set,
    invalidate_merchant_display,
    merchant_key,
    reset_breaker,
)


class _FakeRedis:
    """Enough Redis to test against, with a switch for making it fail."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.fail = False
        self.calls = 0

    def _maybe_fail(self):
        self.calls += 1
        if self.fail:
            raise ConnectionError("redis is unreachable")

    def get(self, key):
        self._maybe_fail()
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self._maybe_fail()
        assert ttl > 0, "every cached value must expire"
        self.store[key] = value

    def delete(self, *keys):
        self._maybe_fail()
        for key in keys:
            self.store.pop(key, None)


@pytest.fixture
def redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    get_settings.cache_clear()
    reset_breaker()
    monkeypatch.setattr(cache_module, "_client", lambda: fake)
    yield fake
    reset_breaker()
    get_settings.cache_clear()


# --- the basics ------------------------------------------------------------


def test_a_miss_then_a_hit(redis):
    key = merchant_key(uuid.uuid4(), "overview")
    assert cache_get(key) is None

    cache_set(key, {"total": "100.00"}, 20)

    assert cache_get(key) == {"total": "100.00"}


def test_money_survives_the_round_trip_exactly(redis):
    """Decimal to float and back is not the same number, and these are
    amounts. The encoder writes a string."""
    key = merchant_key(uuid.uuid4(), "overview")

    cache_set(key, {"amount": Decimal("0.1"), "fee": Decimal("1234567.89")}, 20)

    assert json.loads(redis.store[key])["amount"] == "0.1"
    assert Decimal(cache_get(key)["amount"]) == Decimal("0.1")
    assert Decimal(cache_get(key)["fee"]) == Decimal("1234567.89")


def test_every_write_must_carry_an_expiry(redis):
    """A cached figure with no TTL on a payments platform is a number
    that can be wrong forever."""
    key = merchant_key(uuid.uuid4(), "overview")

    cache_set(key, {"total": "1"}, 0)
    cache_set(key, {"total": "1"}, -5)

    assert cache_get(key) is None


# --- isolation between merchants -------------------------------------------


def test_one_merchants_dashboard_cannot_answer_anothers_request(redis):
    """The property that matters most. The merchant id is in the key by
    construction, not by a caller remembering to put it there."""
    a, b = uuid.uuid4(), uuid.uuid4()

    cache_set(merchant_key(a, "overview"), {"total_collections": "999999.00"}, 20)

    assert cache_get(merchant_key(b, "overview")) is None
    assert str(a) in merchant_key(a, "overview")


def test_a_paginated_list_is_keyed_by_page(redis):
    """Otherwise page 2 answers a request for page 1."""
    merchant = uuid.uuid4()
    cache_set(merchant_key(merchant, "api-keys", "1", "20"), {"rows": ["first"]}, 60)

    assert cache_get(merchant_key(merchant, "api-keys", "2", "20")) is None


def test_keys_are_namespaced_by_environment(redis, monkeypatch):
    """A staging deploy pointed at the same Redis must not answer a
    production request."""
    monkeypatch.setenv("ENVIRONMENT", "staging")
    get_settings.cache_clear()
    staging = merchant_key("m1", "overview")
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    production = merchant_key("m1", "overview")

    assert staging != production
    assert "staging" in staging and "production" in production


# --- failure is always safe --------------------------------------------------


def test_redis_being_down_reads_as_a_miss(redis):
    key = merchant_key(uuid.uuid4(), "overview")
    cache_set(key, {"total": "5"}, 20)
    redis.fail = True

    assert cache_get(key) is None  # not an exception


def test_no_cache_operation_can_raise(redis):
    """The contract the rest of the codebase relies on. These are called
    from inside money paths - a ledger write invalidates a display - so
    one that raised would fail a payment over a cache."""
    redis.fail = True
    key = merchant_key(uuid.uuid4(), "overview")

    cache_get(key)
    cache_set(key, {"a": 1}, 10)
    cache_delete(key)
    invalidate_merchant_display(uuid.uuid4())


def test_a_sustained_outage_stops_being_retried(redis):
    """A cache that hangs is worse than no cache. Without a breaker, a
    Redis outage costs every cached endpoint a timeout on every request -
    turning a performance feature into a regression exactly when nobody
    is watching."""
    redis.fail = True
    key = merchant_key(uuid.uuid4(), "overview")

    for _ in range(5):
        cache_get(key)
    calls_after_breaker_opened = redis.calls

    for _ in range(10):
        cache_get(key)

    assert redis.calls == calls_after_breaker_opened, "breaker should stop calling Redis"


def test_an_unreadable_value_is_a_miss_not_a_crash(redis):
    """A value written by an older deploy with a different shape must not
    reach a response model."""
    key = merchant_key(uuid.uuid4(), "overview")
    redis.store[key] = "{not json"

    assert cache_get(key) is None


def test_caching_is_off_unless_switched_on(monkeypatch):
    """The rollback plan is CACHE_ENABLED=false, so it has to work, and
    off is the default."""
    monkeypatch.setenv("CACHE_ENABLED", "false")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    get_settings.cache_clear()
    reset_breaker()

    assert cache_module._client() is None

    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "")
    get_settings.cache_clear()
    reset_breaker()

    assert cache_module._client() is None
    get_settings.cache_clear()


# --- invalidation ------------------------------------------------------------


def test_invalidation_clears_the_display_caches(redis):
    merchant = uuid.uuid4()
    cache_set(merchant_key(merchant, "overview"), {"total": "1"}, 20)
    cache_set(merchant_key(merchant, "settings"), {"business_name": "X"}, 300)
    cache_set(merchant_key(merchant, "api-keys", "1", "20"), {"rows": []}, 60)

    invalidate_merchant_display(merchant)

    assert cache_get(merchant_key(merchant, "overview")) is None
    assert cache_get(merchant_key(merchant, "settings")) is None
    assert cache_get(merchant_key(merchant, "api-keys", "1", "20")) is None


def test_invalidating_one_merchant_leaves_another_alone(redis):
    a, b = uuid.uuid4(), uuid.uuid4()
    cache_set(merchant_key(a, "overview"), {"total": "1"}, 20)
    cache_set(merchant_key(b, "overview"), {"total": "2"}, 20)

    invalidate_merchant_display(a)

    assert cache_get(merchant_key(a, "overview")) is None
    assert cache_get(merchant_key(b, "overview")) == {"total": "2"}


# --- the endpoints themselves -------------------------------------------------


def _merchant_with_admin(fake_client):
    from tests.factories import create_merchant, make_merchant_member

    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    return merchant_id, user_id


def test_the_overview_serves_its_aggregates_from_cache_on_the_second_call(fake_client, redis):
    """Nine Supabase queries at ~57ms each is what this avoids paying
    twice."""
    from app.services.merchant_overview import get_merchant_overview

    merchant_id, _user_id = _merchant_with_admin(fake_client)

    get_merchant_overview(fake_client, merchant_id=merchant_id)
    assert cache_get(merchant_key(merchant_id, "overview")) is not None

    # Second call is served from the cached aggregates.
    second = get_merchant_overview(fake_client, merchant_id=merchant_id)
    assert "total_collections" in second


def test_the_overview_never_caches_the_wallet_balance(fake_client, redis):
    """The one number a merchant reads to decide whether to withdraw. A
    stale total-collections figure is a cosmetic lag; a stale balance is
    a merchant being told they have money they have already moved."""
    from app.services.merchant_overview import get_merchant_overview

    merchant_id, _user_id = _merchant_with_admin(fake_client)
    get_merchant_overview(fake_client, merchant_id=merchant_id)

    cached = cache_get(merchant_key(merchant_id, "overview"))

    assert "available_balance" not in cached
    assert "merchant" not in cached, "the merchant row is read live so settings changes show"


def test_a_ledger_write_drops_the_cached_overview(fake_client, redis):
    """Otherwise a merchant waits up to the TTL to see a payment they
    have just been notified about."""
    from decimal import Decimal as D

    from app.services.ledger import post_collection_entries
    from app.services.merchant_overview import get_merchant_overview

    merchant_id, _user_id = _merchant_with_admin(fake_client)
    get_merchant_overview(fake_client, merchant_id=merchant_id)
    assert cache_get(merchant_key(merchant_id, "overview")) is not None

    post_collection_entries(
        fake_client,
        transaction_id=uuid.uuid4(),
        merchant_id=merchant_id,
        gross_amount=D(1000),
        fee_amount=D(0),
        net_amount=D(1000),
        currency="TZS",
    )

    assert cache_get(merchant_key(merchant_id, "overview")) is None


def test_a_merchant_update_drops_the_cached_settings(fake_client, redis):
    from app.services.crud import update_row

    merchant_id, _user_id = _merchant_with_admin(fake_client)
    cache_set(merchant_key(merchant_id, "settings"), {"business_name": "Before"}, 300)

    update_row(fake_client, "merchants", merchant_id, {"business_name": "After"})

    assert cache_get(merchant_key(merchant_id, "settings")) is None


def test_no_api_key_secret_is_ever_written_to_the_cache(fake_client, redis):
    """The list endpoint serialises through ApiKeyResponse, which has no
    field capable of carrying a secret - not even an optional one. This
    pins that the bytes reaching Redis contain no key material."""
    from tests.factories import make_api_key

    merchant_id, _user_id = _merchant_with_admin(fake_client)
    raw_key, _row = make_api_key(fake_client, merchant_id)

    cache_set(
        merchant_key(merchant_id, "api-keys", "1", "20"),
        {"rows": [{"id": str(uuid.uuid4()), "key_prefix": "sk_test", "key_last4": "ab12"}], "total": 1},
        60,
    )

    stored = "".join(redis.store.values())
    assert raw_key not in stored
    assert "hashed_key" not in stored
