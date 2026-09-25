"""X-Forwarded-For handling.

The address this returns is what every rate limit is keyed on, what the
API-key IP allowlist compares against, and what lands in audit_logs. A
caller who can choose it can rotate past every limit and walk through a
merchant's allowlist, so "which entry of the chain do we believe" is a
security decision, not a formatting one.
"""

import pytest

from app.config import get_settings
from app.core.request_ip import client_ip


class _FakeClient:
    def __init__(self, host: str | None):
        self.host = host


class _FakeRequest:
    """Only the two attributes client_ip touches."""

    def __init__(self, *, headers: dict[str, str] | None = None, peer: str | None = "10.0.0.1"):
        self.headers = headers or {}
        self.client = _FakeClient(peer) if peer else None


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_spoofed_leading_entry_is_ignored(monkeypatch):
    """The attack: a caller prepends whatever address it wants. Railway
    appends the address it actually saw, so the real client is on the
    right and the spoof must not win."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    request = _FakeRequest(headers={"x-forwarded-for": "1.2.3.4, 203.0.113.9"})

    assert client_ip(request) == "203.0.113.9"


def test_a_long_spoofed_chain_still_resolves_to_the_proxy_observed_peer(monkeypatch):
    """Padding the chain must not push the trusted entry out of reach —
    otherwise the bypass is just "send more commas"."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    request = _FakeRequest(
        headers={"x-forwarded-for": "9.9.9.9, 8.8.8.8, 7.7.7.7, 203.0.113.9"}
    )

    assert client_ip(request) == "203.0.113.9"


def test_allowlisted_address_cannot_be_claimed_by_the_caller(monkeypatch):
    """The concrete IP-allowlist bypass, written as its own case: a stolen
    live API key plus a spoofed header must not present as the merchant's
    approved address."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    allowlisted = "41.86.0.10"
    request = _FakeRequest(headers={"x-forwarded-for": f"{allowlisted}, 198.51.100.7"})

    assert client_ip(request) != allowlisted
    assert client_ip(request) == "198.51.100.7"


def test_single_entry_header_is_used_as_is(monkeypatch):
    """A proxy that replaces rather than appends leaves one entry, which
    is genuinely the client."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    request = _FakeRequest(headers={"x-forwarded-for": "203.0.113.9"})

    assert client_ip(request) == "203.0.113.9"


def test_two_hops_reads_one_further_left(monkeypatch):
    """With Cloudflare in front of Railway both append, so the client sits
    two in from the right."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    request = _FakeRequest(headers={"x-forwarded-for": "1.2.3.4, 203.0.113.9, 172.16.0.3"})

    assert client_ip(request) == "203.0.113.9"


def test_zero_hops_ignores_the_header_entirely(monkeypatch):
    """No proxy in front means nothing in that header was added by us."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    request = _FakeRequest(headers={"x-forwarded-for": "1.2.3.4"}, peer="203.0.113.9")

    assert client_ip(request) == "203.0.113.9"


def test_falls_back_to_socket_peer_without_the_header(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    request = _FakeRequest(peer="203.0.113.9")

    assert client_ip(request) == "203.0.113.9"


def test_empty_header_does_not_resolve_to_a_blank_identity(monkeypatch):
    """A blank or comma-only header must fall back, not return "" — every
    caller sending one would otherwise share a single rate-limit bucket
    and a blank allowlist comparison."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")

    assert client_ip(_FakeRequest(headers={"x-forwarded-for": "   "}, peer="203.0.113.9")) == "203.0.113.9"
    assert client_ip(_FakeRequest(headers={"x-forwarded-for": " , , "}, peer="203.0.113.9")) == "203.0.113.9"


def test_no_peer_and_no_header_is_none_not_a_crash(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")

    assert client_ip(_FakeRequest(peer=None)) is None
