"""The in-memory Supabase client's ordering comparisons.

This fake stands in for Postgres in roughly 4,700 tests, so anywhere it
disagrees with Postgres is a place where a green suite means nothing.
That is not hypothetical here: `.is_(col, None)` was once a complete
no-op in this fake, and timestamps were compared as strings.

The string comparison is the one pinned below. It is correct only while
both sides carry the same UTC offset, and the Super Admin date filters
deliberately send a Dar es Salaam offset (+03:00) against a column
stored in UTC - so the normal case was the broken one. Postgres
compares timestamptz by instant; now so does this.
"""

from datetime import datetime, timezone

import pytest


@pytest.fixture
def rows(fake_client):
    """Three collections, one per side of the Tanzanian day boundary.

    Tanzania is UTC+3, so the Tanzanian day 2026-11-22 runs from
    2026-11-21T21:00Z to 2026-11-22T21:00Z.
    """
    for reference, created_at in (
        ("BEFORE", "2026-11-21T20:30:00+00:00"),  # 23:30 EAT on the 21st
        ("INSIDE", "2026-11-21T21:30:00+00:00"),  # 00:30 EAT on the 22nd
        ("AFTER", "2026-11-22T21:30:00+00:00"),  # 00:30 EAT on the 23rd
    ):
        fake_client.seed(
            "collections",
            {"id": reference, "merchant_reference": reference, "created_at": created_at},
        )
    return fake_client


def _refs(result):
    return {row["merchant_reference"] for row in result.data}


def test_an_offset_bearing_bound_is_compared_as_an_instant(rows):
    """The case that was broken.

    `2026-11-22T00:00:00+03:00` is the same moment as
    `2026-11-21T21:00:00+00:00`, so INSIDE (21:30Z) is after it. As
    strings, "2026-11-21..." sorts before "2026-11-22..." and INSIDE
    was wrongly excluded.
    """
    result = (
        rows.table("collections")
        .select("*")
        .gte("created_at", "2026-11-22T00:00:00+03:00")
        .lte("created_at", "2026-11-22T23:59:59.999999+03:00")
        .execute()
    )

    assert _refs(result) == {"INSIDE"}


def test_the_same_instant_written_two_ways_filters_identically(rows):
    """+03:00 and its UTC equivalent must not disagree."""
    eat = (
        rows.table("collections").select("*").gte("created_at", "2026-11-22T00:00:00+03:00").execute()
    )
    utc = (
        rows.table("collections").select("*").gte("created_at", "2026-11-21T21:00:00+00:00").execute()
    )

    assert _refs(eat) == _refs(utc) == {"INSIDE", "AFTER"}


def test_a_trailing_z_is_understood(rows):
    result = rows.table("collections").select("*").gte("created_at", "2026-11-22T21:00:00Z").execute()

    assert _refs(result) == {"AFTER"}


def test_an_equal_instant_satisfies_gte_and_lte(rows):
    exact = "2026-11-21T21:30:00+00:00"

    assert _refs(rows.table("collections").select("*").gte("created_at", exact).execute()) == {
        "INSIDE",
        "AFTER",
    }
    assert _refs(rows.table("collections").select("*").lte("created_at", exact).execute()) == {
        "BEFORE",
        "INSIDE",
    }
    # Strictly after / before excludes it.
    assert _refs(rows.table("collections").select("*").gt("created_at", exact).execute()) == {"AFTER"}
    assert _refs(rows.table("collections").select("*").lt("created_at", exact).execute()) == {"BEFORE"}


def test_a_datetime_object_compares_too(rows):
    result = (
        rows.table("collections")
        .select("*")
        .gte("created_at", datetime(2026, 11, 22, 21, 0, tzinfo=timezone.utc))
        .execute()
    )

    assert _refs(result) == {"AFTER"}


def test_a_null_never_satisfies_an_ordering_comparison(fake_client):
    # Matching Postgres: NULL compared with anything is not true.
    fake_client.seed("collections", {"id": "NO-DATE", "merchant_reference": "NO-DATE", "created_at": None})

    result = fake_client.table("collections").select("*").gte("created_at", "2000-01-01").execute()

    assert result.data == []


# --- the guard against being too clever ---------------------------------------


def test_amounts_are_still_compared_as_numbers(fake_client):
    """Money must not become text.

    "9" > "10" as strings, which would make every amount threshold in
    the suite wrong. The timestamp handling must not have cost this.
    """
    for reference, amount in (("SMALL", "9.00"), ("LARGE", "10.00")):
        fake_client.seed(
            "collections", {"id": reference, "merchant_reference": reference, "amount": amount}
        )

    result = fake_client.table("collections").select("*").gte("amount", "10").execute()

    assert _refs(result) == {"LARGE"}


def test_a_plain_number_is_not_mistaken_for_a_timestamp(fake_client):
    # The date detection is anchored on YYYY-MM-DD precisely so that a
    # bare number, an id or a code is never parsed as a date.
    fake_client.seed("collections", {"id": "A", "merchant_reference": "A", "amount": "2026"})

    result = fake_client.table("collections").select("*").gte("amount", "2025").execute()

    assert _refs(result) == {"A"}


def test_text_is_still_compared_as_text(fake_client):
    for reference, code in (("A", "aaa"), ("B", "bbb")):
        fake_client.seed(
            "collections", {"id": reference, "merchant_reference": reference, "channel": code}
        )

    result = fake_client.table("collections").select("*").gte("channel", "b").execute()

    assert _refs(result) == {"B"}
