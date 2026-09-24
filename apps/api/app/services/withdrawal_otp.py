"""Email OTP verification for merchant withdrawals.

A withdrawal request no longer creates a disbursement directly. The
merchant's form submission creates a *challenge* here and emails a 6-digit
code to the merchant's own registered contact address; only a successful
verification calls execute_disbursement and produces a real
PENDING_ADMIN_APPROVAL row.

What this deliberately does NOT change: Super Admin approval. Verifying an
OTP proves the person asking controls the merchant's email — it does not
approve anything. The provider is still only ever reached from
approve_disbursement, and the balance/standing/fraud gates still re-run
there. An OTP is a second factor on *requesting*, not an authorisation to
pay.

The code is never stored. Only a SHA-256 hash is kept, the same one-way
treatment API keys get (app/auth/hashing.py), so a database read cannot
yield a usable code.
"""

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from supabase import Client

from app.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationAPIError
from app.services.crud import execute_maybe_single, insert_row, update_row

logger = logging.getLogger("infinity.withdrawal_otp")

# Deliberately generic and identical for every failure mode — wrong code,
# expired, already used, locked out, or no such challenge. Telling them
# apart would let a caller map out which challenges exist and how far a
# guessing run has got.
_GENERIC_FAILURE = "That code isn't valid. Request a new one and try again."


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_otp() -> str:
    """A 6-digit code from the OS CSPRNG, never random.randint. Zero-padded
    rather than range-limited so every one of the million codes is equally
    likely — starting at 100000 would silently drop a tenth of the space."""
    return f"{secrets.randbelow(1_000_000):06d}"


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    """Binds a code to one exact withdrawal.

    Sorted keys and a fixed separator so the same request always hashes the
    same way regardless of dict ordering, and Decimal is rendered as a
    string so 1000 and 1000.00 cannot collide into one hash. Editing any
    field after the code was sent changes this, which is what stops a code
    issued for a small amount being replayed against a larger one.
    """

    def _default(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(value)

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_default)
    return _hash(canonical)


def mask_email(email: str) -> str:
    """b***a@example.com — enough for the merchant to recognise which inbox
    to open, not enough to disclose an address they didn't already know."""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "your registered email"
    if len(local) <= 2:
        return f"{local[:1]}***@{domain}"
    return f"{local[0]}{'*' * max(1, len(local) - 2)}{local[-1]}@{domain}"


def mask_destination(identifier: str) -> str:
    """Last 4 only. Goes in the CEO notification, where the full account
    number has no business being."""
    value = (identifier or "").strip()
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


def create_challenge(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    requested_by: uuid.UUID,
    payload: dict[str, Any],
) -> tuple[dict, str]:
    """Writes a challenge and returns (row, plaintext_otp).

    The plaintext is returned for the caller to email and is never persisted
    or logged. Any still-live challenge for this merchant is superseded
    first, so a merchant can only ever have one usable code outstanding —
    otherwise an older code for a different amount would stay valid
    alongside the new one.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    _supersede_active(client, merchant_id=merchant_id, at=now)

    otp = generate_otp()
    row = insert_row(
        client,
        "merchant_withdrawal_otp_challenges",
        {
            "merchant_id": str(merchant_id),
            "requested_by": str(requested_by),
            "withdrawal_payload": payload,
            "payload_hash": canonical_payload_hash(payload),
            "otp_hash": _hash(otp),
            "expires_at": (now + timedelta(minutes=settings.withdrawal_otp_expires_minutes)).isoformat(),
            "max_attempts": settings.withdrawal_otp_max_attempts,
            "last_sent_at": now.isoformat(),
        },
    )
    return row, otp


def _supersede_active(client: Client, *, merchant_id: uuid.UUID, at: datetime) -> None:
    """Locks every live challenge for this merchant. Called before issuing a
    new one so exactly one code is ever valid at a time."""
    rows = (
        client.table("merchant_withdrawal_otp_challenges")
        .select("id")
        .eq("merchant_id", str(merchant_id))
        .is_("used_at", None)
        .is_("locked_at", None)
        .execute()
    ).data or []
    for row in rows:
        update_row(
            client,
            "merchant_withdrawal_otp_challenges",
            uuid.UUID(row["id"]),
            {"locked_at": at.isoformat()},
        )


def rotate_otp(client: Client, *, challenge: dict) -> str:
    """Issues a fresh code on the same challenge, for Resend.

    Enforces the cooldown, and resets `attempts` — the new code deserves its
    own budget, and not resetting would let a merchant who fumbled the first
    code be locked out of a code they have not even seen yet.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    last_sent = _parse_ts(challenge.get("last_sent_at"))
    if last_sent is not None:
        elapsed = (now - last_sent).total_seconds()
        remaining = settings.withdrawal_otp_resend_cooldown_seconds - elapsed
        if remaining > 0:
            raise ConflictError(f"Please wait {int(remaining) + 1} seconds before requesting another code.")

    otp = generate_otp()
    update_row(
        client,
        "merchant_withdrawal_otp_challenges",
        uuid.UUID(challenge["id"]),
        {
            "otp_hash": _hash(otp),
            "attempts": 0,
            "resend_count": int(challenge.get("resend_count") or 0) + 1,
            "last_sent_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=settings.withdrawal_otp_expires_minutes)).isoformat(),
            "updated_at": now.isoformat(),
        },
    )
    return otp


def get_own_challenge(client: Client, *, challenge_id: uuid.UUID, merchant_id: uuid.UUID) -> dict:
    """Fetches a challenge scoped to the caller's merchant.

    Someone else's challenge reads as NotFound rather than Forbidden: a
    merchant should not be able to learn that a given challenge id exists at
    all.
    """
    row = execute_maybe_single(
        client.table("merchant_withdrawal_otp_challenges")
        .select("*")
        .eq("id", str(challenge_id))
        .eq("merchant_id", str(merchant_id))
        .maybe_single()
    )
    if not row:
        raise NotFoundError("Verification request not found")
    return row


def verify_otp(client: Client, *, challenge: dict, submitted_code: str) -> dict:
    """Checks a submitted code, returning the challenge row on success.

    Every failure raises the same message. The attempt counter is
    incremented *before* the comparison, so a caller who disconnects mid
    request still spends their attempt.
    """
    now = datetime.now(timezone.utc)
    challenge_id = uuid.UUID(challenge["id"])

    if challenge.get("used_at"):
        raise ValidationAPIError(_GENERIC_FAILURE)
    if challenge.get("locked_at"):
        raise ValidationAPIError(_GENERIC_FAILURE)

    expires_at = _parse_ts(challenge.get("expires_at"))
    if expires_at is None or now >= expires_at:
        raise ValidationAPIError(_GENERIC_FAILURE)

    attempts = int(challenge.get("attempts") or 0) + 1
    max_attempts = int(challenge.get("max_attempts") or get_settings().withdrawal_otp_max_attempts)
    locked = attempts >= max_attempts

    submitted = (submitted_code or "").strip()
    # compare_digest, not ==, so a wrong code cannot be narrowed down by how
    # long the comparison took.
    correct = hmac.compare_digest(_hash(submitted), str(challenge.get("otp_hash") or ""))

    if not correct:
        update_row(
            client,
            "merchant_withdrawal_otp_challenges",
            challenge_id,
            {
                "attempts": attempts,
                "updated_at": now.isoformat(),
                **({"locked_at": now.isoformat()} if locked else {}),
            },
        )
        raise ValidationAPIError(_GENERIC_FAILURE)

    # Marked used in the same step that reports success, so a duplicate
    # verify of the same challenge cannot produce a second withdrawal.
    return update_row(
        client,
        "merchant_withdrawal_otp_challenges",
        challenge_id,
        {"attempts": attempts, "used_at": now.isoformat(), "updated_at": now.isoformat()},
    )


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
