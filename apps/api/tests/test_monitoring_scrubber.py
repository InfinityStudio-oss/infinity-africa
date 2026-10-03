"""What may and may not leave this platform in an error report.

A Sentry event is a payload sent to a third party, and the things an SDK
attaches to an exception by default — the request, its headers, its body
— are precisely the things carrying a merchant's API key, a customer's
phone number and a provider's credentials.

These tests are the contract. Each one names something that must never
appear in an outbound event, so a future change that widens what is sent
fails here rather than in someone's Sentry project.
"""

import pytest

from app.core.monitoring import (
    REDACTED,
    capture_exception,
    capture_message,
    init_sentry,
    redact_text,
    scrub_event,
)

# --- secrets, wherever they appear -----------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "sk_live_example1234",
        "sk_test_example1234",
        "pk_live_example1234",
        "re_AbCdEf123456789",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27u",
        "Bearer abcdef1234567890",
    ],
)
def test_a_secret_is_redacted_wherever_it_appears(secret):
    """Not only in a known field. A key reaches Sentry most often inside
    an exception message, which no structural rule covers."""
    assert secret not in redact_text(
        f"request failed using {secret} against the provider"
    )


@pytest.mark.parametrize(
    "personal",
    [
        "customer@example.com",
        "255712345678",
        "+255712345678",
        "0712345678",
        "19900101123451234512",
    ],
)
def test_personal_data_is_redacted(personal):
    """A phone number is how a payer is identified on this platform, and
    a NIDA is a national identity number. Neither belongs in a crash
    report."""
    assert personal not in redact_text(f"collection for {personal} failed")


def test_redaction_leaves_the_rest_of_the_message_readable():
    """A scrubber that destroys the message defeats the point of having
    error reporting at all."""
    scrubbed = redact_text(
        "Selcom returned HTTP 400 for +255712345678 on order ORD-991"
    )
    assert "Selcom returned HTTP 400" in scrubbed
    assert "ORD-991" in scrubbed
    assert "255712345678" not in scrubbed


# --- whole sections that are dropped, not redacted -------------------------


def test_the_request_body_never_leaves():
    """A payment body is sensitive in its entirety — the amount, the
    phone and the reference ARE the payload, so there is nothing to
    redact down to."""
    event = scrub_event(
        {
            "request": {
                "data": {"amount": "5000.00", "phone": "+255712345678"},
                "url": "/v1/collections",
            }
        }
    )
    assert "data" not in event["request"]
    assert event["request"]["url"] == "/v1/collections"


def test_the_query_string_never_leaves():
    event = scrub_event({"request": {"query_string": "search=TXN-1&token=abc123"}})
    assert "query_string" not in event["request"]


def test_cookies_never_leave():
    event = scrub_event({"request": {"cookies": {"sb-access-token": "eyJhbGciOi..."}}})
    assert "cookies" not in event["request"]


def test_the_server_environment_never_leaves():
    """It holds every secret the process was started with."""
    event = scrub_event(
        {
            "contexts": {
                "env": {"SUPABASE_SERVICE_ROLE_KEY": "real-key"},
                "runtime": {"name": "CPython"},
            },
            "environment_variables": {"RESEND_API_KEY": "re_real"},
        }
    )
    assert "env" not in event["contexts"]
    assert "environment_variables" not in event
    assert event["contexts"]["runtime"]["name"] == "CPython"


# --- headers are allow-listed, not deny-listed -----------------------------


def test_only_allow_listed_headers_survive():
    """A deny-list protects the headers someone thought of. This has to
    protect against the one they did not."""
    event = scrub_event(
        {
            "request": {
                "headers": {
                    "Authorization": "Bearer sk_live_realkey123456",
                    "X-API-Key": "sk_live_realkey123456",
                    "Cookie": "session=abc",
                    "X-Some-Future-Header": "a secret nobody predicted",
                    "Content-Type": "application/json",
                    "User-Agent": "BillNasi/1.0",
                }
            }
        }
    )
    assert set(event["request"]["headers"]) == {"Content-Type", "User-Agent"}


# --- sensitive keys, whatever their value looks like -----------------------


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "api_key",
        "webhook_secret",
        "customer_phone",
        "nida_number",
        "pin",
        "access_token",
    ],
)
def test_a_sensitive_key_has_its_value_dropped(key):
    """Catches a secret that matches no pattern — a short token, a PIN,
    a four-digit code."""
    event = scrub_event({"extra": {key: "1234"}})
    assert event["extra"][key] == REDACTED


def test_nested_structures_are_scrubbed_all_the_way_down():
    event = scrub_event(
        {
            "extra": {
                "provider": {
                    "attempts": [
                        {"note": "retried with sk_live_abcdefgh12345678"},
                    ]
                }
            }
        }
    )
    assert "sk_live_" not in str(event)


def test_a_pathologically_nested_event_terminates():
    """An exception message can contain anything a caller sent, so an
    unbounded recursive scrubber is a denial of service waiting for a
    deeply nested payload."""
    deep = current = {}
    for _ in range(200):
        current["next"] = {}
        current = current["next"]
    assert scrub_event({"extra": deep}) is not None


# --- what we deliberately keep ---------------------------------------------


def test_the_diagnostic_parts_of_an_event_survive():
    """Scrubbing everything would be safe and useless. These are what
    make a report actionable."""
    event = scrub_event(
        {
            "level": "error",
            "transaction": "POST /v1/collections/wallet-push",
            "tags": {
                "environment": "production",
                "provider": "selcom",
                "payment_status": "failed",
            },
            "exception": {
                "values": [
                    {"type": "SelcomTimeout", "value": "provider did not respond"}
                ]
            },
        }
    )
    assert event["level"] == "error"
    assert event["transaction"] == "POST /v1/collections/wallet-push"
    assert event["tags"]["provider"] == "selcom"
    assert event["exception"]["values"][0]["type"] == "SelcomTimeout"


# --- failure modes ----------------------------------------------------------


def test_a_scrubber_failure_drops_the_event_rather_than_sending_it():
    """Returning the event on error would let an unscrubbed payload
    through, which is the one outcome worse than losing the report."""

    class Hostile(dict):
        def get(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    assert scrub_event(Hostile()) is None


def test_monitoring_is_off_without_a_dsn(monkeypatch):
    """Ships inert. No DSN means no init, no network, and no behaviour
    change on a platform already serving payments."""
    from app.config import get_settings

    monkeypatch.setenv("SENTRY_DSN", "")
    get_settings.cache_clear()
    try:
        assert init_sentry() is False
    finally:
        get_settings.cache_clear()


def test_capture_exception_is_a_silent_no_op_when_monitoring_is_off():
    """Called from the unhandled-exception handler, which is already
    dealing with a failed request. If this raised, it would replace a
    merchant's 500 with a crash in the error path itself."""
    assert capture_exception(ValueError("boom")) is None


def test_capture_message_is_a_silent_no_op_when_monitoring_is_off():
    assert (
        capture_message("webhook delivery exhausted", level="error", tags={"merchant_id": "m-1"})
        is None
    )
