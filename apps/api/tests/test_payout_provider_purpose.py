"""The `purpose` sent to Selcom must be a code they accept.

Selcom's live API validates purpose against a fixed enumerated list and
answers error_code 651, "The selected purpose is invalid", for anything
else. Their SANDBOX accepts arbitrary free text, so nothing catches a
wrong value until real money is involved.

This mistake has been made twice in this codebase. Withdrawals shipped
with purpose="withdrawal" and failed on the first production call. The
comment recording that lives in disbursements.py - and payout_dispatch
was then written with purpose="payout" anyway, which is why the first
live payout of TZS 1,000 failed, and why every sandbox attempt before it
failed too and made the sandbox URL look like the cause.

A comment in another file was not enough. This is a test.
"""

import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1] / "app" / "services"

# What Selcom accepts. Extend this only against their published list -
# https://developer.selcom.business/ - never to make a test pass.
ACCEPTED_PURPOSES = {"FT"}


def _purposes_in(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    # Only real arguments, not the word inside a comment.
    body = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
    return re.findall(r'purpose=\s*"([^"]+)"', body)


@pytest.mark.parametrize("module", ["payout_dispatch.py", "disbursements.py"])
def test_every_purpose_sent_to_selcom_is_one_they_accept(module):
    for purpose in _purposes_in(API_ROOT / module):
        assert purpose in ACCEPTED_PURPOSES, (
            f"{module} sends purpose={purpose!r} to Selcom. Their live API rejects anything "
            f"outside their enumerated list with error 651, and their sandbox accepts it "
            f"silently - so this fails only against real money."
        )


def test_the_payout_dispatcher_sends_a_purpose_at_all():
    """Guard the guard: if the argument is ever dropped, the test above
    passes by finding nothing."""
    assert _purposes_in(API_ROOT / "payout_dispatch.py"), (
        "payout_dispatch sends no purpose to Selcom at all"
    )
