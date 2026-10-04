"""The Python and TypeScript minimum-amount rules must match.

The browser blocks a below-minimum payment so the customer finds out
while they are typing; the backend blocks it because the browser is not
something we control. If the two disagree, one of two things happens:
the page accepts an amount the API then refuses — which is the confusing
failure this work exists to remove — or the page refuses a payment the
API would have taken, which is lost revenue nobody ever sees.

Reads the TypeScript source directly rather than mirroring it in a
hardcoded list here. A mirror is just a third copy to forget to update.
"""

import re
from decimal import Decimal
from pathlib import Path

from app.core.payment_minimums import (
    _PREFIX_TO_NETWORK,
    DEFAULT_MESSAGE,
    DEFAULT_MINIMUM,
    MIXX_BY_YAS_MESSAGE,
    MIXX_BY_YAS_MINIMUM,
)

_TS_SOURCE = (
    Path(__file__).resolve().parents[3] / "packages" / "shared" / "src" / "payment-minimums.ts"
)


def _ts_text() -> str:
    return _TS_SOURCE.read_text(encoding="utf-8")


def _ts_prefixes() -> dict[str, str]:
    block = re.search(
        r"NETWORK_PREFIXES:\s*Record<string,\s*MobileNetwork>\s*=\s*\{(.*?)\n\};",
        _ts_text(),
        re.DOTALL,
    )
    assert block, "NETWORK_PREFIXES table not found in payment-minimums.ts"
    return dict(re.findall(r'"(\d{2})":\s*MobileNetwork\.([A-Z]+)', block.group(1)))


def test_the_prefix_tables_match():
    """A prefix mapped to the wrong network on one side means a customer
    is shown one minimum and held to another."""
    assert _ts_prefixes() == {prefix: network.value for prefix, network in _PREFIX_TO_NETWORK.items()}


def test_the_scan_actually_found_the_table():
    """Guards against the regex silently matching nothing, which would
    make the comparison above pass on two empty dicts."""
    assert len(_ts_prefixes()) >= 13


def test_the_minimum_amounts_match():
    text = _ts_text()
    ts_mixx = re.search(r"MIXX_BY_YAS_MINIMUM\s*=\s*(\d+)", text)
    ts_default = re.search(r"DEFAULT_MINIMUM\s*=\s*(\d+)", text)
    assert ts_mixx and ts_default
    assert Decimal(ts_mixx.group(1)) == MIXX_BY_YAS_MINIMUM
    assert Decimal(ts_default.group(1)) == DEFAULT_MINIMUM


def test_the_customer_facing_messages_match():
    """The customer may see either one depending on whether the browser
    or the API caught it. They must not be able to tell which."""
    text = _ts_text()
    # The TS copy is split across two concatenated string literals.
    ts_mixx = "".join(re.findall(r'"([^"]*)"', text.split("MIXX_BY_YAS_MESSAGE =")[1].split(";")[0]))
    ts_default = re.search(r'DEFAULT_MINIMUM_MESSAGE\s*=\s*"([^"]+)"', text)
    assert ts_default
    assert ts_mixx == MIXX_BY_YAS_MESSAGE
    assert ts_default.group(1) == DEFAULT_MESSAGE
