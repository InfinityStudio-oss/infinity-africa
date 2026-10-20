"""Audit log helper — every mutating router action calls this after the
fact, writing to the append-only public.audit_logs table.
"""

import logging
import uuid
from typing import Any, Literal

from supabase import Client

from app.core.monitoring import capture_exception

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
    record_metadata = dict(metadata or {})
    stored_actor_id = str(actor_id) if actor_id else None

    # audit_logs.actor_id is `references auth.users (id)`, and its own column
    # comment says so: "The Supabase Auth user who performed the action; null
    # for system-initiated actions."
    #
    # An API-key caller is not a Supabase Auth user. `caller.actor_id` is the
    # api_keys row id (app/auth/dependencies.py builds the actor that way), so
    # writing it here violates the foreign key and raises - from the *raising*
    # variant, on money paths. Production saw exactly that:
    #
    #   APIError: insert or update on table "audit_logs" violates foreign key
    #   constraint "audit_logs_actor_id_fkey"
    #
    # turning a partner's successful collection or disbursement call into a
    # 500 after the work had already been done.
    #
    # Twelve routers pass `actor_id=caller.actor_id, actor_type=caller.actor_type`,
    # so this is fixed once here rather than twelve times at the call sites -
    # and so the next router to follow the same pattern is correct by default.
    #
    # The identity is not lost: it moves into metadata, where it does not
    # claim to be an auth user. actor_type already records what kind of actor
    # it was, so the column pair stays meaningful.
    if actor_type != "user" and stored_actor_id is not None:
        record_metadata.setdefault("actor_reference", stored_actor_id)
        stored_actor_id = None

    client.table("audit_logs").insert(
        {
            "actor_id": stored_actor_id,
            "actor_type": actor_type,
            "merchant_id": str(merchant_id) if merchant_id else None,
            "action": action,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id else None,
            "metadata": record_metadata,
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
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("audit log write failed (action=%s)", kwargs.get("action"))
        # Still alerts, now that a logged error no longer does on its own.
        # An audit row is the compliance record of who moved money; losing
        # one silently is not something to discover months later.
        capture_exception(exc)
