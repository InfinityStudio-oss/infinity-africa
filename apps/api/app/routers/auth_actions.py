"""Account-level actions that need to run server-side rather than calling
Supabase directly from the browser — forgot-password and resending an
email verification. Public (unauthenticated) by nature: the caller
doesn't have a session yet.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import get_settings
from app.core.rate_limit import enforce_rate_limit, rate_limit
from app.database.session import get_supabase_admin
from app.schemas.auth import ForgotPasswordRequest, ResendVerificationRequest
from app.schemas.common import APIResponse
from app.services.email import send_password_reset_email, send_verification_resend

router = APIRouter(prefix="/auth", tags=["auth"])

# The one message this endpoint ever returns, regardless of whether the
# email matched a real account, whether a Supabase Auth error occurred, or
# whether Resend rejected the send — account enumeration prevention only
# works if every outcome looks identical from the outside.
_GENERIC_MESSAGE = "If an account exists, we've sent password reset instructions."


@router.post("/forgot-password", response_model=APIResponse[dict])
def forgot_password(
    payload: ForgotPasswordRequest,
    _rate_limit: Annotated[None, Depends(rate_limit(scope="forgot_password", limit=5, window_seconds=60))],
):
    """Never raises, never returns a different message for a registered
    vs. unregistered email — send_password_reset_email already swallows
    every failure internally (missing account, Supabase error, Resend
    error) and returns None either way; this endpoint doesn't even look at
    what it returned."""
    # Per-IP is handled by the dependency above. This adds the second
    # dimension: one address cannot be targeted from many IPs, which is
    # what per-IP alone allows. Raised BEFORE any lookup, and the 429 is
    # identical whether or not the address exists -- the whole endpoint
    # is built so the response never distinguishes the two.
    enforce_rate_limit(
        scope="forgot_password_email", key=payload.email, limit=3, window_seconds=900
    )

    client = get_supabase_admin()
    settings = get_settings()
    send_password_reset_email(client, email=payload.email, redirect_to=f"{settings.app_url}{payload.redirect_path}")
    return APIResponse(data={"message": _GENERIC_MESSAGE})


# Same shape as the message above, for the same reason. It deliberately
# does not say whether the address is registered, or whether it still
# needs verifying.
_GENERIC_VERIFICATION_MESSAGE = (
    "If that account still needs verification, we've sent a fresh link. "
    "Check your inbox and spam folder."
)


@router.post("/resend-verification", response_model=APIResponse[dict])
def resend_verification(
    payload: ResendVerificationRequest,
    _rate_limit: Annotated[
        None, Depends(rate_limit(scope="resend_verification", limit=5, window_seconds=60))
    ],
):
    """A merchant who never received the signup link has, until now, had
    no way to ask for another one once they closed the tab.

    The only offer was the "Resend verification email" button on the
    screen that appears immediately after signing up, which is gone as
    soon as that page is. What people did instead was register again
    under a slightly different address - five businesses in production
    did exactly that, which is where the duplicate merchant records came
    from - and since signup started refusing duplicates, that escape
    hatch is closed too. Two accounts reached 26 October 2026 with no way
    in at all.

    Like forgot-password, this never raises and never returns a different
    message for a registered, unregistered or already-verified address:
    send_verification_resend swallows every outcome and returns None
    either way, and this endpoint does not look at what it returned.
    """
    # Per-IP above; per-address here, so one merchant's inbox cannot be
    # filled from a thousand IPs. Raised before any lookup, and the 429 is
    # identical whether or not the address exists.
    enforce_rate_limit(
        scope="resend_verification_email", key=payload.email, limit=3, window_seconds=900
    )

    client = get_supabase_admin()
    settings = get_settings()
    # Fixed, not caller-supplied: an unverified merchant is always headed
    # for onboarding. /auth/callback is the route that reads the token out
    # of the query string - see apps/web/src/app/auth/callback/route.ts.
    send_verification_resend(
        client, email=payload.email, redirect_to=f"{settings.app_url}/auth/callback?next=/onboarding"
    )
    return APIResponse(data={"message": _GENERIC_VERIFICATION_MESSAGE})
