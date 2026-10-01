"""Fraud/risk monitoring rules engine.

Runs after collection initiation and after collection resolution (which
covers payment-link and invoice payments too — both already route through
resolve_collection(), see app/services/collections.py). Six rules are
implemented, matching fraud_rules' seeded rows exactly
(supabase/migrations/20260817090000_fraud_monitoring.sql); tuning a
threshold is a data change to that table, not a code change.

Never accuses anyone of fraud — every alert reason uses neutral wording
("suspicious activity detected", "requires review"). Wrapped so a failure
here can never break a real payment flow: evaluate_collection() swallows
its own exceptions and returns an empty list rather than propagating.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from supabase import Client

from app.config.settings import get_settings
from app.schemas.enums import NotificationType
from app.services.crud import execute_maybe_single, get_by_id, insert_row, update_row
from app.services.notifications_service import notify_merchant

_RISK_LEVEL_BY_RULE = {
    "SAME_PHONE_SAME_AMOUNT_SECONDS": "HIGH",
    "SAME_PHONE_TOO_MANY_ATTEMPTS": "MEDIUM",
    "DUPLICATE_REFERENCE": "HIGH",
    "PAYMENT_AFTER_LINK_EXPIRY": "MEDIUM",
    "HIGH_VALUE_TRANSACTION": "MEDIUM",
    "HIGH_CHARGEBACK_MERCHANT": "CRITICAL",
    "SELF_PAYMENT_OWN_TILL": "CRITICAL",
}


def _normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits[-9:] if len(digits) >= 9 else digits or None


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _load_enabled_rules(client: Client) -> dict[str, dict]:
    rows = client.table("fraud_rules").select("*").eq("enabled", True).execute().data or []
    return {row["rule_code"]: row for row in rows}


def _upsert_transaction_review(
    client: Client, *, transaction_id: uuid.UUID, merchant_id: uuid.UUID, alert_id: uuid.UUID
) -> None:
    existing = execute_maybe_single(
        client.table("transaction_reviews").select("id").eq("transaction_id", str(transaction_id)).maybe_single()
    )
    if existing:
        update_row(
            client,
            "transaction_reviews",
            uuid.UUID(existing["id"]),
            {"status": "UNDER_REVIEW", "latest_alert_id": str(alert_id)},
        )
    else:
        insert_row(
            client,
            "transaction_reviews",
            {
                "transaction_id": str(transaction_id),
                "merchant_id": str(merchant_id),
                "status": "UNDER_REVIEW",
                "latest_alert_id": str(alert_id),
            },
        )


def _raise_alert(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    transaction_id: uuid.UUID | None,
    customer_phone: str | None,
    rule_code: str,
    reason: str,
    metadata: dict | None = None,
) -> dict:
    alert = insert_row(
        client,
        "fraud_alerts",
        {
            "merchant_id": str(merchant_id),
            "transaction_id": str(transaction_id) if transaction_id else None,
            "customer_phone": customer_phone,
            "rule_code": rule_code,
            "risk_level": _RISK_LEVEL_BY_RULE.get(rule_code, "MEDIUM"),
            "reason": reason,
            "status": "OPEN",
            "metadata": metadata or {},
        },
    )
    insert_row(
        client,
        "fraud_alert_events",
        {"alert_id": alert["id"], "actor_type": "system", "action": "created", "to_status": "OPEN", "note": reason},
    )
    if transaction_id:
        _upsert_transaction_review(client, transaction_id=transaction_id, merchant_id=merchant_id, alert_id=uuid.UUID(alert["id"]))
    notify_merchant(
        client,
        merchant_id=merchant_id,
        notification_type=NotificationType.FRAUD_ALERT,
        title="Suspicious activity detected",
        body=reason,
        related_resource_type="fraud_alert",
        related_resource_id=uuid.UUID(alert["id"]),
    )
    return alert


def _exceeds_self_payment_hold_threshold(collection: dict) -> bool:
    """Whether this self-payment is big enough to hold rather than just
    record. A threshold of 0 holds everything, which is where this rule
    started. An unreadable amount holds too — the safe direction when we
    cannot tell how much is moving."""
    threshold = get_settings().self_payment_hold_above_amount
    if threshold <= 0:
        return True
    try:
        return Decimal(str(collection.get("amount") or 0)) > threshold
    except (InvalidOperation, TypeError, ValueError):
        return True


def check_self_payment_risk(client: Client, *, collection: dict, transaction: dict | None) -> dict | None:
    """Gate, not just an alert: called from resolve_collection() *before*
    a collection is credited, so a self-payment/own-till match can hold
    the credit rather than only flag it after money already moved — the
    live incident this rule exists for ("Payment unsuccessful. You are
    trying to pay into your own till") was a case Selcom itself caught
    and reversed, but nothing here would have caught proactively.
    Returns the raised fraud_alerts row if the collection is held for
    review, None if it's clear to credit normally. Never raises — same
    "must never break a real payment flow" guarantee as evaluate_collection,
    just structured as a direct call so its return value can gate the
    caller instead of running fire-and-forget after the fact."""
    try:
        rules = _load_enabled_rules(client)
        if "SELF_PAYMENT_OWN_TILL" not in rules:
            return None

        phone = _normalize_phone(collection.get("customer_phone"))
        if not phone:
            return None

        merchant = get_by_id(client, "merchants", uuid.UUID(collection["merchant_id"]))
        merchant_phone = _normalize_phone(merchant.get("contact_phone")) if merchant else None
        if not merchant_phone or merchant_phone != phone:
            return None

        # Amount decides whether this holds or merely records. A
        # self-payment loses the payer the fee, so it is not profitable by
        # itself; what the hold guards against is paying in, withdrawing,
        # then disputing the original mobile money transaction, which only
        # pays off at size. Holding every one of them taxed the honest
        # case instead — testing from your own phone is the first thing
        # any integrator does, and it stranded their money at
        # pending_review with nothing on screen explaining why.
        held = _exceeds_self_payment_hold_threshold(collection)
        alert = _raise_alert(
            client,
            merchant_id=uuid.UUID(collection["merchant_id"]),
            transaction_id=uuid.UUID(transaction["id"]) if transaction else None,
            customer_phone=collection.get("customer_phone"),
            rule_code="SELF_PAYMENT_OWN_TILL",
            reason=(
                "Suspicious activity detected: the payer's phone number matches this merchant's own registered "
                "contact phone. Held for review before funds become available."
                if held
                else "The payer's phone number matches this merchant's own registered contact phone. Credited "
                "normally — below the amount that holds funds for review. Raised for visibility."
            ),
            metadata={"collection_id": collection["id"], "held": held},
        )
        # The alert is recorded either way; only a held one is returned,
        # because the caller gates on this value.
        return alert if held else None
    except Exception:  # noqa: BLE001 — a fraud-check failure must never break a real payment flow
        return None


def evaluate_collection(
    client: Client, *, collection: dict, transaction: dict | None, event: Literal["initiated", "resolved"]
) -> list[dict]:
    try:
        return _evaluate_collection(client, collection=collection, transaction=transaction, event=event)
    except Exception:  # noqa: BLE001 — a fraud-check failure must never break a real payment flow
        return []


def _evaluate_collection(
    client: Client, *, collection: dict, transaction: dict | None, event: Literal["initiated", "resolved"]
) -> list[dict]:
    rules = _load_enabled_rules(client)
    if not rules:
        return []

    merchant_id = uuid.UUID(collection["merchant_id"])
    transaction_id = uuid.UUID(transaction["id"]) if transaction else None
    phone = collection.get("customer_phone")
    amount = Decimal(str(collection["amount"]))
    alerts: list[dict] = []

    def raise_alert(rule_code: str, reason: str, metadata: dict | None = None) -> None:
        alerts.append(
            _raise_alert(
                client,
                merchant_id=merchant_id,
                transaction_id=transaction_id,
                customer_phone=phone,
                rule_code=rule_code,
                reason=reason,
                metadata=metadata,
            )
        )

    if event == "initiated":
        if phone and "SAME_PHONE_SAME_AMOUNT_SECONDS" in rules:
            window_seconds = rules["SAME_PHONE_SAME_AMOUNT_SECONDS"]["config"].get("window_seconds", 30)
            since = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
            rows = (
                client.table("collections")
                .select("id")
                .eq("customer_phone", phone)
                .eq("amount", str(amount))
                .gte("created_at", since)
                .execute()
            ).data or []
            matches = [r for r in rows if r["id"] != collection["id"]]
            if matches:
                raise_alert(
                    "SAME_PHONE_SAME_AMOUNT_SECONDS",
                    "Suspicious activity detected: this phone number paid the same amount multiple times within a short window. Transaction requires review.",
                    {"window_seconds": window_seconds, "matched_collection_ids": [r["id"] for r in matches]},
                )

        if phone and "SAME_PHONE_TOO_MANY_ATTEMPTS" in rules:
            cfg = rules["SAME_PHONE_TOO_MANY_ATTEMPTS"]["config"]
            window_minutes = cfg.get("window_minutes", 10)
            max_attempts = cfg.get("max_attempts", 5)
            since = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
            rows = (
                client.table("collections").select("id").eq("customer_phone", phone).gte("created_at", since).execute()
            ).data or []
            if len(rows) > max_attempts:
                raise_alert(
                    "SAME_PHONE_TOO_MANY_ATTEMPTS",
                    f"Suspicious activity detected: {len(rows)} payment attempts from this phone number in the last {window_minutes} minutes. Transaction requires review.",
                    {"attempt_count": len(rows), "window_minutes": window_minutes},
                )

        if collection.get("merchant_reference") and "DUPLICATE_REFERENCE" in rules:
            rows = (
                client.table("collections")
                .select("id")
                .eq("merchant_id", str(merchant_id))
                .eq("merchant_reference", collection["merchant_reference"])
                .execute()
            ).data or []
            matches = [r for r in rows if r["id"] != collection["id"]]
            if matches:
                raise_alert(
                    "DUPLICATE_REFERENCE",
                    "Suspicious activity detected: this merchant reference was reused across separate collections. Transaction requires review.",
                    {"merchant_reference": collection["merchant_reference"]},
                )

        if "HIGH_VALUE_TRANSACTION" in rules:
            threshold = Decimal(str(rules["HIGH_VALUE_TRANSACTION"]["config"].get("threshold_amount", 5000000)))
            if amount >= threshold:
                raise_alert(
                    "HIGH_VALUE_TRANSACTION",
                    f"Transaction requires review: amount {amount} meets or exceeds the platform's high-value threshold ({threshold}).",
                    {"threshold_amount": str(threshold)},
                )

    elif event == "resolved":
        if collection.get("payment_link_id") and "PAYMENT_AFTER_LINK_EXPIRY" in rules:
            link = get_by_id(client, "payment_links", uuid.UUID(collection["payment_link_id"]))
            expires_at = link.get("expires_at") if link else None
            completed_at = collection.get("completed_at")
            if expires_at and completed_at and _parse_dt(completed_at) > _parse_dt(expires_at):
                raise_alert(
                    "PAYMENT_AFTER_LINK_EXPIRY",
                    "Suspicious activity detected: payment completed after the payment link had already expired. Transaction requires review.",
                    {"expires_at": expires_at, "completed_at": completed_at},
                )

        if "HIGH_CHARGEBACK_MERCHANT" in rules:
            cfg = rules["HIGH_CHARGEBACK_MERCHANT"]["config"]
            window_days = cfg.get("window_days", 30)
            max_count = cfg.get("max_dispute_count", 3)
            since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
            disputes = (
                client.table("disputes").select("id").eq("merchant_id", str(merchant_id)).gte("created_at", since).execute()
            ).data or []
            if len(disputes) >= max_count:
                raise_alert(
                    "HIGH_CHARGEBACK_MERCHANT",
                    f"This merchant has {len(disputes)} disputes in the last {window_days} days — an unusually high rate. Transaction requires review.",
                    {"dispute_count": len(disputes), "window_days": window_days},
                )

    return alerts
