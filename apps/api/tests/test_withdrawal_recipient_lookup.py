"""Resolving who owns a withdrawal destination, for the review step.

The merchant stopped typing a recipient name because nothing checked it.
This asks Selcom instead. Everything here defends the same idea from
different directions: a name shown on a payout confirmation must either be
the provider's answer or absent, and trying to get one must never make the
payout itself worse.
"""

import logging
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.selcom.outbound_guard import reset_outbound_guard, selcom_outbound
from app.services.selcom_business.client import get_selcom_business_client
from app.services.withdrawals.recipient_lookup import resolve_recipient_name
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
)

client = TestClient(app)

_LOOKUP = "app.services.withdrawals.recipient_lookup"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("SELCOM_BUSINESS_MODE", "mock")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    monkeypatch.setenv("SELCOM_OUTBOUND_MAX_PER_MINUTE", "1000")
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()
    reset_outbound_guard()
    yield
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()
    reset_outbound_guard()


@pytest.fixture
def merchant_admin(fake_client):
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    return merchant_id, user_id


class _CaptureHandler(logging.Handler):
    """The app sets propagate=False on the "infinity" logger (see
    app/main.py, which says so explicitly because of caplog), so caplog
    never sees these records. Attach directly instead."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())

    @property
    def text(self) -> str:
        return chr(10).join(self.messages)


@pytest.fixture
def lookup_logs():
    logger = logging.getLogger("infinity.recipient_lookup")
    handler = _CaptureHandler()
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)
    logger.setLevel(previous_level)


def _lookup(user_id, **overrides):
    payload = {
        "method": "SELCOM_PESA",
        "destination_code": "SELCOM",
        "destination_identifier": "+255700000000",
        **overrides,
    }
    return client.post(
        "/v1/merchant/withdrawals/resolve-recipient", headers=auth_headers(user_id), json=payload
    )


def _fake_client(response=None, side_effect=None):
    fake = AsyncMock()
    fake.account_lookup = AsyncMock(return_value=response, side_effect=side_effect)
    return fake


# --- the name comes from the provider, or not at all -----------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"success": True, "data": {"accountName": "JOHN DOE"}},
        {"success": True, "data": {"recipientName": "JOHN DOE"}},
        {"success": True, "data": {"customer_name": "JOHN DOE"}},
        {"success": True, "data": {"name": "JOHN DOE"}},
        {"success": True, "name": "JOHN DOE"},
    ],
)
async def test_a_name_is_read_from_any_shape_selcom_might_use(response):
    """The response field is the one part of /account/lookup that is not
    verified against a real call, so several plausible shapes are tried."""
    with patch(f"{_LOOKUP}.get_selcom_business_client", return_value=_fake_client(response)):
        name = await resolve_recipient_name(
            destination_code="CRDB", destination_identifier="0123456789"
        )

    assert name == "JOHN DOE"


@pytest.mark.asyncio
async def test_an_unrecognised_response_yields_no_name_rather_than_a_guess():
    """A wrong name on a payout confirmation is worse than no name: it
    reads as though the destination was verified."""
    response = {"success": True, "data": {"bank": "CRDB", "account": "0123456789"}}

    with patch(f"{_LOOKUP}.get_selcom_business_client", return_value=_fake_client(response)):
        name = await resolve_recipient_name(
            destination_code="CRDB", destination_identifier="0123456789"
        )

    assert name is None


@pytest.mark.asyncio
async def test_an_unrecognised_response_logs_its_keys_so_the_real_field_can_be_learned(lookup_logs):
    """The first live call is how the real field name gets discovered —
    the same way the Selcom Checkout webhook's header casing was."""
    response = {"success": True, "data": {"holder": "JOHN DOE"}}

    with patch(f"{_LOOKUP}.get_selcom_business_client", return_value=_fake_client(response)):
        await resolve_recipient_name(destination_code="CRDB", destination_identifier="0123456789")

    assert "data.holder" in lookup_logs.text


@pytest.mark.asyncio
async def test_the_account_holders_name_is_never_written_to_the_log(lookup_logs):
    response = {"success": True, "data": {"holder": "JOHN DOE"}}

    with patch(f"{_LOOKUP}.get_selcom_business_client", return_value=_fake_client(response)):
        await resolve_recipient_name(destination_code="CRDB", destination_identifier="0123456789")

    assert lookup_logs.text, "nothing was captured, so this proves nothing"
    assert "JOHN DOE" not in lookup_logs.text


# --- it cannot make a payout worse -----------------------------------------


@pytest.mark.asyncio
async def test_a_provider_failure_is_an_unknown_name_not_an_error():
    with patch(
        f"{_LOOKUP}.get_selcom_business_client",
        return_value=_fake_client(side_effect=RuntimeError("selcom down")),
    ):
        assert (
            await resolve_recipient_name(
                destination_code="CRDB", destination_identifier="0123456789"
            )
            is None
        )


@pytest.mark.asyncio
async def test_a_failing_lookup_does_not_trip_the_payout_circuit_breaker(monkeypatch):
    """The breaker gates real payouts. /account/lookup has never been
    exercised live, so a lookup that always fails must not take
    withdrawals down with it."""
    monkeypatch.setenv("SELCOM_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "3")
    get_settings.cache_clear()
    reset_outbound_guard()

    with patch(
        f"{_LOOKUP}.get_selcom_business_client",
        return_value=_fake_client(side_effect=RuntimeError("selcom down")),
    ):
        for _ in range(10):
            await resolve_recipient_name(
                destination_code="CRDB", destination_identifier="0123456789"
            )

    # The breaker must still be closed: a real payout can still be made.
    async with selcom_outbound():
        pass


@pytest.mark.asyncio
async def test_an_unconfigured_provider_is_an_unknown_name_not_a_crash():
    with patch(
        f"{_LOOKUP}.get_selcom_business_client", side_effect=RuntimeError("not configured")
    ):
        assert (
            await resolve_recipient_name(
                destination_code="CRDB", destination_identifier="0123456789"
            )
            is None
        )


@pytest.mark.asyncio
async def test_an_empty_destination_asks_the_provider_nothing():
    fake = _fake_client({"success": True, "data": {"name": "X"}})
    with patch(f"{_LOOKUP}.get_selcom_business_client", return_value=fake):
        assert await resolve_recipient_name(destination_code="CRDB", destination_identifier="") is None

    fake.account_lookup.assert_not_called()


# --- the endpoint -----------------------------------------------------------


def test_the_endpoint_returns_the_resolved_name(fake_client, merchant_admin):
    _merchant_id, user_id = merchant_admin

    with patch(
        f"{_LOOKUP}.get_selcom_business_client",
        return_value=_fake_client({"success": True, "data": {"accountName": "JANE DOE"}}),
    ):
        response = _lookup(user_id)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["recipient_name"] == "JANE DOE"


def test_the_endpoint_returns_null_rather_than_failing_when_the_provider_is_down(
    fake_client, merchant_admin
):
    """The review step must still open. A withdrawal is not blocked
    because a courtesy lookup could not be made."""
    _merchant_id, user_id = merchant_admin

    with patch(
        f"{_LOOKUP}.get_selcom_business_client",
        return_value=_fake_client(side_effect=RuntimeError("selcom down")),
    ):
        response = _lookup(user_id)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["recipient_name"] is None


def test_the_lookup_creates_no_withdrawal(fake_client, merchant_admin):
    _merchant_id, user_id = merchant_admin
    before = len(fake_client.table("disbursements")._table.rows)

    with patch(
        f"{_LOOKUP}.get_selcom_business_client",
        return_value=_fake_client({"success": True, "data": {"accountName": "JANE DOE"}}),
    ):
        _lookup(user_id)

    assert len(fake_client.table("disbursements")._table.rows) == before


def test_looking_up_destinations_is_rate_limited(fake_client, merchant_admin):
    """This is an account-name oracle: without a limit, a merchant login
    could walk a range of numbers and harvest the name behind each."""
    _merchant_id, user_id = merchant_admin

    with patch(
        f"{_LOOKUP}.get_selcom_business_client",
        return_value=_fake_client({"success": True, "data": {"accountName": "JANE DOE"}}),
    ):
        statuses = [_lookup(user_id).status_code for _ in range(11)]

    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429, "an 11th lookup in a minute was allowed"


def test_a_lookup_is_audited_with_a_masked_destination_and_no_name(fake_client, merchant_admin):
    _merchant_id, user_id = merchant_admin

    with patch(
        f"{_LOOKUP}.get_selcom_business_client",
        return_value=_fake_client({"success": True, "data": {"accountName": "JANE DOE"}}),
    ):
        _lookup(user_id, destination_identifier="+255712345678")

    row = next(
        r
        for r in fake_client.table("audit_logs")._table.rows
        if r.get("action") == "withdrawal.recipient_lookup"
    )
    serialised = str(row)
    assert "JANE DOE" not in serialised, "the resolved name was written to the audit trail"
    assert "255712345678" not in serialised
    assert row["metadata"]["resolved"] is True


def test_a_merchant_staff_member_cannot_look_up_destinations(fake_client):
    """Merchant-admin only, matching who can request a withdrawal."""
    merchant = create_merchant(fake_client)
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), user_id, "MERCHANT_STAFF")

    assert _lookup(user_id).status_code in (401, 403, 404)


def test_an_invalid_phone_is_refused_before_the_provider_is_asked(fake_client, merchant_admin):
    _merchant_id, user_id = merchant_admin

    fake = _fake_client({"success": True, "data": {"accountName": "JANE DOE"}})
    with patch(f"{_LOOKUP}.get_selcom_business_client", return_value=fake):
        response = _lookup(user_id, destination_identifier="not-a-phone")

    assert response.status_code == 422
    fake.account_lookup.assert_not_called()
