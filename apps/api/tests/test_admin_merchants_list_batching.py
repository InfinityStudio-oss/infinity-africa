"""The Super Admin Businesses page asked the same two questions once per
row, and the page got slow enough to notice.

Reported on 2026-10-23 as "this page taking a long to open". Two lookups
inside the loop over a page of up to a hundred merchants:

  * the production-API gate called find_pricing_rule, which walks six
    precedence tiers - up to six queries per merchant;
  * get_wallet_balance, which costs two queries per merchant.

At 85 merchants that is several hundred sequential round trips for one
page, growing with every business that signs up. Worse, get_wallet_balance
is a get-*or-create*: opening a read-only list inserted ledger accounts.

Both are now asked once for the whole page. The tests that matter here are
not the speed ones - they are the equivalence ones. A faster page that
reports a different balance or quietly grants API eligibility would be far
worse than a slow one, so the batched answers are checked against the
per-merchant helpers they replaced, across every state a merchant can be
in.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.admin_directory import batch_wallet_balances
from app.services.api_access import (
    is_production_api_access_allowed,
    merchants_with_production_api_access,
)
from app.services.ledger import get_wallet_balance
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    create_pricing_rule,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _admin(fake_client):
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    return admin_id


def _rows(fake_client, admin_id):
    response = client.get("/v1/admin/merchants", headers=auth_headers(admin_id))
    assert response.status_code == 200, response.text
    return {r["merchant_id"]: r for r in response.json()["data"]}


def _seed_wallet(fake_client, merchant_id, balance, *, currency="TZS"):
    return fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": f"wallet {merchant_id}",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": currency,
            "balance": str(balance),
        },
    )


def _count_table_calls(fake_client, monkeypatch):
    """Every .table(name) the code under test opens.

    A proxy for query count rather than an exact one, which is all this
    needs: the property under test is whether the work grows with the
    number of merchants, not its precise constant.
    """
    calls: list[str] = []
    original = fake_client.table

    def counting(name):
        calls.append(name)
        return original(name)

    monkeypatch.setattr(fake_client, "table", counting)
    return calls


# --- eligibility: the batched gate must agree with the per-row gate ------


def test_the_batched_gate_agrees_with_the_per_merchant_gate(fake_client):
    """The test this change rests on. Every state a merchant can be in,
    checked both ways - a disagreement here would mean the page grants or
    denies production API access on different grounds than the gate that
    actually guards key creation."""
    with_rule = create_merchant(fake_client)
    create_pricing_rule(fake_client, merchant_id=uuid.UUID(with_rule["id"]))

    no_rule = create_merchant(fake_client)
    suspended = create_merchant(fake_client, api_access_suspended=True)
    create_pricing_rule(fake_client, merchant_id=uuid.UUID(suspended["id"]))
    pending = create_merchant(fake_client, status="pending")
    create_pricing_rule(fake_client, merchant_id=uuid.UUID(pending["id"]))
    unverified = create_merchant(fake_client, kyc_status="pending")
    create_pricing_rule(fake_client, merchant_id=uuid.UUID(unverified["id"]))

    merchants = [with_rule, no_rule, suspended, pending, unverified]
    batched = merchants_with_production_api_access(fake_client, merchants)

    for merchant in merchants:
        per_row = is_production_api_access_allowed(fake_client, merchant)
        assert (str(merchant["id"]) in batched) is per_row, merchant["id"]

    # Guards against the whole matrix agreeing because everything is False.
    assert str(with_rule["id"]) in batched
    assert str(no_rule["id"]) not in batched


def test_a_platform_fallback_makes_every_approved_merchant_eligible(fake_client):
    """The shortcut in merchants_with_pricing_rule: a rule with no
    merchant_id resolves for everyone, so it must not be mistaken for
    nobody having pricing."""
    first = create_merchant(fake_client)
    second = create_merchant(fake_client)
    create_pricing_rule(fake_client, merchant_id=None)

    batched = merchants_with_production_api_access(fake_client, [first, second])

    assert batched == {str(first["id"]), str(second["id"])}
    assert is_production_api_access_allowed(fake_client, first) is True


def test_a_platform_fallback_still_does_not_rescue_a_suspended_merchant(fake_client):
    """The local checks are applied per merchant, before the shortcut. A
    suspended merchant passing because a platform rule exists would turn
    the abuse kill switch off."""
    suspended = create_merchant(fake_client, api_access_suspended=True)
    create_pricing_rule(fake_client, merchant_id=None)

    assert merchants_with_production_api_access(fake_client, [suspended]) == set()
    assert is_production_api_access_allowed(fake_client, suspended) is False


def test_one_merchants_rule_does_not_make_another_eligible(fake_client):
    has = create_merchant(fake_client)
    has_not = create_merchant(fake_client)
    create_pricing_rule(fake_client, merchant_id=uuid.UUID(has["id"]))

    batched = merchants_with_production_api_access(fake_client, [has, has_not])

    assert batched == {str(has["id"])}


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"is_active": False}, "deactivated"),
        ({"effective_from": "2099-01-01T00:00:00+00:00"}, "not yet in effect"),
        ({"effective_to": "2020-01-01T00:00:00+00:00"}, "already expired"),
    ],
)
def test_a_rule_that_is_not_live_now_does_not_count(fake_client, overrides, reason):
    """_pick_active_now is reused rather than reimplemented, so the batched
    form must inherit its date handling exactly."""
    merchant = create_merchant(fake_client)
    create_pricing_rule(fake_client, merchant_id=uuid.UUID(merchant["id"]), **overrides)

    assert merchants_with_production_api_access(fake_client, [merchant]) == set(), reason
    assert is_production_api_access_allowed(fake_client, merchant) is False, reason


def test_no_merchants_asks_nothing(fake_client, monkeypatch):
    calls = _count_table_calls(fake_client, monkeypatch)

    assert merchants_with_production_api_access(fake_client, []) == set()
    assert calls == []


# --- balances: same number, without creating anything -------------------


def test_the_batched_balance_matches_the_single_lookup(fake_client):
    """batch_wallet_balances is not new - it already existed for the
    withdrawal approval queue, read-only by design. This page just wasn't
    using it. Checked against get_wallet_balance all the same, because this
    is now where a Super Admin reads a merchant's balance."""
    merchant = create_merchant(fake_client)
    _seed_wallet(fake_client, merchant["id"], "12500.75")

    batched = batch_wallet_balances(fake_client, {str(merchant["id"])})
    single = get_wallet_balance(
        fake_client, merchant_id=uuid.UUID(merchant["id"]), currency="TZS"
    )

    assert Decimal(batched[str(merchant["id"])]) == single == Decimal("12500.75")


def test_a_merchant_with_no_wallet_account_is_simply_absent(fake_client):
    """Absent, not zero, so the caller decides - and the caller defaults to
    zero. A merchant with no wallet account has never held money."""
    merchant = create_merchant(fake_client)

    assert batch_wallet_balances(fake_client, {str(merchant["id"])}) == {}


def test_listing_merchants_creates_no_ledger_accounts(fake_client):
    """The side effect that mattered as much as the speed: get_wallet_balance
    is a get-or-create, so opening a read-only admin page inserted a row for
    every merchant that had never traded."""
    admin_id = _admin(fake_client)
    for _ in range(3):
        create_merchant(fake_client)
    before = len(fake_client.table("ledger_accounts")._table.rows)

    _rows(fake_client, admin_id)

    assert len(fake_client.table("ledger_accounts")._table.rows) == before


def test_a_non_wallet_ledger_account_is_not_counted_as_a_balance(fake_client):
    """purpose is filtered, as get_wallet_balance filters it. A fee or
    settlement account is not the merchant's money."""
    merchant = create_merchant(fake_client)
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant["id"]),
            "name": "fees",
            "account_type": "revenue",
            "purpose": "platform_fees",
            "currency": "TZS",
            "balance": "4000",
        },
    )

    assert batch_wallet_balances(fake_client, {str(merchant["id"])}) == {}


# --- what the page actually renders -------------------------------------


def test_the_page_still_reports_the_right_balance_and_eligibility(fake_client):
    """End to end through the endpoint, because the batching is only correct
    if the row a Super Admin reads is unchanged."""
    admin_id = _admin(fake_client)
    rich = create_merchant(fake_client, business_name="Rich WiFi")
    _seed_wallet(fake_client, rich["id"], "75000")
    create_pricing_rule(fake_client, merchant_id=uuid.UUID(rich["id"]))
    broke = create_merchant(fake_client, business_name="New WiFi")

    rows = _rows(fake_client, admin_id)

    assert Decimal(str(rows[str(rich["id"])]["available_balance"])) == Decimal(75000)
    assert rows[str(rich["id"])]["production_api_eligible"] is True
    assert Decimal(str(rows[str(broke["id"])]["available_balance"])) == Decimal(0)
    assert rows[str(broke["id"])]["production_api_eligible"] is False


def test_a_suspended_merchant_is_still_shown_as_ineligible_on_the_page(fake_client):
    admin_id = _admin(fake_client)
    suspended = create_merchant(fake_client, api_access_suspended=True)
    create_pricing_rule(fake_client, merchant_id=uuid.UUID(suspended["id"]))

    row = _rows(fake_client, admin_id)[str(suspended["id"])]

    assert row["production_api_eligible"] is False
    assert row["api_access_suspended"] is True


# --- the property that was broken --------------------------------------


def test_the_work_does_not_grow_with_the_number_of_merchants(fake_client, monkeypatch):
    """The actual regression guard. Asserted as a ceiling rather than an
    exact count so unrelated additions to the page do not fail it, but a
    return to per-row lookups would: at 12 merchants the old code opened
    roughly a hundred.
    """
    admin_id = _admin(fake_client)
    for index in range(12):
        merchant = create_merchant(fake_client, business_name=f"Merchant {index}")
        _seed_wallet(fake_client, merchant["id"], "1000")
        create_pricing_rule(fake_client, merchant_id=uuid.UUID(merchant["id"]))

    calls = _count_table_calls(fake_client, monkeypatch)
    rows = _rows(fake_client, admin_id)

    assert len(rows) == 12
    assert len(calls) < 25, f"{len(calls)} table opens for 12 merchants: {calls}"


def test_the_pricing_lookup_is_one_query_for_a_whole_page(fake_client, monkeypatch):
    """Twelve merchants, each with their own rule: one batched query, not
    twelve walks of six tiers."""
    merchants = [create_merchant(fake_client) for _ in range(12)]
    for merchant in merchants:
        create_pricing_rule(fake_client, merchant_id=uuid.UUID(merchant["id"]))

    calls = _count_table_calls(fake_client, monkeypatch)
    eligible = merchants_with_production_api_access(fake_client, merchants)

    assert len(eligible) == 12
    assert calls.count("merchant_pricing_rules") <= 2, calls
