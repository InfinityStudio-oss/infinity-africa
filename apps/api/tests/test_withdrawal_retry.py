"""Retrying a payout that failed for a reason since fixed.

The case this exists for: the platform's Selcom disbursement account ran
out of float, Selcom rejected the payout with HTTP 400, and the
withdrawal went FAILED with the money reversed back into the merchant's
wallet. Topping the float up fixed the cause, but FAILED was terminal —
the only way forward was to ask the merchant to request the whole
withdrawal again.

The risk this is written against is paying a merchant twice. A second
payout goes to a customer-controlled account and is not recoverable, so
the rule these tests pin is: retry only on positive evidence that the
first attempt failed, never on the absence of evidence that it
succeeded.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.selcom_business.client import get_selcom_business_client
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("SELCOM_BUSINESS_MODE", "mock")
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "0")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()


def _merchant_and_admin(fake_client, **overrides):
    merchant = create_merchant(fake_client, **overrides)
    merchant_id = uuid.UUID(merchant["id"])
    admin_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, admin_id, "MERCHANT_ADMIN")
    return merchant_id, admin_id


def _fund_wallet(fake_client, merchant_id, amount, currency="TZS"):
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Merchant Wallet (test)",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": currency,
            "balance": amount,
        },
    )


def _wallet_balance(fake_client, merchant_id) -> Decimal:
    account = next(
        a
        for a in fake_client.table("ledger_accounts")._table.rows
        if a["purpose"] == "merchant_wallet" and a["merchant_id"] == str(merchant_id)
    )
    return Decimal(str(account["balance"]))


def _request_withdrawal(merchant_id, admin_id, amount) -> dict:
    response = client.post(
        "/v1/disbursements/mobile-money",
        headers={**auth_headers(admin_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "merchant_id": str(merchant_id),
            "amount": amount,
            "destination_name": "Jane Doe",
            "destination_identifier": "+255700000000",
            "destination_code": "MPESA",
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]


def _retry(withdrawal_id, super_admin_id):
    return client.post(f"/v1/admin/withdrawals/{withdrawal_id}/retry", headers=auth_headers(super_admin_id))


def _row(fake_client, withdrawal_id) -> dict:
    return next(r for r in fake_client.table("disbursements")._table.rows if r["id"] == withdrawal_id)


class _EmptyFloatProvider:
    """Selcom with no disbursement float: rejects with HTTP 400 and
    records nothing on their side, so no provider_reference is kept."""

    def __init__(self):
        from app.core.errors import SelcomAPIError

        self._error = SelcomAPIError(
            "Selcom Business API returned HTTP 400 for /transaction/process: insufficient balance"
        )

    async def process_transaction(self, **_kwargs):
        raise self._error


class _PayingProvider:
    """Selcom with float restored. Records each payout it was asked for."""

    def __init__(self):
        self.calls: list[dict] = []

    async def process_transaction(self, **kwargs):
        from app.services.selcom_business.schemas import SelcomBusinessResult

        self.calls.append(kwargs)
        return SelcomBusinessResult(
            transaction_id=kwargs["trans_id"],
            status="successful",
            receipt="SB-RETRY-001",
            raw_status="SUCCESS",
            raw_response={"result": "SUCCESS"},
        )


def _setup_failed_withdrawal(fake_client, monkeypatch, *, funded="10000.00", amount="4000.00"):
    """A withdrawal that was approved, hit an empty float, and reversed."""
    import app.services.disbursements as disbursements_module

    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, funded)
    body = _request_withdrawal(merchant_id, admin_id, amount)

    monkeypatch.setattr(disbursements_module, "get_selcom_business_client", lambda: _EmptyFloatProvider())
    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    approve = client.post(
        f"/v1/admin/withdrawals/{body['id']}/approve", headers=auth_headers(super_admin_id)
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["data"]["status"] == "FAILED"
    return merchant_id, super_admin_id, body["id"]


# --- the case this was built for -------------------------------------------


def test_a_withdrawal_that_failed_on_an_empty_float_can_be_retried_once_topped_up(
    fake_client, monkeypatch
):
    import app.services.disbursements as disbursements_module

    merchant_id, super_admin_id, withdrawal_id = _setup_failed_withdrawal(fake_client, monkeypatch)

    # The reversal put the money back, so the merchant is whole while the
    # withdrawal sits failed.
    assert _wallet_balance(fake_client, merchant_id) == Decimal("10000.00")

    provider = _PayingProvider()
    monkeypatch.setattr(disbursements_module, "get_selcom_business_client", lambda: provider)

    response = _retry(withdrawal_id, super_admin_id)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "SUCCESS"
    # Debited exactly once, for exactly this withdrawal.
    assert _wallet_balance(fake_client, merchant_id) == Decimal("6000.00")
    assert len(provider.calls) == 1


def test_the_retry_is_recorded_against_the_admin_who_ran_it(fake_client, monkeypatch):
    """A retry moves real money, so it is its own decision in the audit
    trail rather than an edit of the original approval."""
    import app.services.disbursements as disbursements_module

    _merchant_id, super_admin_id, withdrawal_id = _setup_failed_withdrawal(fake_client, monkeypatch)
    monkeypatch.setattr(disbursements_module, "get_selcom_business_client", lambda: _PayingProvider())

    _retry(withdrawal_id, super_admin_id)

    retried = [
        a for a in fake_client.table("audit_logs")._table.rows if a["action"] == "disbursement.payout_retried"
    ]
    assert len(retried) == 1
    assert retried[0]["actor_id"] == str(super_admin_id)
    # The reason it failed is preserved here, because the row's own
    # admin_status_reason is cleared when it goes back to PROCESSING.
    assert retried[0]["metadata"]["previous_status"] == "FAILED"
    assert "insufficient balance" in retried[0]["metadata"]["previous_reason"]


def test_a_failed_withdrawal_that_never_reached_selcom_is_retried_without_asking_selcom(
    fake_client, monkeypatch
):
    """An HTTP 400 rejection creates nothing on Selcom's side and records
    no provider_reference, so there is no first attempt to ask about."""
    import app.services.disbursements as disbursements_module

    _merchant_id, super_admin_id, withdrawal_id = _setup_failed_withdrawal(fake_client, monkeypatch)
    assert not _row(fake_client, withdrawal_id).get("provider_reference")

    class _WouldFailIfQueried(_PayingProvider):
        async def query_transaction(self, **_kwargs):
            raise AssertionError("must not query Selcom when there is no provider reference")

    monkeypatch.setattr(disbursements_module, "get_selcom_business_client", lambda: _WouldFailIfQueried())
    assert _retry(withdrawal_id, super_admin_id).status_code == 200


# --- never pay twice --------------------------------------------------------


def test_a_retry_is_refused_when_selcom_says_the_first_attempt_already_paid(fake_client, monkeypatch):
    """The one that matters. A second payout goes to a customer-controlled
    account and cannot be clawed back, so a record that disagrees with
    Selcom must stop the retry, not be papered over by it."""
    import app.services.disbursements as disbursements_module

    merchant_id, super_admin_id, withdrawal_id = _setup_failed_withdrawal(fake_client, monkeypatch)
    # Stamp a reference, as the clean-rejection path (HTTP 200 + FAIL)
    # does, so the guard has something to ask about.
    _row(fake_client, withdrawal_id)["provider_reference"] = "DIS-20261004-D76569DB"

    class _AlreadyPaidProvider(_PayingProvider):
        async def query_transaction(self, **_kwargs):
            from app.services.selcom_business.schemas import SelcomBusinessResult

            return SelcomBusinessResult(transaction_id="DIS-20261004-D76569DB", status="successful")

    provider = _AlreadyPaidProvider()
    monkeypatch.setattr(disbursements_module, "get_selcom_business_client", lambda: provider)

    response = _retry(withdrawal_id, super_admin_id)

    assert response.status_code == 409, response.text
    assert "already succeeded" in response.text
    # Nothing was paid and nothing was reserved.
    assert provider.calls == []
    assert _wallet_balance(fake_client, merchant_id) == Decimal("10000.00")


@pytest.mark.parametrize("unresolved_status", ["processing", "ambiguous"])
def test_a_retry_is_refused_while_selcom_has_not_resolved_the_first_attempt(
    fake_client, monkeypatch, unresolved_status
):
    """Still in flight means it may yet pay out. Absence of a failure is
    not evidence of one."""
    import app.services.disbursements as disbursements_module

    merchant_id, super_admin_id, withdrawal_id = _setup_failed_withdrawal(fake_client, monkeypatch)
    _row(fake_client, withdrawal_id)["provider_reference"] = "DIS-20261004-D76569DB"

    class _UnresolvedProvider(_PayingProvider):
        async def query_transaction(self, **_kwargs):
            from app.services.selcom_business.schemas import SelcomBusinessResult

            return SelcomBusinessResult(transaction_id="DIS-1", status=unresolved_status)

    provider = _UnresolvedProvider()
    monkeypatch.setattr(disbursements_module, "get_selcom_business_client", lambda: provider)

    response = _retry(withdrawal_id, super_admin_id)

    assert response.status_code == 409
    assert provider.calls == []
    assert _wallet_balance(fake_client, merchant_id) == Decimal("10000.00")


def test_a_retry_is_refused_when_selcom_cannot_be_reached_to_check(fake_client, monkeypatch):
    """If we cannot ask whether the first attempt paid, we do not guess."""
    import app.services.disbursements as disbursements_module
    from app.core.errors import SelcomAPIError

    merchant_id, super_admin_id, withdrawal_id = _setup_failed_withdrawal(fake_client, monkeypatch)
    _row(fake_client, withdrawal_id)["provider_reference"] = "DIS-20261004-D76569DB"

    class _UnreachableProvider(_PayingProvider):
        async def query_transaction(self, **_kwargs):
            raise SelcomAPIError("Could not reach Selcom Business API (TimeoutException)")

    provider = _UnreachableProvider()
    monkeypatch.setattr(disbursements_module, "get_selcom_business_client", lambda: provider)

    response = _retry(withdrawal_id, super_admin_id)

    assert response.status_code == 409
    assert "DIS-20261004-D76569DB" in response.text  # tells the operator what to go and check
    assert provider.calls == []
    assert _wallet_balance(fake_client, merchant_id) == Decimal("10000.00")


def test_a_retry_proceeds_when_selcom_confirms_the_first_attempt_failed(fake_client, monkeypatch):
    import app.services.disbursements as disbursements_module

    merchant_id, super_admin_id, withdrawal_id = _setup_failed_withdrawal(fake_client, monkeypatch)
    _row(fake_client, withdrawal_id)["provider_reference"] = "DIS-20261004-D76569DB"

    class _ConfirmsFailedProvider(_PayingProvider):
        async def query_transaction(self, **_kwargs):
            from app.services.selcom_business.schemas import SelcomBusinessResult

            return SelcomBusinessResult(transaction_id="DIS-1", status="failed")

    monkeypatch.setattr(disbursements_module, "get_selcom_business_client", lambda: _ConfirmsFailedProvider())

    response = _retry(withdrawal_id, super_admin_id)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "SUCCESS"
    assert _wallet_balance(fake_client, merchant_id) == Decimal("6000.00")


# --- funds that were never released -----------------------------------------


def test_retrying_a_blocked_withdrawal_does_not_reserve_the_money_twice(fake_client, monkeypatch):
    """BLOCKED_IP_WHITELIST keeps the reservation deliberately — the
    withdrawal is valid, only our network access was wrong. Reserving
    again on retry would debit the merchant twice for one withdrawal.

    This state previously had no action at all, so the money stayed held
    indefinitely.
    """
    import app.services.disbursements as disbursements_module
    from app.core.errors import SelcomAPIError

    merchant_id, admin_id = _merchant_and_admin(fake_client)
    _fund_wallet(fake_client, merchant_id, "10000.00")
    body = _request_withdrawal(merchant_id, admin_id, "4000.00")

    class _WhitelistBlockedProvider:
        async def process_transaction(self, **_kwargs):
            error = SelcomAPIError("Selcom Business API returned HTTP 403: IP not whitelisted")
            error.is_ip_whitelist_error = True
            raise error

    monkeypatch.setattr(
        disbursements_module, "get_selcom_business_client", lambda: _WhitelistBlockedProvider()
    )
    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    approve = client.post(
        f"/v1/admin/withdrawals/{body['id']}/approve", headers=auth_headers(super_admin_id)
    )
    assert approve.json()["data"]["status"] == "BLOCKED_IP_WHITELIST"
    # Money is held, not returned.
    assert _wallet_balance(fake_client, merchant_id) == Decimal("6000.00")

    provider = _PayingProvider()
    monkeypatch.setattr(disbursements_module, "get_selcom_business_client", lambda: provider)
    response = _retry(body["id"], super_admin_id)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "SUCCESS"
    # Still 6000, not 2000: the existing reservation was reused.
    assert _wallet_balance(fake_client, merchant_id) == Decimal("6000.00")
    assert len(provider.calls) == 1


# --- what cannot be retried --------------------------------------------------


@pytest.mark.parametrize("status", ["SUCCESS", "PENDING_ADMIN_APPROVAL", "PROCESSING", "REJECTED"])
def test_a_withdrawal_in_a_non_retryable_state_is_refused(fake_client, monkeypatch, status):
    """Most importantly SUCCESS: retrying a completed payout would pay the
    merchant a second time."""
    _merchant_id, super_admin_id, withdrawal_id = _setup_failed_withdrawal(fake_client, monkeypatch)
    _row(fake_client, withdrawal_id)["status"] = status

    response = _retry(withdrawal_id, super_admin_id)
    assert response.status_code == 409, response.text
    assert "can be retried" in response.text


def test_a_retry_re_runs_the_merchant_gates(fake_client, monkeypatch):
    """A retry is a fresh decision to move money, so a merchant suspended
    since the original approval must not be paid out just because their
    withdrawal predates the suspension."""
    merchant_id, super_admin_id, withdrawal_id = _setup_failed_withdrawal(fake_client, monkeypatch)

    merchant = next(m for m in fake_client.table("merchants")._table.rows if m["id"] == str(merchant_id))
    merchant["status"] = "suspended"

    response = _retry(withdrawal_id, super_admin_id)
    assert response.status_code in (403, 409), response.text
    assert _wallet_balance(fake_client, merchant_id) == Decimal("10000.00")


def test_a_retry_requires_a_super_admin(fake_client, monkeypatch):
    _merchant_id, _super_admin_id, withdrawal_id = _setup_failed_withdrawal(fake_client, monkeypatch)
    response = _retry(withdrawal_id, uuid.uuid4())
    assert response.status_code in (401, 403)


def test_retrying_an_unknown_withdrawal_is_a_404(fake_client):
    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    assert _retry(str(uuid.uuid4()), super_admin_id).status_code == 404


# --- the float balance that would have prevented all of this ----------------


def test_the_float_balance_is_reported_when_selcom_answers(fake_client, monkeypatch):
    import app.routers.admin_withdrawals as router_module

    monkeypatch.setenv("SELCOM_BUSINESS_ACCOUNT_NUMBER", "5529108708283")
    get_settings.cache_clear()

    class _BalanceProvider:
        async def balance(self, *, account_number):
            return {"result": "SUCCESS", "data": {"account_number": account_number, "balance": "250000.00"}}

    monkeypatch.setattr(router_module, "get_selcom_business_client", lambda: _BalanceProvider())

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    response = client.get("/v1/admin/withdrawals/float-balance", headers=auth_headers(super_admin_id))

    assert response.status_code == 200, response.text
    assert response.json()["data"]["available"] == "250000.00"


@pytest.mark.parametrize(
    ("provider_behaviour", "expected_reason"),
    [
        ("raises", "provider_unavailable"),
        ("unrecognised", "unrecognised_response"),
    ],
)
def test_the_float_balance_degrades_instead_of_breaking_the_page(
    fake_client, monkeypatch, provider_behaviour, expected_reason
):
    """The withdrawals page must still load when Selcom is down, and must
    never show a number we are not sure of — it is the figure an operator
    would decide to approve a payout on."""
    import app.routers.admin_withdrawals as router_module

    monkeypatch.setenv("SELCOM_BUSINESS_ACCOUNT_NUMBER", "5529108708283")
    get_settings.cache_clear()

    class _Provider:
        async def balance(self, *, account_number):
            if provider_behaviour == "raises":
                raise RuntimeError("Selcom unreachable")
            return {"result": "SUCCESS", "data": {"somethingElse": "1"}}

    monkeypatch.setattr(router_module, "get_selcom_business_client", lambda: _Provider())

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    response = client.get("/v1/admin/withdrawals/float-balance", headers=auth_headers(super_admin_id))

    assert response.status_code == 200, response.text
    assert response.json()["data"]["available"] is None
    assert response.json()["data"]["reason"] == expected_reason


def test_the_float_balance_says_so_when_no_account_is_configured(fake_client, monkeypatch):
    monkeypatch.setenv("SELCOM_BUSINESS_ACCOUNT_NUMBER", "")
    get_settings.cache_clear()

    super_admin_id = uuid.uuid4()
    make_super_admin(fake_client, super_admin_id)
    response = client.get("/v1/admin/withdrawals/float-balance", headers=auth_headers(super_admin_id))

    assert response.status_code == 200
    assert response.json()["data"]["reason"] == "not_configured"
