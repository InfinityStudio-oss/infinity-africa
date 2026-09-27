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

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from app.config import get_settings
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


# --- the app must actually start --------------------------------------------


def test_the_app_starts_with_the_delivery_scheduler_enabled(monkeypatch):
    """Regression cover for a production outage.

    Wiring the scheduler in placed the new loop function directly above
    `lifespan` and, in doing so, took `@contextlib.asynccontextmanager`
    with it — leaving `lifespan` undecorated and the loop wrapped as a
    context manager. uvicorn failed with "Application startup failed.
    Exiting." and the API would not boot.

    `import app.main` succeeded throughout, which is exactly why it was
    missed: importing the module never runs the lifespan. Entering
    TestClient as a context manager does, the same way uvicorn does.
    """
    import inspect

    from fastapi.testclient import TestClient

    import app.main as main_module

    monkeypatch.setenv("WEBHOOK_DELIVERY_INTERVAL_SECONDS", "30")
    get_settings.cache_clear()

    with TestClient(main_module.app) as test_client:
        assert test_client.get("/health").status_code == 200

    # The exact shape mix-up the outage came down to, asserted directly.
    assert inspect.iscoroutinefunction(main_module._webhook_delivery_loop), (
        "_webhook_delivery_loop must stay a plain coroutine function — "
        "decorating it makes create_task() schedule the wrong object"
    )


def test_every_scheduler_starter_returns_a_task_or_none(monkeypatch):
    """Each starter either schedules real work or opts out. Returning
    anything else (a coroutine, a context manager) is the failure mode
    that took the API down."""
    import asyncio

    import app.main as main_module

    monkeypatch.setenv("WEBHOOK_DELIVERY_INTERVAL_SECONDS", "30")
    get_settings.cache_clear()

    async def _check():
        for starter in (
            main_module._start_checkout_reconciliation_task,
            main_module._start_disbursement_reconciliation_task,
            main_module._start_webhook_delivery_task,
        ):
            task = starter()
            assert task is None or isinstance(task, asyncio.Task), (
                f"{starter.__name__} returned {type(task).__name__}"
            )
            if task is not None:
                task.cancel()

    asyncio.run(_check())


def test_a_test_delivery_is_distinguishable_from_a_real_one():
    """The test payload deliberately reads `event: collection.success` so a
    merchant exercises their real success handler — which means a partner
    keying only on that field would fulfil a fake order. Three independent
    tells must therefore stay present; the partner doc tells integrators to
    check them.
    """
    from app.routers.merchant_webhooks import _sample_test_payload

    payload = _sample_test_payload({"merchant_code": "27413765"})

    assert payload["test"] is True
    assert payload["collection_id"] == "00000000-0000-0000-0000-000000000000"
    assert payload["reference"] == "TXN-TEST0000"


def test_a_real_delivery_never_claims_to_be_a_test(fake_client):
    """The inverse, and the one that actually matters: if a real event ever
    carried `test: true`, a correctly-written partner would silently drop a
    genuine payment."""
    merchant = _merchant(fake_client)
    _event(fake_client, merchant, payload={"event": "collection.success", "collection_id": "col-1"})

    with patch(_DELIVERY, return_value=_Response(200)) as post:
        deliver_pending_webhooks(fake_client)

    body = json.loads(post.call_args.kwargs["content"])
    assert "test" not in body


# --- sandbox collections emit events too ------------------------------------


def test_a_sandbox_collection_queues_the_same_event_a_real_one_would(fake_client):
    """Without this a partner cannot test their webhook handler at all:
    Send Test Webhook only ever sends one fixed payload, and a live push
    costs real money."""
    from app.services.sandbox_collections import execute_sandbox_collection

    merchant = _merchant(fake_client)

    execute_sandbox_collection(
        fake_client,
        merchant_id=uuid.UUID(merchant["id"]),
        external_method="wallet_push",
        amount=Decimal("1000.00"),
        currency="TZS",
        customer_phone="+255712345678",
        customer_name=None,
        merchant_reference="TEST-001",
        description=None,
        source="API_WALLET_PUSH",
        api_key_id=uuid.uuid4(),
        simulate_status="successful",
    )

    events = fake_client.table("webhook_events")._table.rows
    assert len(events) == 1
    assert events[0]["event_name"] == "collection.success"


def test_a_sandbox_event_says_it_is_sandbox(fake_client):
    """A simulated event must be distinguishable from money actually
    arriving — the same hazard the `test` flag guards on Send Test
    Webhook."""
    from app.services.sandbox_collections import execute_sandbox_collection

    merchant = _merchant(fake_client)
    execute_sandbox_collection(
        fake_client,
        merchant_id=uuid.UUID(merchant["id"]),
        external_method="wallet_push",
        amount=Decimal("1000.00"),
        currency="TZS",
        customer_phone="+255712345678",
        customer_name=None,
        merchant_reference="TEST-001",
        description=None,
        source="API_WALLET_PUSH",
        api_key_id=uuid.uuid4(),
        simulate_status="successful",
    )

    payload = fake_client.table("webhook_events")._table.rows[0]["payload"]
    assert payload["sandbox"] is True
    assert payload["status"] == "successful"


def test_a_simulated_failure_carries_a_normalized_reason(fake_client):
    from app.services.sandbox_collections import execute_sandbox_collection

    merchant = _merchant(fake_client)
    execute_sandbox_collection(
        fake_client,
        merchant_id=uuid.UUID(merchant["id"]),
        external_method="wallet_push",
        amount=Decimal("1000.00"),
        currency="TZS",
        customer_phone="+255712345678",
        customer_name=None,
        merchant_reference="TEST-002",
        description=None,
        source="API_WALLET_PUSH",
        api_key_id=uuid.uuid4(),
        simulate_status="failed",
    )

    event = fake_client.table("webhook_events")._table.rows[0]
    assert event["event_name"] == "collection.failed"
    assert event["payload"]["failure_reason_code"] == "unknown_provider_error"


def test_a_merchant_with_no_webhook_url_gets_no_sandbox_event(fake_client):
    """enqueue_webhook_event no-ops without a configured URL, and a
    sandbox run must not change that."""
    from app.services.sandbox_collections import execute_sandbox_collection

    merchant = create_merchant(fake_client)  # no webhook_url

    execute_sandbox_collection(
        fake_client,
        merchant_id=uuid.UUID(merchant["id"]),
        external_method="wallet_push",
        amount=Decimal("1000.00"),
        currency="TZS",
        customer_phone="+255712345678",
        customer_name=None,
        merchant_reference="TEST-003",
        description=None,
        source="API_WALLET_PUSH",
        api_key_id=uuid.uuid4(),
        simulate_status="successful",
    )

    assert fake_client.table("webhook_events")._table.rows == []


# --- the published example must match what we actually send -----------------


def test_the_documented_verification_example_matches_our_signing():
    """The partner docs publish a verification snippet. If our signing ever
    changed without that snippet changing, every integrator's verifier
    would start rejecting real deliveries — and we would hear about it
    from them, not from a test.
    """
    secret = "whsec_example_value"
    raw = b'{"event":"collection.success","collection_id":"abc"}'

    ours = sign_outbound_payload(raw_body=raw, secret=secret)
    # Exactly the expression published at /developers/direct-wallet-push.
    theirs = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    assert hmac.compare_digest(ours, theirs)


def test_the_signature_covers_the_body_alone_not_the_timestamp():
    """The docs tell integrators to verify over the body only. If the
    timestamp were ever folded into the signed material, every receiver
    that followed those docs would break."""
    secret = "whsec_example_value"
    raw = b'{"event":"collection.success"}'

    body_only = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    assert sign_outbound_payload(raw_body=raw, secret=secret) == body_only


def test_the_sweep_does_not_block_the_event_loop():
    """A slow receiver must not stall the API.

    `deliver_pending_webhooks` is synchronous and uses blocking httpx.
    Called directly from the async scheduler it froze the whole event loop
    for the length of the sweep — up to 50 sequential POSTs at an 8-second
    timeout. Survivable at a trickle; not during a billing run, when every
    subscriber paying at once is also every subscriber waiting on an API
    that has stopped answering.

    Asserts the loop keeps ticking while a deliberately slow sweep runs.
    """
    import asyncio
    import time

    import app.main as main_module

    def _slow_sweep(_client):
        time.sleep(0.4)  # stands in for real network latency
        return {"due": 1, "delivered": 1, "failed": 0}

    async def _check():
        ticks = 0

        async def _heartbeat():
            nonlocal ticks
            for _ in range(8):
                await asyncio.sleep(0.05)
                ticks += 1

        beat = asyncio.create_task(_heartbeat())
        # Exactly how main.py calls it.
        await asyncio.to_thread(_slow_sweep, None)
        await beat
        return ticks

    ticks = asyncio.run(_check())
    assert ticks == 8, (
        f"the event loop only ticked {ticks}/8 times during the sweep — "
        "delivery is blocking the API"
    )
    assert hasattr(main_module, "_webhook_delivery_loop")


def test_main_awaits_the_sweep_in_a_thread():
    """The shape above only holds if main.py actually offloads it."""
    from pathlib import Path

    source = Path(main_module_file()).read_text(encoding="utf-8")
    assert "asyncio.to_thread(deliver_pending_webhooks" in source, (
        "the sweep is being called directly on the event loop again"
    )


def main_module_file() -> str:
    import app.main as main_module

    return main_module.__file__
