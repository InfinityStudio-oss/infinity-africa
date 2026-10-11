"""Merchant referral commissions.

The rule the whole feature exists to enforce: **a signup earns nothing**.
Commission is owed only when a referred business is approved, trades past
a volume floor inside its first 30 days, and a Super Admin approves the
payout.

The number that matters most is the commission base. It is InfinityPay's
*net revenue*, read from the double-entry ledger, not the amount the
merchant collected — the two differ by about two orders of magnitude, so
using the wrong one would overpay by ~100x rather than slightly. There is
a test below that fails if anyone ever "simplifies" it to gross.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.config import get_settings
from app.services.referral_code import generate_referral_code, normalise_referral_code
from app.services.referral_commissions import (
    approve_commission,
    calculate_referral_commission,
    mark_commission_paid,
    recalculate_open_referrals,
    reject_commission,
)
from app.services.referrals import (
    capture_referral,
    issue_referral_code,
    start_referral_period,
)
from tests.fakes import FakeSupabaseClient

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _programme_on(monkeypatch):
    """The programme ships off. Every test here turns it on explicitly,
    and one test below pins that it really is inert when off."""
    get_settings.cache_clear()
    monkeypatch.setenv("REFERRAL_PROGRAM_ENABLED", "true")
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    return FakeSupabaseClient()


def _merchant(client, name, *, status="active", code=None):
    merchant_id = uuid.uuid4()
    client.seed(
        "merchants",
        {
            "id": str(merchant_id),
            "business_name": name,
            "merchant_code": "27000000",
            "status": status,
            "kyc_status": "verified" if status == "active" else "unverified",
            "currency": "TZS",
            "contact_email": f"{name.lower().replace(' ', '')}@example.com",
            "referral_code": code,
            "referral_code_status": "active",
        },
    )
    return merchant_id


def _revenue_account(client):
    """The platform's single revenue account, created once per client.

    Seeding a fresh row per collection would split the fees across
    several accounts and quietly halve the revenue the commission is
    calculated from - which is exactly the bug this helper existed to
    avoid testing around.
    """
    existing = (
        client.table("ledger_accounts").select("*").eq("purpose", "platform_revenue").execute()
    ).data
    if existing:
        return existing[0]
    return client.seed(
        "ledger_accounts",
        {
            "merchant_id": None,
            "purpose": "platform_revenue",
            "account_type": "revenue",
            "currency": "TZS",
            "name": "Platform Revenue",
        },
    )


def _collection(client, merchant_id, *, gross, fee, at, status="successful", reversed_fee=False):
    """A successful collection and the ledger entries it would have
    posted — the same shape app/services/ledger.py writes."""
    transaction_id = uuid.uuid4()
    client.seed(
        "transactions",
        {
            "id": str(transaction_id),
            "merchant_id": str(merchant_id),
            "type": "collection",
            "status": status,
            "gross_amount": str(gross),
            "fee_amount": str(fee),
            "net_amount": str(Decimal(str(gross)) - Decimal(str(fee))),
            "currency": "TZS",
            "created_at": at.isoformat(),
        },
    )
    account = _revenue_account(client)
    if Decimal(str(fee)) > 0 and status == "successful":
        client.seed(
            "ledger_entries",
            {
                "transaction_id": str(transaction_id),
                "ledger_account_id": account["id"],
                "direction": "credit",
                "amount": str(fee),
                "currency": "TZS",
                "created_at": at.isoformat(),
            },
        )
        if reversed_fee:
            # What reverse_collection_entries posts when a provider
            # reverses a collection after it was credited.
            client.seed(
                "ledger_entries",
                {
                    "transaction_id": str(transaction_id),
                    "ledger_account_id": account["id"],
                    "direction": "debit",
                    "amount": str(fee),
                    "currency": "TZS",
                    "created_at": at.isoformat(),
                },
            )
    return transaction_id


def _referral(client, referrer_id, referred_id, *, started_days_ago=1, **overrides):
    start = NOW - timedelta(days=started_days_ago)
    row = {
        "id": str(uuid.uuid4()),
        "referrer_merchant_id": str(referrer_id),
        "referred_merchant_id": str(referred_id),
        "referral_code_used": "INF-TEST22",
        "signup_at": start.isoformat(),
        "referred_approved_at": start.isoformat(),
        "referral_period_start_at": start.isoformat(),
        "referral_period_end_at": (start + timedelta(days=30)).isoformat(),
        "status": "active",
        "qualification_volume_threshold": "100000",
        "commission_rate_bps": 1500,
        "minimum_payout_amount": "5000",
        "currency": "TZS",
    }
    row.update(overrides)
    client.seed("merchant_referrals", row)
    return row


# --- Codes -----------------------------------------------------------------


def test_a_code_is_unique_and_unguessable(client):
    _merchant(client, "A")
    codes = {generate_referral_code(client) for _ in range(50)}

    assert len(codes) == 50, "codes must not repeat"
    for code in codes:
        assert code.startswith("INF-")
        # Ambiguous characters are excluded so a code read aloud cannot
        # be mistyped into somebody else's.
        assert not set(code[4:]) & set("01ILOS")


def test_a_code_is_issued_once_and_not_rotated(client):
    merchant_id = _merchant(client, "Referrer")

    first = issue_referral_code(client, merchant_id=merchant_id, actor_id=None)["referral_code"]
    second = issue_referral_code(client, merchant_id=merchant_id, actor_id=None)["referral_code"]

    assert first == second, "re-issuing would orphan every link already shared"


def test_an_unapproved_merchant_cannot_get_a_code(client):
    from app.core.errors import ValidationAPIError

    merchant_id = _merchant(client, "Pending Co", status="pending")

    with pytest.raises(ValidationAPIError):
        issue_referral_code(client, merchant_id=merchant_id, actor_id=None)


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("INF-8K3P2M", "INF-8K3P2M"),
        ("inf-8k3p2m", "INF-8K3P2M"),
        ("  INF-8K3P2M  ", "INF-8K3P2M"),
        # Typed without the prefix, which is what someone reading six
        # characters off a poster does.
        ("8K3P2M", "INF-8K3P2M"),
        ("not-a-code", None),
        ("INF-00000O", None),  # excluded characters
        ("", None),
        (None, None),
    ],
)
def test_codes_are_normalised_the_way_people_type_them(typed, expected):
    assert normalise_referral_code(typed) == expected


# --- Capture ---------------------------------------------------------------


def test_a_valid_code_links_the_two_merchants(client):
    referrer = _merchant(client, "Referrer", code="INF-AAA222")
    referred = _merchant(client, "Referred", status="pending")

    referral = capture_referral(client, code="INF-AAA222", referred_merchant_id=referred)

    assert referral is not None
    assert referral["referrer_merchant_id"] == str(referrer)
    # Captured, but not earning: the window opens at approval.
    assert referral["status"] == "pending_approval"
    # Absent rather than null in the fake store; either way, not set.
    assert referral.get("referral_period_start_at") is None


def test_self_referral_is_refused(client):
    merchant_id = _merchant(client, "Clever", code="INF-SELF22")

    assert capture_referral(client, code="INF-SELF22", referred_merchant_id=merchant_id) is None


def test_a_merchant_can_only_be_referred_once(client):
    _merchant(client, "First", code="INF-AAA222")
    _merchant(client, "Second", code="INF-BBB333")
    referred = _merchant(client, "Referred", status="pending")

    assert capture_referral(client, code="INF-AAA222", referred_merchant_id=referred) is not None
    assert capture_referral(client, code="INF-BBB333", referred_merchant_id=referred) is None


@pytest.mark.parametrize("code", ["INF-NOPE22", "garbage", "", None])
def test_a_bad_code_never_fails_the_signup(client, code):
    """The one property that matters on this path: a marketing feature
    must not be able to stop a business being created."""
    referred = _merchant(client, "Referred", status="pending")

    assert capture_referral(client, code=code, referred_merchant_id=referred) is None


def test_a_disabled_code_stops_working(client):
    referrer = _merchant(client, "Referrer", code="INF-AAA222")
    client.table("merchants").update({"referral_code_status": "disabled"}).eq(
        "id", str(referrer)
    ).execute()
    referred = _merchant(client, "Referred", status="pending")

    assert capture_referral(client, code="INF-AAA222", referred_merchant_id=referred) is None


def test_a_suspended_referrers_code_stops_working(client):
    referrer = _merchant(client, "Referrer", code="INF-AAA222")
    client.table("merchants").update({"status": "suspended"}).eq("id", str(referrer)).execute()
    referred = _merchant(client, "Referred", status="pending")

    assert capture_referral(client, code="INF-AAA222", referred_merchant_id=referred) is None


def test_nothing_is_captured_while_the_programme_is_off(client, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("REFERRAL_PROGRAM_ENABLED", "false")
    _merchant(client, "Referrer", code="INF-AAA222")
    referred = _merchant(client, "Referred", status="pending")

    assert capture_referral(client, code="INF-AAA222", referred_merchant_id=referred) is None


# --- The window ------------------------------------------------------------


def test_approval_opens_a_thirty_day_window(client):
    _merchant(client, "Referrer", code="INF-AAA222")
    referred = _merchant(client, "Referred", status="pending")
    capture_referral(client, code="INF-AAA222", referred_merchant_id=referred)

    updated = start_referral_period(client, referred_merchant_id=referred)

    assert updated["status"] == "active"
    start = datetime.fromisoformat(updated["referral_period_start_at"])
    end = datetime.fromisoformat(updated["referral_period_end_at"])
    assert (end - start).days == 30


def test_re_approval_does_not_restart_the_window(client):
    _merchant(client, "Referrer", code="INF-AAA222")
    referred = _merchant(client, "Referred", status="pending")
    capture_referral(client, code="INF-AAA222", referred_merchant_id=referred)

    first = start_referral_period(client, referred_merchant_id=referred)
    second = start_referral_period(client, referred_merchant_id=referred)

    assert first["referral_period_end_at"] == second["referral_period_end_at"]


# --- The money -------------------------------------------------------------


def test_no_commission_below_the_volume_floor(client):
    """TZS 99,000 collected is not TZS 100,000. A signup, or a trickle,
    earns nothing."""
    referrer = _merchant(client, "Referrer")
    referred = _merchant(client, "Referred")
    referral = _referral(client, referrer, referred)
    _collection(client, referred, gross=99000, fee=2475, at=NOW - timedelta(hours=2))

    commission = calculate_referral_commission(client, referral=referral)

    assert commission["status"] == "accruing"
    assert Decimal(commission["commission_amount"]) == 0
    assert Decimal(commission["successful_volume"]) == 99000


def test_commission_is_a_share_of_net_revenue_not_of_what_was_collected(client):
    """The test that guards the whole design.

    TZS 200,000 collected at a 2.5% platform fee earns InfinityPay
    TZS 5,000. The referrer gets 15% of *that* - TZS 750 - not 15% of
    200,000, which would be TZS 30,000 and six times the revenue the
    platform made.
    """
    referrer = _merchant(client, "Referrer")
    referred = _merchant(client, "Referred")
    referral = _referral(client, referrer, referred)
    _collection(client, referred, gross=200000, fee=5000, at=NOW - timedelta(hours=2))

    commission = calculate_referral_commission(client, referral=referral)

    assert Decimal(commission["successful_volume"]) == 200000
    assert Decimal(commission["infinitypay_net_revenue"]) == 5000
    assert Decimal(commission["commission_amount"]) == Decimal("750.00")
    assert Decimal(commission["commission_amount"]) != Decimal("30000.00")


def test_failed_collections_count_for_nothing(client):
    referrer = _merchant(client, "Referrer")
    referred = _merchant(client, "Referred")
    referral = _referral(client, referrer, referred)
    _collection(client, referred, gross=500000, fee=12500, at=NOW - timedelta(hours=2), status="failed")

    commission = calculate_referral_commission(client, referral=referral)

    assert Decimal(commission["successful_volume"]) == 0
    assert Decimal(commission["commission_amount"]) == 0


def test_a_reversed_collection_takes_its_fee_back_out(client):
    """The ledger already does this: a reversal posts the matching debit,
    so credits minus debits nets it away without a special case here."""
    referrer = _merchant(client, "Referrer")
    referred = _merchant(client, "Referred")
    referral = _referral(client, referrer, referred)
    _collection(client, referred, gross=200000, fee=5000, at=NOW - timedelta(hours=3))
    _collection(
        client, referred, gross=200000, fee=5000, at=NOW - timedelta(hours=2), reversed_fee=True
    )

    commission = calculate_referral_commission(client, referral=referral)

    # Both collections count toward volume, only one toward revenue.
    assert Decimal(commission["successful_volume"]) == 400000
    assert Decimal(commission["infinitypay_net_revenue"]) == 5000


def test_transactions_outside_the_window_are_excluded(client):
    referrer = _merchant(client, "Referrer")
    referred = _merchant(client, "Referred")
    referral = _referral(client, referrer, referred, started_days_ago=40)  # window closed
    _collection(client, referred, gross=500000, fee=12500, at=NOW - timedelta(hours=2))

    commission = calculate_referral_commission(client, referral=referral)

    assert Decimal(commission["successful_volume"]) == 0


def test_below_the_payout_floor_is_held_not_offered_for_review(client):
    """Qualified on volume, but 15% of the revenue is under TZS 5,000, so
    it is not worth an approval and a payout."""
    referrer = _merchant(client, "Referrer")
    referred = _merchant(client, "Referred")
    referral = _referral(client, referrer, referred, started_days_ago=31)
    _collection(client, referred, gross=150000, fee=3750, at=NOW - timedelta(days=30))

    commission = calculate_referral_commission(client, referral=referral)

    assert Decimal(commission["commission_amount"]) == Decimal("562.50")
    assert commission["status"] == "below_threshold"


def test_a_finished_window_over_the_floor_goes_for_review(client):
    referrer = _merchant(client, "Referrer")
    referred = _merchant(client, "Referred")
    referral = _referral(client, referrer, referred, started_days_ago=31)
    _collection(client, referred, gross=2000000, fee=50000, at=NOW - timedelta(days=30))

    commission = calculate_referral_commission(client, referral=referral)

    assert Decimal(commission["commission_amount"]) == Decimal("7500.00")
    assert commission["status"] == "pending_review"


def test_a_suspended_referrer_earns_nothing(client):
    referrer = _merchant(client, "Referrer", status="suspended")
    referred = _merchant(client, "Referred")
    referral = _referral(client, referrer, referred, started_days_ago=31)
    _collection(client, referred, gross=2000000, fee=50000, at=NOW - timedelta(days=30))

    commission = calculate_referral_commission(client, referral=referral)

    assert commission["status"] == "cancelled"
    assert "referrer_suspended" in commission["calculation_snapshot"]["blockers"]


def test_a_suspended_referred_merchant_stops_the_commission(client):
    referrer = _merchant(client, "Referrer")
    referred = _merchant(client, "Referred", status="suspended")
    referral = _referral(client, referrer, referred, started_days_ago=31)
    _collection(client, referred, gross=2000000, fee=50000, at=NOW - timedelta(days=30))

    commission = calculate_referral_commission(client, referral=referral)

    assert commission["status"] == "cancelled"


def test_a_fraud_hold_stops_the_commission(client):
    referrer = _merchant(client, "Referrer")
    referred = _merchant(client, "Referred")
    referral = _referral(client, referrer, referred, started_days_ago=31, status="fraud_hold")
    _collection(client, referred, gross=2000000, fee=50000, at=NOW - timedelta(days=30))

    commission = calculate_referral_commission(client, referral=referral)

    assert commission["status"] == "cancelled"
    assert "fraud_hold" in commission["calculation_snapshot"]["blockers"]


def test_recalculating_updates_one_record_rather_than_adding_another(client):
    """Idempotence. A second payable record for the same referral would be
    a double payout waiting to happen."""
    referrer = _merchant(client, "Referrer")
    referred = _merchant(client, "Referred")
    referral = _referral(client, referrer, referred)
    _collection(client, referred, gross=200000, fee=5000, at=NOW - timedelta(hours=3))

    first = calculate_referral_commission(client, referral=referral)
    _collection(client, referred, gross=200000, fee=5000, at=NOW - timedelta(hours=2))
    second = calculate_referral_commission(client, referral=referral)

    assert first["id"] == second["id"]
    assert len(client.table("referral_commissions")._table.rows) == 1
    assert Decimal(second["infinitypay_net_revenue"]) == 10000


def test_a_reviewed_commission_is_never_recalculated(client):
    """Once a human has ruled, the figure is history. A sweep that moved
    it would make every approval meaningless."""
    referrer = _merchant(client, "Referrer")
    referred = _merchant(client, "Referred")
    referral = _referral(client, referrer, referred, started_days_ago=31)
    _collection(client, referred, gross=2000000, fee=50000, at=NOW - timedelta(days=30))

    commission = calculate_referral_commission(client, referral=referral)
    approve_commission(client, commission_id=uuid.UUID(commission["id"]), admin_id=uuid.uuid4())

    _collection(client, referred, gross=2000000, fee=50000, at=NOW - timedelta(days=29))
    after = calculate_referral_commission(client, referral=referral)

    assert after["status"] == "approved"
    assert Decimal(after["commission_amount"]) == Decimal("7500.00")


# --- Super Admin decisions -------------------------------------------------


def _reviewable(client):
    referrer = _merchant(client, "Referrer")
    referred = _merchant(client, "Referred")
    referral = _referral(client, referrer, referred, started_days_ago=31)
    _collection(client, referred, gross=2000000, fee=50000, at=NOW - timedelta(days=30))
    return calculate_referral_commission(client, referral=referral)


def test_approving_marks_it_payable_and_logs_who_did_it(client):
    commission = _reviewable(client)
    admin_id = uuid.uuid4()

    approved = approve_commission(client, commission_id=uuid.UUID(commission["id"]), admin_id=admin_id)

    assert approved["status"] == "approved"
    assert approved["reviewed_by_admin_id"] == str(admin_id)
    actions = [row["action"] for row in client.table("audit_logs")._table.rows]
    assert "referral.commission_approved" in actions


def test_rejecting_requires_a_reason_and_keeps_it(client):
    from app.core.errors import ValidationAPIError

    commission = _reviewable(client)

    with pytest.raises(ValidationAPIError):
        reject_commission(
            client, commission_id=uuid.UUID(commission["id"]), admin_id=uuid.uuid4(), reason="  "
        )

    rejected = reject_commission(
        client,
        commission_id=uuid.UUID(commission["id"]),
        admin_id=uuid.uuid4(),
        reason="Same owner as the referrer",
    )
    assert rejected["status"] == "rejected"
    assert rejected["rejection_reason"] == "Same owner as the referrer"


def test_only_an_approved_commission_can_be_marked_paid(client):
    from app.core.errors import ConflictError

    commission = _reviewable(client)

    with pytest.raises(ConflictError):
        mark_commission_paid(
            client, commission_id=uuid.UUID(commission["id"]), admin_id=uuid.uuid4()
        )

    approve_commission(client, commission_id=uuid.UUID(commission["id"]), admin_id=uuid.uuid4())
    paid = mark_commission_paid(
        client, commission_id=uuid.UUID(commission["id"]), admin_id=uuid.uuid4(), note="Sent by M-Pesa"
    )
    assert paid["status"] == "paid"
    assert paid["paid_at"] is not None


def test_the_sweep_values_every_open_referral(client):
    for index in range(3):
        referrer = _merchant(client, f"Referrer {index}")
        referred = _merchant(client, f"Referred {index}")
        _referral(client, referrer, referred)
        _collection(client, referred, gross=200000, fee=5000, at=NOW - timedelta(hours=2))

    summary = recalculate_open_referrals(client)

    assert summary["processed"] == 3
    assert summary["failures"] == 0


def test_the_sweep_does_nothing_while_the_programme_is_off(client, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("REFERRAL_PROGRAM_ENABLED", "false")

    assert recalculate_open_referrals(client)["processed"] == 0
