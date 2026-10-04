"""Per-network minimum payment amounts, and the network a Tanzanian
mobile number belongs to.

Mixx by Yas (Tigo) rejects a push below TZS 1,000. Every other mobile
money network on this platform accepts from TZS 100. Before this module,
a customer entering 500 on a Tigo number got as far as Selcom and came
back as a failed payment — the money never moved, but the merchant saw a
failure, the customer saw a dead prompt, and a provider attempt was spent
on a request that could never have succeeded.

So the rule is applied *before* anything is created: no collection row,
no transaction, no checkout order, no Selcom call. There is nothing to
mark failed afterwards because nothing was started.

One module on purpose. The same numbers are needed by the public API, the
customer payment page, payment links and invoices, and a rule duplicated
across four call sites is a rule that drifts.

The prefix table follows the TCRA allocations and was **confirmed by the
platform owner on 2026-10-04**, including the one entry worth doubting:
077, originally Zantel, merged into Tigo and now sold as Mixx by Yas, so
it carries the 1,000 floor like the rest of that network. Treat it as
settled rather than re-deriving it; if an operator is ever reassigned a
range, correcting it here corrects it everywhere, including the browser
copy, which test_payment_minimums_sync.py holds to this one.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.errors import APIError
from app.core.phone import InvalidPhoneNumberError, normalize_tz_phone
from app.schemas.enums import DestinationCode

# Minimum a push below which the network itself will refuse it.
MIXX_BY_YAS_MINIMUM: Decimal = Decimal(1000)

# Every other network, and the floor applied when the network is unknown
# or the customer has not chosen one yet (a QR scan, a hosted checkout
# page) — see assert_amount_allowed.
DEFAULT_MINIMUM: Decimal = Decimal(100)

# The two-digit national prefix (what follows "255") -> network.
#
# Vodacom     74 75 76
# Mixx by Yas 65 67 71, plus 77 from the former Zantel
# Airtel      68 69 78
# Halotel     61 62
# TTCL        73
_PREFIX_TO_NETWORK: dict[str, DestinationCode] = {
    "74": DestinationCode.MPESA,
    "75": DestinationCode.MPESA,
    "76": DestinationCode.MPESA,
    "65": DestinationCode.MIXXBYYAS,
    "67": DestinationCode.MIXXBYYAS,
    "71": DestinationCode.MIXXBYYAS,
    "77": DestinationCode.MIXXBYYAS,
    "68": DestinationCode.AIRTELMONEY,
    "69": DestinationCode.AIRTELMONEY,
    "78": DestinationCode.AIRTELMONEY,
    "61": DestinationCode.HALOPESA,
    "62": DestinationCode.HALOPESA,
    "73": DestinationCode.TTCLPESA,
}

# Spellings a caller might send for the same network. This platform's own
# enum uses MIXXBYYAS, but "Tigo" is still what most people say and what
# a partner's billing system is likely to send.
_NETWORK_ALIASES: dict[str, DestinationCode] = {
    "TIGO": DestinationCode.MIXXBYYAS,
    "TIGOPESA": DestinationCode.MIXXBYYAS,
    "TIGO_PESA": DestinationCode.MIXXBYYAS,
    "MIX": DestinationCode.MIXXBYYAS,
    "MIXX": DestinationCode.MIXXBYYAS,
    "YAS": DestinationCode.MIXXBYYAS,
    "MIXBYYAS": DestinationCode.MIXXBYYAS,
    "MIX_BY_YAS": DestinationCode.MIXXBYYAS,
    "MIXXBYYAS": DestinationCode.MIXXBYYAS,
    "MIXX_BY_YAS": DestinationCode.MIXXBYYAS,
    "VODACOM": DestinationCode.MPESA,
    "MPESA": DestinationCode.MPESA,
    "M_PESA": DestinationCode.MPESA,
    "AIRTEL": DestinationCode.AIRTELMONEY,
    "AIRTELMONEY": DestinationCode.AIRTELMONEY,
    "HALOTEL": DestinationCode.HALOPESA,
    "HALOPESA": DestinationCode.HALOPESA,
    "TTCL": DestinationCode.TTCLPESA,
    "TTCLPESA": DestinationCode.TTCLPESA,
}

# What the customer is told. Names the network they are actually on and
# gives them both ways out, because "minimum is 1,000" with no
# alternative reads as a refusal rather than a choice.
MIXX_BY_YAS_MESSAGE = (
    "Minimum amount for Tigo / Mixx by Yas is TZS 1,000. "
    "Please enter TZS 1,000 or more, or use another mobile money network."
)
DEFAULT_MESSAGE = "Minimum payment amount is TZS 100."


class AmountBelowOperatorMinimumError(APIError):
    """The amount is below what the customer's own network will accept.

    A 400 rather than a 422: the request is well-formed, it just cannot
    succeed, and a partner branching on `AMOUNT_BELOW_OPERATOR_MINIMUM`
    should not have to distinguish it from a malformed body.

    The message is customer-facing by design — it is shown on the payment
    page and returned to a merchant's API caller unchanged, so it names no
    provider and leaks nothing about how the check was made.
    """

    status_code = 400
    # Upper-case to match the structured code published in the Direct
    # Wallet Push docs, which is what a partner integration matches on.
    code = "AMOUNT_BELOW_OPERATOR_MINIMUM"


def normalize_network(value: str | None) -> DestinationCode | None:
    """Resolves any spelling of a network name to this platform's own
    enum, or None if it is not one we know."""
    if not value:
        return None
    key = "".join(ch for ch in str(value).upper() if ch.isalnum() or ch == "_")
    return _NETWORK_ALIASES.get(key) or _NETWORK_ALIASES.get(key.replace("_", ""))


def detect_network(phone: str | None) -> DestinationCode | None:
    """The mobile money network a Tanzanian number belongs to, or None if
    the number is unusable or its prefix is not one we have mapped.

    Never raises: an unparseable number is the phone validator's problem,
    not this one's, and returning None here means "apply the baseline
    minimum" rather than blocking the payment.
    """
    if not phone:
        return None
    try:
        normalized = normalize_tz_phone(phone)
    except InvalidPhoneNumberError:
        return None
    return _PREFIX_TO_NETWORK.get(normalized[3:5])


def minimum_for(network: DestinationCode | None) -> Decimal:
    """The smallest amount this network will accept."""
    return MIXX_BY_YAS_MINIMUM if network == DestinationCode.MIXXBYYAS else DEFAULT_MINIMUM


def message_for(network: DestinationCode | None) -> str:
    return MIXX_BY_YAS_MESSAGE if network == DestinationCode.MIXXBYYAS else DEFAULT_MESSAGE


def assert_amount_allowed(
    amount: Decimal,
    *,
    customer_phone: str | None = None,
    network: str | DestinationCode | None = None,
) -> None:
    """Raises AmountBelowOperatorMinimumError if this amount cannot
    succeed on this network. Returns None otherwise.

    Pass `customer_phone` only when the payment is actually pushed to that
    number, because that is what makes its network the one that applies.
    A QR scan or a hosted checkout page lets the customer pick a different
    network at the moment of paying, so those pass neither argument and
    get the baseline floor — enforcing a Tigo minimum on a customer who is
    about to pay by M-Pesa would block a payment that would have worked.

    `network` wins when both are given: an explicitly stated network is a
    stronger signal than a prefix lookup.
    """
    resolved = normalize_network(network) if network is not None else None
    if resolved is None:
        resolved = detect_network(customer_phone)

    minimum = minimum_for(resolved)
    if amount < minimum:
        raise AmountBelowOperatorMinimumError(message_for(resolved))
