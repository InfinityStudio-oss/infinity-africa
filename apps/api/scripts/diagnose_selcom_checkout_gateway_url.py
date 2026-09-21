"""Diagnostic: why does Selcom's own `payment_gateway_url` (from a real,
successful create-order-minimal response) return "Page Not Found" when
opened? (First observed 2026-08-22/23 against two independent real
orders, both fully successful on Selcom's side — resultcode 000,
result SUCCESS — with a correctly-decoded, non-truncated URL.)

This script rules out our own request-construction as the cause by
calling create-order-minimal for real, multiple times, with a small
matrix of field-inclusion variants — never wallet-payment, never
anything that moves money. For each variant it also does a safe,
read-only HTTP GET against the resulting payment_gateway_url and
reports whether the body is Selcom's own "Page Not Found" page or
something else, so the actual live evidence (not a guess) decides
whether any of our optional fields are the cause.

Manual use only — never wired into any route or test suite, same
convention as test_selcom_checkout_create_order_minimal.py. Requires
one explicit confirmation covering the whole run (create-order-minimal
is safe/inert — confirmed repeatedly this session — it never charges
anyone or triggers a push by itself).

Never prints the API key, API secret, private key, or a full buyer
email/phone — only masked forms. Gateway URLs are printed with the
domain and path prefix visible but the long opaque token truncated —
enough to eyeball the domain/shape without ever needing to reconstruct
or share a working token.

Usage:

    python apps/api/scripts/diagnose_selcom_checkout_gateway_url.py \\
      --buyer-email test@example.com --buyer-name "Diagnostic Test" \\
      --buyer-phone 255700000000 --amount 1000
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parent.parent
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

import httpx

from app.config import get_settings
from app.core.errors import SelcomAPIError
from app.core.references import generate_reference
from app.services.selcom_checkout.client import (
    SelcomCheckoutHTTPClient,
    get_selcom_checkout_credentials,
)
from app.services.selcom_checkout.errors import SelcomCheckoutMisconfiguredError


def _mask_email(value: str) -> str:
    if "@" not in value:
        return "*" * len(value)
    local, _, domain = value.partition("@")
    return f"{local[0]}{'*' * max(len(local) - 1, 0)}@{domain}"


def _mask_phone(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


def _mask_vendor(value: str) -> str:
    if not value:
        return "(not set)"
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def _mask_gateway_url(url: str | None) -> str:
    """Domain + path prefix visible, opaque token truncated — enough to
    confirm the shape/domain without the value being replayable."""
    if not url:
        return "(none)"
    marker = "/checkout/"
    idx = url.find(marker)
    if idx == -1:
        return url[:40] + ("…" if len(url) > 40 else "")
    prefix = url[: idx + len(marker)]
    token = url[idx + len(marker) :]
    return f"{prefix}{token[:8]}…({len(token)} chars total)"


def _env_or_arg(arg_value: str | None, env_name: str) -> str | None:
    return arg_value if arg_value is not None else os.environ.get(env_name)


# Each variant is (name, kwargs-passed-to-create_order_minimal, description).
# webhook is threaded in separately below (needs settings), everything
# else is literal per-variant.
_FUTURE_EXPIRY_SECONDS = 3600  # 1 hour from now, if `expiry` turns out to
# mean "seconds from now" — genuinely unconfirmed, see report footer.


def _build_variants(webhook_url: str | None) -> list[tuple[str, dict, str]]:
    redirect_url = "https://infinitypay.me/pay/diagnostic-success"
    cancel_url = "https://infinitypay.me/pay/diagnostic-cancel"
    return [
        (
            "bare-minimum",
            {},
            "Only the required fields — no webhook/redirect/cancel/expiry/remarks/colours at all.",
        ),
        (
            "webhook-only",
            {"webhook": webhook_url} if webhook_url else {},
            "Adds only `webhook` — this is what real production traffic sends today.",
        ),
        (
            "redirect-cancel-only",
            {"redirect_url": redirect_url, "cancel_url": cancel_url},
            "Adds only `redirect_url`/`cancel_url` (base64-encoded), no webhook.",
        ),
        (
            "expiry-future-only",
            {"expiry": _FUTURE_EXPIRY_SECONDS},
            f"Adds only `expiry={_FUTURE_EXPIRY_SECONDS}` — format/semantics unconfirmed, see footer.",
        ),
        (
            "remarks-only",
            {"buyer_remarks": "Diagnostic buyer remark", "merchant_remarks": "Diagnostic merchant remark"},
            "Adds only `buyer_remarks`/`merchant_remarks`, no webhook/redirect/cancel/expiry.",
        ),
        (
            "all-optional-combined",
            {
                "webhook": webhook_url,
                "redirect_url": redirect_url,
                "cancel_url": cancel_url,
                "buyer_remarks": "Diagnostic buyer remark",
                "merchant_remarks": "Diagnostic merchant remark",
            }
            if webhook_url
            else {
                "redirect_url": redirect_url,
                "cancel_url": cancel_url,
                "buyer_remarks": "Diagnostic buyer remark",
                "merchant_remarks": "Diagnostic merchant remark",
            },
            "Every optional field this client supports at once, except expiry.",
        ),
    ]


async def _check_gateway_url(url: str) -> str:
    """Read-only GET — never submits anything, never approves a
    payment. Returns a short human-readable verdict string."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http:
            response = await http.get(url)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
        return f"UNREACHABLE ({type(exc).__name__})"

    body_text = response.text
    if "Page Not Found" in body_text or "page not found" in body_text.lower():
        return f"PAGE NOT FOUND (HTTP {response.status_code}, {len(body_text)} bytes)"
    return f"LOADED SOMETHING ELSE (HTTP {response.status_code}, {len(body_text)} bytes) — inspect manually"


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--buyer-email", default=None, help="env: SELCOM_TEST_BUYER_EMAIL")
    parser.add_argument("--buyer-name", default=None, help="env: SELCOM_TEST_BUYER_NAME")
    parser.add_argument("--buyer-phone", default=None, help="env: SELCOM_TEST_BUYER_PHONE (255XXXXXXXXX)")
    parser.add_argument("--amount", default=None, help="env: SELCOM_TEST_AMOUNT")
    parser.add_argument(
        "--skip-url-check",
        action="store_true",
        help="Skip the live HTTP GET against each resulting payment_gateway_url — order-creation-only.",
    )
    args = parser.parse_args()

    buyer_email = _env_or_arg(args.buyer_email, "SELCOM_TEST_BUYER_EMAIL")
    buyer_name = _env_or_arg(args.buyer_name, "SELCOM_TEST_BUYER_NAME")
    buyer_phone = _env_or_arg(args.buyer_phone, "SELCOM_TEST_BUYER_PHONE")
    amount = _env_or_arg(args.amount, "SELCOM_TEST_AMOUNT") or "1000"

    missing = [f for f, v in [("--buyer-email", buyer_email), ("--buyer-name", buyer_name), ("--buyer-phone", buyer_phone)] if not v]
    if missing:
        print(f"Missing required value(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    settings = get_settings()

    print(
        "This creates SEVERAL real order shells on Selcom's live system (one per variant "
        "below) — create-order-minimal never charges anyone or triggers a push by itself, "
        "confirmed repeatedly. Each variant's resulting payment_gateway_url will also be "
        "fetched with a read-only GET (unless --skip-url-check) — never submits anything."
    )
    print(f"  SELCOM_CHECKOUT_BASE_URL: {settings.selcom_checkout_base_url or '(not set)'}")
    print(f"  SELCOM_CHECKOUT_VENDOR:   {_mask_vendor(settings.selcom_checkout_vendor)}")
    print(f"  buyer_email:              {_mask_email(buyer_email)}")
    print(f"  buyer_phone:              {_mask_phone(buyer_phone)}")
    print(f"  amount:                   {amount}")
    confirm = input("Type 'yes' to confirm you intend to create several real orders on Selcom's live system: ")
    if confirm.strip().lower() != "yes":
        print("Aborted.", file=sys.stderr)
        return 1

    try:
        client = SelcomCheckoutHTTPClient(credentials=get_selcom_checkout_credentials(settings))
    except SelcomCheckoutMisconfiguredError as exc:
        print(f"Client misconfigured: {exc}", file=sys.stderr)
        return 2

    webhook_url = settings.selcom_checkout_webhook_url or None
    variants = _build_variants(webhook_url)

    results: list[dict] = []
    for name, extra_kwargs, description in variants:
        order_id = generate_reference(f"ORD-DIAG-{name.upper()[:12]}")
        print()
        print("=" * 78)
        print(f"Variant: {name}")
        print(f"  {description}")
        print(f"  order_id: {order_id}")
        try:
            result = await client.create_order_minimal(
                order_id=order_id,
                buyer_email=buyer_email,
                buyer_name=buyer_name,
                buyer_phone=buyer_phone,
                amount=amount,
                no_of_items=1,
                **extra_kwargs,
            )
        except SelcomAPIError as exc:
            print(f"  Selcom API error: {exc.message} (status {exc.provider_status_code})")
            results.append({"variant": name, "order_id": order_id, "outcome": f"API ERROR: {exc.message}"})
            continue

        print(f"  resultcode: {result.resultcode}  result: {result.result}  reference: {result.reference}")
        print(f"  payment_gateway_url: {_mask_gateway_url(result.payment_gateway_url)}")

        if not result.is_success or not result.payment_gateway_url:
            outcome = f"order not successful (resultcode={result.resultcode})"
            print(f"  -> {outcome}")
            results.append({"variant": name, "order_id": order_id, "reference": result.reference, "outcome": outcome})
            continue

        if args.skip_url_check:
            outcome = "order created — URL check skipped"
        else:
            outcome = await _check_gateway_url(result.payment_gateway_url)
        print(f"  -> {outcome}")
        results.append({"variant": name, "order_id": order_id, "reference": result.reference, "outcome": outcome})

    print()
    print("=" * 78)
    print("Summary")
    print("=" * 78)
    for row in results:
        print(f"  {row['variant']:<24} order={row['order_id']:<28} -> {row['outcome']}")
    print()
    print(
        "Note on `expiry`: this client's `expiry: int | None` is sent as-is under that "
        "name — Selcom's docs don't confirm whether it means seconds-from-now, a Unix "
        "epoch, or something else. This script tested it as seconds-from-now "
        f"({_FUTURE_EXPIRY_SECONDS}s). If the expiry-future-only variant behaves "
        "differently from bare-minimum, that's a real signal worth following up with "
        "Selcom on the exact expected format — not something to guess further here."
    )

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
