"""Response-field parsing for the Selcom Business Disbursement API.

**Verified against a real sandbox response** as of 2026-08-21 — see
docs/selcom-sandbox-test-accounts.md. Two real examples confirmed via
apps/api/scripts/test_selcom_disbursement_sandbox.py's `bank` preset
(processing) and `selcom` preset (failed):

    # processing (HTTP 200)
    {"success": true, "error_code": 1, "message": "Transaction processed successfully.",
     "result": "INPROGRESS", "resultcode": "111",
     "data": {"trans_id": "...", "selcom_receipt": "SBS-...", "status": "ACCEPTED",
               "amount": 1300, "principal_amount": 1000, "total_charges": 300,
               "charges_summary": "...", "currency": "TZS"}}

    # failed (HTTP 400 — raised as SelcomAPIError before reaching this module;
    # kept here too in case Selcom ever returns a FAIL result on a 200)
    {"success": false, "error_code": -40, "message": "Invalid account number for the provided bank/FI code.",
     "result": "FAIL", "resultcode": "-40", "data": []}

Two things the earlier guessed field names got wrong, now fixed: the
transaction id and receipt are nested inside `data`, not top-level, and the
real "processing" code is `"111"`, not the guessed `"001"`. `"927"`
(processing) and `"999"` (ambiguous) are Selcom-documented codes not yet
seen in a real response — included per docs/selcom-sandbox-test-accounts.md's
result-interpretation table, not a guess. `data` is `[]` (not a dict) on
failure — handled below rather than assumed to always be a dict.

**Verified against a real production `SUCCESS` response** (status-check
call, not the initial process call) as of 2026-08-22 — first real pilot
withdrawal, transaction `DIS-20260822-79DEB2B1`:

    {"success": true, "error_code": "000", "resultcode": "000", "result": "SUCCESS",
     "message": "Transaction status retrieved.",
     "data": {"transId": "DIS-20260822-79DEB2B1", "selcomReceipt": "SB0822PB1PU",
               "status": "COMPLETED", "amount": "1000.00", "principalAmount": "1000.00",
               "totalCharges": "0.00", "currency": "TZS", "senderAccount": "5529108708283",
               "senderName": "INFINITY DISBURSEMENT", "createdAt": "...", "updatedAt": "...",
               "transDatetime": "...", "chargesSummary": "-", "receiptMessage": "-"}}

Here `trans_id`/`selcom_receipt` are camelCase (`transId`/`selcomReceipt`),
still nested inside `data` — a third shape variant distinct from both the
sandbox example above and the guessed top-level camelCase originally coded
for. `_extract_transaction_id`/`_extract_receipt` check both casings, both
nesting levels.
"""

from decimal import Decimal, InvalidOperation

from app.services.selcom_business.schemas import (
    SelcomBusinessResult,
    SelcomBusinessStatus,
)

_TEXT_TO_STATUS: dict[str, SelcomBusinessStatus] = {
    "success": "successful",
    "successful": "successful",
    "completed": "successful",
    "pending": "processing",
    "processing": "processing",
    "accepted": "processing",
    "inprogress": "processing",
    "ambiguous": "ambiguous",
    "unknown": "ambiguous",
    "fail": "failed",
    "failed": "failed",
}

_RESULTCODE_TO_STATUS: dict[str, SelcomBusinessStatus] = {
    "000": "successful",
    "111": "processing",
    "927": "processing",
    "999": "ambiguous",
}


def _extract_status(response: dict) -> SelcomBusinessStatus:
    raw_text = str(
        response.get("result") or response.get("status") or response.get("transactionStatus") or ""
    ).strip().lower()
    if raw_text in _TEXT_TO_STATUS:
        return _TEXT_TO_STATUS[raw_text]

    resultcode = str(response.get("resultcode") or "").strip()
    if resultcode in _RESULTCODE_TO_STATUS:
        return _RESULTCODE_TO_STATUS[resultcode]

    return "failed"


def _response_data(response: dict) -> dict:
    """The nested `data` object on a real response — a dict on success/
    processing, an empty list `[]` (confirmed) on failure. Never assume
    it's a dict."""
    data = response.get("data")
    return data if isinstance(data, dict) else {}


def _extract_transaction_id(response: dict, *, fallback: str) -> str:
    data = _response_data(response)
    return str(
        data.get("trans_id")
        or data.get("transId")
        or response.get("transId")
        or response.get("transactionId")
        or response.get("reference")
        or fallback
    )


def _extract_receipt(response: dict) -> str | None:
    data = _response_data(response)
    receipt = (
        data.get("selcom_receipt")
        or data.get("selcomReceipt")
        or response.get("receipt")
        or response.get("receiptNumber")
        or response.get("selcomReceipt")
    )
    return str(receipt) if receipt else None


def parse_transaction_result(response: dict, *, trans_id: str) -> SelcomBusinessResult:
    status = _extract_status(response)
    failure_reason = None
    if status == "failed":
        failure_reason = str(
            response.get("message") or response.get("reason") or "Selcom reported this transaction failed"
        )
    return SelcomBusinessResult(
        transaction_id=_extract_transaction_id(response, fallback=trans_id),
        status=status,
        receipt=_extract_receipt(response),
        failure_reason=failure_reason,
        raw_status=str(response.get("result") or response.get("status") or ""),
        raw_response=response,
    )


# Candidate keys for the account holder's name on GET /account/lookup.
#
# Unlike everything above, this one is NOT verified against a real
# response: Selcom's docs show the request for /account/lookup but no
# example response body, and no lookup has been round-tripped yet. The
# ordering follows the shapes Selcom does use elsewhere — a real
# /transaction/query response carries `senderName` inside `data`, so a
# camelCase `...Name` under `data` is the most likely home for it.
#
# If none match, this returns None and the caller shows "Name not
# available". It never falls back to something else in the payload: a
# wrong name on a payout confirmation is worse than no name.
_ACCOUNT_NAME_KEYS = (
    "accountName",
    "account_name",
    "recipientName",
    "recipient_name",
    "customerName",
    "customer_name",
    "fullName",
    "full_name",
    "name",
)


def parse_account_name(response: dict) -> str | None:
    """The account holder's name from a GET /account/lookup response, or
    None if this response doesn't carry one in any shape we recognise.

    Checks `data` first, then the top level, since every verified Selcom
    response nests its payload under `data`.
    """
    if not isinstance(response, dict):
        return None

    for source in (_response_data(response), response):
        for key in _ACCOUNT_NAME_KEYS:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def account_lookup_succeeded(response: dict) -> bool:
    """Whether the lookup itself reported success.

    A lookup for an account that does not exist is a normal answer, not an
    error — Selcom returns success=false with a message. Either way the
    caller shows "Name not available"; this only exists so the two can be
    told apart in a log.
    """
    if not isinstance(response, dict):
        return False
    if response.get("success") is True:
        return True
    return str(response.get("result") or "").strip().upper() in {"SUCCESS", "COMPLETED"}


def unrecognised_lookup_shape(response: dict) -> list[str]:
    """The keys a lookup response actually carried, for the log line that
    fires when no name could be found.

    Keys only — never values. The point is to learn the real field name
    from the first live call (the same way the Selcom Checkout webhook's
    real header casing was learned), without writing an account holder's
    name into the logs to do it.
    """
    if not isinstance(response, dict):
        return []
    keys = sorted(str(k) for k in response)
    data = _response_data(response)
    return keys + sorted(f"data.{k}" for k in data)


# Candidate keys for the float figure on POST /balance.
#
# NOT verified against a real response — same caveat as _ACCOUNT_NAME_KEYS
# above. Selcom's docs show the request but no example body, and no
# balance call has been round-tripped yet. The ordering follows the shapes
# Selcom does use elsewhere: a nested `data` object, snake_case in the
# sandbox and camelCase in production, so both are checked at both levels.
#
# If none match this returns None and the caller shows "unavailable". It
# never falls back to some other number in the payload: a wrong float
# balance would be worse than no balance, because it is the number an
# operator would decide to approve a payout on.
_BALANCE_KEYS = (
    "balance",
    "available_balance",
    "availableBalance",
    "current_balance",
    "currentBalance",
    "amount",
)


def parse_float_balance(response: dict) -> Decimal | None:
    """The disbursement account's available float, or None if this
    response doesn't carry one in a shape we recognise."""
    if not isinstance(response, dict):
        return None

    for source in (_response_data(response), response):
        for key in _BALANCE_KEYS:
            value = source.get(key)
            if value is None or isinstance(value, bool):
                continue
            try:
                return Decimal(str(value).replace(",", "").strip())
            except (InvalidOperation, ValueError):
                continue
    return None
