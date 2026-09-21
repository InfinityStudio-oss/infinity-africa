"""Transactional email via Resend. RESEND_API_KEY is backend/Railway-only
— apps/web never reads it (nothing in apps/web ever imports this module or
its config). See docs/email-delivery.md.

Every send — success or failure — is logged to email_deliveries
(app/routers/*.py never writes that table directly). send_email() itself
never swallows a failure: it always raises EmailDeliveryError. Individual
send_*_email() functions below decide for themselves whether that should
propagate (invite, invoice — the parent action shouldn't claim success if
the email never went out) or be swallowed (receipt, welcome, inquiry,
password reset — a courtesy/notification email must never break the real
operation it's attached to, and password reset specifically must never
let a caller distinguish "no such account" from "email provider down").
"""

import logging
import uuid
from decimal import Decimal
from typing import Any

import resend
from supabase import Client

from app.config import get_settings
from app.core.errors import EmailDeliveryError
from app.services.crud import execute_maybe_single, insert_row
from app.services.merchant_notifications import get_notification_settings
from app.services.payment_links import build_public_url

logger = logging.getLogger("infinity.email")


def send_email(*, to: str, subject: str, html: str, sender: str, reply_to: str | None = None) -> str:
    """Sends one email through Resend. Returns the provider's message id
    (empty string if Resend didn't return one). Raises EmailDeliveryError
    on any failure — a missing API key, a rejected send, or the request
    itself failing outright. Never logs the API key; the raw exception is
    logged server-side only (not included in the message raised, which is
    safe to surface to a merchant)."""
    settings = get_settings()
    if not settings.resend_api_key:
        raise EmailDeliveryError("Email delivery is not configured yet.")

    resend.api_key = settings.resend_api_key
    params: dict[str, Any] = {"from": sender, "to": [to], "subject": subject, "html": html}
    if reply_to:
        params["reply_to"] = reply_to

    try:
        result = resend.Emails.send(params)
    except Exception:
        logger.exception("Resend send failed (to=%s, subject=%s)", to, subject)
        raise EmailDeliveryError("Couldn't send the email — the email provider rejected the request.") from None

    if isinstance(result, dict):
        return result.get("id") or ""
    return getattr(result, "id", "") or ""


def _log_delivery(
    client: Client,
    *,
    merchant_id: str | None,
    email_type: str,
    related_resource_type: str | None,
    related_resource_id: str | None,
    recipient_email: str,
    sender_email: str,
    subject: str,
    status: str,
    provider_message_id: str | None = None,
    error_message: str | None = None,
) -> dict:
    """Writes one email_deliveries row. Never passed a token, link, or any
    other secret — only metadata safe for Super Admin review. Callers must
    never put a raw invite/reset link or token into `subject` or any other
    argument here."""
    return insert_row(
        client,
        "email_deliveries",
        {
            "merchant_id": merchant_id,
            "email_type": email_type,
            "related_resource_type": related_resource_type,
            "related_resource_id": related_resource_id,
            "recipient_email": recipient_email,
            "sender_email": sender_email,
            "subject": subject,
            "provider": "resend",
            "provider_message_id": provider_message_id,
            "status": status,
            "error_message": error_message,
        },
    )


def batch_latest_email_deliveries(
    client: Client, *, related_resource_type: str, related_resource_ids: set[str], email_type: str | None = None
) -> dict[str, dict]:
    """resource_id -> its most recent email_deliveries row — for Super
    Admin list views that show delivery status alongside the resource
    (e.g. an invoice's Sent column). A resource can have more than one
    delivery attempt (retries after a failure); only the latest matters
    for a summary view.

    `email_type` narrows to one email type — needed wherever a single
    resource can have more than one *kind* of email attached to it (e.g. a
    disbursement gets both "withdrawal_request_notification" and
    "withdrawal_success"): without it, "latest across all types" could
    quietly show the wrong email's status. Every existing caller (invoices,
    one email type per invoice) is unaffected by this being optional."""
    if not related_resource_ids:
        return {}
    query = (
        client.table("email_deliveries")
        .select("*")
        .eq("related_resource_type", related_resource_type)
        .in_("related_resource_id", list(related_resource_ids))
    )
    if email_type is not None:
        query = query.eq("email_type", email_type)
    rows = query.order("created_at", desc=True).execute().data or []
    latest: dict[str, dict] = {}
    for row in rows:
        resource_id = row["related_resource_id"]
        if resource_id not in latest:
            latest[resource_id] = row
    return latest


def _money(value: object, currency: str) -> str:
    amount = Decimal(str(value))
    return f"{currency} {amount:,.2f}"


def _mask_identifier(value: str) -> str:
    """•••• 1234 — same convention as apps/web's maskAccountIdentifier
    (lib/format.ts), so a withdrawal destination looks the same whether a
    merchant sees it in the portal or the CEO sees it in an email. Never
    used for anything that needs to stay fully hidden (this still reveals
    the last 4 digits) — just enough to identify an account without
    emailing the full number."""
    value = value.strip()
    if len(value) <= 4:
        return value
    return f"•••• {value[-4:]}"


# --- shared branded template shell ------------------------------------------


def _email_shell(*, body_html: str) -> str:
    """Wraps `body_html` in the InfinityPay branded header/footer
    every transactional email shares — dark green header band (∞ mark +
    wordmark), white content area, light-gray footer with a help-contact
    line and "Powered by InfinityPay". Table-based HTML with inline
    styles throughout — the only layout approach that renders consistently
    across real email clients (Gmail, Outlook, Apple Mail strip <style>
    blocks and most CSS unless it's inline). The header band sets both the
    CSS background-color AND the legacy bgcolor HTML attribute — Outlook
    desktop's Word-based rendering engine ignores CSS background-color on
    table cells entirely. Never references the Material Symbols icon font
    used elsewhere in the app (unsupported in email); the ∞ mark is a
    plain Unicode character so it always renders."""
    settings = get_settings()
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background-color:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f5;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background-color:#ffffff;border-radius:12px;overflow:hidden;">
            <tr>
              <td bgcolor="#04332a" style="background-color:#04332a;padding:24px 28px;">
                <span style="font-size:20px;color:#9cf5c1;vertical-align:middle;">&#8734;</span>
                <span style="font-size:18px;font-weight:700;color:#ffffff;vertical-align:middle;margin-left:6px;">InfinityPay</span>
              </td>
            </tr>
            <tr>
              <td style="padding:28px;">
                {body_html}
                <p style="margin:28px 0 0;font-size:13px;color:#6b7280;">Need help? Reach us at <a href="mailto:{settings.email_reply_to}" style="color:#04332a;">{settings.email_reply_to}</a>.</p>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 28px;background-color:#f9fafb;text-align:center;">
                <p style="margin:0;font-size:12px;color:#9ca3af;">Powered by InfinityPay</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def _cta_button(url: str, label: str) -> str:
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0 8px;">
      <tr>
        <td align="center">
          <a href="{url}" style="display:inline-block;background-color:#04332a;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;padding:14px 32px;border-radius:8px;">{label}</a>
        </td>
      </tr>
    </table>
    <p style="margin:8px 0 0;font-size:12px;color:#9ca3af;text-align:center;word-break:break-all;">Or copy this link: <a href="{url}" style="color:#04332a;">{url}</a></p>
    """


# --- 1. Invoice payment request (existing) ----------------------------------


def _render_invoice_email_html(*, merchant: dict, invoice: dict, items: list[dict], payment_url: str) -> str:
    business_name = merchant.get("business_name") or "Your merchant"
    customer_name = invoice.get("customer_name") or "Customer"
    currency = invoice.get("currency") or "TZS"
    total_amount = invoice.get("total_amount")
    due_date = invoice.get("due_date")
    notes = invoice.get("notes")

    item_rows = "".join(
        f"""
        <tr>
          <td style="padding:10px 0;border-bottom:1px solid #e5e7eb;font-size:14px;color:#1f2937;">{item.get("description", "")}</td>
          <td style="padding:10px 0;border-bottom:1px solid #e5e7eb;font-size:14px;color:#6b7280;text-align:center;">{item.get("quantity", "")}</td>
          <td style="padding:10px 0;border-bottom:1px solid #e5e7eb;font-size:14px;color:#1f2937;text-align:right;">{_money(item.get("unit_price", 0), currency)}</td>
        </tr>"""
        for item in items
    )
    items_table = (
        f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;">
          <tr>
            <th style="text-align:left;font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;padding-bottom:8px;border-bottom:2px solid #04332a;">Description</th>
            <th style="text-align:center;font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;padding-bottom:8px;border-bottom:2px solid #04332a;">Qty</th>
            <th style="text-align:right;font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;padding-bottom:8px;border-bottom:2px solid #04332a;">Unit Price</th>
          </tr>
          {item_rows}
        </table>"""
        if items
        else ""
    )
    due_date_row = (
        f"""
        <tr>
          <td style="padding:6px 0;font-size:14px;color:#6b7280;">Due date</td>
          <td style="padding:6px 0;font-size:14px;color:#1f2937;text-align:right;">{due_date}</td>
        </tr>"""
        if due_date
        else ""
    )
    notes_block = f"""<p style="margin:16px 0 0;font-size:13px;color:#6b7280;">{notes}</p>""" if notes else ""

    body = f"""
    <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">Payment Request</p>
    <h1 style="margin:0 0 20px;font-size:20px;color:#1f2937;">Invoice {invoice.get("invoice_number", "")} from {business_name}</h1>
    <p style="margin:0 0 20px;font-size:14px;color:#374151;">Hi {customer_name},</p>
    <p style="margin:0 0 20px;font-size:14px;color:#374151;">{business_name} has sent you an invoice via InfinityPay. You can review the details below and pay securely online.</p>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;border-radius:8px;padding:16px;margin:0 0 8px;">
      <tr>
        <td style="padding:6px 16px;font-size:14px;color:#6b7280;">Amount due</td>
        <td style="padding:6px 16px;font-size:20px;font-weight:700;color:#04332a;text-align:right;">{_money(total_amount, currency)}</td>
      </tr>
      {due_date_row}
    </table>
    {items_table}
    {notes_block}
    {_cta_button(payment_url, "Pay Now")}
    <p style="margin:16px 0 0;font-size:13px;color:#6b7280;">Questions about this invoice? Contact {business_name} directly.</p>
    """
    return _email_shell(body_html=body)


def send_invoice_email(
    client: Client, *, merchant: dict, invoice: dict, items: list[dict], payment_url: str
) -> dict:
    """Sends the invoice payment-request email and always records an
    email_deliveries row, success or failure. Raises EmailDeliveryError
    (after logging the failure) if the send didn't go through — callers
    (the "send invoice" endpoints) must never mark an invoice SENT unless
    this returns normally.

    Caller's responsibility: invoice["customer_email"] must already be
    present — this function doesn't validate that (it's a business rule
    the router enforces before generating a payment link at all)."""
    settings = get_settings()
    recipient = invoice["customer_email"]
    business_name = merchant.get("business_name") or "Your merchant"
    subject = f"Invoice from {business_name} via InfinityPay"
    sender = settings.invoice_email_from
    html = _render_invoice_email_html(merchant=merchant, invoice=invoice, items=items, payment_url=payment_url)

    try:
        message_id = send_email(to=recipient, subject=subject, html=html, sender=sender, reply_to=settings.email_reply_to)
    except EmailDeliveryError as exc:
        _log_delivery(
            client,
            merchant_id=merchant.get("id"),
            email_type="invoice_payment_request",
            related_resource_type="invoice",
            related_resource_id=invoice.get("id"),
            recipient_email=recipient,
            sender_email=sender,
            subject=subject,
            status="failed",
            error_message=str(exc),
        )
        raise

    return _log_delivery(
        client,
        merchant_id=merchant.get("id"),
        email_type="invoice_payment_request",
        related_resource_type="invoice",
        related_resource_id=invoice.get("id"),
        recipient_email=recipient,
        sender_email=sender,
        subject=subject,
        status="sent",
        provider_message_id=message_id or None,
    )


# --- 2. Staff / developer invite ---------------------------------------------


def send_staff_invite_email(
    client: Client, *, merchant: dict, invited_email: str, invited_role: str, accept_url: str
) -> dict:
    """Sends the branded staff-invite email carrying a Supabase-generated
    invite link (see app/routers/merchant_portal.py::create_my_merchant_user,
    which calls auth.admin.generate_link(type="invite") instead of
    invite_user_by_email — generate_link creates the same kind of invite
    without Supabase sending its own unbranded email). Raises
    EmailDeliveryError on failure (not swallowed) — an admin who invited a
    teammate needs to know the invite didn't actually go out, the same
    fail-closed reasoning as send_invoice_email. The accept_url itself is
    never written to email_deliveries (only the subject/recipient/status
    are)."""
    settings = get_settings()
    business_name = merchant.get("business_name") or "your merchant account"
    role_label = invited_role.replace("_", " ").title()
    subject = "You're invited to InfinityPay Merchant Portal"
    sender = settings.email_from

    body = f"""
    <h1 style="margin:0 0 20px;font-size:20px;color:#1f2937;">You're invited to join {business_name}</h1>
    <p style="margin:0 0 16px;font-size:14px;color:#374151;">You've been invited to the InfinityPay Merchant Portal as <strong>{role_label}</strong> for <strong>{business_name}</strong>.</p>
    <p style="margin:0 0 16px;font-size:14px;color:#374151;">Accept the invitation below to set your password and get started.</p>
    {_cta_button(accept_url, "Accept Invitation")}
    <p style="margin:16px 0 0;font-size:12px;color:#9ca3af;">This invite link expires after a limited time — if it's expired, ask an admin at {business_name} to send a new one.</p>
    """
    html = _email_shell(body_html=body)

    try:
        message_id = send_email(to=invited_email, subject=subject, html=html, sender=sender, reply_to=settings.email_reply_to)
    except EmailDeliveryError as exc:
        _log_delivery(
            client,
            merchant_id=merchant.get("id"),
            email_type="staff_invite",
            related_resource_type="merchant",
            related_resource_id=merchant.get("id"),
            recipient_email=invited_email,
            sender_email=sender,
            subject=subject,
            status="failed",
            error_message=str(exc),
        )
        raise

    return _log_delivery(
        client,
        merchant_id=merchant.get("id"),
        email_type="staff_invite",
        related_resource_type="merchant",
        related_resource_id=merchant.get("id"),
        recipient_email=invited_email,
        sender_email=sender,
        subject=subject,
        status="sent",
        provider_message_id=message_id or None,
    )


# --- 3. Password reset --------------------------------------------------------


def send_password_reset_email(client: Client, *, email: str, redirect_to: str) -> dict | None:
    """Generates a Supabase recovery link (auth.admin.generate_link, which
    does not send Supabase's own email) and sends our branded reset email
    via Resend. Returns None — logging nothing and raising nothing — if no
    Supabase Auth account exists for this email, or if the send fails for
    any other reason: POST /v1/auth/forgot-password (the only caller)
    always returns the exact same generic response either way, so this
    function's job is to never let that endpoint observe a difference
    between "no such account" and "email provider down" (account
    enumeration prevention). The reset link/token itself is never passed
    to _log_delivery or logged anywhere."""
    try:
        result = client.auth.admin.generate_link(
            {"type": "recovery", "email": email, "options": {"redirect_to": redirect_to}}
        )
    except Exception:  # noqa: BLE001 — "no such account" and any other Supabase
        # failure must be indistinguishable to the caller (account enumeration
        # prevention), so every exception type is swallowed identically here.
        return None

    reset_url = result.properties.action_link
    settings = get_settings()
    subject = "Reset your InfinityPay password"
    sender = settings.email_from

    body = f"""
    <h1 style="margin:0 0 20px;font-size:20px;color:#1f2937;">Reset your password</h1>
    <p style="margin:0 0 16px;font-size:14px;color:#374151;">We received a request to reset the password for your InfinityPay account.</p>
    {_cta_button(reset_url, "Reset Password")}
    <p style="margin:16px 0 0;font-size:13px;color:#6b7280;">If you did not request this, you can ignore this email.</p>
    """
    html = _email_shell(body_html=body)

    try:
        message_id = send_email(to=email, subject=subject, html=html, sender=sender, reply_to=settings.email_reply_to)
    except EmailDeliveryError as exc:
        _log_delivery(
            client,
            merchant_id=None,
            email_type="password_reset",
            related_resource_type=None,
            related_resource_id=None,
            recipient_email=email,
            sender_email=sender,
            subject=subject,
            status="failed",
            error_message=str(exc),
        )
        return None

    return _log_delivery(
        client,
        merchant_id=None,
        email_type="password_reset",
        related_resource_type=None,
        related_resource_id=None,
        recipient_email=email,
        sender_email=sender,
        subject=subject,
        status="sent",
        provider_message_id=message_id or None,
    )


def send_email_verification_email(client: Client, *, email: str, action_link: str) -> dict | None:
    """Sends the "confirm your email address" link for the combined merchant
    signup (app/services/onboarding.py::signup_merchant). Best-effort —
    never raises: the account + onboarding submission already exist by the
    time this is called, and the merchant can request a fresh link from the
    "check your email" screen. NOT the approval/welcome email — that only
    goes out after Super Admin approval (send_merchant_welcome_email). The
    verification link/token is never passed to _log_delivery or logged."""
    settings = get_settings()
    subject = "Confirm your email address"
    sender = settings.email_from

    body = f"""
    <h1 style="margin:0 0 20px;font-size:20px;color:#1f2937;">Confirm your email address</h1>
    <p style="margin:0 0 16px;font-size:14px;color:#374151;">Thanks for signing up with InfinityPay. Confirm your
    email address to finish creating your merchant account.</p>
    {_cta_button(action_link, "Confirm email address")}
    <p style="margin:16px 0 0;font-size:13px;color:#6b7280;">After you confirm, our team reviews your business details
    and will approve your account or contact you if we need anything else. You'll be able to sign in once your account
    is approved.</p>
    """
    html = _email_shell(body_html=body)

    try:
        message_id = send_email(to=email, subject=subject, html=html, sender=sender, reply_to=settings.email_reply_to)
    except EmailDeliveryError as exc:
        _log_delivery(
            client,
            merchant_id=None,
            email_type="email_verification",
            related_resource_type=None,
            related_resource_id=None,
            recipient_email=email,
            sender_email=sender,
            subject=subject,
            status="failed",
            error_message=str(exc),
        )
        return None

    return _log_delivery(
        client,
        merchant_id=None,
        email_type="email_verification",
        related_resource_type=None,
        related_resource_id=None,
        recipient_email=email,
        sender_email=sender,
        subject=subject,
        status="sent",
        provider_message_id=message_id or None,
    )


# --- 4. Payment receipt -------------------------------------------------------


def _resolve_collection_customer_email(client: Client, collection: dict) -> tuple[str | None, str | None]:
    """collections has no customer_email column of its own (only
    customer_phone — USSD/STK/wallet-push collections are inherently
    phone-first). An email exists for a collection either because it came
    in through a payment_links or invoices row that captured one, or
    because the caller (merchant portal "Request Collection", or an API
    key) supplied customer_email directly on the push/QR/hosted-checkout
    request — see create_processing_collection's _build_initiation_metadata,
    which stores that straight into collection.metadata.customer_email
    since collections has nowhere else to put it.
    Returns (customer_email, payment_link_public_slug) — the slug (when
    available) is what lets the receipt email link back to the existing
    public receipt page; a collection with no linked payment link has no
    working receipt URL to link to, so the email is sent with the receipt
    details inline and no button rather than a broken link."""
    payment_link_id = collection.get("payment_link_id")
    if payment_link_id:
        link = execute_maybe_single(
            client.table("payment_links").select("customer_email, public_slug").eq("id", payment_link_id).maybe_single()
        )
        if link and link.get("customer_email"):
            return link["customer_email"], link.get("public_slug")

    invoice_id = collection.get("invoice_id")
    if invoice_id:
        invoice = execute_maybe_single(
            client.table("invoices").select("customer_email").eq("id", invoice_id).maybe_single()
        )
        if invoice and invoice.get("customer_email"):
            return invoice["customer_email"], None

    metadata_email = (collection.get("metadata") or {}).get("customer_email")
    if metadata_email:
        return metadata_email, None

    return None, None


def send_payment_receipt_email(client: Client, *, merchant: dict, transaction: dict, collection: dict) -> dict | None:
    """Best-effort — never raises. Called right after a collection is
    genuinely settled (app/services/collections.py::_apply_collection_success,
    which itself wraps this call in try/except for defense in depth) —
    a receipt email failing to send must never fail the payment itself.
    Returns None (logging the failure) rather than raising."""
    customer_email, public_slug = _resolve_collection_customer_email(client, collection)
    if not customer_email:
        return None

    settings = get_settings()
    business_name = merchant.get("business_name") or "Merchant"
    merchant_code = merchant.get("merchant_code")
    currency = transaction.get("currency") or collection.get("currency") or "TZS"
    amount = transaction.get("gross_amount") or collection.get("amount")
    receipt_number = f"RCPT-{str(collection['id']).replace('-', '')[-8:].upper()}"
    subject = "Your payment receipt from InfinityPay"
    sender = settings.email_from

    receipt_link_block = ""
    if public_slug:
        receipt_url = f"{settings.app_url}/pay/{public_slug}/receipt/{collection['id']}"
        receipt_link_block = _cta_button(receipt_url, "Download Receipt")

    rows = "".join(
        f"""
        <tr>
          <td style="padding:6px 0;font-size:14px;color:#6b7280;">{label}</td>
          <td style="padding:6px 0;font-size:14px;color:#1f2937;text-align:right;">{value}</td>
        </tr>"""
        for label, value in [
            ("Receipt No.", receipt_number),
            ("Merchant", business_name),
            ("Merchant ID", merchant_code or "—"),
            ("Payment Method", collection.get("method") or "—"),
            ("Transaction ID", transaction.get("id") or "—"),
            ("Provider Reference", collection.get("provider_reference") or collection.get("provider_transid") or "—"),
            ("Merchant Reference", collection.get("merchant_reference") or "—"),
            ("Date", collection.get("completed_at") or ""),
            ("Status", "Successful"),
        ]
        if value
    )

    body = f"""
    <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">Payment Receipt</p>
    <h1 style="margin:0 0 20px;font-size:20px;color:#1f2937;">Payment received — thank you</h1>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;border-radius:8px;padding:16px;margin:0 0 16px;">
      <tr>
        <td style="padding:6px 16px;font-size:14px;color:#6b7280;">Amount paid</td>
        <td style="padding:6px 16px;font-size:20px;font-weight:700;color:#04332a;text-align:right;">{_money(amount, currency)}</td>
      </tr>
    </table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      {rows}
    </table>
    {receipt_link_block}
    """
    html = _email_shell(body_html=body)

    try:
        message_id = send_email(to=customer_email, subject=subject, html=html, sender=sender, reply_to=settings.email_reply_to)
    except EmailDeliveryError as exc:
        _log_delivery(
            client,
            merchant_id=merchant.get("id"),
            email_type="payment_receipt",
            related_resource_type="collection",
            related_resource_id=collection.get("id"),
            recipient_email=customer_email,
            sender_email=sender,
            subject=subject,
            status="failed",
            error_message=str(exc),
        )
        return None

    return _log_delivery(
        client,
        merchant_id=merchant.get("id"),
        email_type="payment_receipt",
        related_resource_type="collection",
        related_resource_id=collection.get("id"),
        recipient_email=customer_email,
        sender_email=sender,
        subject=subject,
        status="sent",
        provider_message_id=message_id or None,
    )


# --- 5. Inquiry notification (to CEO) -----------------------------------------


def send_inquiry_notification_email(client: Client, *, inquiry: dict) -> dict | None:
    """Best-effort — never raises. Called after the inquiry row is already
    committed (app/routers/public_inquiries.py) — the inquiry must never
    be lost just because the notification email failed."""
    settings = get_settings()
    if not settings.ceo_email:
        return None

    subject = "New InfinityPay inquiry received"
    sender = settings.email_from
    rows = "".join(
        f"""
        <tr>
          <td style="padding:6px 0;font-size:14px;color:#6b7280;">{label}</td>
          <td style="padding:6px 0;font-size:14px;color:#1f2937;text-align:right;">{value}</td>
        </tr>"""
        for label, value in [
            ("Name", inquiry.get("full_name")),
            ("Business", inquiry.get("business_name") or "—"),
            ("Email", inquiry.get("email")),
            ("Phone", inquiry.get("phone") or "—"),
            ("Source", inquiry.get("source") or "—"),
            ("Submitted", inquiry.get("created_at") or ""),
        ]
        if value
    )
    message = inquiry.get("message") or ""

    body = f"""
    <h1 style="margin:0 0 20px;font-size:20px;color:#1f2937;">New inquiry received</h1>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 16px;">
      {rows}
    </table>
    <p style="margin:0 0 4px;font-size:12px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">Message</p>
    <p style="margin:0;font-size:14px;color:#374151;white-space:pre-wrap;">{message}</p>
    """
    html = _email_shell(body_html=body)

    try:
        message_id = send_email(to=settings.ceo_email, subject=subject, html=html, sender=sender, reply_to=settings.email_reply_to)
    except EmailDeliveryError as exc:
        _log_delivery(
            client,
            merchant_id=None,
            email_type="inquiry_notification",
            related_resource_type="inquiry",
            related_resource_id=inquiry.get("id"),
            recipient_email=settings.ceo_email,
            sender_email=sender,
            subject=subject,
            status="failed",
            error_message=str(exc),
        )
        return None

    return _log_delivery(
        client,
        merchant_id=None,
        email_type="inquiry_notification",
        related_resource_type="inquiry",
        related_resource_id=inquiry.get("id"),
        recipient_email=settings.ceo_email,
        sender_email=sender,
        subject=subject,
        status="sent",
        provider_message_id=message_id or None,
    )


# --- 6. Merchant welcome -------------------------------------------------------


_WELCOME_SERVICES = [
    "Request collections",
    "Generate payment links",
    "Create invoices",
    "Integrate your website, mobile app, or e-commerce/web app using API credentials",
    "Track your wallet ledger",
    "Request withdrawals",
]


def send_merchant_welcome_email(client: Client, *, merchant: dict, portal_url: str) -> dict | None:
    """Best-effort — never raises. Called once a merchant's onboarding is
    approved (app/services/onboarding.py::approve_onboarding_submission),
    wrapped in try/except there for defense in depth — a welcome email
    failing to send must never fail the approval itself.

    Always sent to the merchant's own contact_email — never
    settings.ceo_email, which is reserved for internal notifications (see
    send_merchant_signup_notification_email below, and
    send_withdrawal_request_notification_email). If contact_email is
    missing, this never falls back to any other address — it logs and
    stops. No email_deliveries row is written for that case (its
    recipient_email column is NOT NULL, and nothing was actually
    attempted) — the logger line plus the caller's own audit log entry
    (app/services/onboarding.py::approve_onboarding_submission) are the
    durable record instead."""
    recipient = merchant.get("contact_email")
    if not recipient:
        logger.warning(
            "Merchant welcome email not sent: merchant email missing. merchant_id=%s", merchant.get("id")
        )
        return None

    settings = get_settings()
    business_name = merchant.get("business_name") or "there"
    merchant_code = merchant.get("merchant_code")
    subject = "Your InfinityPay account has been approved"
    sender = settings.email_from

    services_list = "".join(
        f'<li style="margin:0 0 6px;font-size:14px;color:#374151;">{service}</li>' for service in _WELCOME_SERVICES
    )
    merchant_id_row = (
        f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;border-radius:8px;padding:16px;margin:0 0 16px;">
          <tr>
            <td style="padding:6px 16px;font-size:14px;color:#6b7280;">Your Merchant ID</td>
            <td style="padding:6px 16px;font-size:16px;font-weight:700;color:#04332a;text-align:right;font-family:monospace;">{merchant_code}</td>
          </tr>
        </table>"""
        if merchant_code
        else ""
    )

    body = f"""
    <h1 style="margin:0 0 20px;font-size:20px;color:#1f2937;">Welcome to InfinityPay, {business_name}!</h1>
    <p style="margin:0 0 16px;font-size:14px;color:#374151;">Your account is approved and ready to go.</p>
    {merchant_id_row}
    <p style="margin:0 0 8px;font-size:13px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">With InfinityPay you can</p>
    <ul style="margin:0 0 8px;padding-left:20px;">
      {services_list}
    </ul>
    {_cta_button(portal_url, "Open Merchant Portal")}
    """
    html = _email_shell(body_html=body)

    try:
        message_id = send_email(to=recipient, subject=subject, html=html, sender=sender, reply_to=settings.email_reply_to)
    except EmailDeliveryError as exc:
        _log_delivery(
            client,
            merchant_id=merchant.get("id"),
            email_type="merchant_welcome",
            related_resource_type="merchant",
            related_resource_id=merchant.get("id"),
            recipient_email=recipient,
            sender_email=sender,
            subject=subject,
            status="failed",
            error_message=str(exc),
        )
        return None

    return _log_delivery(
        client,
        merchant_id=merchant.get("id"),
        email_type="merchant_welcome",
        related_resource_type="merchant",
        related_resource_id=merchant.get("id"),
        recipient_email=recipient,
        sender_email=sender,
        subject=subject,
        status="sent",
        provider_message_id=message_id or None,
    )


# --- 6b. New merchant signup notification (to CEO) ------------------------------


def send_merchant_signup_notification_email(
    client: Client,
    *,
    merchant: dict,
    contact_name: str | None = None,
    nature_of_business: str | None = None,
    business_category: str | None = None,
    business_location: str | None = None,
    nida_masked: str | None = None,
    submitted_at: str | None = None,
) -> dict | None:
    """Best-effort — never raises. Called right after a *new* onboarding
    submission is created (app/services/onboarding.py::create_merchant_onboarding,
    the fresh-signup path only — a resubmission after rejection/
    info-requested isn't a new merchant, so it doesn't fire this again).

    Distinct from send_merchant_welcome_email above and never to be
    confused with it: this one always goes to settings.ceo_email (an
    internal notification), never to the merchant; the welcome email
    always goes to the merchant's own contact_email, never to
    settings.ceo_email. Keeping them as two separate functions, each
    hardcoded to its own recipient source, is deliberate — it's what
    makes it structurally impossible for a future edit to one to
    accidentally redirect the other's mail.

    Status is always "Pending Review" — this only ever fires the moment a
    submission is created, which is the one point in its lifecycle where
    that's guaranteed true (see AccountStatus.PENDING_VERIFICATION, the
    fixed initial review_status _submission_data sets)."""
    settings = get_settings()
    if not settings.ceo_email:
        return None

    business_name = merchant.get("business_name") or "A merchant"
    merchant_code = merchant.get("merchant_code")
    contact_email = merchant.get("contact_email") or "—"
    contact_phone = merchant.get("contact_phone")
    subject = "New merchant signup submitted"
    sender = settings.email_from
    review_url = f"{settings.app_url}/super-admin/onboarding"

    business_type = ", ".join(v for v in (nature_of_business, business_category) if v) or None

    rows: list[tuple[str, str]] = [
        ("Business", business_name),
        ("Contact person", contact_name or "—"),
        ("Merchant email", contact_email),
        ("Phone number", contact_phone or "—"),
        ("NIDA number", nida_masked or "—"),
        ("Business type/category", business_type or "—"),
        ("Business location", business_location or "—"),
        ("Submitted", submitted_at or "—"),
        ("Merchant ID", merchant_code or "—"),
        ("Status", "Pending Review"),
    ]
    rows_html = "".join(
        f"""
        <tr>
          <td style="padding:6px 0;font-size:14px;color:#6b7280;">{label}</td>
          <td style="padding:6px 0;font-size:14px;color:#1f2937;text-align:right;">{value}</td>
        </tr>"""
        for label, value in rows
    )

    body = f"""
    <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">New Merchant Signup</p>
    <h1 style="margin:0 0 20px;font-size:20px;color:#1f2937;">{business_name} submitted an application</h1>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      {rows_html}
    </table>
    <p style="margin:16px 0 0;font-size:13px;color:#6b7280;">Supporting KYC documents (TIN certificate, business licence, etc.) are collected offline by InfinityPay if needed.</p>
    {_cta_button(review_url, "Review Submission")}
    """
    html = _email_shell(body_html=body)

    try:
        message_id = send_email(
            to=settings.ceo_email, subject=subject, html=html, sender=sender, reply_to=settings.email_reply_to
        )
    except EmailDeliveryError as exc:
        _log_delivery(
            client,
            merchant_id=merchant.get("id"),
            email_type="merchant_signup_notification",
            related_resource_type="merchant",
            related_resource_id=merchant.get("id"),
            recipient_email=settings.ceo_email,
            sender_email=sender,
            subject=subject,
            status="failed",
            error_message=str(exc),
        )
        return None

    return _log_delivery(
        client,
        merchant_id=merchant.get("id"),
        email_type="merchant_signup_notification",
        related_resource_type="merchant",
        related_resource_id=merchant.get("id"),
        recipient_email=settings.ceo_email,
        sender_email=sender,
        subject=subject,
        status="sent",
        provider_message_id=message_id or None,
    )


# --- 7. Withdrawal request notification (to CEO) -------------------------------


def send_withdrawal_request_notification_email(
    client: Client, *, merchant: dict, disbursement: dict, available_balance: Decimal | None = None
) -> dict | None:
    """Best-effort — never raises. Called right after a withdrawal request
    row is inserted (app/services/disbursements.py::execute_disbursement,
    itself wrapped in try/except there for defense in depth) — the request
    is already saved by the time this runs, so a failed notification must
    never be mistaken for a failed withdrawal request."""
    settings = get_settings()
    if not settings.ceo_email:
        return None

    business_name = merchant.get("business_name") or "A merchant"
    merchant_code = merchant.get("merchant_code")
    amount = disbursement.get("amount")
    currency = disbursement.get("currency") or "TZS"
    subject = f"New withdrawal request from {business_name}"
    sender = settings.email_from
    review_url = f"{settings.app_url}/super-admin/withdrawals"

    destination_identifier = disbursement.get("destination_identifier") or ""
    masked_destination = _mask_identifier(destination_identifier) if destination_identifier else "—"
    bank_name = disbursement.get("bank_name")
    destination_label = f"{bank_name} — {masked_destination}" if bank_name else masked_destination
    method = (disbursement.get("method") or "").replace("_", " ").title() or "—"
    status_label = (disbursement.get("status") or "").replace("_", " ").title() or "—"

    rows: list[tuple[str, str]] = [
        ("Merchant", business_name),
        ("Merchant ID", merchant_code or "—"),
        ("Amount", _money(amount, currency)),
        ("Method", method),
        ("Destination", destination_label),
        ("Requested", disbursement.get("initiated_at") or ""),
        ("Status", status_label),
    ]
    if available_balance is not None:
        rows.append(("Available Balance", _money(available_balance, currency)))

    rows_html = "".join(
        f"""
        <tr>
          <td style="padding:6px 0;font-size:14px;color:#6b7280;">{label}</td>
          <td style="padding:6px 0;font-size:14px;color:#1f2937;text-align:right;">{value}</td>
        </tr>"""
        for label, value in rows
        if value
    )

    body = f"""
    <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">Withdrawal Request</p>
    <h1 style="margin:0 0 20px;font-size:20px;color:#1f2937;">New withdrawal request from {business_name}</h1>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      {rows_html}
    </table>
    {_cta_button(review_url, "Review Withdrawal")}
    """
    html = _email_shell(body_html=body)

    try:
        message_id = send_email(
            to=settings.ceo_email, subject=subject, html=html, sender=sender, reply_to=settings.email_reply_to
        )
    except EmailDeliveryError as exc:
        _log_delivery(
            client,
            merchant_id=merchant.get("id"),
            email_type="withdrawal_request_notification",
            related_resource_type="disbursement",
            related_resource_id=disbursement.get("id"),
            recipient_email=settings.ceo_email,
            sender_email=sender,
            subject=subject,
            status="failed",
            error_message=str(exc),
        )
        return None

    return _log_delivery(
        client,
        merchant_id=merchant.get("id"),
        email_type="withdrawal_request_notification",
        related_resource_type="disbursement",
        related_resource_id=disbursement.get("id"),
        recipient_email=settings.ceo_email,
        sender_email=sender,
        subject=subject,
        status="sent",
        provider_message_id=message_id or None,
    )


# --- 8. Withdrawal success (to merchant) ----------------------------------------


def send_withdrawal_success_email(client: Client, *, merchant: dict, disbursement: dict) -> dict | None:
    """Best-effort — never raises. Call only once a disbursement has
    genuinely reached its terminal SUCCESS status — both places that
    happens (app/services/disbursements.py's synchronous
    _reserve_and_run_disbursement_provider path and its delayed
    _resolve_processing_disbursement path, used by both the callback and
    admin-triggered refresh) call this right next to their existing
    notify_merchant(...WITHDRAWAL_SUCCESS...) call, each already wrapped
    in try/except there for defense in depth. Never called for
    PENDING_ADMIN_APPROVAL/PROCESSING/REJECTED/FAILED/REVERSED/etc — those
    statuses never reach this function."""
    recipient = merchant.get("contact_email")
    if not recipient:
        return None

    settings = get_settings()
    business_name = merchant.get("business_name") or "there"
    merchant_code = merchant.get("merchant_code")
    amount = disbursement.get("amount")
    currency = disbursement.get("currency") or "TZS"
    subject = "Your InfinityPay withdrawal is successful"
    sender = settings.email_from
    portal_url = f"{settings.app_url}/merchant/withdrawals"

    destination_identifier = disbursement.get("destination_identifier") or ""
    masked_destination = _mask_identifier(destination_identifier) if destination_identifier else "—"
    bank_name = disbursement.get("bank_name")
    destination_label = f"{bank_name} — {masked_destination}" if bank_name else masked_destination

    rows: list[tuple[str, str]] = [
        ("Merchant", business_name),
        ("Merchant ID", merchant_code or "—"),
        ("Reference", disbursement.get("provider_reference") or "—"),
        ("Completed", disbursement.get("completed_at") or ""),
        ("Destination", destination_label),
        ("Status", "Successful"),
    ]
    rows_html = "".join(
        f"""
        <tr>
          <td style="padding:6px 0;font-size:14px;color:#6b7280;">{label}</td>
          <td style="padding:6px 0;font-size:14px;color:#1f2937;text-align:right;">{value}</td>
        </tr>"""
        for label, value in rows
        if value
    )

    body = f"""
    <h1 style="margin:0 0 20px;font-size:20px;color:#1f2937;">Your withdrawal is successful</h1>
    <p style="margin:0 0 16px;font-size:14px;color:#374151;">Hi {business_name}, your withdrawal has been completed.</p>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;border-radius:8px;padding:16px;margin:0 0 16px;">
      <tr>
        <td style="padding:6px 16px;font-size:14px;color:#6b7280;">Amount</td>
        <td style="padding:6px 16px;font-size:20px;font-weight:700;color:#04332a;text-align:right;">{_money(amount, currency)}</td>
      </tr>
    </table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      {rows_html}
    </table>
    {_cta_button(portal_url, "View Merchant Portal")}
    """
    html = _email_shell(body_html=body)

    try:
        message_id = send_email(to=recipient, subject=subject, html=html, sender=sender, reply_to=settings.email_reply_to)
    except EmailDeliveryError as exc:
        _log_delivery(
            client,
            merchant_id=merchant.get("id"),
            email_type="withdrawal_success",
            related_resource_type="disbursement",
            related_resource_id=disbursement.get("id"),
            recipient_email=recipient,
            sender_email=sender,
            subject=subject,
            status="failed",
            error_message=str(exc),
        )
        return None

    return _log_delivery(
        client,
        merchant_id=merchant.get("id"),
        email_type="withdrawal_success",
        related_resource_type="disbursement",
        related_resource_id=disbursement.get("id"),
        recipient_email=recipient,
        sender_email=sender,
        subject=subject,
        status="sent",
        provider_message_id=message_id or None,
    )


# --- 9. Payment link customer delivery ------------------------------------------


def send_payment_link_customer_email(client: Client, *, merchant: dict, payment_link: dict) -> dict | None:
    """Best-effort — never raises. Called right after a payment link is
    created (app/routers/merchant_portal.py::create_my_payment_link), only
    when payment_link["customer_email"] is present. A missing email is not
    a failure — nothing to send — so this checks for it internally rather
    than requiring every caller to guard first; payment link creation
    itself must never fail just because no customer email was given."""
    recipient = payment_link.get("customer_email")
    if not recipient:
        return None

    settings = get_settings()
    business_name = merchant.get("business_name") or "Your merchant"
    amount = payment_link.get("amount")
    currency = payment_link.get("currency") or "TZS"
    description = payment_link.get("description")
    reference = payment_link.get("merchant_reference")
    payment_url = build_public_url(payment_link["public_slug"])
    subject = f"Payment request from {business_name} via InfinityPay"
    sender = settings.email_from

    rows: list[tuple[str, str]] = [("Amount", _money(amount, currency))]
    if description:
        rows.append(("Description", description))
    if reference:
        rows.append(("Reference", reference))
    rows_html = "".join(
        f"""
        <tr>
          <td style="padding:6px 0;font-size:14px;color:#6b7280;">{label}</td>
          <td style="padding:6px 0;font-size:14px;color:#1f2937;text-align:right;">{value}</td>
        </tr>"""
        for label, value in rows
    )

    body = f"""
    <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">Payment Request</p>
    <h1 style="margin:0 0 20px;font-size:20px;color:#1f2937;">{business_name} has requested a payment</h1>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;border-radius:8px;padding:16px;margin:0 0 16px;">
      {rows_html}
    </table>
    {_cta_button(payment_url, "Pay Now")}
    <p style="margin:16px 0 0;font-size:13px;color:#6b7280;">Questions about this payment? Contact {business_name} directly.</p>
    """
    html = _email_shell(body_html=body)

    try:
        message_id = send_email(to=recipient, subject=subject, html=html, sender=sender, reply_to=settings.email_reply_to)
    except EmailDeliveryError as exc:
        _log_delivery(
            client,
            merchant_id=merchant.get("id"),
            email_type="payment_link_customer",
            related_resource_type="payment_link",
            related_resource_id=payment_link.get("id"),
            recipient_email=recipient,
            sender_email=sender,
            subject=subject,
            status="failed",
            error_message=str(exc),
        )
        return None

    return _log_delivery(
        client,
        merchant_id=merchant.get("id"),
        email_type="payment_link_customer",
        related_resource_type="payment_link",
        related_resource_id=payment_link.get("id"),
        recipient_email=recipient,
        sender_email=sender,
        subject=subject,
        status="sent",
        provider_message_id=message_id or None,
    )


# --- 10. Merchant collection notification (to the merchant's own inbox) --------


def _resolve_collection_customer_details(client: Client, collection: dict) -> dict[str, str | None]:
    """name/email/phone for a collection's payer, for the merchant-facing
    notification email — a superset of _resolve_collection_customer_email
    above (email only). Kept as its own function rather than extending
    that one: send_payment_receipt_email is already relied on in
    production and this avoids touching its signature/behavior at all.
    Same three sources, in the same precedence order: the linked
    payment_link/invoice row, then collection.metadata (where a direct
    "Request Collection"/API push stores whatever the caller supplied,
    since collections has no customer_name/customer_email columns of its
    own). customer_phone is the one field collections *does* store
    directly (USSD/STK/wallet-push collections are inherently
    phone-first)."""
    name: str | None = None
    email: str | None = None
    phone = collection.get("customer_phone")

    payment_link_id = collection.get("payment_link_id")
    if payment_link_id:
        link = execute_maybe_single(
            client.table("payment_links")
            .select("customer_name, customer_email")
            .eq("id", payment_link_id)
            .maybe_single()
        )
        if link:
            name = name or link.get("customer_name")
            email = email or link.get("customer_email")

    invoice_id = collection.get("invoice_id")
    if invoice_id:
        invoice = execute_maybe_single(
            client.table("invoices").select("customer_name, customer_email").eq("id", invoice_id).maybe_single()
        )
        if invoice:
            name = name or invoice.get("customer_name")
            email = email or invoice.get("customer_email")

    metadata = collection.get("metadata") or {}
    name = name or metadata.get("customer_name")
    email = email or metadata.get("customer_email")

    return {"name": name, "email": email, "phone": phone}


def _notification_already_sent(client: Client, *, collection_id: str, recipient_email: str) -> bool:
    """Idempotency guard (feature brief Part 5): true if this exact
    recipient already has a 'sent' merchant_collection_notification row
    for this collection. resolve_collection()/finalize_pending_review_collection()
    are themselves already guarded against re-processing an already-
    resolved collection (both check collection.status before doing
    anything), so in practice this function's caller only ever runs once
    per collection — this is a second, independent layer of protection
    against the specific case the brief calls out: a webhook redelivery, a
    manual "Refresh status" click, or a reconciliation sweep somehow
    re-entering the success path for the same collection."""
    existing = (
        client.table("email_deliveries")
        .select("id")
        .eq("email_type", "merchant_collection_notification")
        .eq("related_resource_type", "collection")
        .eq("related_resource_id", collection_id)
        .eq("recipient_email", recipient_email)
        .eq("status", "sent")
        .limit(1)
        .execute()
    ).data
    return bool(existing)


def send_merchant_collection_notification_email(
    client: Client, *, merchant: dict, transaction: dict, collection: dict
) -> list[dict]:
    """Best-effort — never raises. Called right after send_payment_receipt_email
    from _apply_collection_success (app/services/collections.py), itself
    already wrapped in try/except there for defense in depth — a merchant
    notification failing to send must never fail the payment/wallet credit
    it's reporting on.

    Distinct from send_payment_receipt_email: that goes to the paying
    CUSTOMER (their own email, wherever it came from). This goes to the
    MERCHANT's own configured notification email(s)
    (merchant_notification_settings — see app/services/merchant_notifications.py),
    up to 2, and only when collection_notifications_enabled is true.
    Idempotent per (collection, recipient) — see _notification_already_sent.

    Returns the email_deliveries rows written (sent/failed/skipped, one
    per configured recipient) — mainly for tests; callers otherwise ignore
    the return value the same as every other best-effort send_* here."""
    merchant_id = merchant.get("id")
    if not merchant_id:
        return []

    notification_settings = get_notification_settings(client, uuid.UUID(merchant_id))
    if not notification_settings or not notification_settings.get("collection_notifications_enabled"):
        return []

    recipients = [
        email
        for email in (
            notification_settings.get("primary_notification_email"),
            notification_settings.get("secondary_notification_email"),
        )
        if email
    ]
    if not recipients:
        # Notifications are enabled but no email has ever been configured —
        # nothing to send, and (same convention as send_merchant_welcome_email
        # above) no email_deliveries row: recipient_email is NOT NULL and
        # nothing was actually attempted. The logger line is the record.
        logger.warning(
            "Merchant collection notification not sent: no notification email configured. merchant_id=%s", merchant_id
        )
        return []

    settings = get_settings()
    business_name = merchant.get("business_name") or "Merchant"
    currency = transaction.get("currency") or collection.get("currency") or "TZS"
    gross_amount = transaction.get("gross_amount") or collection.get("amount")
    fee_amount = transaction.get("fee_amount") or "0"
    net_amount = transaction.get("net_amount") or gross_amount
    method = (collection.get("method") or "").replace("_", " ").title() or "—"
    customer = _resolve_collection_customer_details(client, collection)
    collection_id = collection.get("id")
    sender = settings.email_from
    # "Collection payment received - TZS {amount}" from the feature brief,
    # with the collection's real currency substituted for the literal
    # "TZS" (this platform is TZS-only today, so in practice these read
    # identically) — _money() already renders "{currency} {amount}".
    subject = f"Collection payment received - {_money(gross_amount, currency)}"
    portal_url = f"{settings.app_url}/portal/collections"

    rows: list[tuple[str, str]] = [
        ("Merchant", business_name),
        ("Fee / Charge", _money(fee_amount, currency)),
        ("Net Amount Credited", _money(net_amount, currency)),
        ("Payment Method", method),
        ("Customer Name", customer["name"] or ""),
        ("Customer Phone", _mask_identifier(customer["phone"]) if customer["phone"] else ""),
        ("Customer Email", customer["email"] or ""),
        (
            "Provider Reference",
            collection.get("provider_reference") or collection.get("provider_transid") or "",
        ),
        ("Reference", collection.get("merchant_reference") or transaction.get("reference") or ""),
        ("Date", collection.get("completed_at") or ""),
        ("Status", "Successful"),
    ]
    rows_html = "".join(
        f"""
        <tr>
          <td style="padding:6px 0;font-size:14px;color:#6b7280;">{label}</td>
          <td style="padding:6px 0;font-size:14px;color:#1f2937;text-align:right;">{value}</td>
        </tr>"""
        for label, value in rows
        if value
    )

    body = f"""
    <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">Collection Notification</p>
    <h1 style="margin:0 0 20px;font-size:20px;color:#1f2937;">You received a payment</h1>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;border-radius:8px;padding:16px;margin:0 0 16px;">
      <tr>
        <td style="padding:6px 16px;font-size:14px;color:#6b7280;">Gross amount</td>
        <td style="padding:6px 16px;font-size:20px;font-weight:700;color:#04332a;text-align:right;">{_money(gross_amount, currency)}</td>
      </tr>
    </table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      {rows_html}
    </table>
    {_cta_button(portal_url, "View in Merchant Portal")}
    """
    html = _email_shell(body_html=body)

    delivery_rows: list[dict] = []
    for recipient in recipients:
        if _notification_already_sent(client, collection_id=collection_id, recipient_email=recipient):
            delivery_rows.append(
                _log_delivery(
                    client,
                    merchant_id=merchant_id,
                    email_type="merchant_collection_notification",
                    related_resource_type="collection",
                    related_resource_id=collection_id,
                    recipient_email=recipient,
                    sender_email=sender,
                    subject=subject,
                    status="skipped",
                    error_message="Already sent for this collection — retry suppressed.",
                )
            )
            continue

        try:
            message_id = send_email(to=recipient, subject=subject, html=html, sender=sender, reply_to=settings.email_reply_to)
        except EmailDeliveryError as exc:
            delivery_rows.append(
                _log_delivery(
                    client,
                    merchant_id=merchant_id,
                    email_type="merchant_collection_notification",
                    related_resource_type="collection",
                    related_resource_id=collection_id,
                    recipient_email=recipient,
                    sender_email=sender,
                    subject=subject,
                    status="failed",
                    error_message=str(exc),
                )
            )
            continue

        delivery_rows.append(
            _log_delivery(
                client,
                merchant_id=merchant_id,
                email_type="merchant_collection_notification",
                related_resource_type="collection",
                related_resource_id=collection_id,
                recipient_email=recipient,
                sender_email=sender,
                subject=subject,
                status="sent",
                provider_message_id=message_id or None,
            )
        )

    return delivery_rows
