"""Audit log helper — every mutating router action calls this after the
fact, writing to the append-only public.audit_logs table.
"""

import logging
import uuid
from typing import Any, Literal

from supabase import Client

logger = logging.getLogger("infinity.audit")


def write_audit_log(
    client: Client,
    *,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    actor_type: Literal["user", "system", "api_key"] = "user",
    merchant_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    client.table("audit_logs").insert(
        {
            "actor_id": str(actor_id) if actor_id else None,
            "actor_type": actor_type,
            "merchant_id": str(merchant_id) if merchant_id else None,
            "action": action,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id else None,
            "metadata": metadata or {},
            "ip_address": ip_address,
            "user_agent": user_agent,
        }
    ).execute()


def write_audit_log_best_effort(client: Client, **kwargs: Any) -> None:
    """write_audit_log, but never propagates a failure.

    For records that describe something informational rather than a state
    change — a merchant looking at a withdrawal, or a request that was
    already being refused for its own reasons. Those calls sit on read-only
    or already-failing paths, where letting an audit insert raise would
    either break an endpoint that changes nothing or replace a clear,
    merchant-safe error with a 500.

    Deliberately NOT the default. An audit row that accompanies real money
    movement should fail loudly if it cannot be written.
    """
    try:
        write_audit_log(client, **kwargs)
    except Exception:  # pragma: no cover - defensive
        logger.exception("audit log write failed (action=%s)", kwargs.get("action"))
