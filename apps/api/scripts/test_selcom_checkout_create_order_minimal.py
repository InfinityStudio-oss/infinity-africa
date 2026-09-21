"""Direct Selcom Checkout Create Order - Minimal connectivity test
(https://developers.selcommobile.com/#create-order-minimal) — calls
SelcomCheckoutHTTPClient.create_order_minimal() directly, bypassing every
merchant-facing/admin validation layer, so signing and network
reachability can be verified independently.

Manual use only — never wired into any route or test suite. Reads
Checkout credentials the same way the running app does
(get_selcom_checkout_credentials(), app/config/settings.py), so set them
in apps/api/.env for a local run:

    SELCOM_CHECKOUT_BASE_URL=...
    SELCOM_CHECKOUT_API_KEY=...
    SELCOM_CHECKOUT_API_SECRET=...
    SELCOM_CHECKOUT_VENDOR=...

**Important, unlike the Business Disbursement API's equivalent script**:
InfinityPay has no Selcom Checkout sandbox at all (confirmed
2026-08-22) — SELCOM_CHECKOUT_BASE_URL is always a real production
endpoint with real production credentials, and this script always hits
it. That's acceptable for create-order-minimal specifically because it
never charges anyone or triggers a push by itself — it only creates an
order shell on Selcom's live system. It is NOT acceptable for
wallet-payment (see test_selcom_checkout_wallet_payment.py), which does
send a real push to a real phone — that script requires its own,
separate, much more deliberate confirmation. The prompt below still
requires an explicit "yes" before sending anything.

Docs inconsistency this script exists to help resolve, without ever
guessing an answer into production code (app/services/selcom_checkout/
client.py's create_order_minimal() always signs under the real,
actual-payload field order — "default" — regardless of what this script
finds):

- The Create Order - Minimal shell headers example lists a
  Signed-Fields set (buyer_user_id, payment_methods, payer_remarks,
  order_items) that doesn't match any example payload shown for this
  endpoint — those fields most likely belong to the full Create Order
  endpoint's docs, copy-pasted into the Minimal section by mistake.
  --signing-variant official-shell reproduces that shell list literally
  (as the *signature*, not the JSON body — see create_order_minimal()'s
  docstring) so a real sandbox response can confirm whether Selcom's
  server actually expects it. --signing-variant default (the default)
  signs under the real payload's own field order instead — this is what
  production code always uses.
- Timestamp format is separately unconfirmed: the shell headers describe
  "yyyy-dd-mm H:i:s", not the ISO-8601 signer.build_timestamp() produces
  by default. --timestamp-format php-style tests the alternative.

Never prints the API key, API secret, or a full buyer email/phone — only
a masked form, in both the outgoing request summary and Selcom's raw
response body.

Usage:

    python apps/api/scripts/test_selcom_checkout_create_order_minimal.py \\
      --buyer-email test@example.com \\
      --buyer-name "Sandbox Test" \\
      --buyer-phone 255700000000 \\
      --amount 8000

    # Diagnostic: try the shell's literal (body-mismatched) Signed-Fields
    python apps/api/scripts/test_selcom_checkout_create_order_minimal.py \\
      --buyer-email test@example.com --buyer-name "Sandbox Test" \\
      --buyer-phone 255700000000 --amount 8000 \\
      --signing-variant official-shell

Every flag has a matching env var fallback (SELCOM_TEST_BUYER_EMAIL,
SELCOM_TEST_BUYER_NAME, SELCOM_TEST_BUYER_PHONE, SELCOM_TEST_AMOUNT,
SELCOM_TEST_NO_OF_ITEMS) so it can be scripted without shell history
exposing values.
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

from app.config import get_settings
from app.core.errors import SelcomAPIError
from app.core.references import generate_reference
from app.services.selcom_checkout.client import (
    SelcomCheckoutHTTPClient,
    get_selcom_checkout_credentials,
)
from app.services.selcom_checkout.errors import SelcomCheckoutMisconfiguredError
from app.services.selcom_checkout.signer import (
    build_timestamp,
    build_timestamp_php_style,
)


def _mask_email(value: str) -> str:
    if "@" not in value:
        return "*" * len(value)
    local, _, domain = value.partition("@")
    masked_local = local[0] + "*" * max(len(local) - 1, 0)
    return f"{masked_local}@{domain}"


def _mask_phone(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


def _mask_response_body(response: dict) -> dict:
    """Best-effort redaction — Selcom's own data, not a secret of ours,
    but buyer contact details are still sensitive."""
    masked = dict(response)
    data = masked.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        masked = {**masked, "data": [dict(data[0])]}
    return masked


def _env_or_arg(arg_value: str | None, env_name: str) -> str | None:
    if arg_value is not None:
        return arg_value
    return os.environ.get(env_name)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--order-id", default=None, help="default: generated")
    parser.add_argument("--buyer-email", default=None, help="env: SELCOM_TEST_BUYER_EMAIL")
    parser.add_argument("--buyer-name", default=None, help="env: SELCOM_TEST_BUYER_NAME")
    parser.add_argument("--buyer-phone", default=None, help="env: SELCOM_TEST_BUYER_PHONE (255XXXXXXXXX)")
    parser.add_argument("--amount", default=None, help="env: SELCOM_TEST_AMOUNT")
    parser.add_argument("--no-of-items", default=None, help="env: SELCOM_TEST_NO_OF_ITEMS (default: 1)")
    parser.add_argument(
        "--signing-variant",
        choices=("default", "official-shell"),
        default="default",
        help="'default' (production's real behavior) or 'official-shell' — diagnostic only, "
        "signs under the docs' literal (body-mismatched) shell field list. See module docstring.",
    )
    parser.add_argument(
        "--timestamp-format",
        choices=("iso8601", "php-style"),
        default="iso8601",
        help="'iso8601' (production default) or 'php-style' ('yyyy-dd-mm H:i:s', the shell headers' "
        "literal description) — diagnostic only.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()

    order_id = args.order_id or generate_reference("ORD-SANDBOX")
    buyer_email = _env_or_arg(args.buyer_email, "SELCOM_TEST_BUYER_EMAIL")
    buyer_name = _env_or_arg(args.buyer_name, "SELCOM_TEST_BUYER_NAME")
    buyer_phone = _env_or_arg(args.buyer_phone, "SELCOM_TEST_BUYER_PHONE")
    amount = _env_or_arg(args.amount, "SELCOM_TEST_AMOUNT")
    no_of_items = _env_or_arg(args.no_of_items, "SELCOM_TEST_NO_OF_ITEMS") or "1"

    missing = [
        flag
        for flag, value in [
            ("--buyer-email", buyer_email),
            ("--buyer-name", buyer_name),
            ("--buyer-phone", buyer_phone),
            ("--amount", amount),
        ]
        if not value
    ]
    if missing:
        print(f"Missing required value(s): {', '.join(missing)} (pass as a flag or matching env var)", file=sys.stderr)
        return 2

    settings = get_settings()

    print(
        "Confirmed 2026-08-22: InfinityPay has no Selcom Checkout sandbox — "
        "SELCOM_CHECKOUT_BASE_URL is a real production endpoint with real production "
        "credentials. This call creates a real order shell on Selcom's live system "
        "(no charge to any customer — create-order-minimal never triggers a push or "
        "moves money by itself; that only happens via a separate wallet-payment call, "
        "not made by this script)."
    )
    print(f"  SELCOM_CHECKOUT_BASE_URL:  {settings.selcom_checkout_base_url or '(not set)'}")
    print(f"  SELCOM_CHECKOUT_MODE:      {settings.selcom_checkout_mode}")
    confirm = input("Type 'yes' to confirm you intend to create a real order on Selcom's live system: ")
    if confirm.strip().lower() != "yes":
        print("Aborted.", file=sys.stderr)
        return 1

    timestamp = build_timestamp_php_style() if args.timestamp_format == "php-style" else build_timestamp()

    print()
    print("Request summary (masked):")
    print(f"  order_id:            {order_id}")
    print(f"  buyer_email:         {_mask_email(buyer_email)}")
    print(f"  buyer_name:          {buyer_name}")
    print(f"  buyer_phone:         {_mask_phone(buyer_phone)}")
    print(f"  amount:              {amount}")
    print(f"  no_of_items:         {no_of_items}")
    print(f"  api_key_configured:  {bool(settings.selcom_checkout_api_key)}")
    print(f"  digest_method:       {settings.selcom_checkout_digest_method}")
    print(f"  signing_variant:     {args.signing_variant}")
    print(f"  timestamp_format:    {args.timestamp_format}")
    print(f"  timestamp:           {timestamp}")
    print()

    try:
        client = SelcomCheckoutHTTPClient(credentials=get_selcom_checkout_credentials(settings))
    except SelcomCheckoutMisconfiguredError as exc:
        print(f"Client misconfigured: {exc}", file=sys.stderr)
        return 2

    # This script only ever sends the required fields (no CLI flag exists
    # here for webhook/redirect_url/cancel_url/buyer_remarks/
    # merchant_remarks/gateway styling) — so the Signed-Fields value is
    # fully determined by --signing-variant alone. If a future edit adds
    # more optional-field flags to this script, update this preview to
    # match, or better, compute it from the same field-construction logic
    # create_order_minimal() uses rather than hand-typing it again.
    if args.signing_variant == "official-shell":
        signed_fields_preview = (
            "vendor,order_id,buyer_email,buyer_name,buyer_user_id,buyer_phone,amount,currency,"
            "payment_methods,order_items"
        )
    else:
        signed_fields_preview = "vendor,order_id,buyer_email,buyer_name,buyer_phone,amount,currency,no_of_items"
    print(f"Signed-Fields to be used: {signed_fields_preview}")
    print()

    try:
        result = await client.create_order_minimal(
            order_id=order_id,
            buyer_email=buyer_email,
            buyer_name=buyer_name,
            buyer_phone=buyer_phone,
            amount=amount,
            no_of_items=int(no_of_items),
            timestamp=timestamp,
            signed_fields_variant=args.signing_variant,
        )
    except SelcomAPIError as exc:
        print("Selcom API error:")
        print(f"  message:                {exc.message}")
        print(f"  provider_status_code:   {exc.provider_status_code}")
        if exc.provider_response_body is not None:
            print(f"  provider_response_body: {_mask_response_body(exc.provider_response_body)}")
        return 1

    print("Result:")
    print(f"  resultcode:   {result.resultcode}")
    print(f"  result:       {result.result}")
    print(f"  message:      {result.message}")
    print(f"  is_success:   {result.is_success}")
    print(f"  reference:    {result.reference}")
    print(f"  payment_token: {result.payment_token}")
    print(f"  qr:           {result.qr}")
    print(f"  payment_gateway_url: {result.payment_gateway_url}")
    print()
    print("Raw Selcom response body (buyer-shaped fields masked):")
    print(_mask_response_body(result.raw_response))

    if not result.is_success:
        print()
        print(
            "Order was not created successfully — see resultcode/message above. "
            "Do not proceed to wallet-payment integration until this returns SUCCESS."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
