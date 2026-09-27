"""The Python and TypeScript destination-provider label maps must match.

A merchant withdrawing to a bank no longer types the bank's name — they
pick a destination provider, and the backend records
DESTINATION_CODE_LABELS[code] as the bank name on a real payout. The web
app shows the label from its own copy of the same map.

So a drift between the two is not cosmetic: the merchant would see one
bank on screen and a different name would be stored on the disbursement
and sent to the provider. Nothing else would catch that, because each side
is internally consistent.

Reads the TypeScript source directly rather than mirroring it in a
hardcoded list here — a mirror is just a third copy to forget to update.
"""

import re
from pathlib import Path

import pytest

from app.schemas.enums import DESTINATION_CODE_LABELS, DestinationCode

_TS_SOURCE = (
    Path(__file__).resolve().parents[3] / "packages" / "shared" / "src" / "destination-code.ts"
)


def _ts_labels() -> dict[str, str]:
    source = _TS_SOURCE.read_text(encoding="utf-8")
    block = re.search(
        r"DESTINATION_CODE_LABELS\s*:\s*Record<DestinationCode,\s*string>\s*=\s*\{(.*?)\n\};",
        source,
        re.DOTALL,
    )
    assert block, "couldn't find DESTINATION_CODE_LABELS in destination-code.ts"
    return dict(re.findall(r"\[DestinationCode\.(\w+)\]\s*:\s*\"([^\"]*)\"", block.group(1)))


def test_the_typescript_file_is_where_this_test_thinks_it_is():
    """Guards the test itself: a moved or renamed file must fail loudly
    rather than silently skipping the comparison."""
    assert _TS_SOURCE.exists(), f"{_TS_SOURCE} not found"
    assert _ts_labels(), "parsed zero labels — the regex no longer matches the file"


def test_every_destination_code_has_a_label():
    missing = [code for code in DestinationCode if code not in DESTINATION_CODE_LABELS]
    assert not missing, f"no display label for {missing}"


def test_python_and_typescript_cover_the_same_codes():
    assert set(_ts_labels()) == {code.value for code in DESTINATION_CODE_LABELS}


@pytest.mark.parametrize("code", list(DestinationCode))
def test_each_label_reads_the_same_on_both_sides(code):
    assert DESTINATION_CODE_LABELS[code] == _ts_labels()[code.value]


def test_a_bank_label_actually_names_the_bank():
    """The stored bank name comes from here, so these must be real bank
    names rather than codes."""
    assert DESTINATION_CODE_LABELS[DestinationCode.CRDB] == "CRDB Bank"
    assert DESTINATION_CODE_LABELS[DestinationCode.NMB] == "NMB Bank"
