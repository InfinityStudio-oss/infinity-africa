"""The reference receiver we hand to partners must actually be correct.

docs/examples/webhook_receiver.py is example code for the *receiving*
side - any partner or merchant that integrates with us. Shipping an
integration guide whose code has never been run would be worse than
shipping none, because it would be trusted.

These tests cover the cases the rollout promises: a valid delivery is
accepted, an altered payload is rejected, a missing or wrong signature is
rejected, a replay is refused, a retry is safe, and service is activated
exactly once.

The signature in every test is produced by **our own**
`sign_outbound_payload`, not by reimplementing HMAC here. That is the
point: it proves the example verifies what InfinityPay actually sends,
rather than agreeing with a second copy of the same assumption.

**This tests the example. It does not test any partner's integration.**
No partner receiver is verified until their own code has been run against
these cases.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.services.webhooks import sign_outbound_payload

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = REPO_ROOT / "docs" / "examples" / "webhook_receiver.py"

SECRET = "f" * 32 + "a" * 32  # 64 hex chars, same shape as a real one
MERCHANT_ID = "6f1c9a52-0b7e-4f1a-9c3d-2a8e7b4d5c10"
DELIVERY_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(scope="module")
def receiver():
    if not EXAMPLE.is_file():
        pytest.fail(f"the reference receiver handed to partners is missing: {EXAMPLE}")
    spec = importlib.util.spec_from_file_location("webhook_receiver_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("webhook_receiver_example", module)
    spec.loader.exec_module(module)
    return module


class Store:
    """A correct DeliveryStore: one atomic claim per delivery id."""

    def __init__(self):
        self.seen: set[str] = set()

    def mark_seen(self, delivery_id: str) -> bool:
        if delivery_id in self.seen:
            return False
        self.seen.add(delivery_id)
        return True


@pytest.fixture
def activations():
    return []


@pytest.fixture
def store():
    return Store()


def payload(**overrides) -> bytes:
    body = {
        "merchant_id": MERCHANT_ID,
        "reference": "INV-10432",
        "amount": "5000.00",
        "currency": "TZS",
        "status": "successful",
    }
    body.update(overrides)
    return json.dumps(body).encode("utf-8")


def headers(raw_body: bytes, *, signature: str | None = None, **overrides) -> dict:
    base = {
        "Content-Type": "application/json",
        "X-Infinity-Event": "collection.successful",
        "X-Infinity-Delivery": DELIVERY_ID,
        "X-Infinity-Timestamp": "1792486252",
        "X-Infinity-Signature": (
            signature
            if signature is not None
            else sign_outbound_payload(raw_body=raw_body, secret=SECRET)
        ),
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def deliver(receiver, store, activations, raw_body, hdrs, *, now=1792486252.0):
    return receiver.handle_delivery(
        raw_body=raw_body,
        headers=hdrs,
        secret=SECRET,
        store=store,
        activate=activations.append,
        expected_merchant_id=MERCHANT_ID,
        now=now,
    )


# --- a valid delivery --------------------------------------------------


def test_a_valid_delivery_is_accepted_and_activates_once(receiver, store, activations):
    raw = payload()

    status = deliver(receiver, store, activations, raw, headers(raw))

    assert status == 200
    assert len(activations) == 1
    assert activations[0]["reference"] == "INV-10432"
    assert activations[0]["amount"] == 5000.0


def test_our_own_signing_function_is_what_the_example_verifies(receiver):
    """If the two ever diverge, every partner verification breaks at once."""
    raw = payload()
    ours = sign_outbound_payload(raw_body=raw, secret=SECRET)

    assert receiver.verify_signature(raw_body=raw, signature_header=ours, secret=SECRET)


def test_an_uppercase_signature_header_still_verifies(receiver):
    """Some HTTP stacks and proxies normalise header case. Rejecting on it
    would look exactly like an attack to a partner who is doing nothing
    wrong."""
    raw = payload()
    ours = sign_outbound_payload(raw_body=raw, secret=SECRET).upper()

    assert receiver.verify_signature(raw_body=raw, signature_header=ours, secret=SECRET)


# --- rejection ---------------------------------------------------------


def test_an_altered_payload_is_rejected(receiver, store, activations):
    """The attack that matters: a captured delivery with the amount or the
    reference changed, replayed with the original signature."""
    raw = payload()
    signed = headers(raw)
    tampered = payload(amount="500000.00")

    status = deliver(receiver, store, activations, tampered, signed)

    assert status == 401
    assert activations == []


def test_a_changed_reference_is_rejected(receiver, store, activations):
    raw = payload()
    signed = headers(raw)
    tampered = payload(reference="INV-99999")

    status = deliver(receiver, store, activations, tampered, signed)

    assert status == 401
    assert activations == []


def test_a_missing_signature_is_rejected(receiver, store, activations):
    """The state the pre-enforcement integrations are in today. Once a
    secret is configured there is no signature to verify, so there is
    nothing to accept.

    Note the header is *removed*, not set to None: `headers(signature=None)`
    means "compute the real one", and using it here made this test pass
    against a perfectly valid signature.
    """
    raw = payload()
    hdrs = headers(raw)
    del hdrs["X-Infinity-Signature"]

    status = deliver(receiver, store, activations, raw, hdrs)

    assert status == 401
    assert activations == []


def test_a_wrong_signature_is_rejected(receiver, store, activations):
    raw = payload()

    status = deliver(receiver, store, activations, raw, headers(raw, signature="deadbeef" * 8))

    assert status == 401
    assert activations == []


def test_a_signature_from_another_secret_is_rejected(receiver, store, activations):
    """What a rotation looks like mid-flight, and what a forged event from
    someone holding a different merchant's secret looks like."""
    raw = payload()
    other = sign_outbound_payload(raw_body=raw, secret="0" * 64)

    status = deliver(receiver, store, activations, raw, headers(raw, signature=other))

    assert status == 401
    assert activations == []


def test_a_reserialised_body_does_not_verify(receiver):
    """The most common integration mistake: verifying the re-encoded JSON
    instead of the bytes received. Documented, and proven here so the
    warning is not hand-waving."""
    raw = payload()
    signature = sign_outbound_payload(raw_body=raw, secret=SECRET)
    reserialised = json.dumps(json.loads(raw), indent=2, sort_keys=True).encode("utf-8")

    assert not receiver.verify_signature(
        raw_body=reserialised, signature_header=signature, secret=SECRET
    )


# --- only act on what is expected --------------------------------------


def test_an_authentic_event_for_another_merchant_does_not_activate(receiver, store, activations):
    raw = payload(merchant_id="00000000-0000-0000-0000-000000000000")

    status = deliver(receiver, store, activations, raw, headers(raw))

    assert status == 400
    assert activations == []


def test_a_pending_payment_does_not_activate(receiver, store, activations):
    """Accepted as authentic - so we stop retrying - but nothing is
    activated. Never treat "an event arrived" as "money arrived"."""
    raw = payload(status="pending")

    status = deliver(receiver, store, activations, raw, headers(raw))

    assert status == 200
    assert activations == []


def test_a_foreign_currency_does_not_activate(receiver, store, activations):
    raw = payload(currency="USD")

    status = deliver(receiver, store, activations, raw, headers(raw))

    assert status == 400
    assert activations == []


@pytest.mark.parametrize("amount", ["0.00", "-5000.00"])
def test_a_non_positive_amount_does_not_activate(receiver, store, activations, amount):
    raw = payload(amount=amount)

    status = deliver(receiver, store, activations, raw, headers(raw))

    assert status == 400
    assert activations == []


def test_an_unrelated_event_type_is_accepted_without_activating(receiver, store, activations):
    raw = payload()
    hdrs = headers(raw)
    hdrs["X-Infinity-Event"] = "withdrawal.completed"

    status = deliver(receiver, store, activations, raw, hdrs)

    assert status == 200
    assert activations == []


# --- replay, retries and duplicates ------------------------------------


def test_a_replayed_delivery_activates_only_once(receiver, store, activations):
    """A byte-identical delivery with a valid signature - indistinguishable
    from the real one, which is why deduplication and not signature
    checking is what stops it."""
    raw = payload()
    hdrs = headers(raw)

    first = deliver(receiver, store, activations, raw, hdrs)
    second = deliver(receiver, store, activations, raw, hdrs)

    assert (first, second) == (200, 200)
    assert len(activations) == 1, "service was activated twice for one payment"


def test_a_retry_after_our_timeout_is_safe(receiver, store, activations):
    """We retry on timeout, so the receiver can see the same delivery again
    having already recorded it. Returning 200 and doing nothing is the
    correct outcome."""
    raw = payload()
    hdrs = headers(raw)
    deliver(receiver, store, activations, raw, hdrs)

    for _ in range(5):
        assert deliver(receiver, store, activations, raw, hdrs) == 200

    assert len(activations) == 1


def test_two_genuinely_different_payments_both_activate(receiver, store, activations):
    """Deduplication must key on the delivery id, not on the payload. Two
    real payments of the same amount are not duplicates."""
    first = payload(reference="INV-1")
    second = payload(reference="INV-2")

    deliver(receiver, store, activations, first, headers(first))
    deliver(
        receiver,
        store,
        activations,
        second,
        headers(second, **{"X-Infinity-Delivery": "99999999-8888-7777-6666-555555555555"}),
    )

    assert len(activations) == 2


def test_a_delivery_with_no_delivery_id_is_refused(receiver, store, activations):
    """Without it there is no way to deduplicate, so there is no way to act
    safely. Refusing is better than activating something twice."""
    raw = payload()
    hdrs = headers(raw)
    del hdrs["X-Infinity-Delivery"]

    status = deliver(receiver, store, activations, raw, hdrs)

    assert status == 400
    assert activations == []


def test_the_delivery_id_is_claimed_before_activation(receiver, activations):
    """Ordering is the whole of retry safety. If activation ran first and
    then the claim failed, a crash in between would leave service
    activated and the delivery unrecorded - so the retry would activate it
    again."""
    order = []

    class Recording(Store):
        def mark_seen(self, delivery_id: str) -> bool:
            order.append("claim")
            return super().mark_seen(delivery_id)

    def activate(_details):
        order.append("activate")

    raw = payload()
    receiver.handle_delivery(
        raw_body=raw,
        headers=headers(raw),
        secret=SECRET,
        store=Recording(),
        activate=activate,
        expected_merchant_id=MERCHANT_ID,
        now=1792486252.0,
    )

    assert order == ["claim", "activate"]


# --- timestamp handling ------------------------------------------------


def test_a_stale_delivery_is_refused(receiver, store, activations):
    raw = payload()

    status = deliver(
        receiver, store, activations, raw, headers(raw), now=1792486252.0 + 60 * 60 * 48
    )

    assert status == 400


def test_a_missing_timestamp_is_not_treated_as_a_failure(receiver, store, activations):
    """The signature does not cover the timestamp, so rejecting on its
    absence buys nothing and would discard real payments."""
    raw = payload()
    hdrs = headers(raw)
    del hdrs["X-Infinity-Timestamp"]

    status = deliver(receiver, store, activations, raw, hdrs)

    assert status == 200
    assert len(activations) == 1


def test_an_unparsable_timestamp_is_not_treated_as_a_failure(receiver, store, activations):
    raw = payload()

    status = deliver(receiver, store, activations, raw, headers(raw, **{"X-Infinity-Timestamp": "soon"}))

    assert status == 200


# --- malformed bodies --------------------------------------------------


def test_a_signed_but_unparsable_body_is_refused(receiver, store, activations):
    """Authentic and still unusable - so it must not reach the business
    logic."""
    raw = b"{not json"

    status = deliver(receiver, store, activations, raw, headers(raw))

    assert status == 400
    assert activations == []


def test_a_signed_json_array_is_refused(receiver, store, activations):
    raw = b'["collection.successful"]'

    status = deliver(receiver, store, activations, raw, headers(raw))

    assert status == 400
    assert activations == []
