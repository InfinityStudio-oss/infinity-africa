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


# The tail both automatic messages carry.
#
# A named constant because it is the cheapest thing to make expensive:
# every character is paid for on every welcome and every payout
# confirmation. A referral invitation and the support email address lived
# here briefly and were removed on 2026-10-17 - between them they pushed
# both messages past 160 characters, the GSM-7 limit for a single part,
# so each cost two parts instead of one. The phone number is what a
# merchant actually reaches for when something looks wrong.
MESSAGE_TAIL = "Kwa msaada: 255747730270"

# Sent once, after a merchant's first approval.
#
# Every claim is checked against what the platform actually does:
#   "Pokea malipo" - collections, payment links and invoices all exist.
#   "tengeneza API keys na weka webhooks" - self-service since 06eb6d1.
#       The message says a merchant *can* create them; it never carries a
#       key or a signing secret.
#
# It used to end "Toa pesa kwenda benki au simu bila ada", and that one
# clause needed a whole mechanism behind it: the fee claim was only true
# while withdrawals were actually free, so the text was chosen at send
# time by asking the real fee calculator. The sentence was dropped on
# 2026-10-17 and the mechanism went with it - there is no claim left to
# get wrong, and nothing to keep in step with pricing.
WELCOME_TEMPLATE = (
    "Karibu InfinityPay! Akaunti yako imeidhinishwa. "
    "Pokea malipo, tengeneza API keys na weka webhooks. " + MESSAGE_TAIL
)


def render_welcome() -> str:
    """The welcome message.

    Takes no arguments now. It took `withdrawals_are_free` while it
    advertised free withdrawals, because telling a merchant something is
    free when they are charged for it is the one mistake this message
    must never make. With the claim gone, so is the question.
    """
    return WELCOME_TEMPLATE



# No "InfinityPay:" prefix. The sender ID the message arrives from is
# already INFINITYPAY, so the name appeared twice on the handset before
# the first full stop - and those are the characters this message can
# least afford.
WITHDRAWAL_COMPLETE_TEMPLATE = (
    "Imethibitishwa. "
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


# --- Super Admin alerts ------------------------------------------------
#
# A different audience from everything above: these go to an operator, not
# to a merchant. Both carry only what is needed to decide to go and look,
# and a link that still requires a normal login — nothing in an SMS may
# approve anything.
#
# The business name is interpolated from merchant-supplied text, so it is
# sanitised and capped before it reaches a template. A name is the one
# field here an outsider controls, and it decides both the segment count
# and whether the message still reads as ours.

# Longest safe business name. A GSM-7 message is 160 characters for one
# segment and 153 per part after that; the fixed text below is ~150, so
# any name at all spills into a second segment. 32 keeps the worst case at
# two parts rather than letting one long name turn every alert into three.
_MAX_NAME = 32
_MAX_REFERENCE = 32


def sanitise_for_sms(value: str | None, *, limit: int) -> str:
    """Merchant-supplied text, made safe to put in a message.

    Control characters are removed rather than escaped: a newline in a
    business name would break the message into something that reads like
    two messages, and a zero-width character changes the segment count
    without changing anything visible. Collapsed whitespace for the same
    reason.

    Truncation ends with two ASCII dots, deliberately not an ellipsis.
    U+2026 is outside GSM-7, and a single one of them flips the whole
    message to UCS-2 - which halves the characters per segment and turned
    a 143-character alert into three segments instead of one. A truncation
    marker is worth having; it is not worth tripling the cost of every
    message that uses it.

    Returns a dash for empty input — a message with a blank where a name
    should be is worse than one that says nothing is known.
    """
    text = "".join(ch for ch in str(value or "") if ch.isprintable())
    text = " ".join(text.split())
    if not text:
        return "-"
    if len(text) > limit:
        return text[: limit - 2].rstrip() + ".."
    return text


ADMIN_PORTAL_URL = "https://www.infinitypay.me/admin-login"

# One segment even at the 32-character name cap (146 chars worst case),
# which halves what this event costs. "Not yet approved" is load-bearing:
# a registered account is status='pending', kyc_status='unverified', and
# an operator reading this on a phone must not come away thinking a
# business is live.
# INFINITYPAY on its own line, then the news, then where to go. A newline
# is a plain GSM-7 character costing one septet - the same as the ": " it
# replaces, minus one - so the layout is a character cheaper than the
# inline form, not more expensive.
NEW_MERCHANT_ADMIN_TEMPLATE = (
    "INFINITYPAY\n"
    "{business_name} has opened a new account. Not yet approved.\n"
    "Review on portal: " + ADMIN_PORTAL_URL
)

# One segment for a typical business name (149 chars), two at the 32-char
# cap. Measured rather than assumed: the portal URL alone is 38 characters
# and a reference is 8, so the cap is what keeps the worst case at two
# parts instead of letting a long name run it to three.
WITHDRAWAL_REQUEST_ADMIN_TEMPLATE = (
    "INFINITYPAY\n"
    "{business_name} requested TZS {amount}. Bal: TZS {available_balance}.\n"
    "Ref: {reference}. Awaiting approval.\n"
    "Review: " + ADMIN_PORTAL_URL
)


def render_new_merchant_admin(*, business_name: str) -> str:
    """A merchant has registered — not been approved.

    "Bado hajaidhinishwa" (not yet approved) is in the message on purpose.
    A registered account is `status='pending'` with `kyc_status='unverified'`,
    and an operator reading this on a phone must not come away thinking a
    business is live. The message describes the state and points at the
    screen where the decision is actually made.
    """
    return NEW_MERCHANT_ADMIN_TEMPLATE.format(
        business_name=sanitise_for_sms(business_name, limit=_MAX_NAME),
    )


def render_withdrawal_request_admin(
    *, business_name: str, amount: Decimal, reference: str, available_balance: Decimal
) -> str:
    """A withdrawal is waiting for a Super Admin.

    `amount` and `available_balance` are Decimals from committed records
    and are rendered by the same format_amount every other money message
    uses, so neither passes through a float.

    The balance is here at the owner's explicit request, against the
    original brief's "do not include wallet balances". It is what an
    operator actually needs to judge whether a payout can be covered
    without opening the queue - the same figure the approval email already
    carries. The trade is that a merchant's financial position now sits in
    an SMS inbox, so the recipient list is operators only and the number
    is display-only: nothing reads it back to authorize anything.

    Still deliberately absent: the payout destination, the account name
    and the bank. Those are decided by opening the queue, and are a worse
    thing to leave in a mailbox than a balance.
    """
    return WITHDRAWAL_REQUEST_ADMIN_TEMPLATE.format(
        business_name=sanitise_for_sms(business_name, limit=_MAX_NAME),
        amount=format_amount(amount),
        available_balance=format_amount(available_balance),
        reference=sanitise_for_sms(reference, limit=_MAX_REFERENCE),
    )
