"""Admin list endpoints must not ask for an exact count.

`count="exact"` makes PostgREST run a real COUNT over every matching row.
The /v1/admin/* lists are platform-wide, so there is no merchant_id to
narrow them: the count runs over all 84,000 collections, all 153,000
audit log rows, all 514,000 request logs, on every page load.

Measured against production it cost between 0.6s and 3.9s for the same
query, varying only with cache warmth. The Super Admin Collections page
issues three admin requests together, and three of those counts in
flight tipped the statement timeout - surfacing as `APIError: canceling
statement due to statement timeout` and reaching the browser as a 500,
which the page rendered as "No collections have been recorded yet" over
84,000 real rows. It took two days to find, because running the queries
one at a time never reproduced it.

A unit test cannot catch that: the fake client counts a list in memory
and is instant either way. So this guards the decision rather than the
behaviour - if someone puts `count="exact"` back into an admin list, the
reason it was removed is attached to the failure.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from app.core.pagination import LIST_COUNT

ROUTERS = pathlib.Path(__file__).resolve().parents[1] / "app" / "routers"
ADMIN_LIST_ROUTERS = ("admin.py", "admin_risk.py")

# Counts a person reads as a fact, not as a page count. These are filtered
# to a day or a month, so an exact count is cheap, and a dashboard card
# that is 4% wrong is worse than one that takes an extra moment.
SERVICES_THAT_KEEP_EXACT = ("admin_overview.py", "merchant_overview.py")


def test_list_count_is_not_exact():
    assert LIST_COUNT != "exact"
    # `estimated` and not `planned`: estimated still returns a real count
    # below PostgREST's threshold, which is why merchants (122), api_keys
    # (191), payment_links (152), invoices (8) and disbursements (316) all
    # came back identical either way against production. Only the tables
    # big enough to hurt get approximated.
    assert LIST_COUNT == "estimated"


def _code_lines(source: str) -> list[str]:
    """Lines that are actually code — no module docstring, no comments.

    Both of those legitimately mention `count="exact"` while explaining
    why it is not used any more, and a check that trips over its own
    explanation is worse than no check.
    """
    body = ast.parse(source).body
    skip_until = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        skip_until = body[0].end_lineno or 0
    return [
        line
        for n, line in enumerate(source.splitlines(), start=1)
        if n > skip_until and not line.lstrip().startswith("#")
    ]


@pytest.mark.parametrize("filename", ADMIN_LIST_ROUTERS)
def test_no_admin_list_endpoint_asks_for_an_exact_count(filename):
    source = (ROUTERS / filename).read_text(encoding="utf-8")

    offenders = [
        line.strip()
        for line in _code_lines(source)
        if re.search(r'count\s*=\s*["\']exact["\']', line)
    ]

    assert not offenders, (
        f"{filename} asks PostgREST for an exact count:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse count=LIST_COUNT. See app/core/pagination.py for why: an "
        "exact count over a platform-wide table took up to 3.9s and tipped "
        "the statement timeout, turning the Collections page into a 500."
    )


@pytest.mark.parametrize("filename", ADMIN_LIST_ROUTERS)
def test_admin_routers_use_the_shared_constant(filename):
    source = (ROUTERS / filename).read_text(encoding="utf-8")

    if "count=" in source:
        assert "LIST_COUNT" in source, (
            f"{filename} passes a count mode without importing the shared "
            "constant — keep the choice in one place so it can be changed once."
        )


@pytest.mark.parametrize("filename", SERVICES_THAT_KEEP_EXACT)
def test_dashboard_figures_still_count_exactly(filename):
    # The other half of the decision, held in place so a later sweep for
    # `count="exact"` does not take these with it.
    services = pathlib.Path(__file__).resolve().parents[1] / "app" / "services"
    source = (services / filename).read_text(encoding="utf-8")

    assert any(
        re.search(r'count\s*=\s*["\']exact["\']', line) for line in _code_lines(source)
    ), (
        f"{filename} no longer counts exactly. These are figures a person "
        "reads as a fact and they are filtered to a day or a month, so the "
        "count is cheap — they were deliberately left alone."
    )
