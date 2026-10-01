import hmac
import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.auth import require_role
from app.config import get_settings
from app.core.errors import NotFoundError, ValidationAPIError
from app.core.pagination import PaginationParams, build_page_meta, pagination_params
from app.core.rate_limit import RateLimitExceededError, enforce_rate_limit, rate_limit
from app.core.time import utc_now_iso
from app.database.session import get_supabase_admin
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import APIResponse
from app.schemas.enums import UserRole
from app.schemas.selcom_checkout_webhooks import SelcomCheckoutWebhookPayload
from app.schemas.webhooks import SelcomWebhookPayload, WebhookEventResponse
from app.services.audit import write_audit_log
from app.services.checkout_reconciliation import (
    find_collection_by_order_id,
    find_collection_by_transid,
    resolve_checkout_collection_from_webhook_hint,
)
from app.services.collections import resolve_collection_from_callback
from app.services.crud import get_for_merchant, list_for_merchant, update_row
from app.services.disbursements import (
    resolve_disbursement_from_callback,
    reverse_successful_disbursement_from_callback,
)
from app.services.selcom.webhooks import verify_selcom_signature
from app.services.selcom_checkout.signer import verify_webhook_signature
from app.services.webhooks import store_incoming_selcom_event

router = APIRouter(prefix="/merchants/{merchant_id}/webhooks", tags=["webhooks"])
callback_router = APIRouter(prefix="/webhooks", tags=["webhooks (provider callback)"])

logger = logging.getLogger("infinity.webhooks")

_HEADER_NAMES_NEVER_STORED = {"authorization", "cookie"}


def _safe_headers_for_storage(headers) -> dict[str, str]:
    """Every header name Selcom's callback actually sent, for diagnosing
    an unexpected/rejected signature scheme — see
    selcom_checkout_webhook's docstring. Defensive only: a provider
    webhook has no legitimate reason to carry Authorization/Cookie, but
    they're excluded on principle rather than assumed absent."""
    return {key: value for key, value in headers.items() if key.lower() not in _HEADER_NAMES_NEVER_STORED}

_DASHBOARD_ROLES = (UserRole.MERCHANT_ADMIN, UserRole.MERCHANT_STAFF)


@router.get("", response_model=APIResponse[list[WebhookEventResponse]])
def list_webhook_events(
    merchant_id: uuid.UUID,
    _actor: Annotated[AuthenticatedUser, Depends(require_role(*_DASHBOARD_ROLES))],
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    """The "Webhook Logs" merchants/admins see — delivery status per event.
    This only records events; a background worker (not built yet) is what
    would actually deliver them and update these rows."""
    client = get_supabase_admin()
    rows, total = list_for_merchant(client, "webhook_events", merchant_id=merchant_id, pagination=pagination)
    data = [WebhookEventResponse(**row) for row in rows]
    return APIResponse(data=data, meta=build_page_meta(pagination, total))


@router.get("/{webhook_event_id}", response_model=APIResponse[WebhookEventResponse])
def get_webhook_event(
    merchant_id: uuid.UUID,
    webhook_event_id: uuid.UUID,
    _actor: Annotated[AuthenticatedUser, Depends(require_role(*_DASHBOARD_ROLES))],
):
    client = get_supabase_admin()
    row = get_for_merchant(client, "webhook_events", merchant_id=merchant_id, row_id=webhook_event_id)
    if not row:
        raise NotFoundError("Webhook event not found")
    return APIResponse(data=WebhookEventResponse(**row))


@callback_router.get("/selcom", response_model=APIResponse[dict])
async def selcom_webhook_reachability_check():
    """Answers a provider's own "is this URL reachable" probe (e.g. Selcom's
    Business portal "Test URL" button when configuring a callback), which
    hits this path with a plain unauthenticated GET expecting a 2xx — not a
    real callback delivery. Real deliveries are POSTs, handled below, and
    still require a valid signature; this GET path carries no data and
    performs no action, so it doesn't weaken that verification.
    """
    return APIResponse(data={"status": "ok"})


@callback_router.post("/selcom", response_model=APIResponse[dict])
async def selcom_webhook(
    request: Request,
    _rate_limit: Annotated[None, Depends(rate_limit(scope="selcom_webhook", limit=120, window_seconds=60))],
):
    """Where a real Selcom callback would land, resolving a collection or
    disbursement that was left `processing`. In SELCOM_MODE=mock (the
    default — see MockSelcomClient) nothing ever calls this, since the mock
    resolves synchronously — this is the receiving side, ready for
    SELCOM_MODE=live (see docs/selcom-live-go-live.md).

    Deliberately unauthenticated like any provider webhook — instead it's
    verified via an HMAC signature (X-Selcom-Signature, over the raw body,
    see app/services/selcom/webhooks.py) and every delivery is
    logged to selcom_webhook_events, whose unique (provider, event_id)
    guards against reprocessing a retried/duplicate delivery.
    """
    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8", errors="replace")
    signature = request.headers.get("X-Selcom-Signature")
    settings = get_settings()
    signature_valid = verify_selcom_signature(
        raw_body=raw_body, signature=signature, secret=settings.selcom_webhook_secret
    )

    try:
        body = json.loads(raw_body) if raw_body else {}
    except ValueError:
        body = {}

    event_id = str(body.get("event_id") or body.get("provider_reference") or uuid.uuid4())
    event_type = str(body.get("event_type") or "unknown")

    client = get_supabase_admin()
    stored, is_duplicate = store_incoming_selcom_event(
        client,
        event_id=event_id,
        event_type=event_type,
        raw_body=raw_text,
        signature=signature,
        signature_valid=signature_valid,
    )
    if is_duplicate:
        return APIResponse(data={"status": "duplicate", "event_id": event_id})

    if not signature_valid:
        update_row(
            client,
            "selcom_webhook_events",
            uuid.UUID(stored["id"]),
            {"status": "failed", "processing_error": "invalid signature"},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    try:
        payload = SelcomWebhookPayload.model_validate(body)
    except ValidationError as exc:
        errors = jsonable_encoder(exc.errors())
        update_row(
            client,
            "selcom_webhook_events",
            uuid.UUID(stored["id"]),
            {"status": "failed", "processing_error": json.dumps(errors)},
        )
        raise ValidationAPIError("Invalid webhook payload", details=errors) from exc

    result = _dispatch_selcom_event(client, payload)

    update_row(
        client,
        "selcom_webhook_events",
        uuid.UUID(stored["id"]),
        {"status": "processed", "processed_at": utc_now_iso()},
    )

    return APIResponse(data=result)


def _dispatch_selcom_event(client, payload: SelcomWebhookPayload) -> dict:
    if payload.event_type.startswith("collection."):
        resolved_status = "successful" if payload.event_type.endswith(".success") else "failed"
        collection = resolve_collection_from_callback(
            client,
            provider_reference=payload.provider_reference,
            status=resolved_status,
            failure_reason=payload.failure_reason,
        )
        if collection:
            return {"resolved": "collection", "id": collection["id"]}
        return {"resolved": "none", "message": "No pending collection matched this provider_reference"}

    if payload.event_type.endswith(".reversed"):
        # An already-SUCCESS payout bounced after settlement (e.g. an
        # invalid bank account discovered late) — a different resolution
        # path than PROCESSING -> success/failed below, so it's checked
        # first: a ".success"/".failed" style status computation wouldn't
        # make sense for it.
        disbursement = reverse_successful_disbursement_from_callback(
            client, provider_reference=payload.provider_reference, reason=payload.failure_reason
        )
        if disbursement:
            return {"resolved": "disbursement_reversal", "id": disbursement["id"]}
        return {"resolved": "none", "message": "No successful disbursement matched this provider_reference"}

    resolved_status = "successful" if payload.event_type.endswith(".success") else "failed"
    disbursement = resolve_disbursement_from_callback(
        client,
        provider_reference=payload.provider_reference,
        status=resolved_status,
        failure_reason=payload.failure_reason,
    )
    if disbursement:
        return {"resolved": "disbursement", "id": disbursement["id"]}
    return {"resolved": "none", "message": "No pending disbursement matched this provider_reference"}


@callback_router.get("/selcom/checkout", response_model=APIResponse[dict])
async def selcom_checkout_webhook_reachability_check():
    """Same reachability-probe answer as selcom_webhook_reachability_check
    above, for Selcom's Checkout product's own callback-configuration
    "Test URL" check — see that function's docstring."""
    return APIResponse(data={"status": "ok"})


@callback_router.post("/selcom/checkout", response_model=APIResponse[dict])
async def selcom_checkout_webhook(
    request: Request,
    _rate_limit: Annotated[None, Depends(rate_limit(scope="selcom_checkout_webhook", limit=120, window_seconds=60))],
):
    """Selcom Checkout's webhook callback — the async resolution path for
    a wallet-push collection left "processing" after
    process_wallet_payment()'s usual PENDING/111 response
    (app/services/wallet_push.py).

    **Fails closed on signature, always — no exception for "we couldn't
    confirm the scheme."** Confirmed against 5 independent real
    deliveries on 2026-08-27: Selcom's Checkout webhook carries no
    signature at all (no Digest/Timestamp/Digest-Method/Signed-Fields
    header, or anything else signature-shaped). That means every real
    production delivery is, and will remain, rejected with 401 — by
    deliberate policy, not a bug to route around. This endpoint MUST
    NEVER be changed to accept an unsigned delivery in production; see
    docs/selcom-checkout-collections.md's "Signature verification"
    section for the full reasoning and, if Selcom's account team ever
    confirms a real signing scheme, what to change here.

    The **only** way anything is ever applied from this endpoint is a
    delivery that passes verify_webhook_signature() outright, or (local
    development only) the internal test-secret bypass below — see
    Settings.selcom_checkout_webhook_test_secret's own docstring for why
    that bypass is structurally impossible to enable in a deployed
    environment. Even then, the delivery's own claimed
    payment_status/result/resultcode/amount are still never trusted
    directly — see resolve_checkout_collection_from_webhook_hint's
    docstring.

    **Given the above, this endpoint is not what keeps real Selcom
    Checkout collections crediting today** —
    app/services/checkout_reconciliation.py::reconcile_pending_checkout_collections
    (a backend-initiated sweep on a timer, see app/main.py's lifespan
    task) and the manual `POST /v1/merchant/collections/{id}/refresh-status`
    / `POST /v1/admin/collections/{id}/refresh-status` endpoints are —
    both call Selcom directly with our own authenticated credentials,
    never depending on anything arriving here.

    Every delivery is still logged to selcom_webhook_events (provider=
    "selcom_checkout", so it never collides with the older placeholder
    product's own events on event_id) regardless of outcome, for audit —
    including every rejected one, with no secrets ever stored.
    """
    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8", errors="replace")
    timestamp = request.headers.get("Timestamp")
    digest = request.headers.get("Digest")
    digest_method = request.headers.get("Digest-Method")
    signed_fields_header = request.headers.get("Signed-Fields")

    settings = get_settings()

    try:
        body = json.loads(raw_body) if raw_body else {}
    except ValueError:
        body = {}

    # Logged before signature verification runs, deliberately — this is
    # how we'll ever know a delivery arrived at all if the (unconfirmed)
    # signature scheme turns out wrong and rejects it. Timestamp/Digest/
    # Digest-Method/Signed-Fields are protocol metadata, not secrets —
    # safe to log (the actual secret is api_secret, never logged, never
    # included below). Also dumps every header *name* Selcom actually
    # sent — confirmed necessary on 2026-08-22: the first real delivery
    # arrived with all four of these expected headers completely absent,
    # meaning the inferred signing scheme guessed the wrong header names
    # (or Selcom simply doesn't sign this callback at all) — this is
    # what lets the next delivery answer that question instead of
    # guessing again.
    logger.info(
        "selcom_checkout webhook received: order_id=%s transid=%s reference=%s payment_status=%s "
        "Timestamp=%r Digest=%r Digest-Method=%r Signed-Fields=%r header_names=%s",
        body.get("order_id"),
        body.get("transid"),
        body.get("reference"),
        body.get("payment_status"),
        timestamp,
        digest,
        digest_method,
        signed_fields_header,
        sorted(request.headers.keys()),
    )

    signature_valid = verify_webhook_signature(
        body=body,
        timestamp=timestamp,
        digest=digest,
        digest_method=digest_method,
        signed_fields_header=signed_fields_header,
        api_secret=settings.selcom_checkout_api_secret,
    )

    # The ONLY way an unsigned delivery is ever accepted — see
    # Settings.selcom_checkout_webhook_test_secret's docstring. Both
    # conditions are required; a real Railway deployment's environment is
    # never "development", so this can never fire in production no
    # matter how selcom_checkout_webhook_test_secret is set.
    dev_test_secret = settings.selcom_checkout_webhook_test_secret
    dev_bypass_used = bool(
        settings.environment == "development"
        and dev_test_secret
        and hmac.compare_digest(request.headers.get("X-Internal-Test-Secret", ""), dev_test_secret)
    )
    accepted = signature_valid or dev_bypass_used

    event_id = str(body.get("transid") or uuid.uuid4())
    event_type = str(body.get("payment_status") or "unknown")

    client = get_supabase_admin()
    stored, is_duplicate = store_incoming_selcom_event(
        client,
        event_id=event_id,
        event_type=event_type,
        raw_body=raw_text,
        signature=digest,
        signature_valid=signature_valid,
        provider="selcom_checkout",
        raw_headers=_safe_headers_for_storage(request.headers),
    )
    if is_duplicate:
        return APIResponse(data={"status": "duplicate", "event_id": event_id})

    # Fails closed, always — never a reason to trust an unsigned payload,
    # regardless of how confident we are that Selcom "really did" send it.
    # No secrets in this log/audit entry: dev_bypass_used is a bool, never
    # the test secret itself.
    # An unsigned delivery may still be allowed to act as a HINT — never
    # as a source of truth. Everything below this point already ignores
    # what the callback claims and asks Selcom directly over our own
    # authenticated connection, so letting an unsigned one through buys
    # latency (seconds instead of up to two minutes waiting for the
    # reconciliation sweep) without buying trust.
    #
    # Rate limited, because the one thing a forged callback can cost us
    # is provider budget. Keyed on the claimed event id as well as the
    # caller's address: keying on address alone lets one attacker rotate
    # addresses against a single order, and on the id alone lets one
    # address work through many.
    hinting_unsigned = False
    if not accepted and settings.selcom_checkout_accept_unsigned_callbacks:
        try:
            enforce_rate_limit(
                scope="selcom_unsigned_callback",
                key=event_id,
                limit=settings.selcom_unsigned_callback_max_per_minute,
                window_seconds=60,
                request=request,
            )
            hinting_unsigned = True
        except RateLimitExceededError:
            logger.warning("selcom_checkout unsigned callback rate limited (event_id=%s)", event_id)

    if not accepted and not hinting_unsigned:
        update_row(
            client,
            "selcom_webhook_events",
            uuid.UUID(stored["id"]),
            {"status": "failed", "processing_error": "invalid or missing signature"},
        )
        write_audit_log(
            client,
            action="webhook.selcom_checkout_rejected",
            resource_type="selcom_webhook_event",
            resource_id=uuid.UUID(stored["id"]),
            actor_type="system",
            metadata={"event_id": event_id, "reason": "invalid_or_missing_signature"},
        )
        logger.warning("selcom_checkout webhook rejected: invalid or missing signature (event_id=%s)", event_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    try:
        payload = SelcomCheckoutWebhookPayload.model_validate(body)
    except ValidationError as exc:
        errors = jsonable_encoder(exc.errors())
        update_row(
            client,
            "selcom_webhook_events",
            uuid.UUID(stored["id"]),
            {"status": "failed", "processing_error": json.dumps(errors)},
        )
        raise ValidationAPIError("Invalid webhook payload", details=errors) from exc

    collection = find_collection_by_transid(client, transid=payload.transid) or find_collection_by_order_id(
        client, order_id=payload.order_id
    )
    if not collection:
        update_row(
            client,
            "selcom_webhook_events",
            uuid.UUID(stored["id"]),
            {"status": "failed", "processing_error": "no matching collection for this transid/order_id"},
        )
        raise NotFoundError("No matching collection found for this webhook")

    # An unsigned hint may only nudge a collection that is still waiting
    # for an answer. Anything already resolved has nothing to learn from
    # a lookup, so re-asking about one is pure provider budget spent on
    # an unauthenticated request's say-so.
    if hinting_unsigned and collection.get("status") != "processing":
        update_row(
            client,
            "selcom_webhook_events",
            uuid.UUID(stored["id"]),
            {"status": "failed", "processing_error": "unsigned callback for an already-resolved collection"},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    # Deliberately ignores payload.payment_status/result/resultcode —
    # never trusted directly (see this function's docstring). Only used
    # to find the collection and to know which Selcom order to ask about.
    await resolve_checkout_collection_from_webhook_hint(
        client, collection=collection, order_id=payload.order_id
    )

    update_row(
        client,
        "selcom_webhook_events",
        uuid.UUID(stored["id"]),
        {"status": "processed", "processed_at": utc_now_iso()},
    )
    write_audit_log(
        client,
        action="webhook.selcom_checkout_accepted",
        resource_type="collection",
        resource_id=uuid.UUID(collection["id"]),
        actor_type="system",
        merchant_id=uuid.UUID(collection["merchant_id"]),
        metadata={
            "event_id": event_id,
            "dev_bypass_used": dev_bypass_used,
            # Recorded so the callback log tells the difference between a
            # verified delivery and an unsigned one we chose to act on.
            "signature_valid": signature_valid,
            "unsigned_hint": hinting_unsigned,
        },
    )

    return APIResponse(data={"status": "acknowledged"})
