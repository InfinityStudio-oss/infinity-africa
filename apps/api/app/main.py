import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.config.production_readiness import (
    production_config_problems,
    production_config_warnings,
)
from app.core.analytics import init_analytics, shutdown_analytics
from app.core.errors import register_exception_handlers
from app.core.monitoring import capture_exception, init_sentry
from app.database.session import get_supabase_admin
from app.middleware.api_request_log import ApiRequestLogMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import (
    admin,
    admin_collection_pricing,
    admin_diagnostics,
    admin_disputes,
    admin_onboarding,
    admin_pricing,
    admin_risk,
    admin_withdrawals,
    auth_actions,
    collections,
    collections_api,
    developer_docs,
    disbursements,
    health,
    invoices,
    merchant_portal,
    merchant_webhooks,
    merchants,
    onboarding,
    pay_by_link,
    payment_links,
    public_disputes,
    public_inquiries,
    system,
    transactions,
    webhooks,
)
from app.services.checkout_reconciliation import reconcile_pending_checkout_collections
from app.services.collection_expiry import expire_stale_pushes
from app.services.disbursements import reconcile_pending_disbursements
from app.services.webhook_delivery import deliver_pending_webhooks

settings = get_settings()


def _configure_logging(level: str) -> None:
    """Every logger in this app is named "infinity.X" (see
    Settings.log_level's own docstring for the full story of why this
    exists) — configuring their shared "infinity" parent logger, rather
    than the root logger via logging.basicConfig(), covers all of them
    through normal logger-hierarchy propagation without touching the
    root logger at all. That matters: touching the root logger risks
    interfering with anything else already managing it (uvicorn's own
    "uvicorn"/"uvicorn.error"/"uvicorn.access" loggers, and — the reason
    this isn't just logging.basicConfig() — pytest's caplog fixture,
    which attaches its own handler to the root logger during tests).
    propagate=False on the "infinity" logger stops messages also
    bubbling up to the root logger and potentially double-printing if
    something else ever does configure it.

    Idempotent: safe to call more than once (e.g. if a future test ever
    imports this module multiple times) — checks for an existing handler
    before adding another."""
    infinity_logger = logging.getLogger("infinity")
    infinity_logger.setLevel(level.upper())
    if not infinity_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        infinity_logger.addHandler(handler)
    infinity_logger.propagate = False


_configure_logging(settings.log_level)

logger = logging.getLogger("infinity.scheduler")

# Error monitoring and product analytics. Both do nothing at all unless
# SENTRY_DSN / POSTHOG_API_KEY are set, so these two lines are a no-op on
# every deploy that has not opted in. Called before the app is
# constructed because the SDK instruments Starlette as the app is built,
# not afterwards. See docs/MONITORING_AND_OBSERVABILITY.md.
init_sentry()
init_analytics()

if not settings.require_admin_approval_for_all_withdrawals and settings.auto_withdrawals_enabled:
    # Both flags being set is what actually enables withdrawal automation
    # — see Settings.auto_withdrawals_enabled's own docstring for the
    # full eligibility rules that still apply. Loud and early, same as
    # the warning below, so an operator sees this in deploy logs the
    # moment it takes effect rather than discovering it during an audit.
    logging.getLogger("infinity.config").warning(
        "Withdrawal automation is ENABLED (REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS=false and "
        "AUTO_WITHDRAWALS_ENABLED=true) — eligible withdrawals will reach Selcom without a Super "
        "Admin approving them first. Confirm AUTO_WITHDRAWAL_MAX_AMOUNT_TZS/"
        "AUTO_WITHDRAWAL_DAILY_LIMIT_TZS are set deliberately, not left at defaults."
    )
elif not settings.require_admin_approval_for_all_withdrawals:
    # The belt-and-suspenders case: someone flipped this flag without
    # also enabling auto_withdrawals_enabled — automation is still fully
    # off (every withdrawal still needs a human), so this has no effect
    # beyond the misconfiguration itself being worth flagging.
    logging.getLogger("infinity.config").warning(
        "REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS is set to false, but AUTO_WITHDRAWALS_ENABLED "
        "is not — every withdrawal still requires Super Admin approval exactly as before. This "
        "combination has no effect other than this warning. Set AUTO_WITHDRAWALS_ENABLED=true too "
        "if withdrawal automation is actually intended, or revert this var if not."
    )


async def _checkout_reconciliation_loop(interval_seconds: float) -> None:
    """Backend-initiated, webhook-independent sweep — see
    Settings.selcom_checkout_reconcile_interval_seconds and
    app/services/checkout_reconciliation.py::reconcile_pending_checkout_collections's
    own docstring for why this, not the inbound webhook, is what actually
    keeps Selcom Checkout collections crediting in production. Runs for
    the lifetime of the app process; a single failed sweep is logged and
    never crashes the loop (or the app) — the next tick tries again.

    Logs every tick unconditionally (not just when there's work) —
    deliberately, so "is this actually running at all" is answerable from
    Railway logs alone without waiting for a real pending collection to
    show up. Per-collection detail (which id, what it resolved to) comes
    from reconcile_pending_checkout_collections itself."""
    logger.info("checkout_reconciliation_loop_running interval_seconds=%s", interval_seconds)
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            client = get_supabase_admin()
            summary = await reconcile_pending_checkout_collections(client)
            logger.info("scheduled_checkout_reconciliation %s", summary)
        except Exception as exc:
            logger.exception("scheduled_checkout_reconciliation_failed")
            # A sweep that keeps failing means collections are not
            # crediting, which no merchant-facing error ever reveals.
            # No-op when monitoring is off.
            capture_exception(exc)

        # Same tick rather than a loop of its own: expiry is the other
        # half of resolving a pending collection, it draws on the same
        # rate-limited provider budget, and running it here means
        # ENABLE_AUTO_RECONCILIATION stops both with one switch. Kept in
        # its own try so an expiry failure never stops reconciliation --
        # crediting wallets matters more than closing stale ones.
        try:
            expiry_summary = await expire_stale_pushes(get_supabase_admin())
            logger.info("scheduled_collection_expiry %s", expiry_summary)
        except Exception as exc:
            logger.exception("scheduled_collection_expiry_failed")
            capture_exception(exc)


def _start_checkout_reconciliation_task() -> asyncio.Task | None:
    """Split out from lifespan() so tests can exercise the start/no-start
    decision directly without spinning up the whole app. 0 (the
    default — see .env.example) disables it entirely, so local dev/tests
    never have a background task running unless explicitly opted in.
    ENABLE_AUTO_RECONCILIATION=false (Settings.enable_auto_reconciliation)
    pauses this regardless of the interval — a single flag to stop both
    reconciliation schedulers at once without separately zeroing each
    interval var."""
    interval = settings.selcom_checkout_reconcile_interval_seconds
    if not settings.enable_auto_reconciliation or interval <= 0:
        logger.info(
            "checkout_reconciliation_scheduler_disabled interval_seconds=%s enable_auto_reconciliation=%s",
            interval,
            settings.enable_auto_reconciliation,
        )
        return None
    logger.info("checkout_reconciliation_scheduler_started interval_seconds=%s", interval)
    return asyncio.create_task(_checkout_reconciliation_loop(interval))


async def _disbursement_reconciliation_loop(interval_seconds: float) -> None:
    """Withdrawal counterpart to _checkout_reconciliation_loop above — see
    Settings.selcom_disbursement_reconcile_interval_seconds for why this
    exists even though the disbursement webhook is signed and verified
    (unlike the checkout one): a safety net for a delayed/dropped/never-sent
    delivery, not a replacement for a broken signal."""
    logger.info("disbursement_reconciliation_loop_running interval_seconds=%s", interval_seconds)
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            client = get_supabase_admin()
            summary = await reconcile_pending_disbursements(client)
            logger.info("scheduled_disbursement_reconciliation %s", summary)
        except Exception as exc:
            logger.exception("scheduled_disbursement_reconciliation_failed")
            capture_exception(exc)


def _start_disbursement_reconciliation_task() -> asyncio.Task | None:
    """Same split-out-for-testability shape as
    _start_checkout_reconciliation_task above, including the same
    ENABLE_AUTO_RECONCILIATION gate."""
    interval = settings.selcom_disbursement_reconcile_interval_seconds
    if not settings.enable_auto_reconciliation or interval <= 0:
        logger.info(
            "disbursement_reconciliation_scheduler_disabled interval_seconds=%s enable_auto_reconciliation=%s",
            interval,
            settings.enable_auto_reconciliation,
        )
        return None
    logger.info("disbursement_reconciliation_scheduler_started interval_seconds=%s", interval)
    return asyncio.create_task(_disbursement_reconciliation_loop(interval))


async def _webhook_delivery_loop(interval_seconds: float) -> None:
    """Drains the outbound merchant webhook queue on a timer.

    enqueue_webhook_event has always written webhook_events rows that
    nothing read — so a partner told to wait for `collection.success`
    never received one. This is the delivery side of that queue."""
    logger.info("webhook_delivery_loop_running interval_seconds=%s", interval_seconds)
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            # Off the event loop: deliver_pending_webhooks is synchronous
            # and uses blocking httpx, so calling it directly here would
            # stall every request this API is serving for the duration of
            # the sweep — up to 50 sequential POSTs at an 8s timeout each.
            # That is survivable at a trickle and not at all survivable
            # during a billing run.
            summary = await asyncio.to_thread(deliver_pending_webhooks, get_supabase_admin())
            # Only worth a line when it actually did something; an idle
            # queue every 30s would drown the log.
            if summary["due"]:
                logger.info("scheduled_webhook_delivery %s", summary)
        except Exception as exc:
            logger.exception("scheduled_webhook_delivery_failed")
            capture_exception(exc)


def _start_webhook_delivery_task() -> asyncio.Task | None:
    """Same opt-in shape as the two reconciliation schedulers above: 0 (the
    default) disables it, so local dev and tests never deliver webhooks in
    the background unless explicitly asked to."""
    interval = settings.webhook_delivery_interval_seconds
    if interval <= 0:
        logger.info("webhook_delivery_scheduler_disabled interval_seconds=%s", interval)
        return None
    logger.info("webhook_delivery_scheduler_started interval_seconds=%s", interval)
    return asyncio.create_task(_webhook_delivery_loop(interval))


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Before anything else. Every required secret defaults to an empty
    # string, so a missing environment variable otherwise surfaces as a
    # 500 on a real merchant's request rather than as a failed deploy.
    # Raising here means the platform shows it immediately and the
    # previous release keeps serving. Development is never blocked.
    problems = production_config_problems(settings)
    if problems:
        for problem in problems:
            logger.error("production_config_problem %s", problem)
        raise RuntimeError(
            "Refusing to start: production configuration is incomplete — " + "; ".join(problems)
        )
    for warning in production_config_warnings(settings):
        logger.warning("production_config_warning %s", warning)

    tasks = [
        task
        for task in (
            _start_checkout_reconciliation_task(),
            _start_disbursement_reconciliation_task(),
            _start_webhook_delivery_task(),
        )
        if task is not None
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # Last, so events queued by a worker's final tick are not lost.
        shutdown_analytics()


# See Settings.docs_enabled's own docstring for why these are conditional.
app = FastAPI(
    title="InfinityPay API",
    description="Payment infrastructure for African merchants — collections, payment links, invoices, and merchant tools.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ApiRequestLogMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

register_exception_handlers(app)

app.include_router(health.router)

app.include_router(merchants.router, prefix="/v1")
app.include_router(merchant_portal.router, prefix="/v1")
app.include_router(onboarding.router, prefix="/v1")
app.include_router(admin_onboarding.router, prefix="/v1")
app.include_router(admin.router, prefix="/v1")
app.include_router(admin_risk.router, prefix="/v1")
app.include_router(admin_disputes.router, prefix="/v1")
app.include_router(admin_withdrawals.router, prefix="/v1")
app.include_router(admin_pricing.router, prefix="/v1")
app.include_router(admin_collection_pricing.router, prefix="/v1")
app.include_router(admin_diagnostics.router, prefix="/v1")
app.include_router(public_disputes.router, prefix="/v1")
app.include_router(payment_links.router, prefix="/v1")
app.include_router(payment_links.public_router)  # /public/payment-links — no /v1 prefix
app.include_router(pay_by_link.router, prefix="/v1")
app.include_router(pay_by_link.public_router)  # /public/pay-by-link — no /v1 prefix
app.include_router(invoices.router, prefix="/v1")
app.include_router(collections.router, prefix="/v1")
app.include_router(collections.initiate_router, prefix="/v1")
app.include_router(collections_api.router, prefix="/v1")
app.include_router(disbursements.router, prefix="/v1")  # /v1/disbursements — fully flat
app.include_router(transactions.router, prefix="/v1")
app.include_router(transactions.by_reference_router, prefix="/v1")
app.include_router(webhooks.router, prefix="/v1")
app.include_router(webhooks.callback_router, prefix="/v1")
app.include_router(developer_docs.router, prefix="/v1")
app.include_router(merchant_webhooks.router, prefix="/v1")
app.include_router(system.router, prefix="/v1")
app.include_router(auth_actions.router, prefix="/v1")
app.include_router(public_inquiries.router, prefix="/v1")
