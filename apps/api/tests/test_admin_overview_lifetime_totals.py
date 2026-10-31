"""Lifetime Collections Total and Revenue Total on the Command Center.

Two cards that must be right for the life of the platform, so the things
worth pinning are the ones that only go wrong slowly: a payment counted
twice, a period boundary that quietly resets a total, a figure that stops
at the first page of rows, and a failure that renders as zero.

**Definitions, matched to the cards that already existed rather than
invented here:**

* collections - ``public.transactions`` where ``type = 'collection'`` and
  ``status = 'successful'``, summing ``gross_amount``. The transactions
  table, never ``public.collections``: one successful payment writes a row
  in each and adding both doubles everything.
* revenue - credit entries on the one ``platform_revenue`` ledger account.
  Reversals are debits and are deliberately NOT subtracted; that is the
  existing treatment, preserved on purpose and asserted below so a future
  change to it has to be deliberate too.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.time import dar_es_salaam_day_start_utc, dar_es_salaam_month_start_utc
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_super_admin,
)

client = TestClient(app)

OVERVIEW = "/v1/admin/overview"


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _admin(fake_client):
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    return admin_id


def _revenue_account(fake_client) -> str:
    return fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": None,
            "name": "Platform Revenue",
            "account_type": "revenue",
            "purpose": "platform_revenue",
            "currency": "TZS",
            "balance": "0",
        },
    )["id"]


def _collection(fake_client, merchant_id, *, amount, when, status="successful", kind="collection"):
    return fake_client.seed(
        "transactions",
        {
            "merchant_id": str(merchant_id),
            "type": kind,
            "status": status,
            "gross_amount": amount,
            "fee_amount": "0",
            "net_amount": amount,
            "currency": "TZS",
            "created_at": when,
        },
    )


def _revenue_entry(fake_client, account_id, *, amount, when, direction="credit"):
    return fake_client.seed(
        "ledger_entries",
        {
            "ledger_account_id": account_id,
            "direction": direction,
            "amount": amount,
            "currency": "TZS",
            "created_at": when,
        },
    )


def _overview(fake_client):
    response = client.get(OVERVIEW, headers=auth_headers(_admin(fake_client)))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def seeded(fake_client):
    """A platform with history: one payment years back, one last month,
    one today. Every figure below is checkable by hand."""
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    account_id = _revenue_account(fake_client)

    now = datetime.now(timezone.utc)
    today = _iso(datetime.fromisoformat(dar_es_salaam_day_start_utc(now).replace("Z", "+00:00")) + timedelta(hours=1))
    this_month = _iso(
        datetime.fromisoformat(dar_es_salaam_month_start_utc(now).replace("Z", "+00:00")) + timedelta(hours=1)
    )
    long_ago = _iso(now - timedelta(days=400))

    _collection(fake_client, merchant_id, amount="1000.00", when=today)
    _collection(fake_client, merchant_id, amount="200.00", when=this_month)
    _collection(fake_client, merchant_id, amount="30.00", when=long_ago)

    _revenue_entry(fake_client, account_id, amount="23.00", when=today)
    _revenue_entry(fake_client, account_id, amount="4.60", when=this_month)
    # Deliberately NOT 2.3% of 30.00. Pricing has changed over the
    # platform's life and merchant rates differ, so a lifetime figure
    # that could be reproduced by one rate would prove nothing.
    _revenue_entry(fake_client, account_id, amount="1.50", when=long_ago)

    return {"merchant_id": merchant_id, "account_id": account_id, "today": today, "long_ago": long_ago}


# --- The totals themselves -------------------------------------------------


def test_collections_total_is_every_successful_collection_ever(fake_client, seeded):
    data = _overview(fake_client)

    # 1000 + 200 + 30, including the one from over a year ago.
    assert Decimal(data["collections_total"]) == Decimal("1230.00")


def test_revenue_total_is_every_credit_ever(fake_client, seeded):
    data = _overview(fake_client)

    assert Decimal(data["revenue_total"]) == Decimal("29.10")


def test_amounts_cross_the_api_as_decimal_strings(fake_client, seeded):
    """Money does not travel as a JSON number. A numeric(14,2) read back
    through one arrives as a float, and the browser then formats a value
    that is not quite what the database holds."""
    data = _overview(fake_client)

    for field in ("collections_total", "revenue_total", "collections_today", "platform_revenue"):
        assert isinstance(data[field], str), f"{field} came back as {type(data[field]).__name__}"


# --- Counted once, and only the right rows ---------------------------------


def test_a_payment_is_counted_once_not_once_per_table(fake_client, seeded):
    """One successful payment writes a transactions row AND a collections
    row. Summing both doubles every figure on the dashboard."""
    fake_client.seed(
        "collections",
        {
            "merchant_id": str(seeded["merchant_id"]),
            "amount": "1000.00",
            "currency": "TZS",
            "status": "successful",
            "created_at": seeded["today"],
        },
    )

    data = _overview(fake_client)

    assert Decimal(data["collections_total"]) == Decimal("1230.00")


@pytest.mark.parametrize("status", ["pending", "failed", "cancelled", "rejected", "processing"])
def test_only_successful_collections_count(fake_client, seeded, status):
    _collection(fake_client, seeded["merchant_id"], amount="999999.00", when=seeded["today"], status=status)

    data = _overview(fake_client)

    assert Decimal(data["collections_total"]) == Decimal("1230.00")


def test_a_withdrawal_is_not_a_collection(fake_client, seeded):
    """Merchant balances, payouts and customer funds are not platform
    income and must not reach either card."""
    _collection(
        fake_client,
        seeded["merchant_id"],
        amount="500000.00",
        when=seeded["today"],
        kind="disbursement",
    )

    data = _overview(fake_client)

    assert Decimal(data["collections_total"]) == Decimal("1230.00")


def test_another_ledger_account_is_not_platform_revenue(fake_client, seeded):
    """A merchant wallet is the merchant's money. Revenue is one account."""
    wallet = fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(seeded["merchant_id"]),
            "name": "Merchant Wallet",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": "TZS",
            "balance": "0",
        },
    )["id"]
    _revenue_entry(fake_client, wallet, amount="750000.00", when=seeded["today"])

    data = _overview(fake_client)

    assert Decimal(data["revenue_total"]) == Decimal("29.10")


# --- Refunds and reversals, as they already behaved ------------------------


def test_a_reversal_does_not_reduce_revenue(fake_client, seeded):
    """**Documents existing behaviour rather than endorsing it.**

    Revenue counts credits only, so a debit that reverses a fee leaves
    the figure where it was. On 2026-10-31 production held nine such
    debits totalling TZS 3,728 — eight withdrawal fees reversed after a
    payout failed, one platform fee reversed after a provider reversed a
    collection — and none of them reduced any card.

    That treatment is carried into the lifetime totals unchanged, because
    changing what revenue means is a business decision rather than a side
    effect of adding a card. It matters more here than on a daily figure,
    since the distortion only accumulates. If this test ever has to
    change, that should be because somebody decided it should.
    """
    _revenue_entry(fake_client, seeded["account_id"], amount="20.00", when=seeded["today"], direction="debit")

    data = _overview(fake_client)

    assert Decimal(data["revenue_total"]) == Decimal("29.10")
    assert Decimal(data["platform_revenue_today"]) == Decimal("23.00")


def test_revenue_uses_recorded_amounts_not_a_rate_applied_to_collections(fake_client, seeded):
    """Historic pricing differed and merchant rates differ. Revenue is
    read from the ledger, so it cannot be collections times any rate."""
    data = _overview(fake_client)

    collections = Decimal(data["collections_total"])
    revenue = Decimal(data["revenue_total"])

    assert revenue != collections * Decimal("0.023")
    assert revenue == Decimal("29.10")


# --- Periods, and the rollover ---------------------------------------------


def test_the_daily_and_monthly_cards_still_report_their_own_periods(fake_client, seeded):
    """The lifetime cards are additions, not replacements."""
    data = _overview(fake_client)

    assert Decimal(data["collections_today"]) == Decimal("1000.00")
    assert Decimal(data["collections_this_month"]) == Decimal("1200.00")
    assert Decimal(data["platform_revenue_today"]) == Decimal("23.00")
    assert Decimal(data["platform_revenue"]) == Decimal("27.60")


def test_lifetime_totals_include_what_the_monthly_ones_have_left_behind(fake_client, seeded):
    """The whole point of the pair. The 400-day-old payment is outside
    every period card and inside both lifetime ones."""
    data = _overview(fake_client)

    assert Decimal(data["collections_this_month"]) == Decimal("1200.00")
    assert Decimal(data["collections_total"]) == Decimal("1230.00")
    assert Decimal(data["collections_total"]) > Decimal(data["collections_this_month"])


def test_a_month_boundary_moves_the_monthly_cards_and_not_the_lifetime_ones(fake_client, monkeypatch):
    """1 November, told as a story.

    October's activity leaves the monthly cards and stays in the lifetime
    ones. Nothing is reset, deleted or rewritten; the monthly figure is
    small again only because its query asks for a different period.
    """
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    account_id = _revenue_account(fake_client)

    # Late October, Dar es Salaam.
    october = "2026-10-31T20:00:00Z"
    november = "2026-11-01T06:00:00Z"
    _collection(fake_client, merchant_id, amount="5000.00", when=october)
    _revenue_entry(fake_client, account_id, amount="115.00", when=october)

    import app.services.admin_overview as overview_module

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(overview_module, "datetime", _FixedDatetime)

    _collection(fake_client, merchant_id, amount="700.00", when=november)
    _revenue_entry(fake_client, account_id, amount="16.10", when=november)

    data = _overview(fake_client)

    # November only.
    assert Decimal(data["collections_this_month"]) == Decimal("700.00")
    assert Decimal(data["platform_revenue"]) == Decimal("16.10")
    # October is still there, where it belongs.
    assert Decimal(data["collections_total"]) == Decimal("5700.00")
    assert Decimal(data["revenue_total"]) == Decimal("131.10")


def test_lifetime_totals_do_not_reset(fake_client, seeded):
    """Read twice; nothing about asking changes the answer."""
    first = _overview(fake_client)
    second = _overview(fake_client)

    assert first["collections_total"] == second["collections_total"]
    assert first["revenue_total"] == second["revenue_total"]


# --- Beyond one page -------------------------------------------------------


def test_the_total_is_not_capped_at_one_page_of_rows(fake_client):
    """The failure mode this feature is most exposed to. PostgREST serves
    1000 rows a page, and a figure summed from one page stops dead at
    that line — which is exactly how Collections Today once read TZS 0.00
    on a morning that had taken 41 payments. A lifetime total is past
    that line permanently."""
    merchant = create_merchant(fake_client)
    merchant_id = uuid.UUID(merchant["id"])
    account_id = _revenue_account(fake_client)

    now = datetime.now(timezone.utc)
    for index in range(1200):
        when = _iso(now - timedelta(days=index % 500, seconds=index))
        _collection(fake_client, merchant_id, amount="10.00", when=when)
        _revenue_entry(fake_client, account_id, amount="0.23", when=when)

    data = _overview(fake_client)

    assert Decimal(data["collections_total"]) == Decimal("12000.00")
    assert Decimal(data["revenue_total"]) == Decimal("276.00")


# --- When the database function is not there -------------------------------


def _break_the_rpc(fake_client, monkeypatch):
    real = fake_client.rpc

    def missing(fn_name: str, params: dict | None = None):
        if fn_name == "admin_overview_money":
            raise RuntimeError("PGRST202: Could not find the function")
        return real(fn_name, params or {})

    monkeypatch.setattr(fake_client, "rpc", missing)


def test_a_missing_function_reports_unavailable_not_zero(fake_client, seeded, monkeypatch):
    """The migration ships separately, so the API will run without it for
    a while. A lifetime total of 0.00 reads as "this platform has never
    taken a payment" — the most alarming and least likely thing this
    dashboard could say. Null, and the card renders a dash."""
    _break_the_rpc(fake_client, monkeypatch)

    data = _overview(fake_client)

    assert data["collections_total"] is None
    assert data["revenue_total"] is None


def test_the_daily_and_monthly_cards_survive_a_missing_function(fake_client, seeded, monkeypatch):
    """The fallback is the code that computed them before this change, so
    nothing an operator relies on today depends on the migration."""
    _break_the_rpc(fake_client, monkeypatch)

    data = _overview(fake_client)

    assert Decimal(data["collections_today"]) == Decimal("1000.00")
    assert Decimal(data["collections_this_month"]) == Decimal("1200.00")
    assert Decimal(data["platform_revenue_today"]) == Decimal("23.00")
    assert Decimal(data["platform_revenue"]) == Decimal("27.60")


# --- Who may see any of this -----------------------------------------------


def test_a_merchant_cannot_read_platform_totals(fake_client, seeded):
    from tests.factories import make_merchant_member

    user_id = uuid.uuid4()
    make_merchant_member(fake_client, seeded["merchant_id"], user_id, "MERCHANT_ADMIN")

    assert client.get(OVERVIEW, headers=auth_headers(user_id)).status_code == 403


def test_an_unauthenticated_caller_cannot_read_platform_totals(fake_client, seeded):
    assert client.get(OVERVIEW).status_code in (401, 403)


def test_a_second_factor_is_required_when_mfa_is_enforced(fake_client, seeded, monkeypatch):
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "true")
    get_settings.cache_clear()
    admin_id = _admin(fake_client)

    assert client.get(OVERVIEW, headers=auth_headers(admin_id)).status_code == 403
    assert client.get(OVERVIEW, headers=auth_headers(admin_id, aal="aal2")).status_code == 200


def test_the_old_fields_are_still_returned(fake_client, seeded):
    """Two cards were replaced on screen. The figures behind them are
    still computed and still in the response - something else may read
    them, and proving a removal safe is a separate piece of work."""
    data = _overview(fake_client)

    assert "failed_transactions" in data
    assert "active_payment_links" in data
