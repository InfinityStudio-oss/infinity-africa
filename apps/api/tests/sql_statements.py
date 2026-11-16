"""Splitting a migration into statements, without lying about quotes.

The Postgres-backed tests replay real migration files. They used to pick
statements out with a regular expression that ended each one at the first
semicolon, which is wrong twice over: a semicolon inside a string literal
ended the statement early, and a dollar-quoted function body containing
one did the same. Both appear in these migrations -

    comment on table ... is '... the hard ceilings above it; see the
    header of this migration ...';

- and the result was a file whose locking guarantees silently stopped
  being exercised, because every test in it errored during setup.

So this is a small lexer rather than a pattern. It tracks the four things
that make a semicolon not a terminator - line comments, block comments
(which nest in Postgres), quoted identifiers and strings, and dollar
quotes - and splits only on the ones that are.
"""

import re

# Statements worth replaying. DDL and grants are the point; inserts and
# updates are a migration seeding production data, which a test supplies
# itself.
_REPLAYABLE = re.compile(
    r"^\s*(create|alter|comment|grant|revoke|drop|do)\b",
    re.IGNORECASE,
)


def split_sql(text: str) -> list[str]:
    """Every top-level statement in `text`, semicolons stripped."""
    statements: list[str] = []
    start = 0
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # -- line comment
        if ch == "-" and text.startswith("--", i):
            end = text.find("\n", i)
            i = n if end == -1 else end + 1
            continue

        # /* block comment */, which nests
        if ch == "/" and text.startswith("/*", i):
            depth = 1
            i += 2
            while i < n and depth:
                if text.startswith("/*", i):
                    depth += 1
                    i += 2
                elif text.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            continue

        # 'string' or "identifier", doubling the quote to escape it
        if ch in ("'", '"'):
            i += 1
            while i < n:
                if text[i] == ch:
                    if i + 1 < n and text[i + 1] == ch:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue

        # $$ ... $$ or $tag$ ... $tag$
        if ch == "$":
            tag = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", text[i:])
            if tag:
                marker = tag.group(0)
                end = text.find(marker, i + len(marker))
                i = n if end == -1 else end + len(marker)
                continue

        if ch == ";":
            statements.append(text[start:i])
            i += 1
            start = i
            continue

        i += 1

    statements.append(text[start:])
    return [s.strip() for s in statements if s.strip()]


def replayable_statements(text: str) -> str:
    """The DDL and grants from a migration, ready to execute as one block.

    Data statements are dropped: a migration seeding a production row is
    not something a test wants replayed underneath its own fixtures.
    """
    kept = [s for s in split_sql(text) if _REPLAYABLE.match(s)]
    return ";\n".join(kept) + (";" if kept else "")
