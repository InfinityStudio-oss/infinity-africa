"""The merchant alert text, and what it costs to send.

Two jobs, both pure: render the Swahili message from committed financial
values, and work out how many SMS parts the rendered result actually is.
No database, no provider, no clock - so the message a test renders is
byte-for-byte the message the worker freezes.

**Money is formatted, never recomputed.** Every value arrives as a Decimal
read from a committed record. Nothing here adds, subtracts or derives a
figure; `net` is not computed from `gross - fee`, it is passed in, because
the ledger already decided it and a second opinion in a text renderer is
how two sources of truth start.
"""

from decimal import Decimal

# GSM 03.38 - the characters a message can use before the provider has to
# fall back to UCS-2 and the part size drops from 160 to 70. Worth being
# exact about: a single curly quote or long dash in an announcement more
# than doubles its cost, and that surprise should be visible in the
# Compose screen rather than on the invoice.
_GSM_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅå_ÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
    "ΔΦΓΛΩΠΨΣΘΞ"
)
# These cost two characters each in GSM-7: they are sent as an escape plus
# the character.
_GSM_EXTENDED = "^{}\\[~]|€"

GSM_SINGLE = 160
GSM_CONCAT = 153
UCS2_SINGLE = 70
UCS2_CONCAT = 67


def _is_gsm7(text: str) -> bool:
    return all(ch in _GSM_BASIC or ch in _GSM_EXTENDED for ch in text)


def _gsm7_length(text: str) -> int:
    return sum(2 if ch in _GSM_EXTENDED else 1 for ch in text)


def message_cost(text: str) -> dict:
    """Encoding and part count for an already-rendered message.

    The brief is explicit that a payment receipt must not be assumed to
    fit one part, and with a long reference and four amounts it often
    does not. Returning the number rather than hiding it is what lets the
    Compose screen show a cost before anyone clicks Send.
    """
    if _is_gsm7(text):
        length = _gsm7_length(text)
        single, concat, encoding = GSM_SINGLE, GSM_CONCAT, "GSM-7"
    else:
        # UCS-2 counts UTF-16 code units, so an emoji outside the BMP
        # costs two. len() on a str would undercount it.
        length = len(text.encode("utf-16-le")) // 2
        single, concat, encoding = UCS2_SINGLE, UCS2_CONCAT, "UCS-2"

    if length == 0:
        segments = 0
    elif length <= single:
        segments = 1
    else:
        segments = -(-length // concat)  # ceiling division

    return {"encoding": encoding, "length": length, "segments": segments}


def format_amount(value: Decimal | str | int | None) -> str:
    """``10000.00`` -> ``10,000``; ``9770.50`` -> ``9,770.50``.

    Trailing ``.00`` is dropped because TZS has no circulating subunit and
    "TZS 10,000.00" reads like a system talking to itself. A non-zero
    fraction is always kept in full - dropping it would be truncating a
    financial value to save two characters, which the brief rules out and
    which would also make the SMS disagree with the portal.
    """
    if value is None:
        return "-"
    amount = Decimal(str(value))
    quantized = amount.quantize(Decimal("0.01"))
    if quantized == quantized.to_integral_value():
        return f"{quantized.to_integral_value():,}"
    return f"{quantized:,.2f}"


# The exact wording from the brief. "Salio baada ya muamala" is the balance
# immediately after this transaction - which is what
# ledger_entries.balance_after holds, and is why that column, rather than a
# later wallet read, is the only acceptable source. It is not described as
# available or withdrawable, because a wallet balance on this platform is
# not the same thing as a withdrawable amount.
#
# No emoji, no decorative characters: everything here stays inside GSM-7 so
# a receipt costs the fewest parts it can.
COLLECTION_ALERT_TEMPLATE = (
    "InfinityPay: Umepokea TZS {amount}. "
    "Makato: TZS {fee}. "
    "Kiasi halisi: TZS {net}. "
    "Salio baada ya muamala: TZS {closing_balance}. "
    "Kumbukumbu: {reference}."
)


def render_collection_alert(
    *,
    gross_amount: Decimal,
    fee_amount: Decimal,
    net_amount: Decimal,
    closing_balance: Decimal,
    reference: str,
) -> str:
    """The merchant's payment alert.

    Every argument is a committed value: gross/fee/net from the
    transactions row the ledger posted against, closing_balance from that
    posting's own ledger_entries.balance_after, reference from
    transactions.reference. Nothing is derived here.

    Carries no customer phone number, no secret, and no claim that any
    service was activated - we do not know whether it was.
    """
    return COLLECTION_ALERT_TEMPLATE.format(
        amount=format_amount(gross_amount),
        fee=format_amount(fee_amount),
        net=format_amount(net_amount),
        closing_balance=format_amount(closing_balance),
        reference=reference,
    )
