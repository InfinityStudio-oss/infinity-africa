"""The shape of the link in a password reset email.

Reset links were arriving at the page carrying nothing at all — no token
and no error — so the page reported "this link is invalid or has expired"
while Supabase had rejected nothing. Two causes, both belonging to
`action_link`:

Supabase's verify endpoint hands the session back in a URL *fragment*
(`#access_token=...`), and a fragment does not survive a further redirect.
Apex-to-www, http-to-https, a trailing slash — any hop between that
redirect and the page drops it silently.

And the token is spent by *fetching* the URL, so a mail provider that
prefetches links (Apple, Outlook, corporate filters) burns it before the
recipient taps anything.

A `token_hash` query parameter has neither problem: query parameters
survive redirects, and the token is only spent when the page's own
JavaScript calls verifyOtp, which a scanner never runs.
"""

import re
from unittest.mock import patch

import pytest

from app.config import get_settings
from app.services.email import send_password_reset_email
from tests.factories import TEST_JWT_SECRET

_SEND = "app.services.email.send_email"
_REDIRECT = "https://infinitypay.me/admin-login/reset-password"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _reset(fake_client, email="admin@infinitypay.me", redirect_to=_REDIRECT):
    fake_client.seed_auth_user("11111111-1111-1111-1111-111111111111", email=email)
    with patch(_SEND, return_value="msg_1") as send:
        send_password_reset_email(fake_client, email=email, redirect_to=redirect_to)
    return send


def _link(send):
    """The href actually emailed. Deliberately not a substring search for
    the redirect URL: action_link carries redirect_to inside its own query
    string, so searching for it finds a match either way and a test built
    that way passes against the exact bug it is meant to catch."""
    html = send.call_args.kwargs["html"]
    hrefs = re.findall(r'href="([^"]+)"', html)
    # The same URL appears more than once — the CTA button and a plain
    # fallback link beneath it — so dedupe rather than expecting one match.
    # They must agree: a button and a fallback pointing at different tokens
    # would mean one of them is always dead.
    reset_links = {href for href in hrefs if "token" in href or "reset-password" in href}
    assert len(reset_links) == 1, f"expected one distinct reset link, got {reset_links}"
    return reset_links.pop()


def test_the_link_points_at_our_own_page_not_supabases_verify_endpoint(fake_client):
    send = _reset(fake_client)

    link = _link(send)
    assert link.startswith(_REDIRECT)
    assert "supabase" not in link


def test_the_token_travels_as_a_query_parameter_not_a_fragment(fake_client):
    """A fragment is dropped by any redirect between Supabase and the page,
    which is what left the page with nothing to exchange."""
    send = _reset(fake_client)

    link = _link(send)
    assert "token_hash=" in link
    assert "#" not in link


def test_the_link_declares_the_recovery_type_the_page_expects(fake_client):
    """The page only attempts verifyOtp for types it allows; without this
    the token branch is skipped entirely and the link reads as empty."""
    send = _reset(fake_client)

    assert "type=recovery" in _link(send)


def test_a_redirect_path_that_already_has_a_query_keeps_both_parts(fake_client):
    send = _reset(fake_client, redirect_to=f"{_REDIRECT}?from=email")

    link = _link(send)
    assert "from=email" in link
    assert "&token_hash=" in link
    assert link.count("?") == 1


def test_no_account_still_sends_nothing_and_says_nothing(fake_client):
    """Account-enumeration prevention is unchanged by any of this."""
    with patch(_SEND) as send:
        result = send_password_reset_email(
            fake_client, email="nobody@example.com", redirect_to=_REDIRECT
        )

    assert result is None
    send.assert_not_called()
