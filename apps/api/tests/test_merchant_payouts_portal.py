"""The portal's view of payouts: a person reading their own money.

Separate routes from /v1/payouts, and separate tests, because the two
surfaces answer different credentials and that separation is the control.
/v1/payouts takes a payout key and reads its merchant and environment off
that key. /v1/merchant/payouts takes a person and reads both off their
membership. A single handler serving both would be one function holding
two ideas of who is calling, on a money surface.

What is pinned here:

1. A payout API key cannot reach any of it, and is told so plainly.
2. A dashboard user sees only their own merchant's payouts.
3. The environment is decided by the server from merchant_payout_settings,
   not by whatever the client asked for.
4. Reading is open to every merchant-scoped role; funding is admin-only.
5. Nothing on this surface is cached - these are the numbers a merchant
   reads before deciding to fund or to chase a payment.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_api_key,
    make_merchant_member,
)

client = TestClient(app)

CUR = "TZS"


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _merchant(fake_client, role="MERCHANT_ADMIN"):
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, role)
    return merchant_id, user_id


def _settings(fake_client, merchant_id, **overrides):
    row = {
        "merchant_id": str(merchant_id),
        "live_enabled": True,
        "sandbox_enabled": True,
        "paused": False,
        "daily_limit_tzs": "1000000.00",
        "version": 1,
    }
    row.update(overrides)
    fake_client.seed("merchant_payout_settings", row)
    return row


def _wallet(fake_client, merchant_id, *, available="0", reserved="0", environment="live"):
    for purpose, balance in (("payout_available", available), ("payout_reserved", reserved)):
        fake_client.seed(
            "ledger_accounts",
            {
                "merchant_id": str(merchant_id),
                "name": purpose,
                "account_type": "liability",
                "purpose": purpose,
                "currency": CUR,
                "environment": environment,
                "balance": balance,
            },
        )


def _payout(fake_client, merchant_id, *, environment="live", amount="1000.00", status="processing"):
    return fake_client.seed(
        "payouts",
        {
            "merchant_id": str(merchant_id),
            "environment": environment,
            "beneficiary_id": str(uuid.uuid4()),
            "amount": amount,
            "fee_amount": "0.00",
            "total_debit": amount,
            "currency": CUR,
            "status": status,
            "provider_reference": f"PO-{uuid.uuid4().hex[:12]}",
        },
    )


# --- no API keys on this surface ---------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/v1/merchant/payouts"),
        ("get", "/v1/merchant/payout-wallet"),
    ],
)
def test_a_payout_key_cannot_read_the_dashboard_surface(fake_client, method, path):
    """A payout key is a server credential for the partner API. Letting
    it read the portal surface would give it a second route to the same
    data under rules written for a person."""
    merchant_id, _user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id)
    raw_key, _row = make_api_key(
        fake_client,
        merchant_id,
        scopes=["payouts:create", "payouts:read"],
        key_type="payout",
    )

    response = getattr(client, method)(path, headers={"X-API-Key": raw_key})

    assert response.status_code == 403, response.text
    assert "not available to API keys" in response.json()["error"]["message"]


def test_a_payout_key_cannot_read_one_payout_in_the_dashboard(fake_client):
    merchant_id, _user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id)
    row = _payout(fake_client, merchant_id)
    raw_key, _key = make_api_key(
        fake_client, merchant_id, scopes=["payouts:read"], key_type="payout"
    )

    response = client.get(
        f"/v1/merchant/payouts/{row['id']}", headers={"X-API-Key": raw_key}
    )

    assert response.status_code == 403, response.text
    assert "not available to API keys" in response.json()["error"]["message"]


def test_a_collections_key_cannot_read_the_dashboard_surface_either(fake_client):
    """Not a payout-key-specific ban - no API key belongs here."""
    merchant_id, _user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id)
    raw_key, _row = make_api_key(fake_client, merchant_id, scopes=["collections:read"])

    response = client.get("/v1/merchant/payouts", headers={"X-API-Key": raw_key})

    assert response.status_code == 403, response.text


def test_an_unauthenticated_request_is_refused(fake_client):
    merchant_id, _user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id)

    assert client.get("/v1/merchant/payouts").status_code == 401


# --- a user sees only their own merchant -------------------------------------


def test_a_user_sees_their_own_payouts(fake_client):
    merchant_id, user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id)
    _payout(fake_client, merchant_id, amount="5000.00")

    response = client.get("/v1/merchant/payouts", headers=auth_headers(user_id))

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert len(data) == 1
    assert Decimal(data[0]["amount"]) == Decimal("5000.00")


def test_a_user_never_sees_another_merchants_payouts(fake_client):
    """The tenant is taken from the membership, so there is no parameter
    to point somewhere else - this pins that no row leaks anyway."""
    mine, user_id = _merchant(fake_client)
    _settings(fake_client, mine)
    _payout(fake_client, mine, amount="1000.00")

    theirs, _other_user = _merchant(fake_client)
    _settings(fake_client, theirs)
    _payout(fake_client, theirs, amount="999999.00")

    response = client.get("/v1/merchant/payouts", headers=auth_headers(user_id))

    amounts = {row["amount"] for row in response.json()["data"]}
    assert amounts == {"1000.00"}


def test_fetching_another_merchants_payout_by_id_is_a_404(fake_client):
    """404 rather than 403, so the id space cannot be mapped by probing
    for which ones come back forbidden."""
    _mine, user_id = _merchant(fake_client)
    _settings(fake_client, _mine)
    theirs, _other = _merchant(fake_client)
    _settings(fake_client, theirs)
    row = _payout(fake_client, theirs)

    response = client.get(
        f"/v1/merchant/payouts/{row['id']}", headers=auth_headers(user_id)
    )

    assert response.status_code == 404, response.text


def test_a_user_with_no_membership_sees_nothing(fake_client):
    merchant_id, _user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id)
    _payout(fake_client, merchant_id)
    stranger = uuid.uuid4()

    response = client.get("/v1/merchant/payouts", headers=auth_headers(stranger))

    assert response.status_code in (403, 404), response.text


def test_a_suspended_member_cannot_read_payouts(fake_client):
    merchant_id, _admin = _merchant(fake_client)
    _settings(fake_client, merchant_id)
    suspended = uuid.uuid4()
    fake_client.seed(
        "merchant_users",
        {
            "merchant_id": str(merchant_id),
            "user_id": str(suspended),
            "role": "MERCHANT_ADMIN",
            "status": "suspended",
        },
    )

    response = client.get("/v1/merchant/payouts", headers=auth_headers(suspended))

    assert response.status_code in (403, 404), response.text


# --- the server decides the environment --------------------------------------


def test_a_merchant_with_only_the_sandbox_on_gets_the_sandbox(fake_client):
    """No environment asked for, and live is off. The server must not
    default to live and answer with an empty page - the portal would
    show "no payouts" to a merchant who has some."""
    merchant_id, user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id, live_enabled=False, sandbox_enabled=True)
    _payout(fake_client, merchant_id, environment="sandbox", amount="2500.00")

    response = client.get("/v1/merchant/payouts", headers=auth_headers(user_id))

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["environment"] == "sandbox"


def test_asking_for_an_environment_the_account_lacks_is_refused(fake_client):
    """The client may ask; it does not choose. Answering with live data
    for a sandbox-only account would be the whole point of the split
    undone by a query parameter."""
    merchant_id, user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id, live_enabled=False, sandbox_enabled=True)
    _payout(fake_client, merchant_id, environment="live", amount="777.00")

    response = client.get(
        "/v1/merchant/payouts", params={"environment": "live"}, headers=auth_headers(user_id)
    )

    assert response.status_code >= 400, response.text
    assert "777.00" not in response.text


def test_a_sandbox_request_does_not_return_live_payouts(fake_client):
    merchant_id, user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id)
    _payout(fake_client, merchant_id, environment="live", amount="111.00")
    _payout(fake_client, merchant_id, environment="sandbox", amount="222.00")

    response = client.get(
        "/v1/merchant/payouts", params={"environment": "sandbox"}, headers=auth_headers(user_id)
    )

    amounts = {row["amount"] for row in response.json()["data"]}
    assert amounts == {"222.00"}


def test_an_unknown_environment_is_rejected_by_the_route(fake_client):
    merchant_id, user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id)

    response = client.get(
        "/v1/merchant/payouts", params={"environment": "staging"}, headers=auth_headers(user_id)
    )

    assert response.status_code == 422, response.text


def test_a_merchant_without_payout_access_gets_nothing(fake_client):
    """An absent settings row means no access, never a permissive
    default."""
    merchant_id, user_id = _merchant(fake_client)

    response = client.get("/v1/merchant/payouts", headers=auth_headers(user_id))

    assert response.status_code == 404, response.text


def test_both_environments_off_is_no_access(fake_client):
    merchant_id, user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id, live_enabled=False, sandbox_enabled=False)

    response = client.get("/v1/merchant/payouts", headers=auth_headers(user_id))

    assert response.status_code == 404, response.text


# --- the wallet card ---------------------------------------------------------


def test_the_wallet_returns_both_balances(fake_client):
    merchant_id, user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id)
    _wallet(fake_client, merchant_id, available="48500.00", reserved="51500.00")

    response = client.get("/v1/merchant/payout-wallet", headers=auth_headers(user_id))

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert Decimal(body["available"]) == Decimal("48500.00")
    assert Decimal(body["reserved"]) == Decimal("51500.00")
    assert body["environment"] == "live"


def test_the_wallet_reports_the_pause_state(fake_client):
    """A healthy balance beside an enabled Fund button, on a paused
    account, is a page inviting an action the server will refuse."""
    merchant_id, user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id, paused=True, paused_reason="Under review")
    _wallet(fake_client, merchant_id, available="10000.00")

    body = client.get(
        "/v1/merchant/payout-wallet", headers=auth_headers(user_id)
    ).json()["data"]

    assert body["paused"] is True
    assert body["paused_reason"] == "Under review"


def test_a_never_funded_wallet_reads_zero_rather_than_erroring(fake_client):
    merchant_id, user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id)

    body = client.get(
        "/v1/merchant/payout-wallet", headers=auth_headers(user_id)
    ).json()["data"]

    assert Decimal(body["available"]) == Decimal(0)
    assert Decimal(body["reserved"]) == Decimal(0)


# --- read is for everyone, funding is for admins -----------------------------


@pytest.mark.parametrize("role", ["MERCHANT_ADMIN", "MERCHANT_STAFF", "DEVELOPER"])
def test_every_merchant_role_may_read_payouts(fake_client, role):
    merchant_id, user_id = _merchant(fake_client, role)
    _settings(fake_client, merchant_id)
    _payout(fake_client, merchant_id)

    response = client.get("/v1/merchant/payouts", headers=auth_headers(user_id))

    assert response.status_code == 200, response.text


@pytest.mark.parametrize("role", ["MERCHANT_STAFF", "DEVELOPER"])
def test_only_an_admin_may_fund(fake_client, role):
    merchant_id, user_id = _merchant(fake_client, role)
    _settings(fake_client, merchant_id)

    response = client.post(
        "/v1/merchant/payout-wallet/fund",
        headers={**auth_headers(user_id, aal="aal2"), "Idempotency-Key": str(uuid.uuid4())},
        json={"amount": "1000.00"},
    )

    assert response.status_code == 403, response.text


@pytest.mark.parametrize("role", ["MERCHANT_STAFF", "DEVELOPER"])
def test_can_fund_is_false_for_a_role_that_cannot(fake_client, role):
    """So the page does not render a button the server will refuse."""
    merchant_id, user_id = _merchant(fake_client, role)
    _settings(fake_client, merchant_id)

    body = client.get(
        "/v1/merchant/payout-wallet", headers=auth_headers(user_id)
    ).json()["data"]

    assert body["can_fund"] is False


def test_can_fund_is_true_for_an_admin(fake_client):
    merchant_id, user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id)

    body = client.get(
        "/v1/merchant/payout-wallet", headers=auth_headers(user_id)
    ).json()["data"]

    assert body["can_fund"] is True


# --- nothing here is cached --------------------------------------------------


def test_the_wallet_balance_is_never_served_from_cache(fake_client, monkeypatch):
    """The rule the rest of this codebase already follows for the
    Collections balance: a stale total is a cosmetic lag, a stale balance
    is a merchant told they have money they have already committed."""
    from app.core import cache as cache_module
    from app.core.cache import reset_breaker

    writes: list[str] = []

    class _RecordingRedis:
        def __init__(self):
            self.store: dict[str, str] = {}

        def get(self, key):
            return self.store.get(key)

        def setex(self, key, ttl, value):
            writes.append(key)
            self.store[key] = value

        def delete(self, *keys):
            for key in keys:
                self.store.pop(key, None)

    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    get_settings.cache_clear()
    reset_breaker()
    monkeypatch.setattr(cache_module, "_client", lambda: _RecordingRedis())

    merchant_id, user_id = _merchant(fake_client)
    _settings(fake_client, merchant_id)
    _wallet(fake_client, merchant_id, available="1000.00")

    client.get("/v1/merchant/payout-wallet", headers=auth_headers(user_id))
    client.get("/v1/merchant/payouts", headers=auth_headers(user_id))

    reset_breaker()
    get_settings.cache_clear()
    assert not [key for key in writes if "payout" in key], (
        f"a payout figure was written to the cache: {writes}"
    )
