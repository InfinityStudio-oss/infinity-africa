"""The Disbursement API over HTTP, and the walls around it.

The service layer is tested in test_payouts_service.py and the money
invariants against real Postgres in test_payout_wallet_postgres.py. What
is left, and what this file is for, is the part a partner actually
touches: which credential reaches which route.

The separation being tested is the reason this API can exist without a
person approving each call. A payout key spends a prefunded pot, and the
size of that pot is the ceiling on what a leaked key can cost. That only
holds if the key cannot top the pot up, cannot reach the Collections
balance behind it, and cannot use the legacy withdrawal routes that spend
that balance directly. Each of those is a test here, stated as what the
key must NOT be able to do.
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


def _idem() -> str:
    return str(uuid.uuid4())


def _merchant(fake_client, *, role="MERCHANT_ADMIN"):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, role)
    return merchant_id, user_id


def _enable_payouts(fake_client, merchant_id, **overrides):
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


def _beneficiary(fake_client, merchant_id, environment="live"):
    return fake_client.seed(
        "payout_beneficiaries",
        {
            "merchant_id": str(merchant_id),
            "environment": environment,
            "name": "Test Destination",
            "method": "MOBILE_MONEY",
            "destination_code": "VODACOM",
            "destination_identifier": "255700000000",
            "status": "active",
        },
    )["id"]


def _fund(fake_client, merchant_id, amount, *, environment="live"):
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Payout available",
            "account_type": "liability",
            "purpose": "payout_available",
            "currency": CUR,
            "environment": environment,
            "balance": amount,
        },
    )
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Payout reserved",
            "account_type": "liability",
            "purpose": "payout_reserved",
            "currency": CUR,
            "environment": environment,
            "balance": "0",
        },
    )


def _payout_key(fake_client, merchant_id, *, environment="live"):
    raw, _row = make_api_key(
        fake_client,
        merchant_id,
        scopes=["payouts:create", "payouts:read"],
        key_type="payout",
        environment=environment,
    )
    return raw


def _ready(fake_client, *, funded="100000.00"):
    merchant_id, user_id = _merchant(fake_client)
    _enable_payouts(fake_client, merchant_id)
    beneficiary_id = _beneficiary(fake_client, merchant_id)
    _fund(fake_client, merchant_id, funded)
    return merchant_id, user_id, beneficiary_id


# --- creating a payout -------------------------------------------------------


def test_a_payout_key_can_create_a_payout(fake_client):
    merchant_id, _user_id, beneficiary_id = _ready(fake_client)
    raw_key = _payout_key(fake_client, merchant_id)

    response = client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key, "Idempotency-Key": _idem()},
        json={"beneficiary_id": str(beneficiary_id), "amount": "5000.00"},
    )

    assert response.status_code == 201, response.text
    body = response.json()["data"]
    assert body["status"] == "processing"
    assert Decimal(body["amount"]) == Decimal("5000.00")
    assert body["beneficiary_id"] == str(beneficiary_id)


def test_the_response_never_carries_the_provider_payload_or_the_key(fake_client):
    """provider_raw_response is ours to debug with and api_key_id is a
    credential reference. Neither belongs in a partner's response."""
    merchant_id, _user_id, beneficiary_id = _ready(fake_client)
    raw_key = _payout_key(fake_client, merchant_id)

    response = client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key, "Idempotency-Key": _idem()},
        json={"beneficiary_id": str(beneficiary_id), "amount": "1000.00"},
    )

    body = response.json()["data"]
    for leaked in ("provider_raw_response", "api_key_id", "hashed_key", "merchant_id"):
        assert leaked not in body


def test_a_merchant_id_in_the_body_is_refused(fake_client):
    """Not ignored - refused. A money-moving call that silently discards a
    merchant_id is one a caller can believe they aimed somewhere else."""
    merchant_id, _user_id, beneficiary_id = _ready(fake_client)
    raw_key = _payout_key(fake_client, merchant_id)
    other_merchant = uuid.UUID(create_merchant(fake_client)["id"])

    response = client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key, "Idempotency-Key": _idem()},
        json={
            "beneficiary_id": str(beneficiary_id),
            "amount": "1000.00",
            "merchant_id": str(other_merchant),
        },
    )

    assert response.status_code == 422, response.text


def test_the_idempotency_key_is_required(fake_client):
    """A partner retrying a timed-out payout is the normal case. Without a
    key, the safe-looking action - retry - sends the money twice."""
    merchant_id, _user_id, beneficiary_id = _ready(fake_client)
    raw_key = _payout_key(fake_client, merchant_id)

    response = client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key},
        json={"beneficiary_id": str(beneficiary_id), "amount": "1000.00"},
    )

    assert response.status_code == 422, response.text


def test_a_replayed_request_does_not_send_a_second_payout(fake_client):
    merchant_id, _user_id, beneficiary_id = _ready(fake_client)
    raw_key = _payout_key(fake_client, merchant_id)
    key = _idem()
    body = {"beneficiary_id": str(beneficiary_id), "amount": "7000.00"}

    first = client.post("/v1/payouts", headers={"X-API-Key": raw_key, "Idempotency-Key": key}, json=body)
    second = client.post("/v1/payouts", headers={"X-API-Key": raw_key, "Idempotency-Key": key}, json=body)

    assert first.status_code == 201, first.text
    assert second.status_code in (200, 201), second.text
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert len(fake_client.table("payouts")._table.rows) == 1


def test_the_same_key_with_a_different_amount_is_refused(fake_client):
    """The dangerous replay: a retry that is not actually the same
    request. Re-running it would send a different sum; returning the
    stored response would answer for a payout that was never created."""
    merchant_id, _user_id, beneficiary_id = _ready(fake_client)
    raw_key = _payout_key(fake_client, merchant_id)
    key = _idem()

    client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key, "Idempotency-Key": key},
        json={"beneficiary_id": str(beneficiary_id), "amount": "1000.00"},
    )
    second = client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key, "Idempotency-Key": key},
        json={"beneficiary_id": str(beneficiary_id), "amount": "9000.00"},
    )

    assert second.status_code == 409, second.text
    assert len(fake_client.table("payouts")._table.rows) == 1


# --- what a payout key must NOT be able to do --------------------------------


def test_a_payout_key_cannot_fund_the_wallet_it_spends(fake_client):
    """The invariant the whole design rests on.

    The wallet balance is the ceiling on what a leaked payout key can
    cost. A key that could raise that ceiling would have no ceiling, and
    the Disbursement API would be a way to drain the Collections balance
    with no human in the loop - which is the thing it was built to avoid.
    """
    merchant_id, _user_id, _beneficiary_id = _ready(fake_client)
    raw_key = _payout_key(fake_client, merchant_id)

    response = client.post(
        "/v1/merchant/payout-wallet/fund",
        headers={"X-API-Key": raw_key, "Idempotency-Key": _idem()},
        json={"amount": "50000.00"},
    )

    assert response.status_code == 403, response.text
    assert "not available to API keys" in response.json()["error"]["message"]


def test_a_payout_key_cannot_read_the_wallet(fake_client):
    merchant_id, _user_id, _beneficiary_id = _ready(fake_client)
    raw_key = _payout_key(fake_client, merchant_id)

    response = client.get("/v1/merchant/payout-wallet", headers={"X-API-Key": raw_key})

    assert response.status_code in (401, 403), response.text


def test_a_collections_key_cannot_create_a_payout(fake_client):
    """A standard key, correctly authenticated against its own merchant,
    holds no payout scope and must be refused."""
    merchant_id, _user_id, beneficiary_id = _ready(fake_client)
    raw_key, _row = make_api_key(
        fake_client, merchant_id, scopes=["collections:write", "collections:read"]
    )

    response = client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key, "Idempotency-Key": _idem()},
        json={"beneficiary_id": str(beneficiary_id), "amount": "1000.00"},
    )

    assert response.status_code == 403, response.text


def test_a_payout_key_cannot_reach_the_legacy_withdrawal_route(fake_client):
    """Those routes spend the Collections balance directly. If a payout
    key reached them, isolating the payout wallet would buy nothing."""
    merchant_id, _user_id, _beneficiary_id = _ready(fake_client)
    raw_key = _payout_key(fake_client, merchant_id)

    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={"X-API-Key": raw_key, "Idempotency-Key": _idem()},
        json={
            "merchant_id": str(merchant_id),
            "amount": "1000.00",
            "currency": CUR,
            "destination_name": "Test Destination",
            "destination_code": "MPESA",
            "destination_identifier": "255700000000",
        },
    )

    assert response.status_code == 403, response.text


def test_a_payout_key_cannot_read_another_merchants_payout(fake_client):
    merchant_id, _user_id, beneficiary_id = _ready(fake_client)
    raw_key = _payout_key(fake_client, merchant_id)
    created = client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key, "Idempotency-Key": _idem()},
        json={"beneficiary_id": str(beneficiary_id), "amount": "1000.00"},
    ).json()["data"]

    other_id, _other_user, _other_ben = _ready(fake_client)
    other_key = _payout_key(fake_client, other_id)

    response = client.get(f"/v1/payouts/{created['id']}", headers={"X-API-Key": other_key})

    assert response.status_code in (403, 404), response.text


def test_a_sandbox_key_cannot_read_a_live_payout(fake_client):
    """Environments are not a label on the same data. A sandbox
    credential reading live payouts would be a live data leak through a
    credential a partner treats as disposable."""
    merchant_id, _user_id, beneficiary_id = _ready(fake_client)
    live_key = _payout_key(fake_client, merchant_id, environment="live")
    created = client.post(
        "/v1/payouts",
        headers={"X-API-Key": live_key, "Idempotency-Key": _idem()},
        json={"beneficiary_id": str(beneficiary_id), "amount": "1000.00"},
    ).json()["data"]

    sandbox_key = _payout_key(fake_client, merchant_id, environment="sandbox")

    response = client.get(f"/v1/payouts/{created['id']}", headers={"X-API-Key": sandbox_key})

    assert response.status_code == 404, response.text


def test_listing_is_scoped_to_the_callers_environment(fake_client):
    merchant_id, _user_id, beneficiary_id = _ready(fake_client)
    live_key = _payout_key(fake_client, merchant_id, environment="live")
    client.post(
        "/v1/payouts",
        headers={"X-API-Key": live_key, "Idempotency-Key": _idem()},
        json={"beneficiary_id": str(beneficiary_id), "amount": "1000.00"},
    )

    sandbox_key = _payout_key(fake_client, merchant_id, environment="sandbox")
    response = client.get("/v1/payouts", headers={"X-API-Key": sandbox_key})

    assert response.status_code == 200, response.text
    assert response.json()["data"] == []


# --- the dashboard-only funding endpoint -------------------------------------


def test_funding_requires_step_up_mfa(fake_client):
    """This is the act that sets the ceiling on everything an API key can
    spend, so a live session alone is not enough."""
    _merchant_id, user_id, _beneficiary_id = _ready(fake_client)

    response = client.post(
        "/v1/merchant/payout-wallet/fund",
        headers={**auth_headers(user_id), "Idempotency-Key": _idem()},
        json={"amount": "10000.00"},
    )

    assert response.status_code == 403, response.text
    assert "two-factor" in response.json()["error"]["message"].lower()


def test_funding_with_mfa_moves_money_out_of_collections(fake_client):
    merchant_id, user_id, _beneficiary_id = _ready(fake_client, funded="0")
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Collections",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": CUR,
            "balance": "80000.00",
        },
    )

    response = client.post(
        "/v1/merchant/payout-wallet/fund",
        headers={**auth_headers(user_id, aal="aal2"), "Idempotency-Key": _idem()},
        json={"amount": "30000.00"},
    )

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert Decimal(body["available"]) == Decimal("30000.00")

    accounts = {
        (r["purpose"], r.get("environment", "live")): Decimal(str(r["balance"]))
        for r in fake_client.table("ledger_accounts")._table.rows
        if r["merchant_id"] == str(merchant_id)
    }
    assert accounts[("merchant_wallet", "live")] == Decimal("50000.00")
    assert accounts[("payout_available", "live")] == Decimal("30000.00")


def test_funding_more_than_collections_holds_is_refused(fake_client):
    """And refused by the ledger, not by a friendly pre-check, so a
    concurrent withdrawal cannot slip between the two."""
    merchant_id, user_id, _beneficiary_id = _ready(fake_client, funded="0")
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Collections",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": CUR,
            "balance": "1000.00",
        },
    )

    response = client.post(
        "/v1/merchant/payout-wallet/fund",
        headers={**auth_headers(user_id, aal="aal2"), "Idempotency-Key": _idem()},
        json={"amount": "5000.00"},
    )

    assert response.status_code >= 400, response.text
    accounts = {
        r["purpose"]: Decimal(str(r["balance"]))
        for r in fake_client.table("ledger_accounts")._table.rows
        if r["merchant_id"] == str(merchant_id)
    }
    assert accounts["merchant_wallet"] == Decimal("1000.00")
    assert accounts.get("payout_available", Decimal(0)) == Decimal(0)


def test_merchant_staff_cannot_fund_the_wallet(fake_client):
    merchant_id, _admin_id = _merchant(fake_client)
    _enable_payouts(fake_client, merchant_id)
    staff_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, staff_id, "MERCHANT_STAFF")

    response = client.post(
        "/v1/merchant/payout-wallet/fund",
        headers={**auth_headers(staff_id, aal="aal2"), "Idempotency-Key": _idem()},
        json={"amount": "1000.00"},
    )

    assert response.status_code == 403, response.text


def test_funding_is_idempotent(fake_client):
    merchant_id, user_id, _beneficiary_id = _ready(fake_client, funded="0")
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Collections",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": CUR,
            "balance": "80000.00",
        },
    )
    key = _idem()
    headers = {**auth_headers(user_id, aal="aal2"), "Idempotency-Key": key}

    client.post("/v1/merchant/payout-wallet/fund", headers=headers, json={"amount": "10000.00"})
    client.post("/v1/merchant/payout-wallet/fund", headers=headers, json={"amount": "10000.00"})

    accounts = {
        r["purpose"]: Decimal(str(r["balance"]))
        for r in fake_client.table("ledger_accounts")._table.rows
        if r["merchant_id"] == str(merchant_id)
    }
    assert accounts["payout_available"] == Decimal("10000.00"), "the replay funded twice"
    assert accounts["merchant_wallet"] == Decimal("70000.00")


# --- access and pause --------------------------------------------------------


def test_a_merchant_without_payout_settings_gets_no_access(fake_client):
    """Absent row means not enabled, never a permissive default."""
    merchant_id, _user_id = _merchant(fake_client)
    beneficiary_id = _beneficiary(fake_client, merchant_id)
    _fund(fake_client, merchant_id, "100000.00")
    raw_key, _row = make_api_key(
        fake_client, merchant_id, scopes=["payouts:create", "payouts:read"], key_type="payout"
    )

    response = client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key, "Idempotency-Key": _idem()},
        json={"beneficiary_id": str(beneficiary_id), "amount": "1000.00"},
    )

    assert response.status_code >= 400, response.text


def test_a_paused_account_cannot_create_a_payout_but_can_still_read(fake_client):
    """Pause stops new money leaving. It must not blind a partner to the
    payouts already in flight - that is when they most need to look."""
    merchant_id, _user_id, beneficiary_id = _ready(fake_client)
    raw_key = _payout_key(fake_client, merchant_id)
    client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key, "Idempotency-Key": _idem()},
        json={"beneficiary_id": str(beneficiary_id), "amount": "1000.00"},
    )

    row = next(
        r
        for r in fake_client.table("merchant_payout_settings")._table.rows
        if r["merchant_id"] == str(merchant_id)
    )
    row["paused"] = True
    row["paused_reason"] = "Under review"

    blocked = client.post(
        "/v1/payouts",
        headers={"X-API-Key": raw_key, "Idempotency-Key": _idem()},
        json={"beneficiary_id": str(beneficiary_id), "amount": "1000.00"},
    )
    readable = client.get("/v1/payouts", headers={"X-API-Key": raw_key})

    assert blocked.status_code == 409, blocked.text
    assert readable.status_code == 200, readable.text
    assert len(readable.json()["data"]) == 1
