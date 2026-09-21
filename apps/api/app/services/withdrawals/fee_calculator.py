"""Withdrawal fee calculation (calculate_withdrawal_fee) and
merchant_pricing_rules precedence lookup (find_pricing_rule).

MVP pricing policy (2026-08-31): InfinityPay earns fees from
collections only — calculate_withdrawal_fee always returns zero fees now
(see its own docstring), regardless of what's configured in
merchant_pricing_rules. That table and find_pricing_rule below are NOT
dead code, though: app/services/api_access.py::has_resolvable_pricing_rule
still calls find_pricing_rule as a production-API-eligibility gate ("has
this merchant been assigned pricing at all") — unrelated to fee amounts.

find_pricing_rule's precedence (most to least specific):
  1. merchant + destination_code
  2. merchant + channel (destination_code null)
  3. merchant default (channel and destination_code both null)
  4. platform fallback (merchant_id null), itself searched in the same
     destination -> channel -> generic order — a robustness addition
     beyond the literal 4-tier spec, so a platform-wide per-channel
     default can still beat a fully generic platform rule.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from supabase import Client

from app.schemas.enums import DestinationCode, DisbursementMethod
from app.schemas.withdrawals import FeeBreakdown


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _query_candidates(
    client: Client, *, merchant_id: uuid.UUID | None, channel: str | None, destination_code: str | None
) -> list[dict]:
    query = client.table("merchant_pricing_rules").select("*").eq("is_active", True)
    query = query.eq("merchant_id", str(merchant_id)) if merchant_id else query.is_("merchant_id", "null")
    query = query.eq("channel", channel) if channel else query.is_("channel", "null")
    query = (
        query.eq("destination_code", destination_code) if destination_code else query.is_("destination_code", "null")
    )
    result = query.execute()
    return result.data or []


def _pick_active_now(candidates: list[dict], now: datetime) -> dict | None:
    live = []
    for rule in candidates:
        if _parse_dt(rule["effective_from"]) > now:
            continue
        effective_to = rule.get("effective_to")
        if effective_to is not None and _parse_dt(effective_to) <= now:
            continue
        live.append(rule)
    if not live:
        return None
    # Most-recently-created wins if more than one active rule somehow
    # matches the same tier (shouldn't happen for well-formed data, but
    # avoids an arbitrary/undefined pick).
    return max(live, key=lambda r: r["created_at"])


def find_pricing_rule(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    channel: DisbursementMethod | str,
    destination_code: DestinationCode | str,
) -> dict | None:
    channel_value = channel.value if isinstance(channel, DisbursementMethod) else channel
    destination_value = destination_code.value if isinstance(destination_code, DestinationCode) else destination_code
    now = datetime.now(timezone.utc)

    tiers: list[tuple[uuid.UUID | None, str | None, str | None]] = [
        (merchant_id, channel_value, destination_value),
        (merchant_id, channel_value, None),
        (merchant_id, None, None),
        (None, channel_value, destination_value),
        (None, channel_value, None),
        (None, None, None),
    ]
    for tier_merchant_id, tier_channel, tier_destination in tiers:
        candidates = _query_candidates(
            client, merchant_id=tier_merchant_id, channel=tier_channel, destination_code=tier_destination
        )
        rule = _pick_active_now(candidates, now)
        if rule:
            return rule
    return None


def calculate_withdrawal_fee(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    amount: Decimal,
    channel: DisbursementMethod | str,
    destination_code: DestinationCode | str,
) -> FeeBreakdown:
    """MVP pricing policy (2026-08-31): InfinityPay earns fees from
    collections only — withdrawals never charge the merchant anything,
    regardless of any merchant_pricing_rules row that exists. No
    percentage fee, no flat fee, no processor charge passed through;
    `total_reserved_amount` and `recipient_net_amount` both always equal
    the requested `amount` exactly, so a withdrawal reserves/debits the
    merchant's wallet for precisely what they asked to withdraw.

    Deliberately does not call find_pricing_rule at all — a configured
    rule (if any exists, e.g. left over from before this policy) is
    never consulted for the amount math. find_pricing_rule itself is
    unrelated to fees now, still called elsewhere purely as an
    eligibility gate (app/services/api_access.py::has_resolvable_pricing_rule
    — "has this merchant been assigned pricing at all", independent of
    what that pricing actually charges) — not this function's concern.

    If InfinityPay ever needs to track a real provider disbursement
    cost, that must be recorded as an internal platform cost (a separate
    field/table), never deducted from what the merchant receives —
    intentionally not built here; nothing today reads merchant_pricing_rules
    for a disbursement's amount math."""
    channel_value = channel.value if isinstance(channel, DisbursementMethod) else channel
    destination_value = destination_code.value if isinstance(destination_code, DestinationCode) else destination_code

    return FeeBreakdown(
        withdrawal_amount=amount,
        processor_charge=Decimal(0),
        infinity_fee=Decimal(0),
        percentage_fee=Decimal(0),
        flat_fee=Decimal(0),
        total_charges=Decimal(0),
        total_reserved_amount=amount,
        recipient_net_amount=amount,
        channel=channel_value,
        destination_code=destination_value,
        pricing_rule_id=None,
        pricing_rule_label=None,
        processor_fee_pass_through=False,
    )
