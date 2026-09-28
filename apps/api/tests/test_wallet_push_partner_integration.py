"""Direct Wallet Push, as a billing-system partner will actually call it.

Every assertion here corresponds to a claim made in
docs/DIRECT_WALLET_PUSH_PARTNER_INTEGRATION.md. The point is that the
document handed to the partner cannot drift from the API: if one of these
fails, the docs are wrong, not just the code.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import TEST_JWT_SECRET, create_merchant

client = TestClient(app)

_PUSH = "app.routers.collections_api.execute_wallet_push_collection"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("ENABLE_COLLECTIONS", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _api_key(fake_client, merchant_id, *, environment="live", scopes=None, revoked=False):
    """Seeds a key in the `sk_live_`/`sk_test_` shape the portal actually
    issues today (app/routers/merchant_portal.py::_generate_api_key), not
    the older `inf_` shape tests/factories.py still uses — the partner docs
    quote `sk_live_…`, so that is what these tests must exercise."""
    from app.auth import hash_api_key

    tag = "live" if environment == "live" else "test"
    secret = f"sk_{tag}_{uuid.uuid4().hex}"
    fake_client.seed(
        "api_keys",
        {
            "merchant_id": str(merchant_id),
            "name": "Billing partner",
            "public_key": f"pk_{tag}_{uuid.uuid4().hex}",
            "environment": environment,
            "key_prefix": secret[:16],
            "key_last4": secret[-4:],
            "hashed_key": hash_api_key(secret),
            "scopes": scopes if scopes is not None else ["collections:write", "collections:read"],
            "status": "revoked" if revoked else "active",
            "ip_whitelist_enabled": False,
            "continue_without_ip_whitelist": True,
        },
    )
    return secret


def _body(merchant_id, **overrides):
    return {
        "merchant_id": str(merchant_id),
        "amount": "5000.00",
        "currency": "TZS",
        "phone": "+255712345678",
        "reference": "INV-2026-000412",
        **overrides,
    }


def _push(secret, body, *, idem=None, headers=None):
    return client.post(
        "/v1/collections/wallet-push",
        headers={
            "Authorization": f"Bearer {secret}",
            "Idempotency-Key": idem or str(uuid.uuid4()),
            **(headers or {}),
        },
        json=body,
    )


def _approved(fake_client):
    return create_merchant(fake_client, status="active", kyc_status="verified")


def _fake_collection(merchant_id, **overrides):
    return {
        "id": str(uuid.uuid4()),
        "merchant_id": str(merchant_id),
        "status": "processing",
        "merchant_reference": "INV-2026-000412",
        "amount": "5000.00",
        "currency": "TZS",
        **overrides,
    }


# --- authentication ---------------------------------------------------------


def test_an_approved_merchants_live_key_can_initiate_a_push(fake_client):
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])

    with patch(_PUSH, return_value=_fake_collection(merchant["id"])) as push:
        response = _push(secret, _body(merchant["id"]))

    assert response.status_code == 202, response.text
    assert response.json()["data"]["status"] == "processing"
    push.assert_called_once()


def test_an_invalid_key_is_rejected(fake_client):
    merchant = _approved(fake_client)

    with patch(_PUSH) as push:
        response = _push("sk_live_not_a_real_key_at_all", _body(merchant["id"]))

    assert response.status_code in (401, 403)
    push.assert_not_called()


def test_a_revoked_key_is_rejected(fake_client):
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"], revoked=True)

    with patch(_PUSH) as push:
        response = _push(secret, _body(merchant["id"]))

    assert response.status_code in (401, 403)
    push.assert_not_called()


def test_a_public_key_cannot_authenticate(fake_client):
    """pk_ is an identifier, not a credential — the docs say so, and it is
    rejected before any lookup."""
    merchant = _approved(fake_client)
    _api_key(fake_client, merchant["id"])

    with patch(_PUSH) as push:
        response = _push(f"pk_live_{uuid.uuid4().hex}", _body(merchant["id"]))

    assert response.status_code in (401, 403)
    push.assert_not_called()


def test_a_key_without_the_collections_scope_is_rejected(fake_client):
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"], scopes=["collections:read"])

    with patch(_PUSH) as push:
        response = _push(secret, _body(merchant["id"]))

    assert response.status_code == 403
    push.assert_not_called()


def test_a_key_cannot_push_for_a_different_merchant(fake_client):
    """The body's merchant_id must be the key's own merchant."""
    mine = _approved(fake_client)
    theirs = _approved(fake_client)
    secret = _api_key(fake_client, mine["id"])

    with patch(_PUSH) as push:
        response = _push(secret, _body(theirs["id"]))

    assert response.status_code in (403, 404)
    push.assert_not_called()


# --- merchant standing ------------------------------------------------------


@pytest.mark.parametrize("status,kyc", [("pending", "pending"), ("suspended", "verified")])
def test_an_unapproved_or_suspended_merchant_cannot_take_live_payments(status, kyc, fake_client):
    """The docs tell the partner live keys do not work before approval.
    The gate is in create_processing_transaction, so it holds for every
    collection path, not just this endpoint."""
    merchant = create_merchant(fake_client, status=status, kyc_status=kyc)
    secret = _api_key(fake_client, merchant["id"])

    response = _push(secret, _body(merchant["id"]))

    assert response.status_code >= 400
    assert response.status_code != 202


# --- validation -------------------------------------------------------------


@pytest.mark.parametrize("missing", ["amount", "phone"])
def test_a_missing_required_field_is_a_clear_validation_error(missing, fake_client):
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])
    body = _body(merchant["id"])
    del body[missing]

    response = _push(secret, body)

    assert response.status_code == 422, response.text


@pytest.mark.parametrize("amount", ["-1", "0", "abc", ""])
def test_a_nonsensical_amount_is_refused(amount, fake_client):
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])

    response = _push(secret, _body(merchant["id"], amount=amount))

    assert response.status_code in (400, 422), f"amount={amount!r} was accepted"


def test_the_idempotency_key_header_is_required(fake_client):
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])

    response = client.post(
        "/v1/collections/wallet-push",
        headers={"Authorization": f"Bearer {secret}"},
        json=_body(merchant["id"]),
    )

    assert response.status_code == 422


# --- idempotency ------------------------------------------------------------


def test_a_repeated_key_returns_the_first_result_without_a_second_push(fake_client):
    """The partner will retry on a timeout. That must not prompt the
    customer twice or create a second Selcom attempt."""
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])
    key = str(uuid.uuid4())

    with patch(_PUSH, return_value=_fake_collection(merchant["id"])) as push:
        first = _push(secret, _body(merchant["id"]), idem=key)
        second = _push(secret, _body(merchant["id"]), idem=key)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["data"]["collection_id"] == first.json()["data"]["collection_id"]
    assert push.call_count == 1, "the provider was called twice for one idempotency key"


def test_the_same_key_with_a_different_body_is_refused(fake_client):
    """Silently returning the first result for a different payment would
    be worse than an error."""
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])
    key = str(uuid.uuid4())

    with patch(_PUSH, return_value=_fake_collection(merchant["id"])):
        _push(secret, _body(merchant["id"], amount="5000.00"), idem=key)
        conflict = _push(secret, _body(merchant["id"], amount="9999.00"), idem=key)

    assert conflict.status_code == 409


def test_a_different_key_creates_a_genuinely_new_payment(fake_client):
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])

    with patch(_PUSH, side_effect=lambda *a, **k: _fake_collection(merchant["id"])) as push:
        _push(secret, _body(merchant["id"]))
        _push(secret, _body(merchant["id"]))

    assert push.call_count == 2


# --- nothing provider-side leaks -------------------------------------------


def test_no_selcom_credential_or_detail_appears_in_the_response(fake_client, monkeypatch):
    monkeypatch.setenv("SELCOM_CHECKOUT_API_SECRET", "super-secret-selcom-value")
    monkeypatch.setenv("SELCOM_CHECKOUT_API_KEY", "selcom-api-key-value")
    get_settings.cache_clear()

    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])

    with patch(_PUSH, return_value=_fake_collection(merchant["id"])):
        response = _push(secret, _body(merchant["id"]))

    body = response.text
    assert "super-secret-selcom-value" not in body
    assert "selcom-api-key-value" not in body
    assert "selcom" not in body.lower(), "the provider is named in a merchant-facing response"


def test_the_api_secret_is_not_echoed_back(fake_client):
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])

    with patch(_PUSH, return_value=_fake_collection(merchant["id"])):
        response = _push(secret, _body(merchant["id"]))

    assert secret not in response.text


def test_a_sandbox_key_never_reaches_the_provider(fake_client):
    """sk_test_ is documented as making no real call and moving no money."""
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"], environment="sandbox")

    with patch(_PUSH) as push:
        response = _push(secret, _body(merchant["id"]))

    assert response.status_code == 202, response.text
    push.assert_not_called()


# --- IP allowlist, both ways ------------------------------------------------
#
# The docs tell the partner it is optional and off by default, and that
# turning it on restricts a key to their billing servers. Both halves of
# that claim are exercised here.


def _allow(fake_client, merchant_id, ip, *, environment="live"):
    return fake_client.seed(
        "api_ip_allowlist",
        {
            "merchant_id": str(merchant_id),
            "api_key_id": None,
            "environment": environment,
            "label": "Billing server",
            "ip_address_or_cidr": ip,
            "status": "active",
            "notes": None,
            "created_by": None,
            "approved_by": None,
        },
    )


def _enable_allowlist(fake_client, secret_prefix):
    row = next(
        r
        for r in fake_client.table("api_keys")._table.rows
        if r["key_prefix"] == secret_prefix
    )
    row["ip_whitelist_enabled"] = True
    row["continue_without_ip_whitelist"] = False


def test_with_the_allowlist_off_a_valid_key_works_from_any_address(fake_client):
    """The documented default — a partner who never configures one is not
    silently locked out."""
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])

    with patch(_PUSH, return_value=_fake_collection(merchant["id"])):
        response = _push(
            secret, _body(merchant["id"]), headers={"X-Forwarded-For": "197.250.1.9"}
        )

    assert response.status_code == 202, response.text


def test_with_the_allowlist_on_an_allowed_address_passes(fake_client):
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])
    _enable_allowlist(fake_client, secret[:16])
    _allow(fake_client, merchant["id"], "41.222.10.5")

    with patch(_PUSH, return_value=_fake_collection(merchant["id"])):
        response = _push(
            secret, _body(merchant["id"]), headers={"X-Forwarded-For": "41.222.10.5"}
        )

    assert response.status_code == 202, response.text


def test_with_the_allowlist_on_another_address_is_rejected_before_any_push(fake_client):
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])
    _enable_allowlist(fake_client, secret[:16])
    _allow(fake_client, merchant["id"], "41.222.10.5")

    with patch(_PUSH) as push:
        response = _push(
            secret, _body(merchant["id"]), headers={"X-Forwarded-For": "8.8.8.8"}
        )

    assert response.status_code == 403
    push.assert_not_called()


def test_an_allowlist_rejection_reveals_nothing_about_the_allowlist(fake_client):
    """A caller who is blocked should not learn which addresses would have
    worked, or even that an allowlist is the reason."""
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])
    _enable_allowlist(fake_client, secret[:16])
    _allow(fake_client, merchant["id"], "41.222.10.5")

    response = _push(secret, _body(merchant["id"]), headers={"X-Forwarded-For": "8.8.8.8"})

    body = response.text
    assert "41.222.10.5" not in body
    assert secret not in body


# --- merchant_id is optional for an API key ---------------------------------
#
# The key already identifies the merchant. Requiring the UUID in the body
# meant an integrator had to discover their own merchant id before they
# could make a first call, and the portal does not display it anywhere.


def test_a_push_works_with_no_merchant_id_at_all(fake_client):
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])
    body = _body(merchant["id"])
    del body["merchant_id"]

    with patch(_PUSH, return_value=_fake_collection(merchant["id"])) as push:
        response = _push(secret, body)

    assert response.status_code == 202, response.text
    assert str(push.call_args.kwargs["merchant_id"]) == merchant["id"]


def test_an_omitted_merchant_id_resolves_to_the_keys_own_merchant(fake_client):
    """Not just "it works" — it must resolve to the right merchant, not
    whichever one happens to be first in the table."""
    _other = _approved(fake_client)
    mine = _approved(fake_client)
    secret = _api_key(fake_client, mine["id"])
    body = _body(mine["id"])
    del body["merchant_id"]

    with patch(_PUSH, return_value=_fake_collection(mine["id"])) as push:
        _push(secret, body)

    assert str(push.call_args.kwargs["merchant_id"]) == mine["id"]


def test_sending_someone_elses_merchant_id_is_still_refused(fake_client):
    """Making the field optional must not make it a way in. An explicit
    value is still checked against the key's own merchant."""
    theirs = _approved(fake_client)
    mine = _approved(fake_client)
    secret = _api_key(fake_client, mine["id"])

    with patch(_PUSH) as push:
        response = _push(secret, _body(theirs["id"]))

    assert response.status_code in (403, 404)
    push.assert_not_called()


def test_sending_your_own_merchant_id_still_works(fake_client):
    """Existing integrations that send it must not break."""
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])

    with patch(_PUSH, return_value=_fake_collection(merchant["id"])):
        assert _push(secret, _body(merchant["id"])).status_code == 202


# --- rate limiting ----------------------------------------------------------
#
# A billing platform calls for many merchants from ONE address, so a limit
# keyed only on the source address makes those merchants share a bucket.
# See the collection_create_max_per_minute_* settings.


def _limits(monkeypatch, *, per_ip, per_key):
    monkeypatch.setenv("COLLECTION_CREATE_MAX_PER_MINUTE_PER_IP", str(per_ip))
    monkeypatch.setenv("COLLECTION_CREATE_MAX_PER_MINUTE_PER_KEY", str(per_key))
    get_settings.cache_clear()


def _push_until_refused(secret, merchant_id, *, ceiling=40):
    """Pushes until one is refused, returning how many were accepted.
    `ceiling` only stops a broken limit from looping forever."""
    for accepted in range(ceiling):
        with patch(_PUSH, return_value=_fake_collection(merchant_id)):
            if _push(secret, _body(merchant_id)).status_code != 202:
                return accepted
    raise AssertionError(f"never refused after {ceiling} pushes")


def test_one_merchants_billing_run_does_not_lock_out_another_on_the_same_address(
    fake_client, monkeypatch
):
    """The regression this limit exists for. Both merchants reach us from
    one billing platform, so both present the same source address."""
    _limits(monkeypatch, per_ip=10, per_key=3)
    busy = _approved(fake_client)
    quiet = _approved(fake_client)
    busy_key = _api_key(fake_client, busy["id"])
    quiet_key = _api_key(fake_client, quiet["id"])

    _push_until_refused(busy_key, busy["id"])

    with patch(_PUSH, return_value=_fake_collection(quiet["id"])):
        response = _push(quiet_key, _body(quiet["id"]))

    assert response.status_code == 202, "a neighbour's billing run exhausted the shared bucket"


def test_a_single_key_is_capped_and_told_when_to_retry(fake_client, monkeypatch):
    _limits(monkeypatch, per_ip=50, per_key=3)
    merchant = _approved(fake_client)
    secret = _api_key(fake_client, merchant["id"])

    assert _push_until_refused(secret, merchant["id"]) == 3

    with patch(_PUSH) as push:
        response = _push(secret, _body(merchant["id"]))

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    # A refused push must never reach Selcom.
    push.assert_not_called()


def test_the_shared_address_still_has_a_ceiling_of_its_own(fake_client, monkeypatch):
    """Per-key alone would let one host open many keys and concentrate
    their combined traffic onto Selcom, so the address limit stays.

    Note that a push refused by the per-key limit still spends address
    budget — rejecting it is work we did. That is why the first key's
    four requests (three accepted, one refused) leave four of the six.
    """
    _limits(monkeypatch, per_ip=6, per_key=3)
    first = _approved(fake_client)
    second = _approved(fake_client)
    first_key = _api_key(fake_client, first["id"])
    second_key = _api_key(fake_client, second["id"])

    assert _push_until_refused(first_key, first["id"]) == 3

    # The second key has its own untouched per-key allowance of 3, but
    # only two of the address's six remain.
    for _ in range(2):
        with patch(_PUSH, return_value=_fake_collection(second["id"])):
            assert _push(second_key, _body(second["id"])).status_code == 202

    with patch(_PUSH) as push:
        response = _push(second_key, _body(second["id"]))

    assert response.status_code == 429
    push.assert_not_called()
