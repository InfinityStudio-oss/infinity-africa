"""Creating a payout from the prefunded Payout Wallet.

The shape of the decision, in the order it has to happen:

  1. Is this merchant allowed to send payouts in this environment at all,
     and are they paused?
  2. Is the beneficiary theirs, in this environment, and active?
  3. What does it cost - amount plus the merchant's fee schedule?
  4. Is it within the per-payout limit?
  5. Is there enough in the Payout Wallet for amount + fee?
  6. Create the row and reserve the funds.

**What is NOT here yet, and must be before any live pilot:**

* The rolling 24h limit. `merchant_payout_settings.daily_limit_tzs` is
  read and carried on PayoutSettings but nothing enforces it. A merchant
  is currently bounded only by the per-payout limit and their wallet
  balance.
* Serialization of steps 5 and 6. The balance read and the reservation
  are two round trips, so two concurrent payouts can both see the same
  available balance and both pass step 5. They cannot both SPEND it -
  post_payout_reservation refuses an overdraw under a row lock, and the
  loser is cancelled below - but the daily limit, once it exists, will
  need the whole decision inside one Postgres function under
  pg_advisory_xact_lock, the way finalize_withdrawal_limits does it for
  withdrawals.

  Session-scoped advisory locks (pg_try_advisory_lock) are not an option
  here: the connection is pooled, so the lock outlives the request on a
  connection handed to someone else. Transaction-scoped inside a function
  is the form that works - 20261016120000_scheduler_leases.sql documents
  the same trap.

Nothing here dispatches to a provider. A payout leaves this module
`queued` and funded; the worker is what talks to Selcom.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from supabase import Client

from app.core.errors import (
    ConflictError,
    InsufficientBalanceError,
    NotFoundError,
    ValidationAPIError,
)
from app.services.crud import execute_maybe_single, get_by_id, insert_row
from app.services.ledger import (
    get_payout_wallet_balances,
    post_payout_reservation,
)

logger = logging.getLogger("infinity.payouts")

MONEY = Decimal("0.01")


@dataclass(frozen=True)
class PayoutSettings:
    """A merchant's payout permissions, as the database holds them."""

    enabled: bool
    paused: bool
    paused_reason: str | None
    per_payout_limit_tzs: Decimal | None
    daily_limit_tzs: Decimal | None
    fee_flat_tzs: Decimal
    fee_percentage: Decimal


def load_payout_settings(
    client: Client, *, merchant_id: uuid.UUID, environment: str
) -> PayoutSettings | None:
    """None means the merchant has no payout access at all.

    An ABSENT row is the default state for every merchant, and it means
    no. That is deliberate: access is granted one merchant at a time by a
    Super Admin, so "we could not find a setting" and "they are not
    allowed" must be the same answer. Treating a missing row as
    permissive is the classic way a default-off feature turns itself on.
    """
    row = execute_maybe_single(
        client.table("merchant_payout_settings")
        .select("*")
        .eq("merchant_id", str(merchant_id))
        .maybe_single()
    )
    if not row:
        return None

    enabled = bool(row["live_enabled"] if environment == "live" else row["sandbox_enabled"])
    return PayoutSettings(
        enabled=enabled,
        paused=bool(row.get("paused")),
        paused_reason=row.get("paused_reason"),
        per_payout_limit_tzs=_money_or_none(row.get("per_payout_limit_tzs")),
        daily_limit_tzs=_money_or_none(row.get("daily_limit_tzs")),
        fee_flat_tzs=Decimal(str(row.get("fee_flat_tzs") or 0)),
        fee_percentage=Decimal(str(row.get("fee_percentage") or 0)),
    )


def _money_or_none(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def quote_fee(settings: PayoutSettings, amount: Decimal) -> Decimal:
    """flat + percentage, rounded HALF_UP to the cent.

    HALF_UP rather than the ROUND_DOWN used on withdrawal ceilings: a
    ceiling nudged down lets less money through unattended, which is the
    safe direction there, but a FEE nudged down is revenue quietly lost
    on every payout. Different quantity, different safe direction.
    """
    percentage_part = (amount * settings.fee_percentage) / Decimal(100)
    return (settings.fee_flat_tzs + percentage_part).quantize(MONEY, rounding=ROUND_HALF_UP)


def load_beneficiary(
    client: Client, *, beneficiary_id: uuid.UUID, merchant_id: uuid.UUID, environment: str
) -> dict:
    """The beneficiary, if it is this merchant's, in this environment, and
    active.

    All three failures answer 404, not 403. A payout key probing ids must
    not be able to tell "exists but belongs to someone else" from "does
    not exist" - that difference is an enumeration oracle over other
    merchants' destinations.
    """
    row = get_by_id(client, "payout_beneficiaries", beneficiary_id)
    if (
        not row
        or row["merchant_id"] != str(merchant_id)
        or row["environment"] != environment
        or row["status"] != "active"
    ):
        raise NotFoundError("Beneficiary not found")
    return row


def build_provider_reference(merchant_code: str | None = None) -> str:
    """Our stable handle for the provider.

    Generated once, at creation, and never regenerated - it is what makes
    a retry after an ambiguous dispatch ask about the SAME payout instead
    of starting a second one. Unique per (merchant, environment) by
    database index; the uuid4 suffix is what carries the uniqueness, the
    prefix is only there to make it legible in a provider's dashboard.
    """
    return f"PO-{uuid.uuid4().hex[:20].upper()}"


def assert_payout_allowed(settings: PayoutSettings | None, *, environment: str) -> PayoutSettings:
    """Access and pause, before anything is priced or reserved."""
    if settings is None or not settings.enabled:
        raise ValidationAPIError(
            "The Disbursement API is not enabled for this account. "
            "Contact InfinityPay support to request access."
        )
    if settings.paused:
        detail = f" ({settings.paused_reason})" if settings.paused_reason else ""
        raise ConflictError(
            f"Payouts are temporarily paused for this account{detail}. "
            "Payouts already sent are unaffected."
        )
    return settings


def create_payout(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    environment: str,
    beneficiary_id: uuid.UUID,
    amount: Decimal,
    currency: str,
    api_key_id: uuid.UUID | None,
    metadata: dict | None = None,
) -> dict:
    """Validate, price, reserve and queue - or change nothing at all.

    Returns the created payout row, `queued` and funded. The reservation
    is posted through the same locked, no-negative ledger function every
    other money movement uses, so a payout that gets a row is a payout
    whose funds are already held.
    """
    settings = assert_payout_allowed(
        load_payout_settings(client, merchant_id=merchant_id, environment=environment),
        environment=environment,
    )
    beneficiary = load_beneficiary(
        client, beneficiary_id=beneficiary_id, merchant_id=merchant_id, environment=environment
    )

    amount = Decimal(str(amount)).quantize(MONEY)
    if amount <= 0:
        raise ValidationAPIError("Amount must be greater than zero.")

    fee = quote_fee(settings, amount)
    total_debit = amount + fee

    if settings.per_payout_limit_tzs is not None and amount > settings.per_payout_limit_tzs:
        raise ValidationAPIError(
            f"Amount {amount} {currency} is above this account's per-payout limit of "
            f"{settings.per_payout_limit_tzs} {currency}."
        )

    # Friendly, fast rejection. NOT the real guarantee: two concurrent
    # calls can both read the same available balance here and both pass.
    # post_payout_reservation is what actually cannot overdraw, because
    # the database checks under a row lock - see
    # 20261116090000_payout_wallet_ledger_accounts.sql.
    available, _reserved = get_payout_wallet_balances(
        client, merchant_id=merchant_id, currency=currency, environment=environment
    )
    if total_debit > available:
        raise InsufficientBalanceError(
            f"Payout wallet has {available} {currency}; this payout needs "
            f"{total_debit} {currency} ({amount} plus {fee} fee). Fund the payout wallet first."
        )

    payout = insert_row(
        client,
        "payouts",
        {
            "merchant_id": str(merchant_id),
            "environment": environment,
            "api_key_id": str(api_key_id) if api_key_id else None,
            "beneficiary_id": str(beneficiary["id"]),
            "amount": str(amount),
            "fee_amount": str(fee),
            "total_debit": str(total_debit),
            "currency": currency,
            "status": "queued",
            "provider_reference": build_provider_reference(),
            "metadata": metadata or {},
        },
    )

    try:
        post_payout_reservation(
            client,
            transaction_id=uuid.UUID(payout["id"]),
            merchant_id=merchant_id,
            total_debit=total_debit,
            currency=currency,
            environment=environment,
        )
    except InsufficientBalanceError:
        # Lost the race the friendly check above cannot win: another
        # payout took the funds between the read and the reservation.
        # The row must not survive as a `queued` payout with nothing
        # behind it - the worker would dispatch money that was never
        # reserved. Cancelled rather than deleted so the attempt stays
        # visible, and cancelled is honest: it was never dispatched.
        client.table("payouts").update(
            {
                "status": "cancelled",
                "failure_code": "insufficient_funds",
                "failure_reason": "Payout wallet balance was taken by another payout before this one reserved.",
                "completed_at": "now()",
            }
        ).eq("id", payout["id"]).execute()
        raise

    logger.info(
        "payout_created id=%s merchant=%s env=%s amount=%s fee=%s",
        payout["id"],
        merchant_id,
        environment,
        amount,
        fee,
    )
    return payout
