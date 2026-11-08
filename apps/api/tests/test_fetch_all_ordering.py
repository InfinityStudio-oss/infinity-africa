"""fetch_all must return every row exactly once, across pages.

Each page is a separate request. Postgres is free to return rows in a
different order for each one unless the query orders, so OFFSET paging
over an unordered query can hand back the same row twice and never hand
back another - with no error anywhere.

That is not theoretical. Measured against production on 2026-11-07, over
one merchant's 26,556 lifetime collections, the unordered read repeated
4,556 rows and missed 4,556, and the merchant's lifetime total came out
TZS 81,850 too high. Two identical reads disagreed with each other.

The table below behaves the way the real one did: it returns a different
arbitrary order every time it is asked, unless it was asked to sort.
"""

from __future__ import annotations

import pytest

from app.services.crud import fetch_all


class _Table:
    """Minimal PostgREST-shaped query builder with an unstable sort.

    Mirrors the one property that matters: without ORDER BY, two reads of
    the same rows can come back in different orders, so OFFSET windows
    overlap and gap. With ORDER BY on a unique column they cannot.
    """

    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._order: str | None = None
        self._range: tuple[int, int] | None = None
        self.calls = 0
        self.ordered_calls = 0

    # The bits of the builder fetch_all touches.
    def select(self, *_args, **_kwargs) -> "_Table":
        return self

    def order(self, column: str, desc: bool = False) -> "_Table":
        self._order = column
        return self

    def range(self, start: int, end: int) -> "_Table":
        self._range = (start, end)
        return self

    def execute(self):
        self.calls += 1
        if self._order is not None:
            self.ordered_calls += 1
            rows = sorted(self._rows, key=lambda r: r[self._order])
        else:
            # Rotate by one each call: a different order every time, the
            # cheapest faithful stand-in for "the planner chose
            # differently".
            shift = self.calls
            rows = self._rows[shift:] + self._rows[:shift]
        start, end = self._range
        return type("Result", (), {"data": rows[start : end + 1]})()


def _rows(n: int) -> list[dict]:
    return [{"id": f"{i:06d}", "amount": i} for i in range(n)]


@pytest.fixture
def table():
    # Deliberately more than one page: 2,500 rows at a page size of 1,000
    # is three requests, which is where the overlap shows.
    return _Table(_rows(2500))


def test_returns_every_row_exactly_once(table):
    got = fetch_all(lambda: table.select("*"))

    ids = [r["id"] for r in got]
    assert len(ids) == 2500
    assert len(set(ids)) == 2500, "a row was returned twice and another was lost"
    assert set(ids) == {r["id"] for r in _rows(2500)}


def test_sums_the_same_thing_twice(table):
    # The symptom that reached a merchant: the lifetime total moved
    # between two reads of unchanged data.
    first = sum(r["amount"] for r in fetch_all(lambda: table.select("*")))
    second = sum(r["amount"] for r in fetch_all(lambda: table.select("*")))

    assert first == second == sum(range(2500))


def test_every_paged_request_is_ordered(table):
    # One request is deliberately unordered: the probe that asks whether
    # there is more than one page at all. If the answer is no, nothing
    # was paged and the sort would buy nothing - while costing a plan.
    # `ORDER BY id LIMIT n` beside a selective filter can send the
    # planner down the primary key instead of the filtered index, which
    # cancelled a statement in production at this very call.
    fetch_all(lambda: table.select("*"))

    assert table.calls > 1, "the fixture must span more than one page to be meaningful"
    assert table.ordered_calls == table.calls - 1, (
        "every request except the first probe must carry the order"
    )


def test_a_single_page_is_never_ordered(table):
    small = _Table(_rows(10))
    got = fetch_all(lambda: small.select("*"))

    assert len(got) == 10
    assert small.calls == 1
    assert small.ordered_calls == 0, (
        "a result that fits in one page has no OFFSET, so ordering it is pure cost"
    )


def test_order_by_none_leaves_the_caller_in_charge(table):
    # The escape hatch, for a caller that sorts in its own factory. It
    # must genuinely not add an order, or that caller's sort would be
    # overridden.
    fetch_all(lambda: table.select("*"), order_by=None)

    assert table.ordered_calls == 0


def test_a_caller_can_choose_the_sort_column(table):
    fetch_all(lambda: table.select("*"), order_by="amount")

    assert table.ordered_calls == table.calls - 1  # all but the probe


def test_short_first_page_costs_one_request(table):
    small = _Table(_rows(10))
    got = fetch_all(lambda: small.select("*"))

    assert len(got) == 10
    assert small.calls == 1


def test_max_rows_still_caps(table):
    got = fetch_all(lambda: table.select("*"), max_rows=1500)

    assert len(got) == 1500
