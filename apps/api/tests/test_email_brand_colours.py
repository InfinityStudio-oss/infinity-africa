"""The email templates carry their colours as inline literals, because
email clients have no CSS variables and most strip <style> blocks. That
makes them invisible to the app's theme: when InfinityPay moved to the
navy/teal theme, the pre-theme green survived in 16 separate literals in
app/services/email.py and the welcome email kept sending it for months
before anyone noticed from a phone screenshot.

These tests are the thing that was missing. They read the module source
rather than a rendered email, so a stray colour is caught wherever it is
written, including in a template no test happens to render.
"""

import re
from pathlib import Path

import pytest

from app.services.email import _BRAND_INK, _BRAND_MUTED, _cta_button

EMAIL_SOURCE = Path(__file__).resolve().parents[1] / "app" / "services" / "email.py"

# Pre-theme brand green. If either reappears, something was copied from
# an old template or an old screenshot.
RETIRED = ["#04332a", "#5f6b68"]

# Everything the templates are allowed to use. Brand ink, the neutral
# grey ramp the body copy sits on, and the status colours for
# success/warning/failure states.
ALLOWED = {
    "#1e3a5f",  # brand ink
    "#ffffff",
    "#000000",
    "#f9fafb",
    "#f4f4f5",
    "#e5e7eb",
    "#9ca3af",
    "#6b7280",
    "#374151",
    "#1f2937",
}


def source() -> str:
    return EMAIL_SOURCE.read_text(encoding="utf-8")


@pytest.mark.parametrize("retired", RETIRED)
def test_a_retired_brand_colour_never_comes_back(retired: str) -> None:
    text = source()
    # The documentation comment names them on purpose so the next person
    # knows what not to reintroduce; only real uses should fail.
    uses = [
        line
        for line in text.splitlines()
        if retired in line.lower() and not line.lstrip().startswith("#")
    ]
    assert uses == [], f"{retired} is a retired brand colour, still used on: {uses}"


def template_colours() -> set[str]:
    """Every hex the templates actually render, ignoring the comments —
    the documentation above names the retired colours on purpose, and a
    scan that counted those would either fail forever or have to be
    loosened until it caught nothing."""
    body = "\n".join(line for line in source().splitlines() if not line.lstrip().startswith("#"))
    return {h.lower() for h in re.findall(r"#[0-9a-fA-F]{6}", body)}


def test_every_colour_in_the_templates_is_one_we_chose() -> None:
    """Catches a hex nobody decided on — a template drifts off-brand one
    pasted colour at a time, not by a deliberate repalette. Nine colours
    render today and all nine are listed; there is no allowance for
    "looks like a status colour", because that is the hole a stray navy
    would slip through."""
    unexpected = template_colours() - ALLOWED
    assert unexpected == set(), f"unapproved colours in the email templates: {sorted(unexpected)}"


def test_the_header_band_and_the_button_use_the_brand_ink() -> None:
    """The two things a recipient actually sees as "the brand" — the band
    across the top and the call to action."""
    # Outlook's Word engine ignores CSS background-color on table cells,
    # which is why the band carries the legacy bgcolor attribute too —
    # and why both have to come from the constant, not a literal.
    assert 'bgcolor="{_BRAND_INK}"' in source()

    button = _cta_button("https://infinitypay.me/portal", "Open Merchant Portal")
    assert f"background-color:{_BRAND_INK}" in button
    assert "Open Merchant Portal" in button


def test_the_brand_constants_are_the_theme_colours() -> None:
    """Pinned to the app's own tokens: --color-primary is #1e3a5f in
    apps/web/src/app/globals.css. An email that drifts from the portal it
    links to reads as a phishing attempt, not a rebrand."""
    assert _BRAND_INK == "#1e3a5f"
    assert _BRAND_MUTED == "#6b7280"
