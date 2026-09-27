"""Resolve the name behind a withdrawal destination, before it is paid.

The merchant no longer types a recipient name — nothing checked it, so it
confirmed nothing. This asks Selcom instead, through `GET /account/lookup`,
so the review step can show who the money is actually going to.

Three rules, all of them about not making a payout worse:

**It never raises.** A lookup is a courtesy on a confirmation screen. If
Selcom is slow, down, rejects the parameters, or answers in a shape we
don't recognise, the merchant sees "Name not available" — exactly what
they saw before this existed. A withdrawal must never fail because a name
could not be fetched.

**It never trips the payout circuit breaker.** `selcom_outbound`'s breaker
exists to stop hammering a provider that is already failing, and an open
breaker blocks real payouts. `/account/lookup` has never been exercised
against a live Selcom account, so it is exactly the kind of call that
might fail consistently for its own reasons — if those failures counted,
an unusable lookup endpoint would take withdrawals down with it. Failures
are swallowed *inside* the guard, so the guard sees a clean exit. The
concurrency and rate limits still apply, and an already-open breaker still
skips the call, because both of those protect Selcom rather than us.

**It never invents a name.** If no recognised field carries one, the
answer is None. A wrong name on a payout confirmation is worse than no
name, because it reads as though the destination was verified.

The response field names are the one unverified part of this: Selcom's
docs show the request for `/account/lookup` but no example response, and
no lookup has been round-tripped yet. `parse_account_name` tries the
shapes Selcom uses elsewhere; when none match, the response's *keys* are
logged so the real field can be read off the first live call — the same
way the Selcom Checkout webhook's real header casing was learned.
"""

import logging

from app.services.selcom.outbound_guard import selcom_outbound
from app.services.selcom_business.client import get_selcom_business_client
from app.services.selcom_business.live_client import generate_trans_id
from app.services.selcom_business.parsing import (
    account_lookup_succeeded,
    parse_account_name,
    unrecognised_lookup_shape,
)

logger = logging.getLogger("infinity.recipient_lookup")


async def resolve_recipient_name(
    *, destination_code: str, destination_identifier: str, amount: str | None = None
) -> str | None:
    """The account holder's name, or None if it could not be established.

    None is a normal answer, not an error: an account that does not exist,
    a channel Selcom does not support lookups for, and a provider outage
    all land here, and the merchant is told the same thing in each case.
    """
    if not destination_code or not destination_identifier:
        return None

    try:
        client = get_selcom_business_client()
    except Exception:  # noqa: BLE001 - a lookup must never raise; see module docstring
        # Not configured (no credentials in this environment). Nothing to
        # log loudly about — it is the expected state outside production.
        logger.debug("recipient lookup skipped: selcom business client unavailable")
        return None

    try:
        async with selcom_outbound():
            # Swallowed INSIDE the guard on purpose: see the module
            # docstring. A failure here must not count toward the breaker
            # that gates real payouts.
            try:
                response = await client.account_lookup(
                    recipient_fi_code=destination_code,
                    recipient_account=destination_identifier,
                    trans_id=generate_trans_id(),
                    amount=amount,
                )
            except Exception as exc:  # noqa: BLE001 - swallowed inside the guard on purpose
                logger.info(
                    "recipient lookup failed destination_code=%s error=%s",
                    destination_code,
                    type(exc).__name__,
                )
                return None
    except Exception:  # noqa: BLE001 - an open breaker is not an error here
        # Raised by the guard itself — an open breaker, or a cancelled
        # wait. Same outcome for the merchant.
        logger.info("recipient lookup skipped destination_code=%s", destination_code)
        return None

    name = parse_account_name(response)
    if name:
        return name

    # No recognised name field. If the lookup itself reported success, the
    # response shape is the thing we do not understand yet — record its
    # keys (never its values) so the real field name can be read off a
    # live call instead of guessed at again.
    if account_lookup_succeeded(response):
        logger.warning(
            "recipient lookup succeeded but carried no recognised name field "
            "destination_code=%s response_keys=%s",
            destination_code,
            unrecognised_lookup_shape(response),
        )
    return None
