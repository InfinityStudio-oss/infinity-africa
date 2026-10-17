"""Sending queued SMS, and the many ways a provider can answer.

The costly mistake in this module is not a message that fails to send -
it is a message sent twice, because the provider's answer was ambiguous
and we decided to "try again cleanly" with a fresh idempotency key. Most
of what follows exists to hold that line.

The provider is mocked throughout. Nothing in the automated suite may
reach a real gateway, because a real gateway charges real credits and
texts real merchants.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.core.rate_limit import _limiter
from app.services import sms_dispatch, sms_provider
from app.services.sms_dispatch import MAX_ATTEMPTS, dispatch_pending_sms
from app.services.sms_provider import SmsResult
from tests.factories import create_merchant


@pytest.fixture(autouse=True)
def _sms_on(monkeypatch):
    monkeypatch.setenv("OASIS_SMS_ENABLED", "true")
    monkeypatch.setenv("OASIS_SMS_SENDER_ID", "INFINITYPAY")
    monkeypatch.setenv("OASIS_SMS_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OASIS_SMS_RATE_LIMIT_PER_MINUTE", "240")
    get_settings.cache_clear()
    _limiter._hits.clear()
    yield
    _limiter._hits.clear()
    get_settings.cache_clear()


def _queue(fake_client, **overrides) -> dict:
    merchant = create_merchant(fake_client)
    row = {
        "merchant_id": merchant["id"],
        # A transactional message. Was "collection_alert" until that
        # purpose was retired on 2026-10-17; these tests are about the
        # worker's mechanics - claiming, retrying, throttling - not about
        # which kind of message it happens to be carrying.
        "purpose": "withdrawal_complete",
        "disbursement_id": str(uuid.uuid4()),
        "recipient_phone": "255712000001",
        "sender_id": "INFINITYPAY",
        "body": "InfinityPay: Umepokea TZS 10,000.",
        "status": "queued",
        "attempts": 0,
        "idempotency_key": f"ipay-c-{uuid.uuid4().hex}",
        "next_attempt_at": datetime.now(timezone.utc).isoformat(),
    }
    row.update(overrides)
    return fake_client.seed("sms_messages", row)


def _row(fake_client, message_id):
    return next(r for r in fake_client.table("sms_messages")._table.rows if r["id"] == message_id)


def _answer(monkeypatch, result: SmsResult, record=None):
    """Replace the provider with one canned answer, recording the calls."""
    calls: list[dict] = []

    def _send(*, to, sender, message, idempotency_key, dry_run=False):
        calls.append(
            {"to": to, "sender": sender, "message": message, "key": idempotency_key}
        )
        return result

    monkeypatch.setattr(sms_dispatch, "send_sms", _send)
    return calls if record is None else record


# --- the happy path ----------------------------------------------------


def test_a_queued_message_is_sent_and_marked_sent(fake_client, monkeypatch):
    row = _queue(fake_client)
    calls = _answer(monkeypatch, SmsResult(outcome="sent", status_code=200, provider_ref="pr-1"))

    summary = dispatch_pending_sms(fake_client)

    assert summary["alerts"] == 1
    assert len(calls) == 1
    saved = _row(fake_client, row["id"])
    assert saved["status"] == "sent"
    assert saved["provider_ref"] == "pr-1"
    assert saved["sent_at"]


def test_the_frozen_text_and_key_are_what_get_sent(fake_client, monkeypatch):
    """Nothing is re-rendered at send time. The row is the message."""
    row = _queue(fake_client, body="exact bytes", idempotency_key="ipay-c-fixed")
    calls = _answer(monkeypatch, SmsResult(outcome="sent", status_code=200))

    dispatch_pending_sms(fake_client)

    assert calls[0]["message"] == "exact bytes"
    assert calls[0]["key"] == "ipay-c-fixed"


def test_nothing_is_dispatched_while_the_feature_is_off(fake_client, monkeypatch):
    monkeypatch.setenv("OASIS_SMS_ENABLED", "false")
    get_settings.cache_clear()
    _queue(fake_client)
    calls = _answer(monkeypatch, SmsResult(outcome="sent"))

    dispatch_pending_sms(fake_client)

    assert calls == []


# --- ambiguous answers must never become a second message --------------


def test_a_pending_response_is_terminal_and_never_resent(fake_client, monkeypatch):
    """202: the provider could not confirm in time but documents the
    message as most likely sent and charged. Resending is the duplicate."""
    row = _queue(fake_client)
    calls = _answer(monkeypatch, SmsResult(outcome="pending", status_code=202))

    dispatch_pending_sms(fake_client)
    dispatch_pending_sms(fake_client)

    assert len(calls) == 1
    assert _row(fake_client, row["id"])["status"] == "pending"


def test_an_already_processed_response_counts_as_sent(fake_client, monkeypatch):
    """409 already_processed. Documented: treat as already sent, do not
    resend with a new key."""
    row = _queue(fake_client)
    _answer(monkeypatch, SmsResult(outcome="duplicate", status_code=409))

    dispatch_pending_sms(fake_client)

    assert _row(fake_client, row["id"])["status"] == "sent"


def test_an_unknown_outcome_is_retried_with_the_same_key(fake_client, monkeypatch):
    """A timeout. The key is what makes the retry safe: the provider
    replays the original response rather than sending again."""
    row = _queue(fake_client, idempotency_key="ipay-c-stable")
    calls = _answer(monkeypatch, SmsResult(outcome="unknown", error="Timed out"))

    dispatch_pending_sms(fake_client)
    saved = _row(fake_client, row["id"])
    saved["next_attempt_at"] = datetime.now(timezone.utc).isoformat()
    dispatch_pending_sms(fake_client)

    assert [c["key"] for c in calls] == ["ipay-c-stable", "ipay-c-stable"]


def test_an_unknown_outcome_stops_at_the_attempt_ceiling(fake_client, monkeypatch):
    """Visible as 'unknown' rather than retried forever: we genuinely do
    not know whether these were sent, and that is worth an operator
    looking at."""
    row = _queue(fake_client, attempts=MAX_ATTEMPTS - 1)
    _answer(monkeypatch, SmsResult(outcome="unknown", error="Timed out"))

    dispatch_pending_sms(fake_client)

    assert _row(fake_client, row["id"])["status"] == "unknown"


def test_a_sent_message_is_never_picked_up_again(fake_client, monkeypatch):
    _queue(fake_client, status="sent")
    calls = _answer(monkeypatch, SmsResult(outcome="sent"))

    dispatch_pending_sms(fake_client)

    assert calls == []


# --- crash recovery ----------------------------------------------------


def test_an_abandoned_claim_returns_to_the_queue(fake_client, monkeypatch):
    """A worker that died mid-send. The lock expires, the row comes back,
    and the unchanged key makes resending it safe."""
    row = _queue(
        fake_client,
        status="sending",
        locked_by="dead-worker",
        locked_until=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    )
    calls = _answer(monkeypatch, SmsResult(outcome="sent", status_code=200))

    summary = dispatch_pending_sms(fake_client)

    assert summary["reclaimed"] == 1
    assert len(calls) == 1
    assert _row(fake_client, row["id"])["status"] == "sent"


def test_a_live_claim_is_left_alone(fake_client, monkeypatch):
    """Still in flight. Reclaiming it here is how one message becomes two."""
    _queue(
        fake_client,
        status="sending",
        locked_by="busy-worker",
        locked_until=(datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat(),
    )
    calls = _answer(monkeypatch, SmsResult(outcome="sent"))

    summary = dispatch_pending_sms(fake_client)

    assert summary["reclaimed"] == 0
    assert calls == []


def test_a_crash_after_acceptance_cannot_mint_a_new_key(fake_client, monkeypatch):
    """The specific hazard the brief names. The key is written before the
    first attempt and lives on the row, so no code path can generate a
    different one for a retry."""
    row = _queue(fake_client, idempotency_key="ipay-c-written-first")
    before = _row(fake_client, row["id"])["idempotency_key"]
    _answer(monkeypatch, SmsResult(outcome="unknown"))

    dispatch_pending_sms(fake_client)

    assert _row(fake_client, row["id"])["idempotency_key"] == before


# --- provider refusals -------------------------------------------------


def test_insufficient_credits_parks_the_message_instead_of_retrying(fake_client, monkeypatch):
    """402. Retrying cannot help until somebody buys credits, and a queue
    of failing sends hammering the provider is the retry storm the brief
    warns about."""
    row = _queue(fake_client)
    calls = _answer(
        monkeypatch, SmsResult(outcome="no_credits", status_code=402, error="Insufficient credits")
    )

    dispatch_pending_sms(fake_client)
    dispatch_pending_sms(fake_client)

    assert len(calls) == 1
    saved = _row(fake_client, row["id"])
    assert saved["status"] == "failed"
    assert "credits" in saved["last_error"].lower()


def test_a_configuration_error_fails_visibly_rather_than_churning(fake_client, monkeypatch):
    """403: unapproved sender, failed KYC. A person has to fix it."""
    row = _queue(fake_client)
    calls = _answer(
        monkeypatch, SmsResult(outcome="config", status_code=403, error="Sender not approved")
    )

    dispatch_pending_sms(fake_client)
    dispatch_pending_sms(fake_client)

    assert len(calls) == 1
    assert _row(fake_client, row["id"])["status"] == "failed"


def test_throttling_reschedules_without_spending_an_attempt(fake_client, monkeypatch):
    """429 does not consume the idempotency key and is not the message's
    fault, so it must not burn one of its five attempts."""
    row = _queue(fake_client, attempts=0)
    _answer(
        monkeypatch,
        SmsResult(outcome="throttled", status_code=429, retry_after_seconds=30),
    )

    dispatch_pending_sms(fake_client)

    saved = _row(fake_client, row["id"])
    assert saved["status"] == "queued"
    assert saved["attempts"] == 0
    assert saved["next_attempt_at"] > datetime.now(timezone.utc).isoformat()


def test_a_refused_message_is_retried(fake_client, monkeypatch):
    """502: the gateway refused it and did not charge, so retrying costs
    nothing and may well work."""
    row = _queue(fake_client)
    _answer(monkeypatch, SmsResult(outcome="failed", status_code=502, error="refused"))

    dispatch_pending_sms(fake_client)

    saved = _row(fake_client, row["id"])
    assert saved["status"] == "failed"
    assert saved["attempts"] == 1


# --- our own budget ----------------------------------------------------


def test_our_rate_limit_requeues_rather_than_failing(fake_client, monkeypatch):
    """The account limit is 300/minute and we reserve headroom under it.
    A message held back by our own budget has not failed and must not
    spend an attempt."""
    monkeypatch.setenv("OASIS_SMS_RATE_LIMIT_PER_MINUTE", "1")
    get_settings.cache_clear()
    first = _queue(fake_client)
    second = _queue(fake_client)
    calls = _answer(monkeypatch, SmsResult(outcome="sent", status_code=200))

    dispatch_pending_sms(fake_client)

    assert len(calls) == 1
    statuses = {_row(fake_client, r["id"])["status"] for r in (first, second)}
    assert statuses == {"sent", "queued"}


def test_the_batch_is_bounded(fake_client, monkeypatch):
    monkeypatch.setenv("OASIS_SMS_BATCH_SIZE", "2")
    get_settings.cache_clear()
    for _ in range(5):
        _queue(fake_client)
    calls = _answer(monkeypatch, SmsResult(outcome="sent", status_code=200))

    dispatch_pending_sms(fake_client)

    assert len(calls) == 2


def test_transactional_messages_are_drained_before_announcements(fake_client, monkeypatch):
    """A 60-merchant announcement must not leave a merchant's payout
    confirmation waiting behind it."""
    _queue(fake_client, purpose="announcement", disbursement_id=None, body="announcement")
    _queue(fake_client, body="alert")
    order: list[str] = []

    def _send(*, to, sender, message, idempotency_key, dry_run=False):
        order.append(message)
        return SmsResult(outcome="sent", status_code=200)

    monkeypatch.setattr(sms_dispatch, "send_sms", _send)
    dispatch_pending_sms(fake_client)

    assert order[0] == "alert"


# --- the adapter's own classification ----------------------------------


class _Response:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._body


@pytest.mark.parametrize(
    ("status_code", "body", "expected"),
    [
        (200, {"status": "sent"}, "sent"),
        (200, {"status": "sent", "idempotent_replay": True}, "duplicate"),
        (202, {"status": "pending"}, "pending"),
        (202, {"status": "processing", "background": True}, "pending"),
        (409, {"already_processed": True}, "duplicate"),
        (429, {"retry_after_seconds": 12}, "throttled"),
        (402, {"credits_required": 5, "credits_available": 0}, "no_credits"),
        (403, {"error": "sender not approved"}, "config"),
        (422, {"idempotency_key_reused": True}, "config"),
        (400, {"error": "invalid numbers"}, "config"),
        (502, {"status": "failed"}, "failed"),
        (503, {}, "failed"),
        (500, {}, "unknown"),
    ],
)
def test_every_documented_response_maps_to_the_right_outcome(status_code, body, expected):
    result = sms_provider._classify(_Response(status_code, body))
    assert result.outcome == expected


def test_the_replay_header_alone_is_enough_to_mean_duplicate():
    result = sms_provider._classify(
        _Response(200, {"status": "sent"}, {"Idempotent-Replayed": "true"})
    )
    assert result.outcome == "duplicate"


def test_a_throttle_respects_retry_after():
    result = sms_provider._classify(_Response(429, {}, {"Retry-After": "45"}))
    assert result.retry_after_seconds == 45
