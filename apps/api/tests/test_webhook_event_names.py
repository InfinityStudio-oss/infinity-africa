"""The portal's event list must match what the platform actually sends.

A merchant can narrow their webhook subscription to a subset of events
in the portal, and enqueue_webhook_event drops anything outside it. So
an event missing from the portal's checkbox list is not merely hidden -
it is **unreachable**. There is no box to tick, so a merchant who has
narrowed their selection can never receive it again.

That was the live state. Five emitted events were missing from the
list, the reversals among them, and a reversal is money being taken
back. The one merchant who had narrowed their selection was silently
receiving none of them. Four more were offered in the portal while
nothing emitted them, so ticking those did nothing at all.

These tests pin the two lists together in both directions.

--- Why this does not just grep for event_name="..."

Because that would pass while the bug was present. `collection.pending_review`
is emitted from a dict in sandbox_collections.py, not as a keyword
argument, so a grep for `event_name="..."` never sees it. A test that
looked only for the keyword form would have reported everything in
order. The declared maps are read too.
"""

import re
from pathlib import Path

import pytest

from app.services.webhook_event_names import KNOWN_WEBHOOK_EVENTS, WEBHOOK_EVENT_NAMES

# parents[1] is apps/api, parents[2] is apps, parents[3] is the repo
# root. Off-by-one here has cost time twice on this project, so it is
# asserted rather than trusted.
REPO_ROOT = Path(__file__).resolve().parents[3]
API_APP = REPO_ROOT / "apps" / "api" / "app"
PORTAL_TYPES = REPO_ROOT / "apps" / "web" / "src" / "lib" / "portal" / "types.ts"


def test_the_paths_resolve():
    """The guard for the guard. Every assertion below is vacuous if
    these point at nothing, and a test that silently checks an empty
    set is worse than no test."""
    assert API_APP.is_dir(), f"not a directory: {API_APP}"
    assert PORTAL_TYPES.is_file(), f"not a file: {PORTAL_TYPES}"


def _emitted_event_names() -> set[str]:
    """Every event name this codebase can pass to enqueue_webhook_event.

    Two shapes, because the code uses two:
      - the keyword literal, `event_name="collection.success"`
      - a declared map of status -> event name, which the keyword grep
        misses entirely
    """
    names: set[str] = set()
    for path in API_APP.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "webhook" not in source and "event_name" not in source:
            continue
        names |= set(re.findall(r'event_name\s*=\s*"([a-z_]+\.[a-z_]+)"', source))
        # A map whose values are event names, e.g. _STATUS_TO_EVENT in
        # sandbox_collections.py. Matched on the value shape rather than
        # the variable name so a differently-named map is still caught.
        for block in re.findall(r"_TO_EVENT[^=]*=\s*\{(.*?)\}", source, re.S):
            names |= set(re.findall(r'"([a-z_]+\.[a-z_]+)"', block))
    return names


def test_every_emitted_event_is_declared():
    """A new emitter that forgets this list makes its event unreachable
    for anyone who has narrowed their subscription."""
    emitted = _emitted_event_names()

    assert emitted, "found no event names at all — the scan is broken, not the code"
    undeclared = sorted(emitted - KNOWN_WEBHOOK_EVENTS)
    assert not undeclared, (
        f"emitted but missing from WEBHOOK_EVENT_NAMES: {undeclared}. "
        "A merchant with a narrowed subscription can never receive these."
    )


def test_the_scan_sees_the_map_shape_a_grep_would_miss():
    """Pins the reason this test is not a grep.

    collection.pending_review is emitted from a dict. If the scan stops
    reading maps, this fails and the next person knows why it mattered.
    """
    assert "collection.pending_review" in _emitted_event_names()


def _portal_event_names() -> list[str]:
    source = PORTAL_TYPES.read_text(encoding="utf-8")
    match = re.search(r"export const WEBHOOK_EVENT_NAMES = \[(.*?)\] as const;", source, re.S)
    assert match, "WEBHOOK_EVENT_NAMES not found in the portal types — did it move?"
    return re.findall(r'"([^"]+)"', match.group(1))


def test_the_portal_list_matches_this_one_exactly():
    """Same events, same order.

    Order because the checkbox list is read by a person and is grouped
    by what the money did; alphabetical would scatter the collection
    events across the list.
    """
    assert _portal_event_names() == list(WEBHOOK_EVENT_NAMES)


def test_nothing_is_offered_that_nobody_sends():
    """The other direction.

    collection.pending, invoice.overdue, payment_link.created and
    payment_link.expired were all offered in the portal and emitted by
    nothing. Ticking one did nothing, which is a quiet way to lose
    somebody's trust in the whole screen.
    """
    emitted = _emitted_event_names()
    phantom = sorted(KNOWN_WEBHOOK_EVENTS - emitted)
    assert not phantom, (
        f"offered to merchants but emitted by nothing: {phantom}. "
        "Either wire up the emitter or take it off the list."
    )


def test_the_list_has_no_duplicates():
    assert len(WEBHOOK_EVENT_NAMES) == len(set(WEBHOOK_EVENT_NAMES))


@pytest.mark.parametrize("name", WEBHOOK_EVENT_NAMES)
def test_every_name_is_a_dotted_lowercase_pair(name):
    # The shape merchants match on in their own code, and the shape the
    # scan above relies on.
    assert re.fullmatch(r"[a-z_]+\.[a-z_]+", name), name
