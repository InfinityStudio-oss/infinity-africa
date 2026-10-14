"""The `.in_()` chunk size has to stay under a limit nobody can see.

`.in_(column, ids)` is rendered into the URL, so a long id list produces a
request the server in front of PostgREST rejects for its length rather
than answering. There is nothing in the code that announces this: the
only symptom is `APIError: JSON could not be generated`, which names
neither the table nor the cause, and it appears for a merchant only once
they have traded enough to cross the line.

So the measurement lives here, as an assertion. Raising IN_CHUNK_SIZE is
a reasonable thing to want - every increase is fewer round trips to a
database in a different city from the API - and this is what stops that
wish from quietly re-creating the bug.

Measured against production Supabase on 2026-10-13:
    675 uuids = 25,054 URL characters -> accepted
    676 uuids = 25,091 URL characters -> 400, body "Bad Request"
"""

from app.services.crud import IN_CHUNK_SIZE

# What one uuid costs inside an `in.(...)` list: 36 characters and a comma.
_CHARS_PER_ID = 37

# The largest list production accepted, in characters.
_MEASURED_CEILING = 25_054

# Everything before the ids: scheme, host, table, select clause, filter.
# Generous on purpose - a longer table or select name spends more of the
# budget before the first id, and the margin has to survive that.
_ASSUMED_PREFIX = 500


def test_a_full_chunk_fits_well_inside_the_measured_limit():
    rendered = _ASSUMED_PREFIX + IN_CHUNK_SIZE * _CHARS_PER_ID
    assert rendered < _MEASURED_CEILING, (
        f"IN_CHUNK_SIZE={IN_CHUNK_SIZE} renders about {rendered} characters of URL, "
        f"past the {_MEASURED_CEILING} production accepted. Requests would start "
        f"failing as APIError: JSON could not be generated, and only for merchants "
        f"with enough history to fill a chunk."
    )


def test_the_margin_is_a_margin_and_not_a_near_miss():
    """Half the measured ceiling, so the limit being lower on a different
    day - a longer table name, a proxy with a tighter setting - is absorbed
    rather than discovered in production."""
    rendered = _ASSUMED_PREFIX + IN_CHUNK_SIZE * _CHARS_PER_ID
    assert rendered < _MEASURED_CEILING / 2 + _ASSUMED_PREFIX, (
        f"IN_CHUNK_SIZE={IN_CHUNK_SIZE} leaves less than half the measured budget "
        f"spare. That is probably still fine, but it is no longer a margin - if "
        f"this is deliberate, move to PostgREST resource embedding instead and "
        f"stop sending id lists at all."
    )


def test_the_chunk_size_is_big_enough_to_be_worth_having():
    """The other direction. Each chunk is a round trip to a database in a
    different city, so a very small chunk turns one slow request into many
    slow requests."""
    assert IN_CHUNK_SIZE >= 200
