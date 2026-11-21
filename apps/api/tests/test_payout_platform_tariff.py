"""The platform payout tariff, and the difference between free and unset.

Payout fees used to come only from two per-merchant columns that were
`not null default 0`. Every merchant switched on therefore paid nothing,
and there was no platform rate to fall back to - collections and
withdrawals both have one, payouts were the odd one out.

The columns are nullable now, and the distinction they carry is the
point: NULL means "nobody has priced this merchant, charge the tariff",
0 means "priced at zero, on purpose". Conflating those is the same
mistake that left a merchant receiving collection email nobody had
chosen for them, because an absent settings row read as "enabled".
"""

import uuid
from decimal import Decimal

from app.services.payouts import load_payout_settings, quote_fee


def _merchant_with_fees(fake_client, *, flat, pct, updated_by=None):
    merchant_id = uuid.uuid4()
    fake_client.seed(
        "merchant_payout_settings",
        {
            "merchant_id": str(merchant_id),
            "sandbox_enabled": True,
            "live_enabled": False,
            "paused": False,
            "fee_flat_tzs": flat,
            "fee_percentage": pct,
            "version": 1,
            "updated_by": updated_by,
        },
    )
    return merchant_id


def _tariff(fake_client, *, pct, flat="0"):
    fake_client.seed(
        "payout_platform_pricing",
        {"id": True, "percentage_fee": pct, "flat_fee": flat, "version": 1},
    )


def test_a_merchant_with_no_negotiated_rate_pays_the_platform_tariff(fake_client):
    _tariff(fake_client, pct="1")
    merchant_id = _merchant_with_fees(fake_client, flat=None, pct=None)

    settings = load_payout_settings(fake_client, merchant_id=merchant_id, environment="sandbox")

    assert settings is not None
    assert settings.fee_percentage == Decimal(1)
    assert settings.fee_is_platform_default is True
    # 1% of 10,000.
    assert quote_fee(settings, Decimal("10000.00")) == Decimal("100.00")


def test_the_tariff_is_one_percent_of_the_payout_whatever_the_destination(fake_client):
    """One rate for every mobile money network, Selcom Pesa and every
    bank - the tariff is not keyed on destination at all, so there is no
    per-network branch that could disagree."""
    _tariff(fake_client, pct="1")
    merchant_id = _merchant_with_fees(fake_client, flat=None, pct=None)
    settings = load_payout_settings(fake_client, merchant_id=merchant_id, environment="sandbox")

    for amount, expected in [
        ("1000.00", "10.00"),
        ("5000.00", "50.00"),
        ("17450.00", "174.50"),
        # HALF_UP, so a half cent goes to revenue rather than being lost
        # on every payout.
        ("1050.50", "10.51"),
    ]:
        assert quote_fee(settings, Decimal(amount)) == Decimal(expected), amount


def test_a_negotiated_rate_wins_over_the_tariff(fake_client):
    _tariff(fake_client, pct="1")
    merchant_id = _merchant_with_fees(fake_client, flat="0", pct="0.5", updated_by=str(uuid.uuid4()))

    settings = load_payout_settings(fake_client, merchant_id=merchant_id, environment="sandbox")

    assert settings.fee_percentage == Decimal("0.5")
    assert settings.fee_is_platform_default is False
    assert quote_fee(settings, Decimal("10000.00")) == Decimal("50.00")


def test_a_merchant_priced_at_zero_stays_free(fake_client):
    """The distinction the nullable columns exist for. Reading these with
    `or 0` would treat a deliberate zero as absent and put this merchant
    back on the 1% tariff."""
    _tariff(fake_client, pct="1")
    merchant_id = _merchant_with_fees(fake_client, flat="0", pct="0", updated_by=str(uuid.uuid4()))

    settings = load_payout_settings(fake_client, merchant_id=merchant_id, environment="sandbox")

    assert settings.fee_percentage == Decimal(0)
    assert settings.fee_is_platform_default is False
    assert quote_fee(settings, Decimal("10000.00")) == Decimal(0)


def test_a_missing_tariff_row_does_not_make_every_payout_free(fake_client):
    """It can only happen between the migration landing and the seed, but
    the safe direction matters: a tariff that silently reads as zero is
    revenue lost quietly, and nobody notices until the month is counted."""
    merchant_id = _merchant_with_fees(fake_client, flat=None, pct=None)

    settings = load_payout_settings(fake_client, merchant_id=merchant_id, environment="sandbox")

    assert settings.fee_percentage == Decimal(1)
    assert quote_fee(settings, Decimal("10000.00")) == Decimal("100.00")
