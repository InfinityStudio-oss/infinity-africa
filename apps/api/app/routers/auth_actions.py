"""Account-level actions that need to run server-side rather than calling
Supabase directly from the browser — currently just forgot-password. Public
(unauthenticated) by nature: the caller doesn't have a session yet.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import get_settings
from app.core.rate_limit import enforce_rate_limit, rate_limit
from app.database.session import get_supabase_admin
from app.schemas.auth import ForgotPasswordRequest
from app.schemas.common import APIResponse
from app.services.email import send_password_reset_email

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
