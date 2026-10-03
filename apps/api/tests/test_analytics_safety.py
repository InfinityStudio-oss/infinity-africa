"""Analytics must never be able to break a payment.

The whole risk of adding product analytics to a payment platform is that
a metrics call sits on the path of something that moves money. These
tests pin the property that makes that safe: every entry point in
app.core.analytics swallows its own failures, and a collection still
resolves and still credits a wallet when the analytics client is
broken.
"""

import logging

import pytest

from app.core import analytics


@pytest.fixture(autouse=True)
def _no_client_leaks():
    """Each test owns the module-level client, and none leaks into the
    next — or into the rest of the suite, where a stray client would try
    to reach PostHog."""
    original = analytics._client
    analytics._client = None
    yield
    analytics._client = original


class ExplodingClient:
    """Every method raises. Stands in for PostHog being down, wrongly
    configured, rate-limited or mid-outage."""

    def capture(self, *_args, **_kwargs):
        raise RuntimeError("posthog is down")

    def shutdown(self):
        raise RuntimeError("posthog is down")


class RecordingClient:
    def __init__(self):
        self.captured: list[dict] = []

    def capture(self, **kwargs):
        self.captured.append(kwargs)

    def shutdown(self):
        pass


# --- failure is always silent ----------------------------------------------


def test_track_does_not_raise_when_the_client_explodes():
    analytics._client = ExplodingClient()
    analytics.track(
        "collection_resolved", merchant_id="m-1", properties={"status": "successful"}
    )


def test_shutdown_does_not_raise_when_the_client_explodes():
    analytics._client = ExplodingClient()
    analytics.shutdown_analytics()


def test_track_is_a_no_op_when_analytics_is_off():
    """The default on every deploy that has not set POSTHOG_API_KEY."""
    analytics._client = None
    analytics.track("collection_resolved", merchant_id="m-1")


def test_init_is_off_without_a_key(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("POSTHOG_API_KEY", "")
    get_settings.cache_clear()
    try:
        assert analytics.init_analytics() is False
    finally:
        get_settings.cache_clear()


def test_the_error_hook_logs_and_returns(caplog):
    """PostHog's SDK calls on_error instead of raising out of capture().
    If this hook ever raised, the failure would surface inside whatever
    was being tracked."""
    # caplog's handler is attached to the ROOT logger, and app.main's
    # _configure_logging() sets propagate=False on the "infinity" logger —
    # so once anything in the suite has imported the app, these records
    # never reach caplog. Attaching the handler directly makes this test
    # independent of whether that import has happened yet, which is what it
    # was not when it passed alone and failed in the full run.
    analytics_logger = logging.getLogger("infinity.analytics")
    analytics_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="infinity.analytics"):
            analytics._swallow_error(RuntimeError("connection reset"))
    finally:
        analytics_logger.removeHandler(caplog.handler)
    assert "posthog_send_failed" in caplog.text


# --- nothing identifying leaves --------------------------------------------


def test_only_allow_listed_properties_are_sent():
    """A property nobody allow-listed is dropped, not sent. This is what
    stops a well-meaning future call site adding customer_name."""
    client = RecordingClient()
    analytics._client = client
    analytics.track(
        "collection_resolved",
        merchant_id="m-1",
        properties={
            "status": "successful",
            "customer_name": "Jane Mwakyusa",
            "customer_phone": "+255712345678",
            "amount": "50000.00",
        },
    )
    assert client.captured[0]["properties"] == {"status": "successful"}


def test_an_allow_listed_property_is_still_pattern_redacted():
    """Belt and braces: the allow-list says which keys, the scrubber
    says what may be in them."""
    client = RecordingClient()
    analytics._client = client
    analytics.track(
        "collection_resolved", properties={"provider": "selcom +255712345678"}
    )
    assert "255712345678" not in client.captured[0]["properties"]["provider"]


def test_the_only_identity_sent_is_the_merchant_id():
    client = RecordingClient()
    analytics._client = client
    analytics.track(
        "collection_resolved", merchant_id="8f14e45f-ea2b-4c1b-9c3d-2a1b7e5f6d4c"
    )
    assert client.captured[0]["distinct_id"] == "8f14e45f-ea2b-4c1b-9c3d-2a1b7e5f6d4c"


def test_an_event_with_no_merchant_is_attributed_to_the_platform():
    client = RecordingClient()
    analytics._client = client
    analytics.track("worker_tick")
    assert client.captured[0]["distinct_id"] == "platform"


# --- amounts are banded, never sent ---------------------------------------


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (500, "<1k"),
        (999.99, "<1k"),
        (1_000, "1k-10k"),
        (9_999, "1k-10k"),
        (10_000, "10k-100k"),
        (99_999, "10k-100k"),
        (100_000, "100k-1m"),
        (1_000_000, ">=1m"),
        (5_000_000, ">=1m"),
    ],
)
def test_amounts_are_banded(amount, expected):
    """An exact amount plus a timestamp re-identifies one payment, and
    with it one payer. A band answers the question without that."""
    assert analytics.amount_band(amount) == expected


@pytest.mark.parametrize("amount", [None, "", "not-a-number"])
def test_an_unparseable_amount_does_not_raise(amount):
    assert analytics.amount_band(amount) == "unknown"
