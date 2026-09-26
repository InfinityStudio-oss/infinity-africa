"""The Selcom Checkout/Collections API client
(https://developers.selcommobile.com/).

create_order_minimal() below is the first endpoint method implemented —
Step 1 for STK/USSD/wallet push, payment-link checkout, and dynamic
QR/token display. It creates an order shell on Selcom's side and returns
a payment_token/qr/gateway URL; it never itself pulls money (no
wallet-payment call happens here or anywhere in this module yet).

Every other endpoint method (get-order-status, process-wallet-payment,
etc.) still needs three things confirmed first, none of them guessed:

1. The exact request field names and their required order (that order
   becomes both the signing string and the Signed-Fields header).
2. The exact response field names.
3. A real sandbox round-trip proving both.

SelcomCheckoutHTTPClient._signed_request below is the one place every
endpoint method calls through — it handles signing, sending, and
envelope decoding generically; only the per-endpoint path/fields change
per call. Confirmed endpoint paths, for when more of these are added
(https://developers.selcommobile.com/, fetched 2026-08-22):

    POST /v1/checkout/create-order
    POST /v1/checkout/create-order-minimal   (implemented — see below)
    POST /v1/checkout/cancel-order
    GET  /v1/checkout/get-order-status?order_id={order_id}   (implemented — see below)
    GET  /v1/checkout/list-orders
    GET  /v1/checkout/fetch-card-tokens
    POST /v1/checkout/delete-card
    POST /v1/checkout/process-card-payment
    POST /v1/checkout/process-wallet-payment   (implemented — see below)
    POST /v1/checkout/process-selcom-pesa-payment
    POST /v1/checkout/create-till-alias
    POST /v1/checkout/webhook-callback   (inbound — handled in a router, not this client)

USSD Push / STK Push / Dynamic QR were not documented on the fetched
page (only a wallet-cashin-flavored "Push USSD" for C2B collection was
shown) — confirm these with Selcom support before assuming they exist
under these or similar paths.
"""

import logging
import time

import httpx

from app.config import Settings, get_settings
from app.services.selcom.outbound_guard import SelcomCircuitOpenError, selcom_outbound
from app.services.selcom_checkout.errors import (
    SelcomCheckoutError,
    SelcomCheckoutMisconfiguredError,
)
from app.services.selcom_checkout.parsing import (
    base64_encode_url,
    decode_json_response,
    parse_create_order_minimal_response,
    parse_order_status_response,
    parse_selcompesa_payment_response,
    parse_wallet_payment_response,
)
from app.services.selcom_checkout.schemas import (
    CreateOrderMinimalResult,
    OrderStatusResult,
    SelcomCheckoutCredentials,
    SelcomPesaPaymentResult,
    WalletPaymentResult,
)
from app.services.selcom_checkout.signer import build_auth_headers

logger = logging.getLogger("infinity.selcom_checkout")


def _join_url(base_url: str, path: str) -> str:
    """Joins a configured base URL with an endpoint path constant,
    collapsing a duplicated API-version segment if the base URL already
    ends with one — confirmed necessary against real production Selcom
    infrastructure (2026-08-22): SELCOM_CHECKOUT_BASE_URL is
    "https://apigw.selcommobile.com/v1", and every path constant in this
    module already starts with "/v1/..." (matching the docs' own
    "POST /v1/checkout/create-order-minimal" notation, written as if from
    the domain root) — naive concatenation produced
    ".../v1/v1/checkout/create-order-minimal" and a real HTTP 404 from
    Selcom. Only collapses a `/v1` (or `/v1/`) suffix specifically, not a
    general de-duplication — if Selcom's base URL for some other
    environment doesn't include a version segment, this is a no-op."""
    base = base_url.rstrip("/")
    if base.endswith("/v1") and path.startswith("/v1/"):
        return base[: -len("/v1")] + path
    return base + path


def get_selcom_checkout_credentials(settings: Settings | None = None) -> SelcomCheckoutCredentials:
    """Builds credentials from Settings — the only place SELCOM_CHECKOUT_*
    env vars are read for this client. Returns them bundled in one object
    rather than as loose strings so nothing accidentally ends up in a log
    call's format string."""
    s = settings or get_settings()
    return SelcomCheckoutCredentials(
        base_url=s.selcom_checkout_base_url,
        api_key=s.selcom_checkout_api_key,
        api_secret=s.selcom_checkout_api_secret,
        digest_method=s.selcom_checkout_digest_method,
        vendor=s.selcom_checkout_vendor,
        private_key_base64=s.selcom_checkout_private_key_base64,
        timeout_seconds=s.selcom_checkout_timeout_seconds,
    )


class SelcomCheckoutHTTPClient:
    """Raw signed HTTP calls to Selcom's Checkout API. No endpoint-specific
    methods yet — see module docstring for why, and for the confirmed
    path list ready for when that work starts."""

    def __init__(self, *, credentials: SelcomCheckoutCredentials):
        if not credentials.base_url:
            raise SelcomCheckoutMisconfiguredError("SELCOM_CHECKOUT_BASE_URL is not configured")
        if not credentials.api_key:
            raise SelcomCheckoutMisconfiguredError("SELCOM_CHECKOUT_API_KEY is not configured")
        self._credentials = credentials

    async def _signed_request(
        self,
        method: str,
        path: str,
        fields: dict[str, str],
        *,
        signed_fields: dict[str, str] | None = None,
        timestamp: str | None = None,
    ) -> dict:
        """`fields` is the JSON body, sent verbatim (POST-shaped calls
        only; a GET/query-parameter endpoint needs its own handling once
        implemented, not guessed here) — its key order is what Selcom's
        docs require the signing string/Signed-Fields header to match by
        default. Never logs `fields` (may contain customer phone
        numbers/amounts) or any credential — only path/status/latency,
        matching the convention already established in
        app/services/selcom_business/live_client.py.

        `signed_fields` overrides what gets signed/named in Signed-Fields
        *without changing the JSON body* — exists only so
        create_order_minimal()'s diagnostic-only "official-shell"
        variant can probe a body/signature field-name mismatch against a
        real sandbox. Defaults to `fields` itself (the normal case: body
        and signature agree). Never set this from application code.

        `timestamp` defaults to signer.build_timestamp()'s UTC ISO-8601
        shape (via build_auth_headers) — the override exists only so
        scripts/test_selcom_checkout_create_order_minimal.py can test the
        docs' alternative "yyyy-dd-mm H:i:s" format against a real
        sandbox without touching this production default. Never set this
        from application code."""
        credentials = self._credentials
        headers = build_auth_headers(
            signed_fields if signed_fields is not None else fields,
            api_key=credentials.api_key,
            digest_method=credentials.digest_method,
            api_secret=credentials.api_secret,
            private_key_base64=credentials.private_key_base64,
            timestamp=timestamp,
        )
        if credentials.vendor:
            headers["Vendor"] = credentials.vendor

        url = _join_url(credentials.base_url, path)
        started = time.monotonic()
        try:
            # The highest-volume path to Selcom: every checkout order and
            # every reconciliation poll. Throttled so a billing cycle
            # cannot look like abuse from our IP.
            async with selcom_outbound(), httpx.AsyncClient(timeout=credentials.timeout_seconds) as http:
                if method == "GET":
                    # GET /v1/checkout/order-status?order_id=... — the
                    # field(s) still get signed exactly like a POST body
                    # (same Signed-Fields/signing-string convention), they
                    # just travel as query params instead of a JSON body.
                    response = await http.request(method, url, params=fields, headers=headers)
                else:
                    response = await http.request(method, url, json=fields, headers=headers)
        except SelcomCircuitOpenError as exc:
            # Breaker open: no request was made. Raised as the same error
            # a transport failure produces, so existing handling applies.
            raise SelcomCheckoutError(str(exc)) from exc
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            logger.warning(
                "selcom_checkout_request_failed path=%s latency_ms=%d error=%s",
                path,
                latency_ms,
                type(exc).__name__,
            )
            raise SelcomCheckoutError(f"Could not reach Selcom Checkout ({type(exc).__name__})") from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "selcom_checkout_request path=%s status=%d latency_ms=%d", path, response.status_code, latency_ms
        )
        return decode_json_response(status_code=response.status_code, body=response.content, path=path)

    async def create_order_minimal(
        self,
        *,
        order_id: str,
        buyer_email: str,
        buyer_name: str,
        buyer_phone: str,
        amount: str,
        no_of_items: int,
        currency: str = "TZS",
        buyer_remarks: str | None = None,
        merchant_remarks: str | None = None,
        redirect_url: str | None = None,
        cancel_url: str | None = None,
        webhook: str | None = None,
        header_colour: str | None = None,
        link_colour: str | None = None,
        button_colour: str | None = None,
        expiry: int | None = None,
        timestamp: str | None = None,
        signed_fields_variant: str = "default",
    ) -> CreateOrderMinimalResult:
        """POST /v1/checkout/create-order-minimal
        (https://developers.selcommobile.com/#create-order-minimal) —
        creates an order shell for non-card payments; never itself pulls
        money (this method never calls a wallet-payment endpoint, and
        neither does anything else in this module yet).

        Field order below is deliberate, not incidental — it becomes both
        the signing string and the Signed-Fields header, and the docs
        require both to match the payload exactly:

            vendor,order_id,buyer_email,buyer_name,buyer_phone,amount,currency,
            redirect_url,cancel_url,webhook,buyer_remarks,merchant_remarks,no_of_items

        with header_colour/link_colour/button_colour/expiry appended in
        that order when present — the docs' explicit default-order
        recitation stops at no_of_items, but the parameter table lists
        these four afterward, so that's where they go. Any absent
        optional field is omitted entirely from both the signature and
        the JSON body — never sent as an empty string.

        The docs' own shell example lists a *different* Signed-Fields set
        for this endpoint (buyer_user_id, payment_methods, payer_remarks,
        order_items) that doesn't match any example payload shown for
        Create Order - Minimal (those fields belong to a different
        Checkout endpoint's docs, most likely the full Create Order, not
        Minimal). Once fields not present in any Minimal example are
        dropped, the shell's order and the order above turn out identical
        for every field this method actually sends — so this discrepancy
        doesn't change anything in the `signed_fields_variant="default"`
        path. `signed_fields_variant="official-shell"` exists purely so
        scripts/test_selcom_checkout_create_order_minimal.py can probe
        the shell's literal, mismatched field names (payer_remarks/
        order_items in place of buyer_remarks/no_of_items, plus
        buyer_user_id/payment_methods signed as empty strings even though
        never sent in the body) against a real sandbox — diagnostic only,
        never selected by application code, which always uses "default".

        Also still unconfirmed: Timestamp *format* — the shell headers
        describe "yyyy-dd-mm H:i:s", not the ISO-8601
        signer.build_timestamp() produces by default. See the
        `timestamp` param and the diagnostic script, which tries both
        against a real sandbox.

        buyer_phone must already be normalized to "255XXXXXXXXX" by the
        caller (app.core.phone.normalize_tz_phone) — not re-validated
        here, since this client has no phone-format opinion of its own.

        redirect_url/cancel_url/webhook are base64-encoded here per the
        docs ("All URLs in the request and response are base64
        encoded") — never encode buyer_email/buyer_name/remarks/header_colour/
        link_colour/button_colour/etc. `qr` in the response is parsed
        exactly as returned (see parsing.py) — never base64-decoded
        unless Selcom's own response ever actually shows it base64-encoded,
        which the confirmed sample response doesn't.

        `timestamp` overrides the default ISO-8601 UTC timestamp;
        `signed_fields_variant` overrides the field-name mapping used for
        signing. Neither should ever be set from application code — both
        exist only for the sandbox diagnostic script.
        """
        if signed_fields_variant not in ("default", "official-shell"):
            raise ValueError(f"Unknown signed_fields_variant: {signed_fields_variant!r}")

        fields: dict[str, str] = {
            "vendor": self._credentials.vendor,
            "order_id": order_id,
            "buyer_email": buyer_email,
            "buyer_name": buyer_name,
            "buyer_phone": buyer_phone,
            "amount": amount,
            "currency": currency,
        }
        if redirect_url:
            fields["redirect_url"] = base64_encode_url(redirect_url)
        if cancel_url:
            fields["cancel_url"] = base64_encode_url(cancel_url)
        if webhook:
            fields["webhook"] = base64_encode_url(webhook)
        if buyer_remarks:
            fields["buyer_remarks"] = buyer_remarks
        if merchant_remarks:
            fields["merchant_remarks"] = merchant_remarks
        fields["no_of_items"] = str(no_of_items)
        if header_colour:
            fields["header_colour"] = header_colour
        if link_colour:
            fields["link_colour"] = link_colour
        if button_colour:
            fields["button_colour"] = button_colour
        if expiry is not None:
            fields["expiry"] = str(expiry)

        signed_fields = None
        if signed_fields_variant == "official-shell":
            # Diagnostic only — see the docstring above. A literal,
            # explicit reproduction of the shell's stated field list
            # (vendor,order_id,buyer_email,buyer_name,buyer_user_id,
            # buyer_phone,amount,currency,payment_methods,webhook,
            # payer_remarks,merchant_remarks,order_items), built directly
            # rather than derived from `fields` — deriving it by
            # transforming `fields` risks exactly the kind of
            # position/order mistake this whole exercise is trying to
            # rule out. buyer_user_id/payment_methods are signed as empty
            # strings (the shell lists them unconditionally) but never
            # added to the actual JSON body, which stays `fields`,
            # untouched. webhook/payer_remarks/merchant_remarks are
            # included only if the caller actually provided the
            # corresponding value, same optionality as the default path.
            signed_fields = {
                "vendor": self._credentials.vendor,
                "order_id": order_id,
                "buyer_email": buyer_email,
                "buyer_name": buyer_name,
                "buyer_user_id": "",
                "buyer_phone": buyer_phone,
                "amount": amount,
                "currency": currency,
                "payment_methods": "",
            }
            if webhook:
                signed_fields["webhook"] = fields["webhook"]
            if buyer_remarks:
                signed_fields["payer_remarks"] = buyer_remarks
            if merchant_remarks:
                signed_fields["merchant_remarks"] = merchant_remarks
            signed_fields["order_items"] = str(no_of_items)

        response = await self._signed_request(
            "POST",
            "/v1/checkout/create-order-minimal",
            fields,
            signed_fields=signed_fields,
            timestamp=timestamp,
        )
        return parse_create_order_minimal_response(response)

    async def process_wallet_payment(self, *, transid: str, order_id: str, msisdn: str) -> WalletPaymentResult:
        """POST /v1/checkout/wallet-payment — Step 2 of the Selcom
        Checkout push flow, after create_order_minimal() has already
        created an order shell. **This is the one call in this entire
        module that can actually move money** — triggers a real STK/USSD/
        wallet-pull push to `msisdn`. Never call this speculatively,
        automatically, or more than once per genuine customer payment
        attempt; see app/services/wallet_push.py for the one call site
        that should ever reach this in application code.

        Required fields, Signed-Fields order confirmed by the task
        brief (no shell/payload inconsistency this time, unlike
        create-order-minimal): transid,order_id,msisdn.

        The normal, expected response is PENDING (resultcode "111") —
        see parsing.py's parse_wallet_payment_response() and
        WalletPaymentResult's docstring for why that's deliberately not
        treated as failure, and why this method never decides on its own
        whether to credit anyone.

        msisdn must already be normalized to "255XXXXXXXXX" — no plus
        sign — by the caller (app.core.phone.normalize_tz_phone); not
        re-validated here, since this client has no phone-format opinion
        of its own (same convention as create_order_minimal's
        buyer_phone).
        """
        fields: dict[str, str] = {
            "transid": transid,
            "order_id": order_id,
            "msisdn": msisdn,
        }
        response = await self._signed_request("POST", "/v1/checkout/wallet-payment", fields)
        return parse_wallet_payment_response(response)

    async def selcompesa_payment(self, *, transid: str, order_id: str, msisdn: str) -> SelcomPesaPaymentResult:
        """POST /v1/checkout/selcompesa-payment — the Selcom Pesa
        counterpart to process_wallet_payment() above, after
        create_order_minimal() has already created an order shell. Same
        rules apply: **this is the one call in this method's flow that
        can actually move money** — triggers a real prompt to the
        customer's Selcom Pesa app for `msisdn`. Never call this
        speculatively, automatically, or more than once per genuine
        payment attempt; see app/services/selcompesa_push.py for the one
        call site that should ever reach this in application code.

        Request field shape (transid, order_id, msisdn) mirrors
        process_wallet_payment()'s exactly — same product family, same
        documented convention every other Checkout push endpoint uses —
        pending independent confirmation against a real sandbox call via
        scripts/test_selcom_checkout_selcompesa_payment.py, same
        "confirm before fully trusting" posture as this module's other
        still-only-task-brief-confirmed fields (see module docstring).

        The normal, expected response is PENDING, same as
        process_wallet_payment() — this method never decides on its own
        whether to credit anyone; see parse_selcompesa_payment_response().

        msisdn must already be normalized to "255XXXXXXXXX" — no plus
        sign — by the caller (app.core.phone.normalize_tz_phone), same
        convention as process_wallet_payment()."""
        fields: dict[str, str] = {
            "transid": transid,
            "order_id": order_id,
            "msisdn": msisdn,
        }
        response = await self._signed_request("POST", "/v1/checkout/selcompesa-payment", fields)
        return parse_selcompesa_payment_response(response)

    async def get_order_status(self, *, order_id: str) -> OrderStatusResult:
        """GET /v1/checkout/order-status?order_id={order_id} — the
        reconciliation query used to resolve a collection that a webhook
        hasn't (yet) resolved, or to independently confirm one that has.
        Signed-Fields is just `order_id` (confirmed by the task brief,
        unlike create-order-minimal there's no shell/payload
        inconsistency here to worry about).

        Read-only — never itself credits anyone or changes anything on
        Selcom's side; app/services/checkout_reconciliation.py is what
        applies the result, and only when payment_status/result/
        resultcode together satisfy the completion rule."""
        fields: dict[str, str] = {"order_id": order_id}
        response = await self._signed_request("GET", "/v1/checkout/order-status", fields)
        return parse_order_status_response(response)
