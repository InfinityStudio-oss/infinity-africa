"""scripts/test_selcom_checkout_wallet_payment.py — the live wallet-push
diagnostic script's own gating logic. This is the one script in this
codebase deliberately given test coverage (per explicit task
instruction) despite the "scripts are manual-only, never wired into any
test suite" convention every other script here documents — the coverage
is for the *refusal*/*sequencing* logic, not for making a real Selcom
call; SelcomCheckoutHTTPClient is monkeypatched out in every test below,
so nothing here ever reaches the network.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "test_selcom_checkout_wallet_payment.py"


def _load_script():
    """Scripts/ isn't a package (no __init__.py, and the module itself
    does its own sys.path manipulation) — loaded by file path rather
    than a normal import."""
    spec = importlib.util.spec_from_file_location("wallet_payment_script", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(monkeypatch):
    monkeypatch.setenv("SELCOM_CHECKOUT_BASE_URL", "https://checkout.example.selcommobile.com")
    monkeypatch.setenv("SELCOM_CHECKOUT_API_KEY", "test-key")
    monkeypatch.setenv("SELCOM_CHECKOUT_API_SECRET", "test-secret")
    monkeypatch.setenv("SELCOM_CHECKOUT_VENDOR", "VENDORTEST")
    import app.config as config_module

    config_module.get_settings.cache_clear()
    module = _load_script()
    yield module
    config_module.get_settings.cache_clear()
    sys.modules.pop("wallet_payment_script", None)


_BASE_ARGS = [
    "--buyer-email",
    "test@infinitypay.me",
    "--buyer-name",
    "InfinityPay Test Customer",
    "--buyer-phone",
    "255747730270",
    "--amount",
    "1000",
]


class _NeverCallMe:
    """Stands in for SelcomCheckoutHTTPClient in the refusal-path tests
    — instantiating it at all is a test failure, since the script must
    refuse before ever constructing a client."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("SelcomCheckoutHTTPClient must never be constructed without --confirm-live-payment")


class _FakeClient:
    def __init__(self, *, credentials=None, order_response=None, payment_response=None):
        self.calls: list[tuple[str, dict]] = []
        self._order_response = order_response
        self._payment_response = payment_response

    async def create_order_minimal(self, **kwargs):
        from app.services.selcom_checkout.parsing import (
            parse_create_order_minimal_response,
        )

        self.calls.append(("create_order_minimal", kwargs))
        return parse_create_order_minimal_response(self._order_response)

    async def process_wallet_payment(self, **kwargs):
        from app.services.selcom_checkout.parsing import parse_wallet_payment_response

        self.calls.append(("process_wallet_payment", kwargs))
        return parse_wallet_payment_response(self._payment_response)


ORDER_SUCCESS = {
    "reference": "S20690427372",
    "resultcode": "000",
    "result": "SUCCESS",
    "message": "Payment notification logged",
    "data": [{"payment_token": "63850827", "payment_gateway_url": "aHR0cHM6Ly9leGFtcGxlLmNvbS9wYXk=", "qr": "QR"}],
}

ORDER_FAILED = {"reference": "", "resultcode": "651", "result": "FAIL", "message": "Invalid vendor", "data": []}

PAYMENT_PENDING = {
    "reference": "0289999288",
    "resultcode": "111",
    "result": "PENDING",
    "message": "Request in progress. You will receive a callback shortly.",
    "data": [],
}


# --- refusal without the flag ---------------------------------------------------------


@pytest.mark.asyncio
async def test_refuses_to_run_without_confirm_live_payment_flag(script, monkeypatch, capsys):
    monkeypatch.setattr(script, "SelcomCheckoutHTTPClient", _NeverCallMe)

    exit_code = await script._main(_BASE_ARGS)  # no --confirm-live-payment

    assert exit_code == 2
    captured = capsys.readouterr()
    assert script.REFUSAL_MESSAGE in captured.err


def test_refusal_message_matches_the_exact_required_text(script):
    assert script.REFUSAL_MESSAGE == (
        "This command triggers a real live payment push. Re-run with "
        "--confirm-live-payment only if you intentionally want to test live."
    )


@pytest.mark.asyncio
async def test_confirm_live_payment_flag_alone_is_sufficient_no_interactive_prompt(script, monkeypatch):
    """The flag is the only gate — this script must never call input()
    or otherwise block on stdin, unlike the create-order-minimal
    diagnostic script."""
    fake = _FakeClient(order_response=ORDER_SUCCESS, payment_response=PAYMENT_PENDING)
    monkeypatch.setattr(script, "SelcomCheckoutHTTPClient", lambda **kwargs: fake)

    def _fail_if_called(*_a, **_k):
        raise AssertionError("must not prompt interactively")

    monkeypatch.setattr("builtins.input", _fail_if_called)

    exit_code = await script._main([*_BASE_ARGS, "--confirm-live-payment"])

    assert exit_code == 0
    assert len(fake.calls) == 2


# --- create-order-minimal must succeed before wallet-payment continues --------------


@pytest.mark.asyncio
async def test_stops_before_wallet_payment_if_order_creation_fails(script, monkeypatch, capsys):
    fake = _FakeClient(order_response=ORDER_FAILED, payment_response=PAYMENT_PENDING)
    monkeypatch.setattr(script, "SelcomCheckoutHTTPClient", lambda **kwargs: fake)

    exit_code = await script._main([*_BASE_ARGS, "--confirm-live-payment"])

    assert exit_code == 1
    call_names = [name for name, _ in fake.calls]
    assert call_names == ["create_order_minimal"]  # process_wallet_payment never reached
    assert "NOT attempted" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_successful_order_creation_proceeds_to_wallet_payment_with_matching_order_id(script, monkeypatch):
    fake = _FakeClient(order_response=ORDER_SUCCESS, payment_response=PAYMENT_PENDING)
    monkeypatch.setattr(script, "SelcomCheckoutHTTPClient", lambda **kwargs: fake)

    exit_code = await script._main([*_BASE_ARGS, "--confirm-live-payment"])

    assert exit_code == 0
    call_names = [name for name, _ in fake.calls]
    assert call_names == ["create_order_minimal", "process_wallet_payment"]
    order_call, payment_call = fake.calls[0][1], fake.calls[1][1]
    assert payment_call["order_id"] == order_call["order_id"]


# --- msisdn/phone normalization -----------------------------------------------------


@pytest.mark.asyncio
async def test_buyer_phone_is_normalized_before_reaching_selcom(script, monkeypatch):
    fake = _FakeClient(order_response=ORDER_SUCCESS, payment_response=PAYMENT_PENDING)
    monkeypatch.setattr(script, "SelcomCheckoutHTTPClient", lambda **kwargs: fake)

    args = [
        "--buyer-email",
        "test@infinitypay.me",
        "--buyer-name",
        "InfinityPay Test Customer",
        "--buyer-phone",
        "+255 747 730 270",
        "--amount",
        "1000",
        "--confirm-live-payment",
    ]
    exit_code = await script._main(args)

    assert exit_code == 0
    assert fake.calls[0][1]["buyer_phone"] == "255747730270"
    assert fake.calls[1][1]["msisdn"] == "255747730270"


@pytest.mark.asyncio
async def test_invalid_phone_refuses_before_constructing_a_client(script, monkeypatch):
    monkeypatch.setattr(script, "SelcomCheckoutHTTPClient", _NeverCallMe)

    args = [
        "--buyer-email",
        "test@infinitypay.me",
        "--buyer-name",
        "InfinityPay Test Customer",
        "--buyer-phone",
        "not-a-phone-number",
        "--amount",
        "1000",
        "--confirm-live-payment",
    ]
    exit_code = await script._main(args)

    assert exit_code == 2


# --- transid uniqueness --------------------------------------------------------------


@pytest.mark.asyncio
async def test_transid_and_order_id_are_generated_not_reused_across_runs(script, monkeypatch):
    fake = _FakeClient(order_response=ORDER_SUCCESS, payment_response=PAYMENT_PENDING)
    monkeypatch.setattr(script, "SelcomCheckoutHTTPClient", lambda **kwargs: fake)

    await script._main([*_BASE_ARGS, "--confirm-live-payment"])
    first_order_id = fake.calls[0][1]["order_id"]
    first_transid = fake.calls[1][1]["transid"]

    fake.calls.clear()
    await script._main([*_BASE_ARGS, "--confirm-live-payment"])
    second_order_id = fake.calls[0][1]["order_id"]
    second_transid = fake.calls[1][1]["transid"]

    assert first_order_id != second_order_id
    assert first_transid != second_transid
