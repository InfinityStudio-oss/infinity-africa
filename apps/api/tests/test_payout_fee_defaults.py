"""A merchant nobody has priced must land on the tariff, not on zero.

merchant_payout_settings.fee_flat_tzs and fee_percentage carry a
distinction the whole pricing model rests on: NULL means "no negotiated
rate, charge the platform tariff", 0 means "priced at zero, on purpose".

Migration 20261121110000 dropped NOT NULL and left the DEFAULT 0 behind,
so every row inserted without naming those columns still got 0. The row
that matters is the one the access-request flow creates: the first real
merchant to request payout access landed on 0% and would have had free
payouts, with nothing on screen looking wrong - the Super Admin table
faithfully reported a deliberate zero, because that is what the data
said.

The distinction only works if absent really means absent.
"""

import re
import uuid
from pathlib import Path

from app.services.payouts import load_payout_settings

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"


def test_the_fee_columns_carry_no_default():
    """Read from the migrations, because the fake has no DDL and would
    happily report whatever the test seeded."""
    sql = "\n".join(p.read_text(encoding="utf-8") for p in sorted(MIGRATIONS.glob("*.sql")))

    # The default must be dropped after the columns are made nullable.
    assert re.search(r"alter column fee_flat_tzs drop default", sql), (
        "fee_flat_tzs still carries a DEFAULT, so a row created without it is priced at zero "
        "rather than put on the platform tariff"
    )
    assert re.search(r"alter column fee_percentage drop default", sql), (
        "fee_percentage still carries a DEFAULT"
    )


def test_a_requested_merchant_with_no_fee_set_pays_the_tariff(fake_client):
    """What the operator sees on the Super Admin row, end to end."""
    merchant_id = uuid.uuid4()
    fake_client.seed(
        "payout_platform_pricing", {"id": True, "percentage_fee": "1", "flat_fee": "0", "version": 1}
    )
    # Exactly what request_payout_access inserts: no fee columns at all.
    fake_client.seed(
        "merchant_payout_settings",
        {
            "merchant_id": str(merchant_id),
            "sandbox_enabled": True,
            "live_enabled": False,
            "paused": False,
            "version": 1,
            "access_requested_at": "2026-11-22T13:12:06+00:00",
        },
    )

    settings = load_payout_settings(fake_client, merchant_id=merchant_id, environment="sandbox")

    assert settings is not None
    assert settings.fee_is_platform_default is True, (
        "a merchant nobody has priced must fall back to the tariff, not be free"
    )
    assert str(settings.fee_percentage) == "1"
