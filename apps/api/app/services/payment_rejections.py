"""Record a payment refused before it ever started.

`assert_amount_allowed` rejects a push the network itself would refuse -
Mixx by Yas will not accept below TZS 1,000 - before any row is created:
no collection, no transaction, no checkout order, no provider call. That
is the right behaviour, and it left nothing behind at all.

Production, 23 October: 153 attempts refused that way in one day across
seven merchants, 107 of them for a single merchant. Grouping them by time
showed roughly twelve customers, three of whom tried **16, 28 and 30
times** - one for thirteen minutes - because the merchant's own screen
showed "Pending" and never displayed the reason we returned. Asked for
those customers' numbers to help them, there was nothing to give: the
request was refused before anything about it was stored.

So each refusal now leaves a record. Enough to help the customer, not
enough to be a customer database:

    amount, currency, network, the minimum required, and the phone
    **masked** to its last four digits.

The mask is the same convention used for settlement accounts in
app/services/email.py and on the withdrawals screen. A support agent can
confirm "is this your number?" without the platform retaining it.

Written through write_audit_log_best_effort on purpose. This is a record
*about* a request that was already being refused - letting the write turn
that clean 400 into a 500 would be a bad trade, and worse, would break
the very protection it is reporting on.
"""

from __future__ import annotations

import logging
import re
import uuid
from decimal import Decimal

from supabase import Client

from app.core.payment_minimums import AmountBelowOperatorMinimumError, detect_network
from app.services.audit import write_audit_log_best_effort

logger = logging.getLogger("infinity.payments")

ACTION = "payment.below_operator_minimum"


def mask_phone(phone: str | None) -> str | None:
    """`255712345678` -> `•••• 5678`.

    Last four digits only, which is what a support agent needs to confirm
    identity and all they need. Same shape as the settlement-account mask
    so the two read alike wherever they appear together.
    """
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) < 4:
        return None
    return f"•••• {digits[-4:]}"


def record_minimum_rejection(
    client: Client,
    *,
    merchant_id: uuid.UUID | str | None,
    amount: Decimal,
    currency: str = "TZS",
    customer_phone: str | None,
    minimum_required: Decimal | None = None,
    network: str | None = None,
) -> None:
    """Leave a trace of a refusal, masked. Never raises."""
    try:
        resolved_network = network or detect_network(customer_phone)
    except Exception:  # pragma: no cover - network detection must not break this
        resolved_network = None

    # write_audit_log_best_effort already swallows a failed insert, but it
    # is not the only thing that can raise here - a bad merchant_id, a
    # metadata value that will not serialise, a future change to the
    # helper. This records something about a request that is *already*
    # being refused, so nothing it does may turn that clean 400 into a
    # 500. Wrapped so the guarantee holds regardless of what changes
    # underneath it.
    try:
        write_audit_log_best_effort(
            client,
            action=ACTION,
            resource_type="collection",
            actor_type="system",
            merchant_id=uuid.UUID(str(merchant_id)) if merchant_id else None,
            metadata={
                "amount": str(amount),
                "currency": currency,
                "network": str(resolved_network) if resolved_network else None,
                "customer_phone_masked": mask_phone(customer_phone),
                "minimum_required": str(minimum_required) if minimum_required is not None else None,
            },
        )
    except Exception:  # noqa: BLE001 - never let a record break a refusal
        logger.warning("payment_minimum_rejection_not_recorded", exc_info=True)


def assert_amount_allowed_recording(
    client: Client,
    amount: Decimal,
    *,
    merchant_id: uuid.UUID | str | None,
    customer_phone: str | None = None,
    network: str | None = None,
    currency: str = "TZS",
) -> None:
    """`assert_amount_allowed`, but a refusal leaves a masked record.

    Deliberately a wrapper rather than a change to
    app/core/payment_minimums.py: that module is pure, has no database and
    is shared with the browser copy of the same rules. Pushing a write
    into it would couple a validation rule to a table.
    """
    from app.core.payment_minimums import (
        assert_amount_allowed,
        minimum_for,
        normalize_network,
    )

    try:
        assert_amount_allowed(amount, customer_phone=customer_phone, network=network)
    except AmountBelowOperatorMinimumError:
        # The error carries a customer-facing sentence, not the number, so
        # the minimum is resolved the same way the check itself resolves
        # it rather than parsed back out of the message.
        try:
            resolved = (
                normalize_network(network) if network is not None else detect_network(customer_phone)
            )
            required = minimum_for(resolved)
        except Exception:  # pragma: no cover - never shadow the real error
            required = None
        record_minimum_rejection(
            client,
            merchant_id=merchant_id,
            amount=amount,
            currency=currency,
            customer_phone=customer_phone,
            minimum_required=required,
            network=network,
        )
        raise
