"""Generates a merchant's referral code: INF- plus six characters, e.g.
INF-8K3P2M.

Deliberately not derived from anything. A code built from the merchant id
or Merchant ID would let anyone holding one work out another, and would
leak which business invited them. This is random, from `secrets` — the
same cryptographically safe RNG app/services/merchant_code.py uses, not
`random`.

The alphabet omits 0, 1, I, L, O and S - one of each pair people
mis-transcribe, which leaves 5 and 2 unambiguous because S and Z's
partners are gone. Codes get written on paper, read aloud over the phone
and typed in by someone who did not choose them, and a referral silently
attributed to the wrong merchant is worse than a longer code.

A code is an identifier, never a credential: it proves nothing and grants
nothing. Using one at signup creates an attribution that pays only if the
referred business is approved by a human and then actually trades.
"""

import secrets

from supabase import Client

from app.core.errors import APIError

_PREFIX = "INF-"
# No 0, 1, I, L, O, S.
_ALPHABET = "23456789ABCDEFGHJKMNPQRTUVWXYZ"
_LENGTH = 6
_MAX_ATTEMPTS = 20

# 30^6 ~= 729 million combinations. At a few thousand merchants a
# collision is vanishingly unlikely, and the unique index is the backstop.


class ReferralCodeGenerationError(APIError):
    """Every candidate collided. Raised rather than reusing or shortening
    a code, because two merchants sharing one would misattribute real
    money."""

    status_code = 500
    code = "referral_code_generation_failed"


def _candidate() -> str:
    return _PREFIX + "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))


def _code_exists(client: Client, code: str) -> bool:
    # Compared upper-case because the unique index is on upper(referral_code)
    # — "inf-8k3p2m" and "INF-8K3P2M" are the same code.
    result = client.table("merchants").select("id").eq("referral_code", code.upper()).execute()
    return bool(result.data)


def normalise_referral_code(value: str | None) -> str | None:
    """What a merchant typed, turned into what is stored.

    Upper-cased and trimmed, and the INF- prefix added if they left it
    off — someone reading a code off a poster will type the six
    characters alone about as often as the whole thing. Returns None for
    anything that cannot be a code, so a caller never has to tell empty
    from invalid.
    """
    if not value:
        return None
    cleaned = "".join(ch for ch in str(value).strip().upper() if ch.isalnum() or ch == "-")
    if not cleaned:
        return None
    if not cleaned.startswith(_PREFIX):
        cleaned = _PREFIX + cleaned.lstrip("-")
    body = cleaned[len(_PREFIX) :]
    if len(body) != _LENGTH or any(ch not in _ALPHABET for ch in body):
        return None
    return cleaned


def generate_referral_code(client: Client) -> str:
    """A random, unique INF-XXXXXX code.

    Checks for a collision on each attempt; the unique index on
    upper(referral_code) is the atomic backstop against a race between
    that check and the caller's write.
    """
    for _ in range(_MAX_ATTEMPTS):
        candidate = _candidate()
        if not _code_exists(client, candidate):
            return candidate
    raise ReferralCodeGenerationError(
        f"Could not generate a unique referral code after {_MAX_ATTEMPTS} attempts"
    )
