"""The InfinityPay WhatsApp community invitation, in one place.

The link lives in a single server-side setting
(MERCHANT_COMMUNITY_WHATSAPP_URL) and every template that carries it asks
this module for it. Nothing else reads the setting, and no template holds
a copy of the URL, so changing or withdrawing the invitation is one
environment variable and no deploy.

Where it appears, and only there:

  * the merchant approval welcome - email and SMS
    (app/services/onboarding.py::approve_onboarding_submission)
  * a CONFIRMED successful withdrawal - email and SMS
    (app/services/disbursements.py, both SUCCESS branches)

Never on a pending/failed/unknown withdrawal, a recipient's message, a
developer webhook payload, a Payout API notification, a public checkout
page or the homepage.

**A bad value omits the invitation; it never fails the message.** The
notification it is attached to is transactional - an approval, a payout
confirmation - and is worth far more than the invitation. So this returns
None for anything it does not trust and the caller sends the message
exactly as it was before the invitation existed.

What counts as trusted is deliberately narrow: https, the host
chat.whatsapp.com exactly, no credentials, the default port, a real path,
no whitespace or control characters. A link that only *looks* like
WhatsApp (chat.whatsapp.com.example.net, http://, user@host) is exactly
the kind of thing that ends up in a notification by mistake, and a
merchant tapping a link in a payout confirmation is entitled to assume we
checked it.
"""

import html
import logging
from urllib.parse import urlsplit

from app.config import get_settings

logger = logging.getLogger("infinity.community_invite")

ALLOWED_HOST = "chat.whatsapp.com"

# Long enough for any real invite (they are ~60 characters with their
# tracking parameters), short enough that a pasted paragraph is refused.
_MAX_LENGTH = 200

# English is the language of the emails, Swahili the language of the SMS.
# Each channel keeps its own existing language.
EMAIL_INVITE_TEXT = "Join the InfinityPay WhatsApp community for service updates, support and ideas:"
EMAIL_BUTTON_LABEL = "Join WhatsApp Community"
SMS_INVITE_PREFIX = "Jiunge na jumuiya ya InfinityPay: "


def validate_community_url(raw: str | None) -> str | None:
    """The URL exactly as configured if it is safe to send, else None.

    Returned unmodified - no normalising, no re-encoding - so the link a
    merchant receives is byte-for-byte the one the operator configured,
    query string included.
    """
    value = (raw or "").strip()
    if not value:
        return None
    if len(value) > _MAX_LENGTH:
        return None
    if any(ch.isspace() or not ch.isprintable() for ch in value):
        return None
    try:
        parts = urlsplit(value)
        port = parts.port  # raises ValueError for a non-numeric port
    except ValueError:
        return None
    if parts.scheme != "https":
        return None
    # hostname is lower-cased by urlsplit; netloc is compared too so that
    # "user@chat.whatsapp.com" (credentials) is refused rather than
    # silently accepted on the strength of its hostname.
    if parts.hostname != ALLOWED_HOST or parts.netloc.lower() not in (ALLOWED_HOST, f"{ALLOWED_HOST}:443"):
        return None
    if port not in (None, 443):
        return None
    if parts.path in ("", "/"):
        return None
    return value


def community_invite_url() -> str | None:
    """The configured invitation link, or None if there is none to send.

    Never raises: it is called on paths where money has already moved.
    """
    try:
        raw = get_settings().merchant_community_whatsapp_url
    except Exception:  # noqa: BLE001 — never break the notification
        return None
    url = validate_community_url(raw)
    if raw and raw.strip() and url is None:
        # Configured but refused. Logged without the value itself: it is
        # operator-supplied text and the log line only needs to say where
        # to look.
        logger.warning("community_invite_ignored reason=invalid_url setting=MERCHANT_COMMUNITY_WHATSAPP_URL")
    return url


def email_invite_html(url: str, *, ink: str) -> str:
    """The invitation block for an HTML email.

    The URL is HTML-escaped for the attribute and the visible text, so
    `&` in its query string becomes `&amp;` in the markup - which every
    mail client decodes back to `&`, leaving the destination exactly as
    configured. Unescaped, `&p=i` is still usually tolerated, but `&iam`
    is close enough to a named entity that some parsers would rewrite it.
    """
    safe = html.escape(url, quote=True)
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 0;border-top:1px solid #e5e7eb;">
      <tr>
        <td style="padding:20px 0 0;">
          <p style="margin:0 0 12px;font-size:14px;color:#374151;">{html.escape(EMAIL_INVITE_TEXT)}</p>
          <a href="{safe}" style="display:inline-block;background-color:#ffffff;color:{ink};border:2px solid {ink};font-size:14px;font-weight:600;text-decoration:none;padding:10px 22px;border-radius:8px;">{EMAIL_BUTTON_LABEL}</a>
          <p style="margin:10px 0 0;font-size:12px;color:#6b7280;word-break:break-all;"><a href="{safe}" style="color:{ink};">{safe}</a></p>
        </td>
      </tr>
    </table>
    """


def email_invite_text(url: str) -> str:
    """The same invitation for the plain-text alternative. Not escaped:
    plain text has no entities, and the link must be the real one."""
    return f"{EMAIL_INVITE_TEXT}\n{url}"


def sms_invite_suffix(url: str) -> str:
    """The SMS tail: one sentence, appended once, after everything else.

    Kept to the concise form because every character is paid for. The
    transaction details before it are never shortened to make room - see
    sms_text.py for the segment measurements.

    On its own line: the message before it ends with the support phone
    number, and a space would run the number straight into "Jiunge". A
    newline is one GSM-7 character, exactly what the space cost.
    """
    return "\n" + SMS_INVITE_PREFIX + url
