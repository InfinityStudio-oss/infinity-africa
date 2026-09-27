"""Normalized collection failure reasons.

`collections.failure_reason` is free text and several paths wrote the
provider's own `message` into it — text that reaches the merchant ledger,
the public payment page and the outbound webhook. A partner cannot branch
on prose that changes when the provider rewords it, and that prose is not
ours to forward.

The important property here is restraint: only mappings this codebase can
evidence are asserted. `insufficient_balance`, `wrong_pin` and `timeout`
exist in the vocabulary so a partner can handle them the day Selcom
distinguishes them, but nothing maps to them yet — inventing a mapping
would mean telling a merchant "wrong PIN" about a payment that failed for
some other reason.
"""

import pytest

from app.services.failure_reasons import (
    EXPIRED,
    INSUFFICIENT_BALANCE,
    PROVIDER_DECLINED,
    REVERSED,
    TIMEOUT,
    UNKNOWN,
    USER_CANCELLED,
    WRONG_PIN,
    all_reason_codes,
    message_for,
    normalize_failure_reason,
)

# --- the mappings that are actually evidenced -------------------------------


@pytest.mark.parametrize(
    "payment_status,expected",
    [
        ("USERCANCELLED", USER_CANCELLED),
        ("CANCELLED", USER_CANCELLED),
        ("REJECTED", PROVIDER_DECLINED),
        ("REVERSED", REVERSED),
        ("EXPIRED", EXPIRED),
    ],
)
def test_a_confirmed_provider_status_maps_to_its_code(payment_status, expected):
    """These are the terminal payment_status values
    checkout_reconciliation.py already treats as failures — the only ones
    the provider is known to send."""
    code, _message = normalize_failure_reason(payment_status=payment_status)

    assert code == expected


@pytest.mark.parametrize("payment_status", ["usercancelled", "UserCancelled", " REJECTED "])
def test_provider_status_matching_ignores_case_and_padding(payment_status):
    code, _message = normalize_failure_reason(payment_status=payment_status)

    assert code in {USER_CANCELLED, PROVIDER_DECLINED}


def test_every_code_has_a_merchant_facing_sentence():
    for code in all_reason_codes():
        assert message_for(code)
        assert not message_for(code).endswith("None")


# --- restraint: nothing is claimed that cannot be evidenced -----------------


@pytest.mark.parametrize("unmapped", [INSUFFICIENT_BALANCE, WRONG_PIN, TIMEOUT])
def test_the_unevidenced_codes_are_defined_but_nothing_maps_to_them(unmapped):
    """They exist so a partner can write a handler today, and so adding the
    mapping later is a one-line change. Nothing should reach them until a
    real provider response proves the code."""
    assert message_for(unmapped)

    reached = any(
        normalize_failure_reason(payment_status=status)[0] == unmapped
        for status in ["USERCANCELLED", "CANCELLED", "REJECTED", "REVERSED", "EXPIRED", "FAILED", ""]
    )
    assert not reached, f"{unmapped} was inferred from a provider status that does not prove it"


def test_an_unrecognised_provider_status_is_unknown_not_a_guess():
    code, message = normalize_failure_reason(payment_status="SOMETHING_NEW")

    assert code == UNKNOWN
    assert message == "The payment could not be completed."


def test_the_providers_own_text_is_never_returned_as_the_message():
    """The whole point: provider prose must not reach a merchant."""
    code, message = normalize_failure_reason(
        internal_reason="Selcom payment_status=WEIRD_INTERNAL_DETAIL"
    )

    assert code == UNKNOWN
    assert "Selcom" not in message
    assert "WEIRD_INTERNAL_DETAIL" not in message


def test_a_resultcode_with_no_status_is_a_decline_not_unknown():
    """The provider answered, just not in a shape that names the cause."""
    code, _message = normalize_failure_reason(resultcode="123")

    assert code == PROVIDER_DECLINED


def test_no_signal_at_all_is_unknown():
    assert normalize_failure_reason()[0] == UNKNOWN


def test_an_internal_reason_matching_a_known_code_is_honoured():
    code, message = normalize_failure_reason(internal_reason="provider_unavailable")

    assert code == "provider_unavailable"
    assert "try again" in message.lower()


def test_a_confirmed_status_wins_over_an_internal_reason():
    """What the provider said beats what we guessed locally."""
    code, _message = normalize_failure_reason(
        payment_status="USERCANCELLED", internal_reason="provider_unavailable"
    )

    assert code == USER_CANCELLED


def test_message_for_an_unknown_code_falls_back_rather_than_raising():
    assert message_for("not_a_real_code") == message_for(UNKNOWN)
    assert message_for(None) == message_for(UNKNOWN)


def test_no_message_names_the_provider():
    """A merchant should never read "Selcom" in a failure reason — who we
    route through is not their integration detail."""
    for code in all_reason_codes():
        assert "selcom" not in message_for(code).lower()
