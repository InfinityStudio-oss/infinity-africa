"""Every webhook event this platform can send.

One list, because there were two and they disagreed.

The merchant portal offers a checkbox per event so a receiver can take
a subset instead of everything. enqueue_webhook_event then drops
anything not in that subset. Those two facts together mean an event
missing from the portal's list is not merely hidden - it is
**unreachable**: there is no box to tick, so a merchant who narrows
their selection can never receive it again.

That had happened to five events, reversals among them. A reversal is
money being taken back, and the one merchant who had narrowed their
selection was silently not being told about any.

The list also carried four events in the other direction - offered in
the portal, emitted by nothing - so ticking them did nothing at all.

--- Keeping it honest

tests/test_webhook_event_names.py pins three things:

  1. every event name emitted anywhere in this codebase is in here
  2. this list and the portal's TypeScript copy are identical
  3. nothing here is emitted by nobody

Point 1 cannot be done by grepping for `event_name="..."` alone, and
that is worth stating plainly because it looks like it would work:
`collection.pending_review` is emitted from a dict in
sandbox_collections.py and a grep for the keyword argument misses it
entirely. A test that greps would have passed while the bug it is
meant to catch was present. The test reads the declared maps too.
"""

from typing import Final

# Collections — money coming in.
COLLECTION_SUCCESS: Final = "collection.success"
COLLECTION_FAILED: Final = "collection.failed"
COLLECTION_REVERSED: Final = "collection.reversed"
COLLECTION_PENDING_REVIEW: Final = "collection.pending_review"

# Disbursements — a merchant withdrawing their own balance.
DISBURSEMENT_SUCCESS: Final = "disbursement.success"
DISBURSEMENT_FAILED: Final = "disbursement.failed"
DISBURSEMENT_REVERSED: Final = "disbursement.reversed"

# Payouts — money sent out through the Disbursement API. A different
# thing from a disbursement, and both are live.
PAYOUT_SUCCESS: Final = "payout.success"
PAYOUT_FAILED: Final = "payout.failed"

# Everything else.
INVOICE_PAID: Final = "invoice.paid"
PAYMENT_LINK_PAID: Final = "payment_link.paid"
PAYMENT_LINK_PAYMENT_REVERSED: Final = "payment_link.payment_reversed"
REFUND_SUCCEEDED: Final = "refund.succeeded"
REFUND_FAILED: Final = "refund.failed"
CHARGEBACK_OPENED: Final = "chargeback.opened"
CHARGEBACK_RESOLVED: Final = "chargeback.resolved"

#: Every event name that can reach a merchant's endpoint. Ordered the
#: way the portal should list them - by what the money did, not
#: alphabetically, because the checkbox list is read by people.
WEBHOOK_EVENT_NAMES: Final[tuple[str, ...]] = (
    COLLECTION_SUCCESS,
    COLLECTION_FAILED,
    COLLECTION_REVERSED,
    COLLECTION_PENDING_REVIEW,
    DISBURSEMENT_SUCCESS,
    DISBURSEMENT_FAILED,
    DISBURSEMENT_REVERSED,
    PAYOUT_SUCCESS,
    PAYOUT_FAILED,
    INVOICE_PAID,
    PAYMENT_LINK_PAID,
    PAYMENT_LINK_PAYMENT_REVERSED,
    REFUND_SUCCEEDED,
    REFUND_FAILED,
    CHARGEBACK_OPENED,
    CHARGEBACK_RESOLVED,
)

KNOWN_WEBHOOK_EVENTS: Final[frozenset[str]] = frozenset(WEBHOOK_EVENT_NAMES)
