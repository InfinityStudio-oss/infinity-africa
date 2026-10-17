import json
import logging
from decimal import Decimal
from functools import lru_cache

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("infinity.config")

# What pydantic accepts, plus the words a person actually types into a
# variable whose name ends in _ENABLED.
_TRUE_WORDS = frozenset({"1", "true", "t", "yes", "y", "on", "enable", "enabled"})
_FALSE_WORDS = frozenset({"0", "false", "f", "no", "n", "off", "disable", "disabled", ""})


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    # How many proxies of OUR OWN sit in front of this app, for reading
    # X-Forwarded-For (see app/core/request_ip.py). Railway's edge is one,
    # which is the default. Anything a client sends in that header to the
    # left of our proxies' own entries is unverifiable, so this decides how
    # far in from the right to read — and therefore whether a caller can
    # choose their own IP and walk through every rate limit and the
    # API-key IP allowlist. Set to 0 when no proxy is in front (the header
    # is then ignored entirely); raise it to 2 if Cloudflare or similar is
    # ever put ahead of Railway, or this reads the intermediate proxy
    # instead of the real client.
    trusted_proxy_hops: int = 1

    # Outbound throttle for everything this backend sends to Selcom
    # (app/services/selcom/outbound_guard.py). Every merchant reaches
    # Selcom through us, from our own whitelisted IPs, so all of their
    # traffic concentrates onto a few addresses -- one ISP partner running
    # a billing cycle can look like abuse from a single source, and a
    # blocked IP takes down the whole platform rather than one merchant.
    #
    # Concurrency and rate make callers WAIT for a slot, which smooths a
    # burst instead of failing it. The breaker is the one that fails fast:
    # retrying into a provider that is already down is how a temporary
    # outage becomes a blocked IP.
    selcom_outbound_max_per_minute: int = 60
    selcom_outbound_max_concurrent: int = 5
    selcom_circuit_breaker_failure_threshold: int = 10
    selcom_circuit_breaker_cooldown_seconds: int = 60

    # Inbound limits on the public Collections API's creation endpoints.
    #
    # Two dimensions, because either alone has a hole. Per-IP alone
    # punishes an aggregator: a billing platform serving many merchants
    # calls from one address, so every merchant behind it shares one
    # bucket and the busiest starves the rest (a real finding -- the
    # per-IP limit was 20/min, which a single monthly billing run
    # exhausted in seconds). Per-key alone lets one host open many keys
    # and concentrate their combined traffic onto Selcom.
    #
    # These REJECT (429 + Retry-After) rather than queue, deliberately
    # unlike selcom_outbound_* above, which makes callers wait. Waiting
    # is right for a slot that frees in milliseconds; it is wrong here,
    # where a bulk run would otherwise park hundreds of requests holding
    # open connections until the client times out and retries them all.
    # A 429 with Retry-After lets an integrator pace deterministically.
    #
    # The real ceiling is selcom_outbound_max_per_minute, shared with the
    # reconciliation sweep, so the per-IP default sits at it rather than
    # above it. Raise both once Selcom confirms their actual limit --
    # 60 is still our own guess (docs/DIRECT_WALLET_PUSH_PARTNER_INTEGRATION.md).
    collection_create_max_per_minute_per_ip: int = 60
    collection_create_max_per_minute_per_key: int = 30

    # Giving an abandoned mobile money push a terminal answer
    # (app/services/collection_expiry.py).
    #
    # A customer who dismisses the prompt or mistypes their PIN leaves the
    # collection "processing" and Selcom reporting PENDING -- forever. Our
    # own oldest is from 2026-08-16. Nothing ever resolved these, so an
    # integrator waiting on a webhook waited indefinitely, and the
    # reconciliation sweep re-polled every one of them against a shared
    # provider budget on every pass.
    #
    # 0 disables expiry entirely, which is the switch to reach for if this
    # ever starts failing payments that were really going to succeed.
    collection_push_expiry_minutes: int = 30

    # How many collections one sweep may expire. Each one costs a live
    # provider status call, drawn from selcom_outbound_max_per_minute and
    # therefore competing with real payments. Deliberately small: a long
    # backlog drains over several sweeps rather than saturating the
    # provider budget in one.
    collection_push_expiry_batch_size: int = 25

    # After expiry we keep asking the provider about a collection for this
    # long, because being wrong here costs a customer real money.
    # resolve_collection() no-ops on anything that is not "processing", so
    # an expired collection the provider later reports as paid would never
    # be credited -- the debit leaves the customer's wallet and the
    # merchant is never paid. Within this window such a collection is put
    # back to "processing" and settled normally. 0 disables the recheck.
    collection_push_expiry_grace_hours: int = 24

    # SELF_PAYMENT_OWN_TILL: the amount above which a self-payment is held
    # for review rather than credited (app/services/
    # fraud_monitoring_service.py::check_self_payment_risk).
    #
    # The rule fires when the payer's phone matches the merchant's own
    # registered contact phone. It began as an unconditional hold, after a
    # real "you are trying to pay into your own till" incident. The cost of
    # that was paid by every honest integrator: testing a payment from your
    # own phone is the first thing anyone does, and it left their money
    # sitting at pending_review with nothing explaining why. A partner hit
    # exactly this on 2026-10-01 and reasonably concluded the API was
    # broken.
    #
    # A self-payment is not profitable on its own -- the payer loses the
    # fee. What the hold actually guards is the reversal window: pay in,
    # withdraw the balance, then dispute the original mobile money
    # transaction. That only pays off at size, so size is what decides.
    # Below this, credit immediately and raise the alert anyway; above it,
    # hold as before.
    #
    # 0 holds every self-payment, restoring the original behaviour.
    self_payment_hold_above_amount: Decimal = Decimal(50000)

    # Whether an UNSIGNED Selcom Checkout callback may trigger an
    # authenticated status lookup (app/routers/webhooks.py).
    #
    # Selcom does not sign these callbacks. No real delivery has ever
    # carried a Digest/Timestamp/Digest-Method header -- the scheme in
    # signer.py was inferred from their outbound auth and has never
    # matched anything. So every callback fails closed, and collections
    # are instead resolved by the reconciliation sweep up to two minutes
    # later.
    #
    # Turning this on does NOT make us believe an unsigned payload. The
    # handler already ignores everything a callback claims -- status,
    # amount, result code -- and uses it only to learn which order to ask
    # Selcom about, over our own authenticated connection. An unsigned
    # callback becomes a "look at this one now" nudge for a lookup that
    # already happens on a timer; the answer still comes from Selcom
    # directly.
    #
    # What it does expose is our provider rate budget, so the unsigned
    # path is rate limited and only acts on a collection that is still
    # `processing`. A forged callback can at most make us re-ask about a
    # payment we were already going to ask about.
    #
    # Default off: this is security-adjacent and the platform works
    # without it, so switching it on is a deliberate decision rather than
    # something a deploy does quietly.
    selcom_checkout_accept_unsigned_callbacks: bool = False
    selcom_unsigned_callback_max_per_minute: int = 30

    # Error monitoring (app/core/monitoring.py). Blank disables Sentry
    # entirely — no init, no network, no behaviour change — so this ships
    # inert and is switched on by setting the DSN in Railway.
    #
    # The DSN is a write-only ingest endpoint, not a credential that can
    # read anything back, but it is still kept server-side: a public one
    # invites anyone to forge error reports into the project.
    # Matches supabase-py's own postgrest default. Named here because
    # app/database/session.py passes its own httpx client (to retry a read
    # whose connection died), and doing so replaces the library's
    # construction of it — leaving this unset would silently fall back to
    # httpx's 5s and start failing slow-but-fine queries.
    supabase_client_timeout_seconds: int = 120

    # How many payment prompts one customer may be sent by one merchant
    # inside the window (app/core/push_throttle.py).
    #
    # 5 in 10 minutes, which is generous on purpose: a customer whose
    # first prompt fails and who tries again immediately is an ordinary
    # customer, not a loop, and blocking them would cost a real sale. It
    # is set to stop the pathological case - one number on MAXTON'S WIFI
    # was sent 52 prompts in two hours on 2026-10-12, none completed -
    # not to police normal retrying. 0 disables it.
    collection_push_per_customer_limit: int = 5
    collection_push_per_customer_window_seconds: int = 600

    # --- Cache (app/core/cache.py) ------------------------------------
    #
    # Off unless both of these say otherwise, and off by default. The
    # cache holds dashboard and report *displays* only - nothing in it
    # decides whether money exists, moves or is owed - so switching it
    # off is a performance change and never a correctness one. That is
    # the rollback: CACHE_ENABLED=false, redeploy, done.
    cache_enabled: bool = False
    # redis://... or rediss://... The password lives in this URL, so it is
    # never logged, never echoed in an error, and never returned by an
    # endpoint.
    redis_url: str = ""
    # Fallback TTL for a cached read that does not state its own. Short
    # on purpose: these are figures a merchant reads to understand their
    # own money, and the cost of a stale one is confusion about whether a
    # payment arrived.
    cache_default_ttl_seconds: int = 30

    # A single Supabase round trip slower than this gets one warning line
    # naming the table (never the filters — those are phone numbers and
    # merchant ids). See app/database/session.py::_log_if_slow.
    #
    # 400ms, not 50: the measured floor for any Supabase REST query is
    # 56-60ms (see /health/db-latency), so a threshold near that would
    # fire on everything, and a legitimate report over a busy merchant's
    # history is allowed to take a moment. The number is set to catch a query that has lost its
    # index or outgrown its access pattern, not to narrate normal
    # traffic — a threshold that fires constantly is one people filter
    # out. 0 disables it.
    slow_query_warning_ms: int = 400

    sentry_dsn: str = ""
    sentry_environment: str = ""
    # Traces are off by default. Performance tracing samples real request
    # paths, and a payment platform's URLs and timings are themselves
    # information worth not exporting until someone decides to.
    sentry_traces_sample_rate: float = 0.0

    # Product analytics (PostHog), server side. Off unless a key is set.
    #
    # Deliberately separate from the browser key: this one is a write-only
    # project key but still server-held, and nothing in app/core/analytics.py
    # sends a property that identifies a person — merchant_id, a UUID we
    # already own, is the only identity that leaves.
    posthog_api_key: str = ""
    posthog_host: str = "https://eu.i.posthog.com"

    # Mandatory TOTP for platform admins (docs/SUPER_ADMIN_MFA_RUNBOOK.md).
    # When true, require_super_admin additionally demands a Supabase `aal2`
    # session — a Super Admin holding only a password is refused with
    # `mfa_required` on every /v1/admin route.
    #
    # Default false so deploying this code changes nothing: enrolment has to
    # happen before enforcement, or the first deploy locks every admin out of
    # approving withdrawals. Turning it on is the documented, deliberate step,
    # and setting it back to false is the whole rollback.
    require_super_admin_mfa: bool = False

    # Security alerts (app/services/security_alerts.py) — the subset of
    # audit events worth interrupting someone for: money approved, a
    # merchant admitted, pricing changed, or signs of someone trying to get
    # in. audit_logs remains the complete record either way; turning alerts
    # off silences email only, never the audit trail.
    security_alerts_enabled: bool = True
    # Falls back to the first CEO_EMAIL recipient when unset, so enabling
    # alerts does not require configuring a second address first.
    security_alert_email: str = ""
    # Applies only to events a single actor can trigger repeatedly (failed
    # MFA, rejected IPs). Money decisions are never deduplicated — each one
    # is a separate decision about real funds.
    security_alert_dedupe_window_seconds: int = 600

    # Every logger in this app is named "infinity.X" (logging.getLogger(
    # "infinity.scheduler"), "infinity.webhooks", etc.) — see
    # app/main.py::_configure_logging, which sets this level on their
    # shared "infinity" parent logger. Nothing configured Python's
    # logging system at all before this existed, which meant every
    # logger.info()/.debug() call was silently dropped in production
    # (the root logger defaults to WARNING with no handler) — only
    # .warning()/.error()/.exception() calls were ever visible in
    # Railway logs. Confirmed 2026-08-28 investigating why the checkout
    # reconciliation scheduler's own startup/sweep confirmation logs
    # never appeared even though the scheduler was running correctly.
    log_level: str = "INFO"

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # JWT verification — a Supabase project uses EITHER a legacy shared HS256
    # secret (supabase_jwt_secret) OR JWKS-based asymmetric signing keys
    # (supabase_jwks_url/supabase_jwt_issuer), never both as the *current*
    # key. See app/auth/jwt.py: JWKS is tried first when configured, HS256
    # is the fallback (and what the test suite's fake tokens always use).
    supabase_jwt_secret: str = ""
    supabase_jwks_url: str = ""
    supabase_jwt_issuer: str = ""

    # Database (Supabase Postgres connection string)
    database_url: str = ""

    # CORS — origins allowed to call this API (allow_credentials=True in
    # app/main.py, so this can never be "*" — the CORS spec disallows
    # combining a wildcard origin with credentialed requests, and a browser
    # will reject it). Read as a plain string here (not list[str]) so both
    # a JSON array (CORS_ORIGINS=["https://infinitypay.me"]) and a
    # plain comma-separated value
    # (CORS_ORIGINS=https://infinitypay.me,https://www.infinitypay.me)
    # work — pydantic-settings would otherwise hard-require valid JSON for
    # any list-typed field and reject a bare comma-separated value outright
    # (Railway's env var UI makes typing JSON-with-quotes error-prone). Use
    # the `cors_origins` property below, never this field, to read the
    # parsed list.
    cors_origins_raw: str = Field(
        default='["http://localhost:3000"]', validation_alias="CORS_ORIGINS"
    )

    @property
    def cors_origins(self) -> list[str]:
        stripped = self.cors_origins_raw.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            return json.loads(stripped)
        return [origin.strip() for origin in stripped.split(",") if origin.strip()]

    # Base URL of apps/web, used to build the public payment link URL
    # (public_slug -> {public_app_url}/pay/{public_slug}).
    public_app_url: str = "http://localhost:3000"

    # Mock Selcom client (see app.services.selcom.mock_client) — the default
    # client (SELCOM_MODE=mock below) every collection/disbursement runs
    # through until Selcom whitelisting is done (see
    # docs/selcom-live-go-live.md).
    mock_provider_failure_rate: float = 0.1
    mock_provider_latency_seconds: float = 0.3
    dynamic_qr_expiry_seconds: int = 300

    # Shared secret for verifying the (mock) HMAC signature on incoming
    # POST /v1/webhooks/selcom deliveries — see app/services/selcom/webhooks.py.
    selcom_webhook_secret: str = ""

    # Encryption-at-rest key for merchants.webhook_secret_encrypted (see
    # app/core/secret_box.py) — a merchant's OUTBOUND webhook signing secret,
    # the one secret in this codebase that must be recoverable in full after
    # creation (HMAC signing needs the raw value, not a hash). Backend/Railway
    # only, NEVER set in apps/web/Vercel, NEVER logged. Blank falls back to a
    # key derived from supabase_service_role_key — fine for local dev/test,
    # not for production (set a real Fernet key there).
    webhook_secret_encryption_key: str = ""

    # Selcom production integration (Railway) — see docs/selcom-live-go-live.md
    # for the full deploy/whitelist/go-live procedure. All blank/default
    # until Selcom confirms IP whitelisting and issues live credentials.
    # Backend/Railway env vars only — NEVER set any of these in
    # apps/web/Vercel.
    selcom_base_url: str = ""
    selcom_api_key: str = ""
    selcom_api_secret: str = ""
    selcom_vendor_id: str = ""
    selcom_collection_enabled: bool = False
    selcom_withdrawal_enabled: bool = False
    # Informational only — the real route is registered at this fixed path
    # in app/main.py regardless of this value; it exists so the path Selcom
    # needs for callback configuration is documented alongside the rest of
    # the Selcom config rather than only in code.
    selcom_webhook_path: str = "/v1/webhooks/selcom"
    # "mock" (default) -> app.services.selcom.mock_client.MockSelcomClient,
    # simulated responses only, no network call ever reaches Selcom. "live"
    # -> app.services.selcom.live_client.LiveSelcomClient, real HTTP calls
    # to SELCOM_BASE_URL. See app/services/selcom/client.py::get_selcom_client()
    # and docs/selcom-live-go-live.md before ever setting this to "live" in
    # a deployed environment.
    selcom_mode: str = "mock"

    # Selcom Business Disbursement API (developer.selcom.business) — the
    # real, documented API withdrawals are approved against, distinct from
    # the checkout/collections API above (different product, different
    # RSA-SHA256 signing scheme — see app/services/selcom_business/).
    # "mock" is local-development-only; the shipped default here is
    # "sandbox", never "mock" — a real withdrawal approval must never
    # silently no-op against a fake client. Backend/Railway env vars only,
    # NEVER set any of these in apps/web/Vercel.
    selcom_business_mode: str = "sandbox"
    selcom_business_sandbox_base_url: str = "https://sandbox.selcom.business"
    selcom_business_production_base_url: str = "https://api.selcom.business/v1"
    selcom_business_api_key: str = ""
    selcom_business_private_key_base64: str = ""
    selcom_business_account_number: str = ""
    selcom_business_timeout_seconds: int = 30
    selcom_business_require_ip_whitelist: bool = False

    # Selcom Checkout/Collections API (https://developers.selcommobile.com/)
    # — the real, documented reference for USSD/STK/wallet push, Selcom
    # Pesa push, and dynamic QR collections, superseding the earlier
    # unconfirmed app/services/selcom/ placeholder. Distinct product/
    # signing scheme from selcom_business above (RSA-only, different
    # header names). Backend/Railway env vars only, NEVER set any of
    # these in apps/web/Vercel. See app/services/selcom_checkout/.
    selcom_checkout_mode: str = "mock"
    selcom_checkout_base_url: str = ""
    selcom_checkout_api_key: str = ""
    selcom_checkout_api_secret: str = ""
    selcom_checkout_digest_method: str = "HS256"
    selcom_checkout_vendor: str = ""
    selcom_checkout_timeout_seconds: int = 30
    # Only needed if Selcom confirms this account requires RS256 instead
    # of HS256 — see app/services/selcom_checkout/signer.py.
    selcom_checkout_private_key_base64: str = ""
    # Our own webhook callback URL (not a secret — it's a public endpoint
    # of ours), e.g. https://<api-domain>/v1/webhooks/selcom/checkout.
    # Sent on every create-order-minimal call so Selcom knows where to
    # deliver payment_status updates — see
    # app/services/checkout_orders.py::create_checkout_order_minimal().
    # Left blank, no webhook field is sent at all (Selcom never calls
    # back; reconciliation still works via the manual refresh endpoints).
    selcom_checkout_webhook_url: str = ""

    # Confirmed 2026-08-27 against 5 real deliveries: Selcom's Checkout
    # webhook sends no signature at all, so POST /v1/webhooks/selcom/checkout
    # fails closed on every production delivery by design (see
    # app/routers/webhooks.py::selcom_checkout_webhook and
    # docs/selcom-checkout-collections.md). This is the ONLY way to make
    # the webhook accept an unsigned delivery, and it's a hard AND of
    # both conditions below — never reachable by setting just one:
    #   1. environment must be exactly "development" (mirrors
    #      _reject_wildcard_cors_outside_development's convention below —
    #      never "production", "staging", or anything else)
    #   2. the request must carry header X-Internal-Test-Secret matching
    #      this value exactly (constant-time compared) — blank here means
    #      the bypass can never match, even in development
    # A real Railway production deployment's ENVIRONMENT is never
    # "development", so this is structurally impossible to enable in
    # production by misconfiguring this one variable alone.
    selcom_checkout_webhook_test_secret: str = ""

    # Backend-initiated, webhook-independent reconciliation sweep — see
    # app/services/checkout_reconciliation.py::reconcile_pending_checkout_collections
    # and app/main.py's lifespan startup task. Since the inbound webhook
    # can never pass signature verification for real Selcom traffic (see
    # above), this periodic sweep — not the webhook — is what actually
    # keeps merchant wallets credited without a human clicking "Refresh
    # status": it calls Selcom's own authenticated order-status API
    # directly for every collection still "processing", on a timer,
    # never trusting any inbound signal. 0 (the default) disables it
    # entirely — safe for local dev/tests, where no scheduled task should
    # run unexpectedly in the background. Set a real interval (e.g. 120)
    # in Railway to actually enable it.
    selcom_checkout_reconcile_interval_seconds: int = 0

    # Same idea as selcom_checkout_reconcile_interval_seconds above, for
    # withdrawals — see app/services/disbursements.py::
    # reconcile_pending_disbursements and app/main.py's lifespan startup
    # task. Unlike checkout collections, the Selcom Business disbursement
    # webhook (app/routers/webhooks.py::selcom_webhook) is signed and
    # verified successfully, so this isn't compensating for a broken
    # inbound signal — it's a safety net for a delivery that's delayed,
    # dropped, or never sent, so a withdrawal doesn't sit PROCESSING
    # forever waiting on a human to click "Refresh Status". 0 (the
    # default) disables it entirely. Set a real interval (e.g. 120) in
    # Railway to actually enable it.
    selcom_disbursement_reconcile_interval_seconds: int = 0

    # How many payments one reconciliation sweep may ask the provider
    # about. The sweeps were unbounded until 2026-10-17: they selected
    # every pending row and called Selcom for each, so the sweep interval
    # and the provider load were the same dial.
    #
    # Sized against the measured peak of 78 simultaneously pending
    # collections. A batch of 40 drains that in two ticks at a ten second
    # interval while capping any single sweep's provider calls, so a
    # backlog cannot turn one tick into hundreds of requests.
    #
    # Shared by both sweeps. Collections and disbursements each get their
    # own batch rather than a pooled one, so a collection backlog can
    # never starve payout reconciliation - the two have very different
    # urgencies and a stuck payout is the more expensive to leave.
    selcom_reconcile_batch_size: int = 40


    # Outbound merchant webhook delivery sweep — see
    # app/services/webhook_delivery.py and app/main.py's lifespan task.
    # enqueue_webhook_event has always written webhook_events rows;
    # nothing delivered them until that worker existed, so a partner
    # waiting on `collection.success` received nothing and had to poll.
    # 0 (the default) disables it, so local dev and tests never POST to a
    # merchant's URL in the background. Set a real interval (e.g. 30) in
    # Railway to actually enable it. Deliberately NOT gated by
    # enable_auto_reconciliation: that flag is a kill switch for provider
    # polling, and webhook delivery is outbound to merchants, not Selcom.
    webhook_delivery_interval_seconds: int = 0

    # --- Merchant SMS (OasisTech BulkSMS) ---------------------------------
    #
    # Server-only, all of it. None of these may ever appear in apps/web or
    # apps/mobile: a sender ID is harmless, but an API key in a browser
    # bundle is an account anyone can spend.
    #
    # The master switch. False (the default) means the dispatch worker
    # never starts and nothing is ever offered to the provider - rows are
    # still enqueued, so turning it on later sends what accumulated, and
    # turning it OFF is the rollback: dispatch stops, history is kept, no
    # financial record changes.
    oasis_sms_enabled: bool = False
    oasis_sms_api_key: str = ""
    # Must be an approved sender ID on the provider account, 3-20 chars.
    # An unapproved one is a 403 on every send, not a silent failure.
    oasis_sms_sender_id: str = ""
    # Only needed if provider callbacks are registered. Blank means the
    # callback endpoint rejects everything, which is the safe default for
    # an endpoint whose whole job is to accept unauthenticated POSTs.
    oasis_sms_webhook_secret: str = ""

    oasis_sms_base_url: str = "https://bulksms.oasistech.co.tz"

    # 0 (the default) disables the dispatch loop, exactly like
    # webhook_delivery_interval_seconds above - so local dev and tests
    # never reach a real provider in the background. 30 is the intended
    # production value.
    oasis_sms_dispatch_interval_seconds: int = 0

    # The documented account-wide limit is 300 send requests/minute, with a
    # separate per-IP guard of 600. 240 leaves a fifth of the account's
    # capacity for anything else sharing these credentials - the brief
    # explicitly asks for that headroom, and we do not control what else
    # the account is used for.
    #
    # This is enforced in-process, which is only equivalent to an
    # account-wide limit because the dispatch sweep holds the
    # 'sms_dispatch' scheduler lease and therefore runs in exactly one
    # replica at a time. Remove that lease and this becomes a per-replica
    # limit silently.
    oasis_sms_rate_limit_per_minute: int = 240

    # The provider documents a client timeout of at least 180 seconds.
    # Below that, a slow-but-successful send looks like a timeout, and a
    # timeout is the one outcome we cannot safely retry with a new key.
    oasis_sms_timeout_seconds: int = 180

    # How many messages one sweep may dispatch. Bounded so a large
    # announcement cannot occupy the worker indefinitely while collection
    # alerts wait behind it.
    oasis_sms_batch_size: int = 50

    # Announcements never take more than this share of a batch, so a
    # 60-merchant blast cannot starve transactional alerts.
    oasis_sms_announcement_batch_size: int = 20

    # The two automatic messages, each switchable on its own. Both
    # default OFF: new automation that spends money per message is a
    # deliberate decision, not something a deploy turns on.
    #
    # Collection alerts used to live here too. They were retired on
    # 2026-10-17 for cost - 3,748 payments in sixteen days is roughly 230
    # messages a day - and there is no flag for them any more because
    # nothing enqueues them.
    oasis_sms_welcome_enabled: bool = False
    oasis_sms_withdrawal_enabled: bool = False

    # What one message part costs, for the Super Admin cost estimates.
    # Configurable rather than a constant in the code: a tariff is a
    # commercial fact that changes without a deploy, and a hardcoded
    # figure silently becomes a lie. Nothing financial reads this - it
    # never touches a fee, a ledger entry or what a merchant is charged.
    oasis_sms_credit_cost_tzs: Decimal = Decimal(25)


    # Hosted checkout (payment_gateway_url from create-order-minimal) —
    # confirmed broken on Selcom's own side as of 2026-08-23 (returns
    # "Page Not Found" for every order tested — see
    # docs/selcom-checkout-collections.md, "Known issue" section).
    # Active customer payment methods are wallet-push/Selcom Pesa/TanQR
    # instead (app/services/collection_payment.py). This flag is the
    # explicit, backend-level guard keeping hosted checkout inactive —
    # POST /public/payment-links/{slug}/pay/checkout refuses to run
    # while this is False (the default), even though no current frontend
    # calls it either. Flip only once Selcom confirms hosted checkout is
    # fixed; the endpoint/service code itself is untouched and ready.
    hosted_checkout_enabled: bool = False

    # Platform economics — simple placeholders until real pricing rules exist.
    platform_fee_percentage: Decimal = Decimal("1.5")

    # Backend-controlled withdrawal amount guardrails for MVP launch —
    # supersedes the old temporary WITHDRAWAL_PILOT_MODE/
    # WITHDRAWAL_PILOT_MAX_AMOUNT_TZS cap
    # (docs/withdrawal-production-pilot-checklist.md), which existed only
    # to keep pilot withdrawals to TZS 1,000 while the end-to-end payout
    # path was being proven. Real collections and withdrawals have since
    # been tested successfully — see docs/MVP_LAUNCH_CHECKLIST.md — so
    # this is now a permanent, always-on set of production limits rather
    # than a togglable pilot cap. Enforced in
    # app/services/disbursements.py::_check_withdrawal_amount_limits,
    # called from execute_disbursement before any withdrawal row is
    # written — the frontend never decides these, only displays whatever
    # error message the backend returns.
    min_withdrawal_amount_tzs: Decimal = Decimal(1000)
    max_withdrawal_amount_tzs: Decimal = Decimal(5000000)
    # Rolling 24-hour cumulative cap per merchant, across every
    # non-rejected/non-failed withdrawal request in that window (a
    # rejected/failed request never actually moved money, so it doesn't
    # count against the cap) — catches "many small withdrawals" abuse a
    # per-request max alone wouldn't.
    daily_withdrawal_limit_tzs: Decimal = Decimal(10000000)

    # Master safety switch for withdrawal automation (see
    # app/services/disbursements.py::_evaluate_auto_withdrawal_eligibility).
    # Automatic processing only ever runs when THIS is True *and*
    # auto_withdrawals_enabled below is also True — both, deliberately, so
    # a deploy that sets one but not the other (e.g. someone flips
    # AUTO_WITHDRAWALS_ENABLED=true in Railway without reading this one)
    # still fails safe to "every withdrawal needs a human." Default True
    # (the historical, always-manual behavior) — an operator must
    # deliberately set this to False in Railway to allow automation at
    # all. This used to document a hard invariant with no real "off"
    # switch at all; it now has one, on purpose, as part of the withdrawal
    # automation feature — see auto_withdrawals_enabled's docstring for
    # the full eligibility rules that still apply even when this is False.
    require_admin_approval_for_all_withdrawals: bool = True

    # Withdrawal automation (business request: reduce approval delays for
    # low-risk merchants without removing the safety net). Defaults to
    # False regardless of what a deployment's other withdrawal env vars
    # say — turning on real-money automation must be a deliberate,
    # explicit Railway change by someone who has read this whole block,
    # never a side effect of just deploying this code. Requires BOTH this
    # and require_admin_approval_for_all_withdrawals=False to take any
    # effect at all (see that field's docstring) — belt-and-suspenders so
    # a single misconfigured flag can't silently enable automation.
    #
    # When both are set, execute_disbursement() evaluates every new
    # withdrawal against auto_withdrawal_max_amount_tzs/
    # auto_withdrawal_daily_limit_tzs (below) plus the same merchant-
    # verification and open-high-risk-fraud-alert checks every withdrawal
    # already goes through regardless of automation. Eligible ones proceed
    # straight to the provider, same code path a Super Admin's manual
    # approval already uses (_reserve_and_run_disbursement_provider) — no
    # separate, less-tested "auto" payout path exists. Ineligible ones
    # land PENDING_ADMIN_APPROVAL exactly as before, with
    # disbursements.auto_decision_reason recording why automation didn't
    # apply. Kill switches, in order of what they actually stop:
    #   ENABLE_WITHDRAWALS=false           -> no new withdrawal requests at all
    #   AUTO_WITHDRAWALS_ENABLED=false      -> new requests still accepted,
    #                                          all go back to manual approval
    auto_withdrawals_enabled: bool = False
    # Per-transaction ceiling for automatic processing — deliberately far
    # below max_withdrawal_amount_tzs (the hard per-request cap every
    # withdrawal, auto or manual, must fit under). A request above this
    # amount is never rejected outright; it simply falls back to
    # PENDING_ADMIN_APPROVAL like automation was off, so raising or
    # lowering this only changes how much needs a human, never what's
    # allowed to withdraw at all. 500,000 TZS (~10% of the hard per-
    # request cap) is a conservative starting point, not a business-
    # derived figure — tune once real auto-withdrawal volume exists.
    auto_withdrawal_max_amount_tzs: Decimal = Decimal(500000)
    # Rolling 24-hour cap on the total amount this backend will
    # auto-process for a single merchant, independent of (and stricter
    # than) daily_withdrawal_limit_tzs above, which caps everything
    # requested (auto or manual) for the day. Exceeding this doesn't
    # reject the request — it just stops auto-processing for the rest of
    # that window, falling back to manual approval same as any other
    # ineligible request.
    auto_withdrawal_daily_limit_tzs: Decimal = Decimal(1000000)
    # Documents an invariant, not a real switch, same convention as
    # require_admin_approval_for_all_withdrawals above: every withdrawal
    # path (auto or manual) already calls
    # disbursements._check_merchant_is_verified unconditionally — setting
    # this to False cannot and does not skip it. Kept as an explicit,
    # checkable setting for ops/audit visibility rather than only a code
    # comment.
    auto_withdrawal_require_approved_merchant: bool = True

    # Email OTP on merchant withdrawals (app/services/withdrawal_otp.py).
    # The merchant proves control of their registered email before a
    # withdrawal request is created at all — nothing is written to
    # disbursements, no provider is called, and no CEO notification is sent
    # until the code verifies. Defaults are deliberately usable as-is so a
    # deployment cannot end up with OTP effectively disabled by forgetting
    # an env var; there is no flag to turn this off, because "skip the
    # verification step on money movement" is not a configuration this
    # should offer.
    withdrawal_otp_expires_minutes: int = 10
    withdrawal_otp_max_attempts: int = 5
    withdrawal_otp_resend_cooldown_seconds: int = 60

    # Transactional email (Resend) — see app/services/email.py and
    # docs/email-delivery.md. Backend/Railway only, NEVER set
    # RESEND_API_KEY in apps/web/Vercel. Blank RESEND_API_KEY means email
    # sending is not configured — send_email() raises EmailDeliveryError
    # rather than silently no-op'ing, since a caller (e.g. "send invoice")
    # needs to know delivery didn't happen.
    resend_api_key: str = ""
    # Default sender for every transactional email EXCEPT invoice payment
    # requests (staff invites, password resets, payment receipts, welcome
    # emails, inquiry notifications) — see invoice_email_from below for why
    # invoices use a visually distinct address.
    email_from: str = "InfinityPay <notification@infinitypay.me>"
    # Sender for invoice payment-request emails specifically — a customer
    # should be able to tell "someone wants to be paid" apart from
    # ordinary account/notification mail at a glance. Falls back to
    # email_from when blank (see the invoice_email_from property) so a
    # deployment that forgets to set this still sends *something* sane
    # rather than failing outright.
    invoice_email_from_raw: str = Field(default="", validation_alias="INVOICE_EMAIL_FROM")
    # Reply-to for every transactional email — the customer/merchant
    # support contact shown in every template's footer.
    email_reply_to: str = "info@infinitypay.me"
    # Where internal notifications go — new inquiries, new merchant signups,
    # and withdrawal requests awaiting approval. Set via Railway's CEO_EMAIL
    # env var (no code default).
    #
    # Accepts a comma-separated list, so a second Super Admin can be copied
    # in without code changes. Being in platform_admins does NOT subscribe
    # anyone to these — admin *authorisation* and notification *delivery*
    # are deliberately separate, so adding an admin never silently starts
    # mailing a new address. Read it through ceo_emails, never directly.
    ceo_email: str = ""
    # General site base URL for links inside emails (distinct from
    # public_app_url, which specifically builds the /pay/{slug} payment
    # link — see app/services/payment_links.py::build_public_url). Falls
    # back to public_app_url when blank. Production (Railway): https://infinitypay.me
    app_url_raw: str = Field(default="", validation_alias="APP_URL")

    # Email-volume reduction (business request, 2026-09): each gates one
    # category of email independently — never RESEND_API_KEY itself, so
    # turning any of these off never affects the others. All default False
    # (the currently-desired reduced-volume state), not True — flip
    # individually back to True in Railway to restore a given category
    # without code changes. Never gates: email verification, password
    # reset, staff invite, merchant approval/welcome email, CEO merchant
    # signup notification, or any security-alert email — those are never
    # conditional on any of these three flags, regardless of their values.
    #
    # Customer-facing payment receipt (app/services/email.py::
    # send_payment_receipt_email) — the one email sent to the *paying
    # customer* after a collection succeeds. Does not affect the payment
    # succeeding, the wallet being credited, or the in-portal receipt
    # page/download, all of which are unconditional. Also does not affect
    # send_payment_link_customer_email (the "Pay Now" link sent when a
    # payment link is *created*, a different email entirely) or
    # send_merchant_collection_notification_email (goes to the merchant's
    # own configured notification address, gated separately by that
    # feature's own collection_notifications_enabled setting).
    send_customer_receipt_emails: bool = False
    # CEO-bound "please review this withdrawal request" email
    # (send_withdrawal_request_notification_email) sent on every new
    # withdrawal request. Turning this off never affects the request
    # itself, its audit log, or its visibility in the Super Admin
    # withdrawals queue — only this one notification email.
    send_withdrawal_request_emails: bool = False
    # Merchant-facing "your withdrawal succeeded" email
    # (send_withdrawal_success_email). The in-app notification
    # (notify_merchant(...WITHDRAWAL_SUCCESS...)) and the webhook event
    # are unconditional either way — only this email is gated.
    send_merchant_withdrawal_emails: bool = False

    @property
    def ceo_emails(self) -> list[str]:
        """CEO_EMAIL parsed into recipients, in the order given.

        Blanks and duplicates are dropped so a trailing comma or a repeated
        address cannot send someone the same alert twice, and an empty
        result is the signal callers already use to skip the send entirely.
        """
        seen: list[str] = []
        for part in (self.ceo_email or "").split(","):
            address = part.strip()
            if address and address not in seen:
                seen.append(address)
        return seen

    @property
    def invoice_email_from(self) -> str:
        return self.invoice_email_from_raw or self.email_from

    @property
    def app_url(self) -> str:
        return self.app_url_raw or self.public_app_url

    # Collection clearance (docs/ledger-reconciliation.md) — reserved
    # config for a future delayed-settlement gate. Not yet wired to a
    # background worker (none exists in this codebase); the active
    # safety nets today are reverse_successful_collection() (real
    # reversal after credit) and the SELF_PAYMENT_OWN_TILL fraud rule
    # (pending_review hold before credit). Left False/unused rather than
    # half-wired, so it does nothing until a real recheck mechanism backs
    # it — see the docs file for why.
    collection_auto_settle_enabled: bool = False
    collection_clearance_delay_minutes: int = 10

    # Production safety switches — MVP launch kill switches, distinct from
    # selcom_collection_enabled/selcom_withdrawal_enabled above (those two
    # report whether Selcom credentials are configured at all; these
    # control whether this backend currently accepts *new* requests,
    # independent of provider config). All default True so nothing changes
    # unless deliberately flipped off in Railway. Checked at the top of
    # every collection-creating / withdrawal-creating endpoint (see
    # app/core/feature_flags.py) — existing records always remain
    # viewable/listable regardless of these flags; only new
    # requests/writes are blocked. Flip ENABLE_COLLECTIONS or
    # ENABLE_WITHDRAWALS to false in Railway for an immediate, whole-system
    # pause without a redeploy of code — see docs/MVP_LAUNCH_CHECKLIST.md,
    # "How to disable withdrawals/collections quickly".
    enable_collections: bool = True
    enable_withdrawals: bool = True
    # Gates new API key creation/rotation only (app/routers/merchant_portal.py)
    # — existing issued keys keep working (revoke them individually via
    # the existing revoke endpoint if a key itself needs to be cut off).
    enable_merchant_api_keys: bool = True
    # ANDed with selcom_checkout_reconcile_interval_seconds /
    # selcom_disbursement_reconcile_interval_seconds > 0 in app/main.py —
    # sweeps never start if either this is False or the relevant interval
    # is 0. A single flag to pause both schedulers at once without
    # separately zeroing each interval var.
    enable_auto_reconciliation: bool = True

    # --- Merchant referral commissions -------------------------------
    #
    # Off by default. The tables and endpoints ship inert: with this
    # False, no code is issued, no referral is captured at signup, and the
    # daily recalculation never starts. Turning it on changes nothing
    # retroactively - a referral has to be captured while it is on.
    #
    # Nothing here pays anybody. A commission still needs a Super Admin to
    # approve it, and marking one paid records a payout made elsewhere.
    referral_program_enabled: bool = False
    # 1500 bps = 15% of what InfinityPay earned from the referred
    # merchant, never of what the merchant collected.
    referral_commission_rate_bps: int = 1500
    # The referred merchant must put this much through in successful
    # collections, inside the window, before anything is owed. This is
    # what stops a signup farm paying out.
    referral_min_successful_volume: Decimal = Decimal(100000)
    # Below this, a commission is held as below_threshold rather than
    # offered for review - not worth an approval and a payout each.
    referral_min_payout_amount: Decimal = Decimal(5000)
    # Measured from approval, not signup.
    referral_period_days: int = 30
    # 0 disables the sweep, matching the reconciliation intervals above.
    referral_recalculation_interval_seconds: int = 3600

    @property
    def referral_defaults(self) -> dict:
        """The terms a new referral is captured under. Copied onto the row
        so a later change to these numbers cannot re-price a referral that
        has already been earned."""
        return {
            "qualification_volume_threshold": str(self.referral_min_successful_volume),
            "commission_rate_bps": self.referral_commission_rate_bps,
            "minimum_payout_amount": str(self.referral_min_payout_amount),
        }

    @property
    def docs_enabled(self) -> bool:
        """Whether Swagger UI (/docs), ReDoc (/redoc), and the raw OpenAPI
        schema (/openapi.json) should be wired up at all — see app.main.
        They're unauthenticated by construction (FastAPI serves them to
        anyone who asks), which is fine for local/staging use while
        building against this API but not fine left open on the real
        production fintech backend (a full machine-readable map of every
        route, including admin/withdrawal/wallet endpoints, for an
        unauthenticated caller). Disabling them only removes the docs UI
        itself — no actual endpoint depends on them being enabled."""
        return self.environment != "production"

    @field_validator("*", mode="before")
    @classmethod
    def _tolerate_human_booleans(cls, value: object, info: ValidationInfo) -> object:
        """A mistyped feature flag must not take the platform down.

        On 2026-10-16 OASIS_SMS_ENABLED was set to the word "enabled".
        Pydantic cannot read that as a boolean, so Settings() raised - and
        because app/main.py builds settings at module import, the whole
        API failed to boot. Every merchant lost payments for roughly
        twenty minutes because of one word in a text-message toggle.

        Two changes, in order of how much they matter:

        **Unrecognised values fall back to the field's own default**
        rather than raising. That default is exactly the state the
        platform runs in when the variable is not set at all - the
        configuration every fresh deploy starts from - so it is always a
        known-good state. A typo can now degrade one feature; it can no
        longer stop payments. It is logged at ERROR with the field name,
        because a flag quietly not doing what someone intended still
        needs finding.

        **Common human spellings are accepted**: enabled/disabled, on/off,
        y/n. Somebody typing "enabled" into a variable called *_ENABLED is
        not making a mistake worth punishing.

        Deliberately not applied to anything but booleans, and deliberately
        does not soften _reject_wildcard_cors_outside_development below:
        a wildcard CORS origin in production is a security hole, and
        refusing to boot is the right answer to that. The difference is
        that one is dangerous to run with, and this one is merely wrong.
        """
        field = cls.model_fields.get(info.field_name or "")
        if field is None or field.annotation is not bool or isinstance(value, bool):
            return value

        text = str(value).strip().lower()
        if text in _TRUE_WORDS:
            return True
        if text in _FALSE_WORDS:
            return False

        default = field.default
        logger.error(
            "settings_bool_unparsable field=%s value=%r falling_back_to=%s",
            info.field_name,
            str(value)[:40],
            default,
        )
        return default

    @model_validator(mode="after")
    def _reject_wildcard_cors_outside_development(self) -> "Settings":
        """allow_credentials=True in app/main.py's CORSMiddleware makes a
        "*" origin both a browser-rejected combination and a real security
        hole (any site could call this API with a signed-in merchant's
        cookies/credentials) — refuse it outright anywhere that isn't local
        development, the same guardrail pattern as
        SelcomBusinessMisconfiguredError below for SELCOM_BUSINESS_MODE."""
        if self.environment != "development" and "*" in self.cors_origins:
            raise ValueError(
                'CORS_ORIGINS must not contain "*" when ENVIRONMENT is not "development" '
                "(allow_credentials=True makes a wildcard origin unsafe and browsers reject it "
                "anyway) — list explicit deployed frontend origins instead."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
