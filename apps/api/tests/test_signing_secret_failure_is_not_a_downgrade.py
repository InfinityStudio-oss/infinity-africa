"""A secret we cannot read must not become a delivery we do not sign.

`_secret_for` returned None in two completely different situations: the
merchant never configured signing, and the merchant configured signing but
the ciphertext would not decrypt. The caller could not tell them apart, so
the second case silently sent an **unsigned** payload to a receiver that
had deliberately turned verification on.

Both outcomes of that are bad. A receiver that checks signatures rejects
the delivery, and a real payment notification is lost for a reason nobody
can see. A receiver that accepts it proves it would accept a forged one
too.

So the two cases are now distinct. No secret configured still means
unsigned delivery — that is the documented behaviour for a merchant who
has never generated one, and refusing to deliver to them would turn
"hasn't set a secret yet" into "receives nothing". A secret that cannot be
decrypted withholds the delivery, counts the attempt so it still backs off
and eventually stops, and leaves the row visible as undelivered. Nothing
about the event is changed, so once the key is fixed a later attempt
simply succeeds.
"""

import uuid

import httpx
import pytest

import app.services.webhook_delivery as delivery
from app.services.webhook_delivery import _MAX_ATTEMPTS, SigningSecretUnavailableError


@pytest.fixture
def sent(monkeypatch):
    """Every outbound POST, with its headers."""
    calls: list[dict] = []

    def _post(url, *, content, headers, timeout):
        calls.append({"url": url, "headers": headers, "body": content})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", _post)
    return calls


def _event(fake_client, merchant_id, *, attempts=0):
    return fake_client.seed(
        "webhook_events",
        {
            "merchant_id": str(merchant_id),
            "event_name": "collection.success",
            "target_url": "https://merchant.example/callback",
            "payload": {"amount": "500.00"},
            "status": "retrying" if attempts else "pending",
            "attempts": attempts,
        },
    )


def _row(fake_client, event_id):
    return next(r for r in fake_client.table("webhook_events")._table.rows if r["id"] == event_id)


# --- the downgrade is gone ---------------------------------------------


def test_an_undecryptable_secret_sends_nothing(fake_client, monkeypatch, sent):
    """The whole point. Previously this went out unsigned."""
    merchant_id = uuid.uuid4()
    event = _event(fake_client, merchant_id)
    monkeypatch.setattr(
        delivery, "_secret_for", lambda *_a, **_k: (_ for _ in ()).throw(SigningSecretUnavailableError())
    )

    assert delivery.deliver_event(fake_client, event) is False
    assert sent == []


def test_the_attempt_is_counted_so_it_still_backs_off(fake_client, monkeypatch, sent):
    """Withholding must not become an infinite loop against a broken key."""
    merchant_id = uuid.uuid4()
    event = _event(fake_client, merchant_id)
    monkeypatch.setattr(
        delivery, "_secret_for", lambda *_a, **_k: (_ for _ in ()).throw(SigningSecretUnavailableError())
    )

    delivery.deliver_event(fake_client, event)

    assert _row(fake_client, event["id"])["attempts"] == 1


def test_it_eventually_gives_up_like_any_other_failure(fake_client, monkeypatch, sent):
    merchant_id = uuid.uuid4()
    event = _event(fake_client, merchant_id, attempts=_MAX_ATTEMPTS - 1)
    monkeypatch.setattr(
        delivery, "_secret_for", lambda *_a, **_k: (_ for _ in ()).throw(SigningSecretUnavailableError())
    )

    delivery.deliver_event(fake_client, {**event, "attempts": _MAX_ATTEMPTS - 1})

    assert _row(fake_client, event["id"])["status"] == "failed"


def test_no_response_code_is_invented(fake_client, monkeypatch, sent):
    """Nothing was sent, so there is no reply. Recording one would put a
    status in the log that the merchant's server never gave."""
    merchant_id = uuid.uuid4()
    event = _event(fake_client, merchant_id)
    monkeypatch.setattr(
        delivery, "_secret_for", lambda *_a, **_k: (_ for _ in ()).throw(SigningSecretUnavailableError())
    )

    delivery.deliver_event(fake_client, event)

    assert _row(fake_client, event["id"]).get("response_status_code") is None


def test_the_event_is_left_recoverable(fake_client, monkeypatch, sent):
    """Nothing about the payload or target is changed, so once the key is
    fixed a later attempt succeeds on its own."""
    merchant_id = uuid.uuid4()
    event = _event(fake_client, merchant_id)
    monkeypatch.setattr(
        delivery, "_secret_for", lambda *_a, **_k: (_ for _ in ()).throw(SigningSecretUnavailableError())
    )

    delivery.deliver_event(fake_client, event)

    row = _row(fake_client, event["id"])
    assert row["target_url"] == "https://merchant.example/callback"
    assert row["payload"] == {"amount": "500.00"}


# --- what must NOT change ----------------------------------------------


def test_a_merchant_with_no_secret_still_receives_unsigned(fake_client, monkeypatch, sent):
    """Unchanged and deliberate. Refusing to deliver to a merchant who has
    never generated a secret would turn "hasn't set one up yet" into
    "receives nothing", which is worse and harder to diagnose."""
    merchant_id = uuid.uuid4()
    event = _event(fake_client, merchant_id)
    monkeypatch.setattr(delivery, "_secret_for", lambda *_a, **_k: None)

    assert delivery.deliver_event(fake_client, event) is True
    assert len(sent) == 1
    assert "X-Infinity-Signature" not in sent[0]["headers"]


def test_a_working_secret_still_signs(fake_client, monkeypatch, sent):
    merchant_id = uuid.uuid4()
    event = _event(fake_client, merchant_id)
    monkeypatch.setattr(delivery, "_secret_for", lambda *_a, **_k: "whsec_test_not_a_real_secret")

    assert delivery.deliver_event(fake_client, event) is True
    assert "X-Infinity-Signature" in sent[0]["headers"]


def test_the_secret_itself_never_appears_in_the_request(fake_client, monkeypatch, sent):
    """The signature is derived from it; the secret must never travel."""
    secret = "whsec_test_not_a_real_secret"
    event = _event(fake_client, uuid.uuid4())
    monkeypatch.setattr(delivery, "_secret_for", lambda *_a, **_k: secret)

    delivery.deliver_event(fake_client, event)

    assert secret not in str(sent[0]["headers"])
    assert secret not in str(sent[0]["body"])


# --- the resolver's own contract ---------------------------------------


def test_no_configured_secret_returns_none(fake_client):
    merchant = fake_client.seed("merchants", {"business_name": "No Secret Ltd", "currency": "TZS"})

    assert delivery._secret_for(fake_client, merchant["id"]) is None


def test_an_undecryptable_secret_raises_rather_than_returning_none(fake_client, monkeypatch):
    """The distinction the whole fix rests on."""
    merchant = fake_client.seed(
        "merchants",
        {"business_name": "Has Secret Ltd", "currency": "TZS", "webhook_secret_encrypted": "not-decryptable"},
    )
    monkeypatch.setattr(
        delivery, "decrypt_secret", lambda _v: (_ for _ in ()).throw(ValueError("bad key"))
    )

    with pytest.raises(SigningSecretUnavailableError):
        delivery._secret_for(fake_client, merchant["id"])


def test_end_to_end_a_merchant_with_a_broken_secret_receives_nothing(fake_client, monkeypatch, sent):
    """The test that would actually have caught the original bug.

    Every other test here monkeypatches `_secret_for`, so they verify the
    caller's handling given the exception — not that the resolver raises
    it. This one goes through the real path: a merchant row carrying an
    undecryptable secret, and no stubbing of anything but the cipher.

    Reverting `_secret_for` to `return None` makes this fail, which the
    others do not.
    """
    merchant = fake_client.seed(
        "merchants",
        {"business_name": "Signs Things Ltd", "currency": "TZS", "webhook_secret_encrypted": "corrupt"},
    )
    monkeypatch.setattr(
        delivery, "decrypt_secret", lambda _v: (_ for _ in ()).throw(ValueError("bad key"))
    )
    event = _event(fake_client, merchant["id"])

    assert delivery.deliver_event(fake_client, event) is False
    assert sent == [], "an unsigned delivery went out to a merchant who configured signing"
