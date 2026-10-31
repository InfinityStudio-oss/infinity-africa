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
    admin_referrals,
    admin_risk,
    admin_sms,
    admin_withdrawal_policy,
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
from app.services.referral_commissions import recalculate_open_referrals
from app.services.scheduler_lease import acquire_lease, release_lease
from app.services.sms_dispatch import dispatch_pending_sms
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
    # Both flags being set is what actually PERMITS withdrawal automation
    # — see Settings.auto_withdrawals_enabled's own docstring for the
    # full eligibility rules that still apply. Loud and early, same as
    # the warning below, so an operator sees this in deploy logs the
    # moment it takes effect rather than discovering it during an audit.
    #
    # Permitted is not the same as on. Since migration 20261031010000 the
    # routine switch is withdrawal_automation_policy.enabled in the
    # database, which a Super Admin owns and which is False until someone
    # turns it on in the portal — so this warning says what the deployment
    # now allows, not what it is doing. The live state is read per
    # withdrawal by app/services/withdrawal_policy.py and shown on the
    # Withdrawal Monitoring page; it is not reported here because a value
    # read once at boot would go stale the first time the switch moved.
    logging.getLogger("infinity.config").warning(
        "Withdrawal automation is PERMITTED by this deployment "
        "(REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS=false and AUTO_WITHDRAWALS_ENABLED=true). "
        "Whether it is actually on is the Super Admin policy in the database; while that is "
        "enabled, eligible withdrawals will reach Selcom without a Super Admin approving them "
        "first. AUTO_WITHDRAWAL_MAX_AMOUNT_TZS/AUTO_WITHDRAWAL_DAILY_LIMIT_TZS now act as hard "
        "ceilings above that policy — confirm they are set deliberately, not left at defaults."
    )
elif not settings.require_admin_approval_for_all_withdrawals:
    # The belt-and-suspenders case: someone flipped this flag without
    # also enabling auto_withdrawals_enabled — automation is still fully
    # off (every withdrawal still needs a human), so this has no effect
    # beyond the misconfiguration itself being worth flagging. The Super
    # Admin page says the same thing in plain language, so an operator who
    # cannot see deploy logs is not left guessing why the switch does
    # nothing.
    logging.getLogger("infinity.config").warning(
        "REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS is set to false, but AUTO_WITHDRAWALS_ENABLED "
        "is not — every withdrawal still requires Super Admin approval exactly as before, and the "
        "Super Admin automation switch cannot take effect. This combination has no effect other "
        "than this warning. Set AUTO_WITHDRAWALS_ENABLED=true too if withdrawal automation is "
        "actually intended, or revert this var if not."
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
            # One replica at a time. See app/services/scheduler_lease.py —
            # two replicas sweeping the same queue would ask Selcom about
            # the same collection twice.
            if not acquire_lease(client, "checkout_reconciliation"):
                continue
            try:
                summary = await reconcile_pending_checkout_collections(client)
            finally:
                release_lease(client, "checkout_reconciliation")
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
            expiry_client = get_supabase_admin()
            if acquire_lease(expiry_client, "collection_expiry"):
                try:
                    expiry_summary = await expire_stale_pushes(expiry_client)
                finally:
                    release_lease(expiry_client, "collection_expiry")
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
            if not acquire_lease(client, "disbursement_reconciliation"):
                continue
            try:
                summary = await reconcile_pending_disbursements(client)
            finally:
                release_lease(client, "disbursement_reconciliation")
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
            #
            # The lease matters most here. deliver_event POSTs an event
            # and only then records the outcome, so two replicas sweeping
            # at once would both read the same pending row and both send
            # it — a merchant receiving collection.success twice, which
            # can activate a customer's service twice.
            webhook_client = get_supabase_admin()
            if not acquire_lease(webhook_client, "webhook_delivery"):
                continue
            try:
                summary = await asyncio.to_thread(deliver_pending_webhooks, webhook_client)
            finally:
                release_lease(webhook_client, "webhook_delivery")
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


async def _sms_dispatch_loop(interval_seconds: float) -> None:
    """Drains the queued merchant SMS on a timer.

    Holds the 'sms_dispatch' lease for two reasons, not one. The obvious
    one is the same as webhook delivery: two replicas claiming the same
    row would send a merchant the same payment alert twice. The less
    obvious one is that the provider's 300-requests-per-minute limit is
    enforced here by an in-process counter, which is only equivalent to an
    account-wide limit while exactly one replica is sending.

    Nothing in the sweep can affect a payment - it reads and writes
    sms_messages and talks to the SMS provider, and touches no ledger,
    transaction or collection row.
    """
    logger.info("sms_dispatch_loop_running interval_seconds=%s", interval_seconds)
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            # Off the event loop, like every other sweep here:
            # dispatch_pending_sms is synchronous and the provider
            # documents a 180 second client timeout, so calling it inline
            # could stall this API for minutes.
            sms_client = get_supabase_admin()
            if not acquire_lease(sms_client, "sms_dispatch"):
                continue
            try:
                summary = await asyncio.to_thread(dispatch_pending_sms, sms_client)
            finally:
                release_lease(sms_client, "sms_dispatch")
            if summary["alerts"] or summary["announcements"] or summary["reclaimed"]:
                logger.info("scheduled_sms_dispatch %s", summary)
        except Exception as exc:
            logger.exception("scheduled_sms_dispatch_failed")
            capture_exception(exc)


def _start_sms_dispatch_task() -> asyncio.Task | None:
    """Two switches, both of which must be on.

    OASIS_SMS_ENABLED is the feature flag and the rollback: turning it off
    stops dispatch while leaving every queued row and all history intact.
    The interval is the same opt-in shape as the other sweeps, so tests
    and local dev never reach a real SMS provider in the background.
    """
    interval = settings.oasis_sms_dispatch_interval_seconds
    if not settings.oasis_sms_enabled or interval <= 0:
        logger.info(
            "sms_dispatch_scheduler_disabled interval_seconds=%s oasis_sms_enabled=%s",
            interval,
            settings.oasis_sms_enabled,
        )
        return None
    logger.info("sms_dispatch_scheduler_started interval_seconds=%s", interval)
    return asyncio.create_task(_sms_dispatch_loop(interval))


async def _referral_recalculation_loop(interval_seconds: float) -> None:
    """Revalues open referral commissions on a timer.

    Idempotent by construction: each referral has exactly one commission
    row, updated in place, and anything a Super Admin has already ruled on
    is skipped. So a missed tick costs nothing and a double tick changes
    nothing - there is no retry logic here for that reason.
    """
    logger.info("referral_recalculation_loop_running interval_seconds=%s", interval_seconds)
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            # Off the event loop: the sweep is synchronous and walks every
            # open referral's transactions, which must not stall requests.
            referral_client = get_supabase_admin()
            if not acquire_lease(referral_client, "referral_recalculation"):
                continue
            try:
                summary = await asyncio.to_thread(recalculate_open_referrals, referral_client)
            finally:
                release_lease(referral_client, "referral_recalculation")
            if summary.get("processed"):
                logger.info("scheduled_referral_recalculation %s", summary)
        except Exception as exc:
            logger.exception("scheduled_referral_recalculation_failed")
            capture_exception(exc)


def _start_referral_recalculation_task() -> asyncio.Task | None:
    """Starts only when the programme is on *and* an interval is set, the
    same opt-in shape as the reconciliation sweeps."""
    interval = settings.referral_recalculation_interval_seconds
    if not settings.referral_program_enabled or interval <= 0:
        logger.info(
            "referral_recalculation_scheduler_disabled enabled=%s interval_seconds=%s",
            settings.referral_program_enabled,
            interval,
        )
        return None
    logger.info("referral_recalculation_scheduler_started interval_seconds=%s", interval)
    return asyncio.create_task(_referral_recalculation_loop(interval))


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
            _start_referral_recalculation_task(),
            _start_sms_dispatch_task(),
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
app.include_router(admin_withdrawal_policy.router, prefix="/v1")
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
app.include_router(admin_referrals.router, prefix="/v1")
app.include_router(merchant_webhooks.router, prefix="/v1")
app.include_router(admin_sms.router, prefix="/v1")
app.include_router(admin_sms.callback_router, prefix="/v1")  # /v1/sms/callbacks/oasis
app.include_router(system.router, prefix="/v1")
app.include_router(auth_actions.router, prefix="/v1")
app.include_router(public_inquiries.router, prefix="/v1")
