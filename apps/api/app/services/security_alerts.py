"""Email alerts for security-significant platform events.

Separate from the audit trail, and deliberately narrower than it.
`audit_logs` is the complete record — every admin action lands there and it
is the thing to query after the fact. This module is the subset worth
*interrupting someone* for: money approved, a merchant admitted, pricing
changed, or a sign that someone is trying to get in.

Two rules shape everything here.

**An alert must never break the thing it is reporting.** Every function
swallows its own failures. A withdrawal that was approved has been
approved; a failed notification about it must not turn that into an error
the admin sees, and must certainly not roll anything back.

**An alert must stay worth reading.** Anything that can fire repeatedly —
a blocked admin retrying, a rejected IP hammering an endpoint — is
deduplicated, because an inbox with sixty identical alerts is one nobody
reads, which is the same as having no alerts at all. Money events are never
deduplicated: each one is a distinct decision about real funds.
"""

import logging
import time
import uuid
from collections import OrderedDict
from decimal import Decimal
from threading import Lock
from typing import Any

from supabase import Client

from app.config import get_settings
from app.core.errors import EmailDeliveryError
from app.core.monitoring import capture_exception
from app.services.email import _email_shell, _log_delivery, _mask_identifier, send_email

logger = logging.getLogger("infinity.security_alerts")


class _AlertDeduper:
    """Suppresses repeats of the same alert within a window.

    In-memory and per-process, the same trade app/core/rate_limit.py already
    makes and documents: correct for this single-replica deployment, and
    only ever *over*-sends if that changes, which is the safe direction for
    a security alert. A restart clears it, so a deploy can let one extra
    alert through — also the safe direction.
    """

    # Bounded so a flood of distinct keys cannot grow this without limit.
    _MAX_KEYS = 2048

    def __init__(self) -> None:
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._lock = Lock()

    def should_send(self, key: str, *, window_seconds: float) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._seen.get(key)
            if last is not None and now - last < window_seconds:
                return False
            self._seen[key] = now
            self._seen.move_to_end(key)
            while len(self._seen) > self._MAX_KEYS:
                self._seen.popitem(last=False)
            return True


_deduper = _AlertDeduper()


def _recipients() -> list[str]:
    """SECURITY_ALERT_EMAIL, falling back to the CEO_EMAIL recipients.

    The fallback exists so turning alerts on does not require a second
    address to be configured first — CEO_EMAIL is already the platform's
    internal-notification address. An empty list means "not configured",
    which every caller treats as "do nothing".

    **Comma-separated, like CEO_EMAIL.** It used to be a single string
    handed straight to send_email, so configuring two addresses the
    obvious way (``a@x,b@x``) produced one malformed recipient and Resend
    rejected the send — turning the alerts off while looking configured,
    which is the worst of the three possible states.

    The fallback also used to take only ``ceo_emails[0]``, so a second
    Super Admin added to CEO_EMAIL silently did not receive security
    alerts even though they received everything else. Both addresses was
    a deliberate decision for CEO email; there was no reason for these to
    disagree with it.
    """
    settings = get_settings()
    raw = (settings.security_alert_email or "").strip()
    if not raw:
        return list(settings.ceo_emails)

    seen: list[str] = []
    for part in raw.split(","):
        address = part.strip()
        if address and address not in seen:
            seen.append(address)
    return seen


def mask_phone(value: str | None) -> str:
    """Last 4 only — enough to recognise a destination in an alert, not
    enough to be a leak if the mailbox is ever compromised."""
    return _mask_identifier(value or "") if value else "—"


def _row(label: str, value: str) -> str:
    return (
        f'<tr><td style="padding:6px 12px 6px 0;font-size:13px;color:#6b7280;'
        f'white-space:nowrap;vertical-align:top;">{label}</td>'
        f'<td style="padding:6px 0;font-size:13px;color:#1f2937;">{value}</td></tr>'
    )


def notify_security_event(
    client: Client,
    *,
    event: str,
    title: str,
    actor_email: str | None = None,
    actor_id: uuid.UUID | str | None = None,
    merchant_name: str | None = None,
    amount: Decimal | str | None = None,
    currency: str = "TZS",
    destination: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    extra: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> bool:
    """Email one security alert. Returns True if a message was sent.

    Never raises. `dedupe_key` should be set for anything a single actor can
    trigger repeatedly (failed MFA, rejected IPs); leave it None for
    one-off decisions like approving a withdrawal, where every occurrence
    deserves its own email.

    `destination` is masked here rather than by callers, so no call site can
    forget. Never pass a code, token, secret or full account number in
    `extra` — it is rendered verbatim.
    """
    settings = get_settings()
    try:
        if not settings.security_alerts_enabled:
            return False

        recipients = _recipients()
        if not recipients:
            # Nothing configured. Deliberately silent rather than noisy —
            # the audit log still has the event.
            return False

        if dedupe_key is not None and not _deduper.should_send(
            f"{event}:{dedupe_key}", window_seconds=settings.security_alert_dedupe_window_seconds
        ):
            logger.info("security_alert_deduped event=%s", event)
            return False

        rows = [_row("Event", event)]
        if actor_email:
            rows.append(_row("Actor", actor_email))
        elif actor_id:
            rows.append(_row("Actor", str(actor_id)))
        if merchant_name:
            rows.append(_row("Business", merchant_name))
        if amount is not None:
            rows.append(_row("Amount", f"{currency} {Decimal(str(amount)):,.2f}"))
        if destination:
            rows.append(_row("Destination", mask_phone(destination)))
        if ip_address:
            rows.append(_row("IP address", ip_address))
        if user_agent:
            rows.append(_row("User agent", user_agent[:120]))
        for key, value in (extra or {}).items():
            rows.append(_row(key, str(value)))

        subject = f"InfinityPay Security Alert: {title}"
        body = f"""
    <h1 style="margin:0 0 16px;font-size:20px;color:#1f2937;">{title}</h1>
    <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;margin:0 0 20px;">
      {"".join(rows)}
    </table>
    <p style="margin:0;font-size:13px;color:#6b7280;">Review the full record in Super Admin &rarr; Audit Logs.
    This is an automated notification; no action is needed if you recognise this activity.</p>
    """

        try:
            message_id = send_email(
                to=recipients,
                subject=subject,
                html=_email_shell(body_html=body),
                sender=settings.email_from,
                reply_to=settings.email_reply_to,
            )
        except EmailDeliveryError as exc:
            _safe_log_delivery(client, recipients, subject, status="failed", error=str(exc))
            logger.warning("security_alert_send_failed event=%s", event)
            return False

        _safe_log_delivery(client, recipients, subject, status="sent", message_id=message_id)
        return True
    except Exception as exc:
        logger.exception("security_alert_unexpected_failure event=%s", event)
        # Still alerts. If security alert emails are failing, every other
        # alert this platform leans on is going unseen too.
        capture_exception(exc)
        return False


def _safe_log_delivery(
    client: Client,
    recipients: list[str],
    subject: str,
    *,
    status: str,
    message_id: str | None = None,
    error: str | None = None,
) -> None:
    try:
        _log_delivery(
            client,
            merchant_id=None,
            email_type="security_alert",
            related_resource_type=None,
            related_resource_id=None,
            # One delivery row per send, so several recipients are joined
            # rather than logged as separate sends — Resend sent one
            # message, and the log should say so.
            recipient_email=", ".join(recipients),
            sender_email=get_settings().email_from,
            subject=subject,
            status=status,
            provider_message_id=message_id,
            error_message=error,
        )
    except Exception:  # noqa: BLE001, S110 — logging the log must not fail either
        pass


def should_alert_once(key: str, *, window_seconds: float) -> bool:
    """True the first time `key` is seen in the window, False after.

    The same suppression `notify_security_event` applies to its own emails,
    exposed for alerts that do not go through it - Sentry captures, in
    particular.

    Added for webhook-delivery exhaustion. One merchant's endpoint erroring
    0.5% of the time produced roughly eighteen separate "merchant will not
    receive this event" alerts a day, all describing the same ongoing
    condition. Eighteen mails a day about a known problem is how a real one
    gets missed, so the condition is reported once per merchant per window
    while every individual event is still logged and still recorded on the
    row itself.
    """
    return _deduper.should_send(key, window_seconds=window_seconds)
