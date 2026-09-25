"""Hashing for merchant API keys.

Only the hash is ever stored (see api_keys.hashed_key) — the plaintext key
is shown to the merchant once, at creation time, and never persisted.

**Why a plain SHA-256 and not bcrypt/Argon2.** Slow KDFs exist to make
guessing *low-entropy human-chosen* secrets expensive. An API key here is
`secrets.token_urlsafe(24)` — 192 bits from the OS CSPRNG (see
merchant_portal.py::create_my_api_key). There is no dictionary to try and
no meaningful search space to narrow, so an attacker holding the hash
column gains nothing that a slower hash would prevent; the cost would fall
entirely on legitimate requests, which verify a key on every single API
call.

That reasoning depends on the key staying high-entropy and randomly
generated. If keys ever become user-chosen, shorter, or derived from
anything predictable, this must become Argon2id — and existing keys would
need a rollover, since the stored hashes are not reversible.

Lookup is by indexed equality on the hash (`.eq("hashed_key", ...)`), so no
secret is ever compared byte-by-byte in application code and there is no
timing side channel to close here. User passwords are never handled by this
codebase at all — Supabase Auth owns them end to end.
"""

import hashlib


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
