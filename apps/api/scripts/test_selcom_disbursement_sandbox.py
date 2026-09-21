"""Direct Selcom Business Disbursement API connectivity test — bypasses
every merchant-facing/admin-console validation layer (phone-format
normalization, the withdrawal state machine, Super Admin approval) and
calls SelcomBusinessClient.process_transaction() directly, so RSA-SHA256
signing, network reachability, and Railway's outbound IP whitelisting can
be verified independently of Selcom's sandbox UI (which currently rejects
the sample account values Selcom's own docs provide — see
docs/test-accounts.md).

Manual use only — never wired into any route or test suite. Reads Selcom
sandbox credentials the same way the running app does
(get_selcom_business_client(), app/config/settings.py), so set them in
apps/api/.env for a local run:

    SELCOM_BUSINESS_MODE=sandbox
    SELCOM_BUSINESS_API_KEY=...
    SELCOM_BUSINESS_PRIVATE_KEY_BASE64=...
    SELCOM_BUSINESS_ACCOUNT_NUMBER=...

See docs/deployment-checklist.md for the full local-sandbox-env writeup and
docs/selcom-live-go-live.md for the IP-whitelisting background — Selcom's
sandbox enforces the same source-IP allowlist as production, so a run from
a machine whose IP Selcom hasn't whitelisted will fail with the same 611 /
HTTP 403 signal this script reports below, which is itself a useful,
distinct-from-signing-errors result.

Never prints the API key, private key, digest, or a full recipient account
number — only the last 4 characters of any account-shaped value, in both
the outgoing request summary and Selcom's raw response body.

Usage (from anywhere; the repo-relative apps/api path is resolved below):

    python apps/api/scripts/test_selcom_disbursement_sandbox.py \\
      --recipient-fi-code TESTBANK \\
      --recipient-account 8774738353235 \\
      --recipient-name "Sandbox Test" \\
      --amount 1000 \\
      --purpose "Sandbox withdrawal test" \\
      --remarks "InfinityPay sandbox direct test"

Or use one of the three known-good Selcom sandbox sample recipients via
--preset (selcom, bank, wallet — see docs/selcom-sandbox-test-accounts.md
for the full account list and where they come from):

    python apps/api/scripts/test_selcom_disbursement_sandbox.py \\
      --preset selcom --amount 1000 --purpose "Sandbox internal transfer test"

A --preset supplies recipient_fi_code/recipient_account/recipient_name;
any of --recipient-fi-code/--recipient-account/--recipient-name passed
alongside it overrides just that field. --amount/--purpose are still
required either way. recipient_account is space-normalized (spaces
stripped) before being sent, since Selcom's sandbox portal displays account
numbers with spaces (e.g. "87747 38533 235") but the API expects them
without ("8774738533235") — this applies to both --preset and
--recipient-account values, manual or otherwise.

Every flag has a matching env var fallback (SELCOM_TEST_RECIPIENT_FI_CODE,
SELCOM_TEST_RECIPIENT_ACCOUNT, SELCOM_TEST_RECIPIENT_NAME,
SELCOM_TEST_AMOUNT, SELCOM_TEST_PURPOSE, SELCOM_TEST_REMARKS,
SELCOM_TEST_TRANS_ID) so it can be scripted without shell history exposing
values. TESTBANK/TESTWALLET-style FI codes are fine here even if a
production app provider list would reject them — this script exists
specifically to bypass that layer for connectivity testing.

This is the same call site app/services/disbursements.py's Super-Admin
approval path uses in production
(get_selcom_business_client().process_transaction(...)) — nothing about
signing or transport differs, only that no disbursement row, ledger entry,
or merchant is involved.
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
from app.services.selcom_business.client import (
    SelcomBusinessMisconfiguredError,
    get_selcom_business_client,
)
from app.services.selcom_business.live_client import generate_trans_id

_ACCOUNT_LIKE_RESPONSE_KEYS = ("account", "recipientaccount", "accountnumber")

# Selcom sandbox portal sample recipients — see
# docs/selcom-sandbox-test-accounts.md. Sandbox-only; TESTBANK/TESTWALLET
# and this SELCOM-to-SELCOM account never resolve to anything in
# production. Account numbers here are already in API format (no spaces) —
# _normalize_account() strips spaces regardless, so pasting the portal's
# spaced display format also works.
_PRESETS: dict[str, dict[str, str]] = {
    "selcom": {
        "recipient_fi_code": "SELCOM",
        "recipient_account": "8774738533235",
        "recipient_name": "Sandbox Selcom to Selcom",
    },
    "bank": {
        "recipient_fi_code": "TESTBANK",
        "recipient_account": "4842318480086",
        "recipient_name": "Sandbox Bank",
    },
    "wallet": {
        "recipient_fi_code": "TESTWALLET",
        "recipient_account": "1140554577325",
        "recipient_name": "Sandbox Wallet",
    },
}


def _normalize_account(value: str) -> str:
    """Selcom's sandbox portal displays account numbers with spaces
    (e.g. "87747 38533 235") but the API expects them without. Sandbox
    sample values only — never applies real merchant phone-format
    validation (app/core/phone.py::normalize_tz_phone()), which is
    deliberately not imported into this script at all."""
    return value.replace(" ", "")


def _mask(value: str) -> str:
    """Keep only the last 4 characters — mirrors the rest of this
    codebase's rule of never logging a raw recipient account (see
    live_client.py's module docstring)."""
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


def _mask_response_body(response: dict) -> dict:
    """Best-effort redaction of any account-shaped field in Selcom's raw
    response before it's printed — the response is Selcom's own data, not
    a secret of ours, but a recipient account number is still sensitive."""
    masked = dict(response)
    for key, value in response.items():
        if isinstance(value, str) and key.lower() in _ACCOUNT_LIKE_RESPONSE_KEYS:
            masked[key] = _mask(value)
    return masked


def _env_or_arg(arg_value: str | None, env_name: str) -> str | None:
    if arg_value is not None:
        return arg_value
    return os.environ.get(env_name)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--preset",
        choices=sorted(_PRESETS),
        default=None,
        help="Known-good Selcom sandbox recipient — supplies recipient-fi-code/"
        "recipient-account/recipient-name; any of those three passed explicitly "
        "override just that field. See docs/selcom-sandbox-test-accounts.md.",
    )
    parser.add_argument("--trans-id", default=None, help="env: SELCOM_TEST_TRANS_ID (default: generated)")
    parser.add_argument("--recipient-fi-code", default=None, help="env: SELCOM_TEST_RECIPIENT_FI_CODE")
    parser.add_argument("--recipient-account", default=None, help="env: SELCOM_TEST_RECIPIENT_ACCOUNT")
    parser.add_argument("--recipient-name", default=None, help="env: SELCOM_TEST_RECIPIENT_NAME")
    parser.add_argument("--amount", default=None, help="env: SELCOM_TEST_AMOUNT")
    parser.add_argument("--purpose", default=None, help="env: SELCOM_TEST_PURPOSE")
    parser.add_argument("--remarks", default=None, help="env: SELCOM_TEST_REMARKS (optional)")
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()

    preset = _PRESETS[args.preset] if args.preset else None

    trans_id = _env_or_arg(args.trans_id, "SELCOM_TEST_TRANS_ID") or generate_trans_id()
    # Precedence: explicit --flag > matching env var > --preset value. A
    # --preset only fills in whichever of these three a manual value didn't
    # already supply — see the module docstring.
    recipient_fi_code = _env_or_arg(args.recipient_fi_code, "SELCOM_TEST_RECIPIENT_FI_CODE") or (
        preset["recipient_fi_code"] if preset else None
    )
    recipient_account = _env_or_arg(args.recipient_account, "SELCOM_TEST_RECIPIENT_ACCOUNT") or (
        preset["recipient_account"] if preset else None
    )
    recipient_name = _env_or_arg(args.recipient_name, "SELCOM_TEST_RECIPIENT_NAME") or (
        preset["recipient_name"] if preset else None
    )
    if recipient_account:
        recipient_account = _normalize_account(recipient_account)
    amount = _env_or_arg(args.amount, "SELCOM_TEST_AMOUNT")
    purpose = _env_or_arg(args.purpose, "SELCOM_TEST_PURPOSE")
    remarks = _env_or_arg(args.remarks, "SELCOM_TEST_REMARKS")

    missing = [
        flag
        for flag, value in [
            ("--recipient-fi-code", recipient_fi_code),
            ("--recipient-account", recipient_account),
            ("--recipient-name", recipient_name),
            ("--amount", amount),
            ("--purpose", purpose),
        ]
        if not value
    ]
    if missing:
        print(f"Missing required value(s): {', '.join(missing)} (pass as a flag or matching env var)", file=sys.stderr)
        return 2

    settings = get_settings()
    if settings.selcom_business_mode == "mock":
        print(
            "SELCOM_BUSINESS_MODE=mock never calls Selcom at all — set SELCOM_BUSINESS_MODE=sandbox "
            "in apps/api/.env to reach Selcom's real sandbox. See docs/deployment-checklist.md.",
            file=sys.stderr,
        )
        return 2
    if settings.selcom_business_mode == "live":
        confirm = input(
            "SELCOM_BUSINESS_MODE=live — this sends a REAL production payout via Selcom. "
            "Type 'yes' to continue, anything else to abort: "
        )
        if confirm.strip().lower() != "yes":
            print("Aborted.", file=sys.stderr)
            return 1

    print("Request summary (masked):")
    print(f"  preset:             {args.preset or '(none)'}")
    print(f"  trans_id:           {trans_id}")
    print(f"  recipient_fi_code:  {recipient_fi_code}")
    print(f"  recipient_account:  {_mask(recipient_account)}")
    print(f"  recipient_name:     {recipient_name}")
    print(f"  amount:             {amount}")
    print(f"  purpose:            {purpose}")
    print(f"  remarks:            {remarks or '(none)'}")
    print(f"  business_mode:      {settings.selcom_business_mode}")
    print(f"  api_key_configured: {bool(settings.selcom_business_api_key)}")
    print()

    try:
        client = get_selcom_business_client()
    except SelcomBusinessMisconfiguredError as exc:
        print(f"Client misconfigured: {exc}", file=sys.stderr)
        return 2

    try:
        result = await client.process_transaction(
            trans_id=trans_id,
            recipient_fi_code=recipient_fi_code,
            recipient_account=recipient_account,
            recipient_name=recipient_name,
            amount=amount,
            purpose=purpose,
            remarks=remarks,
        )
    except SelcomAPIError as exc:
        print("Selcom API error:")
        print(f"  message:                {exc.message}")
        print(f"  provider_status_code:   {exc.provider_status_code}")
        print(f"  is_ip_whitelist_error:  {exc.is_ip_whitelist_error}")
        if exc.provider_response_body is not None:
            print(f"  provider_response_body: {_mask_response_body(exc.provider_response_body)}")
        if exc.is_ip_whitelist_error:
            print(
                "  -> This machine's outbound IP likely isn't whitelisted by Selcom for this "
                "account/environment yet. Only Railway's static outbound IP has been shared with "
                "Selcom so far — a local run is expected to hit this until Selcom also whitelists "
                "your local IP, or this script is run somewhere that egresses through Railway's "
                "network. See docs/selcom-live-go-live.md."
            )
        return 1
    except (ValueError, TypeError) as exc:
        # Signing/key-loading failures (signing.py) — e.g. a blank or
        # malformed SELCOM_BUSINESS_PRIVATE_KEY_BASE64. Never contains the
        # key material itself, only a description of what's wrong with it.
        print(f"Signing/configuration error: {exc}", file=sys.stderr)
        return 2

    print("Result:")
    print(f"  status:           {result.status}")
    print(f"  transaction_id:   {result.transaction_id}")
    print(f"  receipt:          {result.receipt}")
    print(f"  failure_reason:   {result.failure_reason}")
    print(f"  raw_status:       {result.raw_status}")
    print()
    print("Raw Selcom response body (account-shaped fields masked):")
    print(_mask_response_body(result.raw_response))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
