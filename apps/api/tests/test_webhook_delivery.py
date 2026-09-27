"""Outbound merchant webhook delivery.

`enqueue_webhook_event` wrote `webhook_events` rows from the beginning and
nothing ever read them — its own docstring called delivery "future work".
So the Collections API told partners to wait for `collection.success`
while that event was never sent, and polling was the only thing that
actually worked.

What these pin: an event reaches the merchant's URL, it is signed the same
way the test-delivery endpoint signs (or a receiver that verified against
a test would reject live traffic), failures back off and eventually stop,
and nothing here can take the queue — or a payment — down with it.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from app.core.secret_box import encrypt_secret
from app.services.webhook_delivery import (
    _MAX_ATTEMPTS,
    deliver_event,
    deliver_pending_webhooks,
)
from app.services.webhooks import sign_outbound_payload
from tests.factories import create_merchant

_DELIVERY = "app.services.webhook_delivery.httpx.post"


def _merchant(fake_client, *, url="https://merchant.example.com/hooks", secret="whsec_test_value"):
    return create_merchant(
        fake_client,
        webhook_url=url,
        webhook_secret_encrypted=encrypt_secret(secret) if secret else None,
    )


def _event(fake_client, merchant, *, status="pending", attempts=0, last_attempted_at=None, payload=None):
    return fake_client.seed(
        "webhook_events",
        {
            "merchant_id": merchant["id"],
            "event_name": "collection.success",
            "payload": payload or {"event": "collection.success", "collection_id": "col-1"},
            "target_url": merchant.get("webhook_url"),
            "status": status,
            "attempts": attempts,
            "last_attempted_at": last_attempted_at,
        },
    )


def _row(fake_client, event_id):
    return next(r for r in fake_client.table("webhook_events")._table.rows if r["id"] == event_id)


class _Response:
    def __init__(self, status_code: int):
        self.status_code = status_code

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300


# --- it actually delivers ---------------------------------------------------


def test_a_pending_event_is_posted_to_the_merchants_url(fake_client):
    merchant = _merchant(fake_client)
    _event(fake_client, merchant)

    with patch(_DELIVERY, return_value=_Response(200)) as post:
        summary = deliver_pending_webhooks(fake_client)

    assert summary == {"due": 1, "delivered": 1, "failed": 0}
    assert post.call_args.args[0] == "https://merchant.example.com/hooks"


def test_a_delivered_event_is_marked_delivered_and_not_sent_twice(fake_client):
    merchant = _merchant(fake_client)
    event = _event(fake_client, merchant)

    with patch(_DELIVERY, return_value=_Response(200)):
        deliver_pending_webhooks(fake_client)
    row = _row(fake_client, event["id"])
    assert row["status"] == "delivered"
    assert row["delivered_at"]
    assert row["response_status_code"] == 200

    with patch(_DELIVERY, return_value=_Response(200)) as post:
        second = deliver_pending_webhooks(fake_client)
    assert second["due"] == 0
    post.assert_not_called()


def test_the_event_body_is_the_enqueued_payload(fake_client):
    merchant = _merchant(fake_client)
    payload = {"event": "collection.success", "collection_id": "col-9", "amount": "1000.00"}
    _event(fake_client, merchant, payload=payload)

    with patch(_DELIVERY, return_value=_Response(200)) as post:
        deliver_pending_webhooks(fake_client)

    assert json.loads(post.call_args.kwargs["content"]) == payload


# --- signing matches the test-delivery endpoint -----------------------------


def test_the_signature_is_hmac_sha256_over_the_exact_bytes_sent(fake_client):
    """A receiver that verified a test delivery must not reject live
    traffic, so both paths sign the same way over the same body."""
    merchant = _merchant(fake_client, secret="whsec_known")
    _event(fake_client, merchant)

    with patch(_DELIVERY, return_value=_Response(200)) as post:
        deliver_pending_webhooks(fake_client)

    sent_body = post.call_args.kwargs["content"]
    headers = post.call_args.kwargs["headers"]
    assert headers["X-Infinity-Signature"] == sign_outbound_payload(
        raw_body=sent_body, secret="whsec_known"
    )


def test_the_delivery_carries_event_and_timestamp_headers(fake_client):
    merchant = _merchant(fake_client)
    event = _event(fake_client, merchant)

    with patch(_DELIVERY, return_value=_Response(200)) as post:
        deliver_pending_webhooks(fake_client)

    headers = post.call_args.kwargs["headers"]
    assert headers["X-Infinity-Event"] == "collection.success"
    assert headers["X-Infinity-Delivery"] == event["id"]
    assert int(headers["X-Infinity-Timestamp"]) > 0


def test_a_merchant_without_a_signing_secret_still_receives_the_event(fake_client):
    """Generating a secret is a separate merchant action. Refusing to
    deliver without one turns "hasn't set it up yet" into "receives
    nothing", which is worse and much harder to diagnose."""
    merchant = _merchant(fake_client, secret=None)
    _event(fake_client, merchant)

    with patch(_DELIVERY, return_value=_Response(200)) as post:
        summary = deliver_pending_webhooks(fake_client)

    assert summary["delivered"] == 1
    assert "X-Infinity-Signature" not in post.call_args.kwargs["headers"]


def test_the_signing_secret_is_never_in_the_payload_or_headers(fake_client):
    merchant = _merchant(fake_client, secret="whsec_super_secret_value")
    _event(fake_client, merchant)

    with patch(_DELIVERY, return_value=_Response(200)) as post:
        deliver_pending_webhooks(fake_client)

    serialised = str(post.call_args.kwargs)
    assert "whsec_super_secret_value" not in serialised


# --- failure, backoff, and giving up ----------------------------------------


def test_a_rejected_delivery_is_marked_for_retry_not_failed(fake_client):
    merchant = _merchant(fake_client)
    event = _event(fake_client, merchant)

    with patch(_DELIVERY, return_value=_Response(500)):
        summary = deliver_pending_webhooks(fake_client)

    assert summary["failed"] == 1
    row = _row(fake_client, event["id"])
    assert row["status"] == "retrying"
    assert row["attempts"] == 1
    assert row["response_status_code"] == 500


def test_an_unreachable_endpoint_is_retried_rather_than_crashing(fake_client):
    merchant = _merchant(fake_client)
    event = _event(fake_client, merchant)

    with patch(_DELIVERY, side_effect=httpx.ConnectError("no route")):
        deliver_pending_webhooks(fake_client)

    row = _row(fake_client, event["id"])
    assert row["status"] == "retrying"
    assert row["response_status_code"] is None


def test_a_retry_is_not_attempted_again_immediately(fake_client):
    """Backoff, not a tight loop against someone else's server."""
    merchant = _merchant(fake_client)
    _event(
        fake_client,
        merchant,
        status="retrying",
        attempts=1,
        last_attempted_at=datetime.now(timezone.utc).isoformat(),
    )

    with patch(_DELIVERY, return_value=_Response(200)) as post:
        summary = deliver_pending_webhooks(fake_client)

    assert summary["due"] == 0
    post.assert_not_called()


def test_a_retry_is_attempted_once_its_backoff_has_elapsed(fake_client):
    merchant = _merchant(fake_client)
    _event(
        fake_client,
        merchant,
        status="retrying",
        attempts=1,
        last_attempted_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    )

    with patch(_DELIVERY, return_value=_Response(200)) as post:
        summary = deliver_pending_webhooks(fake_client)

    assert summary["delivered"] == 1
    post.assert_called_once()


def test_delivery_gives_up_after_the_attempt_limit(fake_client):
    """A permanently dead endpoint must not be retried forever."""
    merchant = _merchant(fake_client)
    event = _event(
        fake_client,
        merchant,
        status="retrying",
        attempts=_MAX_ATTEMPTS - 1,
        last_attempted_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )

    with patch(_DELIVERY, return_value=_Response(500)):
        deliver_pending_webhooks(fake_client)

    row = _row(fake_client, event["id"])
    assert row["status"] == "failed"
    assert row["attempts"] == _MAX_ATTEMPTS


def test_an_exhausted_event_is_never_picked_up_again(fake_client):
    merchant = _merchant(fake_client)
    _event(
        fake_client,
        merchant,
        status="retrying",
        attempts=_MAX_ATTEMPTS,
        last_attempted_at=(datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
    )

    with patch(_DELIVERY, return_value=_Response(200)) as post:
        summary = deliver_pending_webhooks(fake_client)

    assert summary["due"] == 0
    post.assert_not_called()


# --- one bad merchant cannot take out the queue -----------------------------


def test_one_failing_endpoint_does_not_stop_the_others(fake_client):
    good = _merchant(fake_client, url="https://good.example.com/hooks")
    bad = _merchant(fake_client, url="https://bad.example.com/hooks")
    _event(fake_client, bad)
    _event(fake_client, good)

    def _by_url(url, **_kwargs):
        if "bad.example.com" in url:
            raise httpx.ConnectError("down")
        return _Response(200)

    with patch(_DELIVERY, side_effect=_by_url):
        summary = deliver_pending_webhooks(fake_client)

    assert summary["delivered"] == 1
    assert summary["failed"] == 1


def test_a_row_that_raises_does_not_abort_the_sweep(fake_client):
    merchant = _merchant(fake_client)
    _event(fake_client, merchant)
    _event(fake_client, merchant)

    calls = {"n": 0}

    def _explode_once(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("something unexpected")
        return _Response(200)

    with patch(_DELIVERY, side_effect=_explode_once):
        summary = deliver_pending_webhooks(fake_client)

    assert summary["delivered"] == 1, "the second event was not attempted"


def test_an_event_with_no_target_url_is_failed_not_retried_forever(fake_client):
    merchant = _merchant(fake_client)
    event = fake_client.seed(
        "webhook_events",
        {
            "merchant_id": merchant["id"],
            "event_name": "collection.success",
            "payload": {},
            "target_url": None,
            "status": "pending",
            "attempts": 0,
        },
    )

    with patch(_DELIVERY) as post:
        deliver_event(fake_client, _row(fake_client, event["id"]))

    post.assert_not_called()
    assert _row(fake_client, event["id"])["status"] == "failed"


def test_an_undecryptable_secret_still_delivers_unsigned(fake_client):
    """A broken secret must degrade to an unsigned delivery, not silently
    stop a merchant receiving anything at all."""
    merchant = create_merchant(
        fake_client,
        webhook_url="https://merchant.example.com/hooks",
        webhook_secret_encrypted="not-a-valid-ciphertext",
    )
    _event(fake_client, merchant)

    with patch(_DELIVERY, return_value=_Response(200)) as post:
        summary = deliver_pending_webhooks(fake_client)

    assert summary["delivered"] == 1
    assert "X-Infinity-Signature" not in post.call_args.kwargs["headers"]


@pytest.mark.parametrize("code", [200, 201, 202, 204])
def test_any_2xx_counts_as_delivered(code, fake_client):
    merchant = _merchant(fake_client)
    _event(fake_client, merchant)

    with patch(_DELIVERY, return_value=_Response(code)):
        assert deliver_pending_webhooks(fake_client)["delivered"] == 1


@pytest.mark.parametrize("code", [400, 401, 404, 429, 500, 503])
def test_a_non_2xx_is_not_treated_as_delivered(code, fake_client):
    merchant = _merchant(fake_client)
    _event(fake_client, merchant)

    with patch(_DELIVERY, return_value=_Response(code)):
        assert deliver_pending_webhooks(fake_client)["delivered"] == 0
