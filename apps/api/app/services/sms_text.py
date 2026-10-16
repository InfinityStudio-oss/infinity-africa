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


# The tail both automatic messages carry: the referral invitation and
# where to get help. Referrals are a real feature (start_referral_period
# runs on approval), so the commission offer is not an empty promise.
#
# It costs exactly one extra message part on each template, which is the
# whole reason it is a named constant - changing it changes the cost of
# every welcome and every payout confirmation, and that should be visible
# in one place rather than buried twice.
MESSAGE_TAIL = (
    "Alika wafanyabiashara kujiunga na INFINITYPAY ujipatie kamisheni. "
    "Kwa msaada: 255747730270 au help@infinitypay.me"
)

# Sent once, after a merchant's first approval.
#
# Every claim is checked against what the platform actually does:
#   "Pokea malipo" - collections, payment links and invoices all exist.
#   "tengeneza API keys na weka webhooks" - self-service since 06eb6d1.
#       The message says a merchant *can* create them; it never carries a
#       key or a signing secret.
#   "Toa pesa kwenda benki au simu" - both real. Production has paid out
#       to CRDB as well as M-Pesa, Mixx by Yas, Halopesa, Airtel and
#       Selcom; DestinationCode lists twelve banks.
#   "bila ada" - true only while withdrawals are actually free, which is
#       why this one sentence is conditional rather than baked in.
_WELCOME_OPENING = (
    "Karibu InfinityPay! Akaunti yako imeidhinishwa. "
    "Pokea malipo, tengeneza API keys na weka webhooks. "
)
WELCOME_TEMPLATE_FREE = _WELCOME_OPENING + "Toa pesa kwenda benki au simu bila ada. " + MESSAGE_TAIL
# The same message with the fee claim removed, for whenever withdrawals
# are not free. Advertising free withdrawals to a merchant who is charged
# for them is the one thing this message must never do.
WELCOME_TEMPLATE_PAID = _WELCOME_OPENING + "Toa pesa kwenda benki au simu. " + MESSAGE_TAIL


def render_welcome(*, withdrawals_are_free: bool) -> str:
    """The welcome message, with the fee claim only when it is true.

    `withdrawals_are_free` is answered by asking the real fee calculator
    what this merchant would actually be charged, not by a constant - so
    if withdrawal pricing ever changes, the wording follows it instead of
    becoming a false advertisement.
    """
    return WELCOME_TEMPLATE_FREE if withdrawals_are_free else WELCOME_TEMPLATE_PAID


# Sent once, after a payout is confirmed by the provider.
#
# Written from the merchant's side of the movement: they have *received*
# money from InfinityPay into their bank or phone, which is how a mobile
# money receipt reads and how they will recognise it. "Salio baada ya
# muamala" is their InfinityPay wallet balance afterwards - the balance
# the wallet debit produced at approval, not a reading taken now.
#
# No provider receipt code. One was briefly included (selcom_receipt,
# e.g. SB1016W6ZYN) because it is the one figure a merchant could check
# against their mobile money statement, and removed at the owner's
# request - `reference` already identifies the payout in the portal and
# in support conversations.
WITHDRAWAL_COMPLETE_TEMPLATE = (
    "InfinityPay: Imethibitishwa. "
    "Umepokea TZS {amount} kutoka INFINITYPAY. "
    "Ada: TZS {fee}. "
    "Salio baada ya muamala: TZS {closing_balance}. "
    "Kumb: {reference}. " + MESSAGE_TAIL
)


def render_withdrawal_complete(
    *,
    amount: Decimal,
    fee_amount: Decimal,
    closing_balance: Decimal,
    reference: str,
) -> str:
    """A confirmed payout.

    Every figure is read from a committed record: amount and fee from the
    disbursement, closing_balance from the ledger entry that debited the
    wallet for it, reference from the transaction. Nothing is derived
    here, and the fee is rendered rather than assumed - a merchant who
    was charged must never be told the withdrawal was free.
    """
    return WITHDRAWAL_COMPLETE_TEMPLATE.format(
        amount=format_amount(amount),
        fee=format_amount(fee_amount),
        closing_balance=format_amount(closing_balance),
        reference=reference,
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
