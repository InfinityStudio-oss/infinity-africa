"""Rate limiting beyond per-IP.

Per-IP alone leaves two holes that matter on a payments platform: one
attacker rotating addresses against a single account, and one address
attacking many accounts. The second dimension closes the first; the
existing per-IP dependency closes the second. Both are needed.
"""

import uuid

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core import rate_limit as rate_limit_module
from app.core.rate_limit import RateLimitExceededError, enforce_rate_limit
from app.main import app
from tests.factories import TEST_JWT_SECRET, create_merchant, make_api_key

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setattr(resend.Emails, "send", lambda params: {"id": "resend-test-id"})
    get_settings.cache_clear()
    # Clear the singleton rather than replacing it. conftest's own
    # autouse reset holds a reference to the original object, so
    # rebinding this would leave conftest clearing a dead instance while
    # the app used a new one — every later test file would then inherit
    # an unreset limiter and start seeing 429s unrelated to itself.
    rate_limit_module._limiter._hits.clear()
    yield
    get_settings.cache_clear()


# --- the helper itself ---------------------------------------------------


def test_the_same_key_is_limited_across_different_callers():
    for _ in range(3):
        enforce_rate_limit(scope="s", key="user@example.com", limit=3, window_seconds=900)

    with pytest.raises(RateLimitExceededError):
        enforce_rate_limit(scope="s", key="user@example.com", limit=3, window_seconds=900)


def test_a_different_key_has_its_own_budget():
    for _ in range(3):
        enforce_rate_limit(scope="s", key="a@example.com", limit=3, window_seconds=900)

    enforce_rate_limit(scope="s", key="b@example.com", limit=3, window_seconds=900)


def test_keys_are_matched_case_insensitively():
    """Otherwise A@x.com and a@x.com are two budgets for one mailbox."""
    enforce_rate_limit(scope="s", key="User@Example.com", limit=1, window_seconds=900)

    with pytest.raises(RateLimitExceededError):
        enforce_rate_limit(scope="s", key="user@example.com  ", limit=1, window_seconds=900)


def test_scopes_do_not_share_a_budget():
    enforce_rate_limit(scope="one", key="k", limit=1, window_seconds=900)

    enforce_rate_limit(scope="two", key="k", limit=1, window_seconds=900)


def test_the_raw_key_is_never_used_as_the_bucket_name():
    """An email or key id in a bucket name could surface in a traceback or
    a heap dump. Only its digest is kept."""
    enforce_rate_limit(scope="s", key="secret@example.com", limit=5, window_seconds=60)

    buckets = list(rate_limit_module._limiter._hits.keys())
    assert buckets
    assert all("secret@example.com" not in b for b in buckets)


# --- Retry-After ---------------------------------------------------------


def test_the_error_carries_a_retry_after():
    enforce_rate_limit(scope="s", key="k", limit=1, window_seconds=120)

    with pytest.raises(RateLimitExceededError) as exc:
        enforce_rate_limit(scope="s", key="k", limit=1, window_seconds=120)

    assert 0 < exc.value.retry_after <= 121


def test_a_429_response_sets_the_retry_after_header(fake_client):
    """A client that cannot see how long to wait either gives up or keeps
    hammering; neither is what the limit is for."""
    for _ in range(6):
        response = client.post("/v1/auth/forgot-password", json={"email": "someone@example.com"})
        if response.status_code == 429:
            break

    assert response.status_code == 429, "expected the limit to trigger"
    assert response.headers.get("Retry-After")
    assert int(response.headers["Retry-After"]) > 0


# --- password reset: must not become an account oracle -------------------


def test_the_reset_limit_response_is_identical_for_unknown_addresses(fake_client):
    """The whole endpoint is built so a caller cannot tell a registered
    address from an unregistered one. The limiter must not undo that."""
    bodies = []
    for email in ("definitely-not-registered@example.com",) * 6:
        r = client.post("/v1/auth/forgot-password", json={"email": email})
        bodies.append((r.status_code, r.text))

    limited = [b for b in bodies if b[0] == 429]
    assert limited, "expected the limit to trigger"
    # Every 429 is byte-identical, and none of them mentions the address.
    assert len({b[1] for b in limited}) == 1
    assert "definitely-not-registered" not in limited[0][1]


def test_one_address_cannot_be_targeted_past_its_own_limit(fake_client):
    """Per-email, so rotating IPs does not multiply the budget for a single
    mailbox."""
    target = "victim@example.com"
    statuses = [
        client.post("/v1/auth/forgot-password", json={"email": target}).status_code
        for _ in range(5)
    ]

    assert 429 in statuses


# --- API keys ------------------------------------------------------------


def test_api_key_requests_are_limited_per_key(fake_client):
    """One merchant's runaway integration must not spend the budget of
    every other caller behind the same egress address."""
    merchant = create_merchant(fake_client)
    raw, _row = make_api_key(fake_client, merchant_id=uuid.UUID(merchant["id"]))
    path = f"/v1/collections/{uuid.uuid4()}?merchant_id={merchant['id']}"

    statuses = [
        client.get(path, headers={"X-API-Key": raw}).status_code for _ in range(125)
    ]

    assert 429 in statuses


def test_repeated_bad_keys_from_one_ip_are_capped(fake_client):
    """Wrong keys are cheap to generate; a guessing script should stop
    early. A working integration never reaches this path."""
    merchant = create_merchant(fake_client)
    path = f"/v1/collections/{uuid.uuid4()}?merchant_id={merchant['id']}"

    statuses = [
        client.get(path, headers={"X-API-Key": f"inf_live_wrong{n}"}).status_code
        for n in range(25)
    ]

    assert 429 in statuses
    assert 401 in statuses, "the first attempts should still read as auth failures"


def test_a_valid_key_is_not_punished_for_another_keys_failures(fake_client):
    """The failure cap is keyed on the IP but must not lock out a caller
    who then presents a working key within its own budget."""
    merchant = create_merchant(fake_client)
    raw, _row = make_api_key(fake_client, merchant_id=uuid.UUID(merchant["id"]))
    path = f"/v1/collections/{uuid.uuid4()}?merchant_id={merchant['id']}"

    for n in range(5):
        client.get(path, headers={"X-API-Key": f"inf_live_wrong{n}"})

    assert client.get(path, headers={"X-API-Key": raw}).status_code != 429
