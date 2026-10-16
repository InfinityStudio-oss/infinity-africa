"""The OasisTech BulkSMS adapter.

Verified against https://bulksms.oasistech.co.tz/llms-full.txt on
2026-10-17. Everything this file assumes about the provider is written
down here, because the difference between two of its responses is the
difference between a merchant getting one text and getting two.

**The one rule.** A response we did not understand is never retried with a
fresh idempotency key. The key is derived from the collection and stored
on the row before the first attempt (app/services/sms_messages.py), so
every retry of a given message carries the identical key for the full 30
days the provider remembers it. That is what makes a timeout safe: the
provider recognises the replay, returns the original response and charges
nothing. Minting a new key to "try again cleanly" is the one action that
would turn an uncertain outcome into a duplicate SMS.

**Outcomes, and why they differ.**
  sent       200 - the gateway accepted it. NOT a handset delivery receipt.
  pending    202 - the provider could not confirm in time. Documented as
             most likely sent and charged. Never resend.
  duplicate  409 already_processed, or an idempotent replay. Already sent.
  failed     the provider refused it and did not charge. Safe to retry.
  throttled  429. Retry after the interval it names.
  no_credits 402. Retrying cannot help until somebody buys credits.
  config     400/403/415/422. A person has to fix something; retrying a
             malformed request or an unapproved sender just burns calls.
  unknown    we have no idea. Retried with the same key, never a new one.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import get_settings
from app.core.rate_limit import RateLimitExceededError, enforce_rate_limit

logger = logging.getLogger("infinity.sms")

SEND_PATH = "/v1/sms"
BALANCE_PATH = "/v1/balance"

# Terminal: the message reached a final state and must never be offered
# again. 'failed' is absent on purpose - a refused message was not charged
# and can be retried.
TERMINAL_OUTCOMES = frozenset({"sent", "pending", "duplicate"})


@dataclass
class SmsResult:
    outcome: str
    status_code: int | None = None
    provider_sms_log_id: str | None = None
    provider_ref: str | None = None
    provider_status: str | None = None
    credits_used: float | None = None
    retry_after_seconds: int | None = None
    error: str | None = None
    # dry_run only
    segments: int | None = None
    credits_required: float | None = None
    enough_credits: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class SmsNotConfigured(RuntimeError):
    """No API key or no sender ID. Raised rather than returned: this is a
    deployment mistake, not a per-message outcome, and it should stop a
    sweep rather than mark 60 messages failed."""


def _headers(idempotency_key: str | None) -> dict[str, str]:
    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.oasis_sms_api_key}",
        "Content-Type": "application/json",
    }
    if idempotency_key:
        # Header rather than the body field: documented to win if both are
        # set, so sending only the header leaves no chance of the two
        # disagreeing.
        headers["Idempotency-Key"] = idempotency_key
    return headers


def reserve_send_slot() -> None:
    """Take one slot from the account's 300-requests-per-minute budget.

    Raises RateLimitExceededError when the budget is spent, which stops
    the current batch rather than queueing behind a sleep - the sweep runs
    again shortly and the messages are still there.

    This is an in-process counter, and it is equivalent to an account-wide
    one only because the dispatch sweep holds the 'sms_dispatch' scheduler
    lease and so runs in exactly one replica at a time. That is a real
    coupling: drop the lease and this silently becomes a per-replica
    limit, letting two replicas send 2x the account's budget.
    """
    settings = get_settings()
    enforce_rate_limit(
        scope="oasis_sms_send",
        key="account",
        limit=settings.oasis_sms_rate_limit_per_minute,
        window_seconds=60,
    )


def _classify(response: httpx.Response) -> SmsResult:
    """Map one provider response onto an outcome. All of the care in this
    module is here."""
    code = response.status_code
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 — a non-JSON body is still a status code
        body = {}

    status = str(body.get("status") or "")
    # Documented on the response AND as a header. Either means the
    # provider replayed an earlier send: it did not send again, and the
    # original message is already on its way.
    replayed = bool(body.get("idempotent_replay")) or (
        response.headers.get("Idempotent-Replayed", "").lower() == "true"
    )

    first = {}
    results = body.get("results") or body.get("recipients") or []
    if isinstance(results, list) and results:
        first = results[0] if isinstance(results[0], dict) else {}
    credit_info = body.get("credit_info") or {}

    common = {
        "status_code": code,
        "provider_sms_log_id": str(first.get("sms_log_id")) if first.get("sms_log_id") else None,
        "provider_ref": str(first.get("provider_ref")) if first.get("provider_ref") else None,
        "provider_status": status or None,
        "credits_used": _as_float(first.get("credits_used") or credit_info.get("credits_charged")),
        "raw": body if isinstance(body, dict) else {},
    }

    if code == 200:
        return SmsResult(outcome="duplicate" if replayed else "sent", **common)

    if code == 202:
        # pending / scheduled / processing. All three mean the provider has
        # taken responsibility for it and we must not send again.
        return SmsResult(outcome="pending", **common)

    if code == 409:
        # already_processed: the key is older than the 30-day window, or a
        # first request with this key is still in flight. Documented
        # explicitly: treat as already sent, do not resend with a new key.
        return SmsResult(outcome="duplicate", **common)

    if code == 429:
        retry_after = _as_int(
            response.headers.get("Retry-After") or body.get("retry_after_seconds")
        )
        return SmsResult(
            outcome="throttled",
            retry_after_seconds=retry_after or 60,
            error="Provider rate limit reached",
            **common,
        )

    if code == 402:
        required = body.get("credits_required")
        available = body.get("credits_available")
        return SmsResult(
            outcome="no_credits",
            error=f"Insufficient SMS credits (required {required}, available {available})",
            **common,
        )

    if code in (400, 401, 403, 415, 422):
        # A person has to change something: a malformed request, a revoked
        # token, an unapproved sender, failed KYC, every recipient on the
        # do-not-call list, or a key reused for a different message. None
        # of these improve by being retried, and the brief asks for them to
        # fail or pause visibly rather than churn.
        return SmsResult(
            outcome="config",
            error=_error_text(body) or f"Provider rejected the request ({code})",
            **common,
        )

    if code == 502:
        # failed / partial: the gateway refused at least one recipient and
        # did not charge for it. We send one recipient per request, so this
        # is a plain refusal and is safe to retry.
        return SmsResult(
            outcome="failed", error=_error_text(body) or "Gateway refused the message", **common
        )

    if code == 503:
        # Gateway not configured or paused. Documented: retry later with
        # the same key.
        return SmsResult(
            outcome="failed", retry_after_seconds=300, error="Provider gateway unavailable", **common
        )

    if 500 <= code < 600:
        # Any other 5xx. We do not know whether it was sent, so it is
        # unknown rather than failed - and the stable key is what makes
        # retrying it safe.
        return SmsResult(outcome="unknown", error=f"Provider error {code}", **common)

    return SmsResult(outcome="unknown", error=f"Unexpected provider response {code}", **common)


def _error_text(body: dict) -> str | None:
    for key in ("error", "message", "detail", "hint"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value[:300]
    return None


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def send_sms(
    *, to: str, sender: str, message: str, idempotency_key: str, dry_run: bool = False
) -> SmsResult:
    """One message to one recipient.

    One recipient per request on purpose. The provider supports batching,
    but a batch returns per-recipient results that then have to be
    reconciled against our rows, and a partial failure inside a batch is
    far easier to mishandle than a failure of a request that only ever had
    one message in it. At 60 merchants the request count is not the
    constraint; correctness is.

    Never raises for a provider answer - every outcome comes back as an
    SmsResult. Raises only SmsNotConfigured, which is a deployment fault.
    """
    settings = get_settings()
    if not settings.oasis_sms_api_key or not sender:
        raise SmsNotConfigured("OASIS_SMS_API_KEY / OASIS_SMS_SENDER_ID are not configured")

    payload: dict[str, Any] = {"to": to, "sender": sender, "message": message}
    if dry_run:
        # Documented as never consuming the idempotency key, never
        # charging and never storing anything - which is what makes it
        # usable for a cost check before a campaign.
        payload["dry_run"] = True

    url = f"{settings.oasis_sms_base_url.rstrip('/')}{SEND_PATH}"
    try:
        response = httpx.post(
            url,
            json=payload,
            headers=_headers(None if dry_run else idempotency_key),
            # The documented minimum. A shorter timeout would turn slow
            # successes into timeouts, and a timeout is the outcome that
            # costs the most to reason about.
            timeout=settings.oasis_sms_timeout_seconds,
        )
    except httpx.TimeoutException:
        # Safe to retry *with the same key*: either it never arrived, or
        # it did and the replay will return the original response.
        return SmsResult(outcome="unknown", error="Timed out waiting for the provider")
    except httpx.HTTPError as exc:
        return SmsResult(outcome="unknown", error=f"Could not reach the provider: {type(exc).__name__}")

    if dry_run:
        return _classify_dry_run(response)
    return _classify(response)


def _classify_dry_run(response: httpx.Response) -> SmsResult:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = {}
    if response.status_code != 200:
        return SmsResult(
            outcome="config",
            status_code=response.status_code,
            error=_error_text(body) or f"Dry run rejected ({response.status_code})",
            raw=body if isinstance(body, dict) else {},
        )
    return SmsResult(
        outcome="dry_run",
        status_code=200,
        segments=_as_int(body.get("segments")),
        credits_required=_as_float(body.get("credits_required")),
        enough_credits=bool(body.get("enough_credits")),
        raw=body if isinstance(body, dict) else {},
    )


def get_balance() -> float | None:
    """Remaining provider credits, or None if we cannot tell.

    Shown on the Super Admin SMS overview. Never raises: a credit figure
    is useful context, not something worth failing a page over.
    """
    settings = get_settings()
    if not settings.oasis_sms_api_key:
        return None
    try:
        response = httpx.get(
            f"{settings.oasis_sms_base_url.rstrip('/')}{BALANCE_PATH}",
            headers=_headers(None),
            timeout=15,
        )
        if response.status_code != 200:
            return None
        return _as_float(response.json().get("credits"))
    except Exception:  # noqa: BLE001 — display-only
        logger.info("sms_balance_unavailable")
        return None


__all__ = [
    "TERMINAL_OUTCOMES",
    "RateLimitExceededError",
    "SmsNotConfigured",
    "SmsResult",
    "get_balance",
    "reserve_send_slot",
    "send_sms",
]
