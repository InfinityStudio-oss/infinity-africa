"""Normalized failure reasons for collections.

`collections.failure_reason` has always been free text, and some paths put
the provider's own `message` straight into it — which then reaches the
merchant ledger, the public payment page and the outbound webhook. That is
two problems in one: a partner cannot branch on prose that changes
whenever the provider reweords it, and provider text is not ours to
forward verbatim.

This maps what the provider actually tells us onto a small, stable set of
codes a partner can switch on, plus a sentence safe to show a merchant.

**Only mappings the codebase can evidence are asserted.** Selcom's
confirmed terminal `payment_status` vocabulary is CANCELLED,
USERCANCELLED, REJECTED and REVERSED (see
app/services/checkout_reconciliation.py, where those values already drive
the internal status decision). Everything else resolves to
`provider_declined` or `unknown_provider_error`.

Deliberately NOT claimed: `insufficient_balance`, `wrong_pin` and
`timeout` are defined in the vocabulary because a partner should be able
to handle them the day Selcom starts distinguishing them, but nothing
currently maps to them — no confirmed provider code for those cases
exists in this codebase, and inventing a mapping would mean telling a
merchant "wrong PIN" for a payment that actually failed for another
reason. When a real response proves the code, add it here and the rest of
the stack picks it up with no other change.
"""

from typing import Final

# The stable vocabulary a partner may switch on. Adding to this is safe;
# renaming one is a breaking API change.
INSUFFICIENT_BALANCE: Final = "insufficient_balance"
WRONG_PIN: Final = "wrong_pin"
USER_CANCELLED: Final = "user_cancelled"
TIMEOUT: Final = "timeout"
PROVIDER_UNAVAILABLE: Final = "provider_unavailable"
PROVIDER_DECLINED: Final = "provider_declined"
EXPIRED: Final = "expired"
REVERSED: Final = "reversed"
UNKNOWN: Final = "unknown_provider_error"

# Merchant-facing sentence per code. Plain language, no provider naming,
# nothing actionable-sounding that the merchant cannot actually act on.
_MESSAGES: Final[dict[str, str]] = {
    INSUFFICIENT_BALANCE: "The customer does not have enough balance.",
    WRONG_PIN: "Wrong PIN or authorization failed.",
    USER_CANCELLED: "The customer cancelled the payment.",
    TIMEOUT: "The payment authorization timed out.",
    PROVIDER_UNAVAILABLE: "The payment provider was unavailable. Ask the customer to try again.",
    PROVIDER_DECLINED: "The payment was declined.",
    EXPIRED: "The payment request expired before it was approved.",
    REVERSED: "The payment was reversed after it completed.",
    UNKNOWN: "The payment could not be completed.",
}

# Confirmed terminal payment_status values — the same set
# checkout_reconciliation.py already treats as terminal failures.
_BY_PAYMENT_STATUS: Final[dict[str, str]] = {
    "USERCANCELLED": USER_CANCELLED,
    "CANCELLED": USER_CANCELLED,
    "REJECTED": PROVIDER_DECLINED,
    "REVERSED": REVERSED,
    "EXPIRED": EXPIRED,
}


def normalize_failure_reason(
    *,
    payment_status: str | None = None,
    resultcode: str | None = None,
    internal_reason: str | None = None,
) -> tuple[str, str]:
    """Returns (reason_code, merchant_safe_message).

    `internal_reason` is for failures this platform decided itself — a
    provider call that never got off the ground, for instance — where
    there is no provider status to read.

    Always returns a usable pair. An unrecognised provider response is
    `unknown_provider_error`, never the provider's own text: that text can
    change without notice and is not ours to forward.
    """
    status_key = (payment_status or "").strip().upper()
    if status_key in _BY_PAYMENT_STATUS:
        code = _BY_PAYMENT_STATUS[status_key]
        return code, _MESSAGES[code]

    if internal_reason:
        key = internal_reason.strip().lower()
        if key in _MESSAGES:
            return key, _MESSAGES[key]
        # An internal free-text reason predates this mapping. Treated as
        # unknown rather than passed through, so the code field stays a
        # closed set a partner can switch on.
        return UNKNOWN, _MESSAGES[UNKNOWN]

    # A resultcode with no recognised payment_status means the provider
    # answered but not in a shape that identifies the cause.
    if resultcode:
        return PROVIDER_DECLINED, _MESSAGES[PROVIDER_DECLINED]

    return UNKNOWN, _MESSAGES[UNKNOWN]


def message_for(reason_code: str | None) -> str:
    """The merchant-facing sentence for a stored code."""
    return _MESSAGES.get((reason_code or "").strip().lower(), _MESSAGES[UNKNOWN])


def all_reason_codes() -> list[str]:
    """Every code a partner may receive — the list the API docs publish."""
    return sorted(_MESSAGES)
