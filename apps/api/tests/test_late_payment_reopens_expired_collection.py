"""A customer who pays after we stop waiting must still get connected.

`collection_push_expiry_minutes` is 5. Selcom keeps the prompt alive
longer, so a customer can approve after we have given up. Selcom then
sends a COMPLETED callback - which the webhook handler rejected, because
an unsigned delivery was only ever allowed to nudge a collection still
`processing`:

    if hinting_unsigned and collection.get("status") != "processing":
        raise HTTPException(401)

Every Selcom callback is unsigned, and an expired collection is `failed`,
so every late payment hit that line. Measured on 2026-10-25: Selcom's
confirmation arrives a median of **122 seconds** after our expiry write,
and 58 customers over 7 days (TZS 35,000) were charged, never credited
and never connected - with the proof of payment sitting unused in
`selcom_webhook_events` the whole time.

A collection we expired is not "resolved". It is abandoned on our clock,
not the provider's, and it is precisely the case where a late callback
carries real news.

Letting it through buys no trust: the resolver ignores everything the
delivery claims and re-queries Selcom over our own authenticated
connection. The callback only says which order to ask about.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.routers.webhooks import _expired_within_grace

GRACE = 24


def _expired(**over):
    base = {
        "status": "failed",
        "failure_reason_code": "expired",
        "failed_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
    }
    base.update(over)
    return base


# --- what may be reopened ---------------------------------------------


def test_a_collection_we_expired_may_be_reopened_by_a_completed_callback():
    """The case that cost 58 customers their service."""
    assert _expired_within_grace(_expired(), payment_status="COMPLETED", grace_hours=GRACE) is True


def test_the_claim_is_matched_case_insensitively():
    assert _expired_within_grace(_expired(), payment_status="completed", grace_hours=GRACE) is True


def test_it_still_works_near_the_edge_of_the_grace_window():
    old = _expired(failed_at=(datetime.now(timezone.utc) - timedelta(hours=23)).isoformat())

    assert _expired_within_grace(old, payment_status="COMPLETED", grace_hours=GRACE) is True


# --- what may not -----------------------------------------------------


def test_a_provider_decline_is_never_reopened():
    """Only a collection *we* gave up on. A decline is the provider's own
    answer and an unsigned delivery has no standing to overturn it."""
    declined = _expired(failure_reason_code="provider_declined")

    assert _expired_within_grace(declined, payment_status="COMPLETED", grace_hours=GRACE) is False


def test_a_cancelled_payment_is_never_reopened():
    cancelled = _expired(failure_reason_code="user_cancelled")

    assert _expired_within_grace(cancelled, payment_status="COMPLETED", grace_hours=GRACE) is False


def test_a_successful_collection_is_never_touched():
    """Guards against a replayed callback re-crediting a payment."""
    done = _expired(status="successful")

    assert _expired_within_grace(done, payment_status="COMPLETED", grace_hours=GRACE) is False


def test_a_pending_claim_does_not_spend_a_provider_call():
    """The claim is never trusted, but it decides whether asking Selcom is
    worth a call at all. Without this, every late PENDING chirp about a
    payment nobody made would re-query the provider."""
    assert _expired_within_grace(_expired(), payment_status="PENDING", grace_hours=GRACE) is False
    assert _expired_within_grace(_expired(), payment_status="", grace_hours=GRACE) is False


def test_outside_the_grace_window_it_is_left_alone():
    stale = _expired(failed_at=(datetime.now(timezone.utc) - timedelta(hours=30)).isoformat())

    assert _expired_within_grace(stale, payment_status="COMPLETED", grace_hours=GRACE) is False


def test_disabling_the_grace_window_disables_this_entirely():
    assert _expired_within_grace(_expired(), payment_status="COMPLETED", grace_hours=0) is False


@pytest.mark.parametrize("bad", [None, "", "not-a-date"])
def test_an_unusable_failed_at_is_not_reopened(bad):
    """Never guess. Without a reliable close time there is no way to know
    whether the grace window has passed."""
    assert _expired_within_grace(
        _expired(failed_at=bad), payment_status="COMPLETED", grace_hours=GRACE
    ) is False


def test_a_naive_timestamp_is_treated_as_utc():
    """The column holds naive timestamps; comparing one as local time
    would move the window by three hours in Tanzania."""
    naive = _expired(
        failed_at=(datetime.now(timezone.utc) - timedelta(minutes=5)).replace(tzinfo=None).isoformat()
    )

    assert _expired_within_grace(naive, payment_status="COMPLETED", grace_hours=GRACE) is True
