"""How many payment prompts one customer may be sent, per merchant.

The case this exists for, from production on 2026-10-12: a single
customer on MAXTON'S WIFI was sent **52 payment prompts in two hours**,
all for TZS 500, all of which expired without being completed. Selcom
reported "Wallet push successful" every time — the prompt was delivered
and simply never answered.

Nobody was served by any of it. The customer got fifty-two dead prompts
and no WiFi; the merchant got fifty-two failed collections on their
dashboard; the platform spent fifty-two provider calls. Whatever was
wrong — an empty wallet, a handset not showing the prompt, a PIN entered
after the USSD session had already closed on the phone — the fifty-second
attempt was never going to work for the same reason the second one did
not.

So this stops the loop and says something useful instead. The limit is
deliberately generous: a customer whose first attempt fails and who
retries immediately is a normal customer, not a loop, and must not be
blocked.

**Keyed on merchant + phone, not on IP.** These pushes arrive from a
partner's server, so every customer shares one address — an IP limit
would throttle a busy ISP's entire customer base the moment one person
retried. app/routers/collections_api.py's `_enforce_caller_create_limit`
already covers the per-caller dimension; this is the per-customer one.

The phone never becomes a readable bucket name: enforce_rate_limit
hashes the key before use.
"""

import uuid

from app.config import get_settings
from app.core.rate_limit import enforce_rate_limit

# What the customer is told. Names the two things they can actually act
# on, because "too many requests" tells someone retrying in good faith
# nothing at all.
THROTTLED_MESSAGE = (
    "You've been sent several payment prompts that weren't completed. "
    "Please check your mobile money balance and that you can accept the prompt, "
    "then try again in a few minutes."
)


def assert_customer_push_allowed(
    *, merchant_id: uuid.UUID | str, customer_phone: str | None
) -> None:
    """Raises RateLimitExceededError (429) if this customer has already
    been sent too many prompts by this merchant recently.

    Does nothing when no phone is known — a QR scan or a hosted checkout
    page has no destination number yet, and there is no customer to
    throttle.

    Called from the push paths beside assert_amount_allowed, which is the
    other check that exists to stop a payment that cannot succeed before
    anything is created for it.
    """
    if not customer_phone:
        return

    settings = get_settings()
    limit = settings.collection_push_per_customer_limit
    if limit <= 0:
        return

    enforce_rate_limit(
        scope="collection_push_per_customer",
        key=f"{merchant_id}:{customer_phone}",
        limit=limit,
        window_seconds=settings.collection_push_per_customer_window_seconds,
        message=THROTTLED_MESSAGE,
    )
