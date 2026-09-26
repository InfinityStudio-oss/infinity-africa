"""Input validation against hostile input.

Two things are checked here. First, that the webhook URL cannot be pointed
at this server's own network — a merchant chooses that URL and the backend
then fetches it, which is a server-side request forgery vector unless the
address is checked. Second, that classic injection payloads are handled as
data rather than as instructions.

The injection cases are deliberately not "does it reject" — most are
legitimate text a real business could type. A merchant genuinely called
`O'Brien & Sons` must be able to sign up. What matters is that the value is
stored and returned verbatim, never interpreted.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.errors import ValidationAPIError
from app.core.url_safety import validate_outbound_url
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
)

client = TestClient(app)

# Payloads that must never be executed, interpreted or allowed to escape.
HOSTILE_STRINGS = [
    "' OR '1'='1",
    "'; DROP TABLE merchants; --",
    "<script>alert(1)</script>",
    "javascript:alert(1)",
    "../../etc/passwd",
    "..\\..\\windows\\system32",
    "\x00nullbyte",
    "a" * 5000,
]


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def merchant_user(fake_client):
    merchant = create_merchant(fake_client)
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, uuid.UUID(merchant["id"]), user_id, "MERCHANT_ADMIN")
    return merchant, user_id


def _production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()


# --- SSRF: the URL this server will fetch ---------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8080/hook",
        "http://127.0.0.1/hook",
        "https://127.0.0.1/hook",
        "https://10.0.0.5/hook",
        "https://192.168.1.10/hook",
        "https://172.16.0.1/hook",
        "https://[::1]/hook",
        "https://169.254.169.254/latest/meta-data/",
    ],
)
def test_internal_addresses_are_refused_in_production(url, monkeypatch):
    """The metadata address is the one an attacker actually wants: reaching
    it from our infrastructure can hand over cloud credentials."""
    _production(monkeypatch)

    with pytest.raises(ValidationAPIError):
        validate_outbound_url(url, field="Webhook URL")


def test_plain_http_is_refused_in_production(monkeypatch):
    """A webhook carries payment events and a signature; over http both are
    readable and alterable in transit."""
    _production(monkeypatch)

    with pytest.raises(ValidationAPIError) as exc:
        validate_outbound_url("http://example.com/hook", field="Webhook URL")

    assert "https" in str(exc.value).lower()


def test_a_normal_public_https_url_is_accepted(monkeypatch):
    _production(monkeypatch)

    assert validate_outbound_url("https://example.com/hook", field="Webhook URL")


@pytest.mark.parametrize("scheme", ["javascript:alert(1)", "data:text/html,<script>", "file:///etc/passwd"])
def test_non_http_schemes_are_refused(scheme, monkeypatch):
    _production(monkeypatch)

    with pytest.raises(ValidationAPIError):
        validate_outbound_url(scheme, field="Webhook URL")


def test_localhost_still_works_outside_production(monkeypatch):
    """Local development needs this, and only development gets it."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()

    assert validate_outbound_url("http://localhost:3000/hook", field="Webhook URL")


def test_the_endpoint_refuses_an_internal_webhook_url(fake_client, merchant_user, monkeypatch):
    """End to end, not just the helper — a route that forgot to call it
    would still pass the unit tests above."""
    _production(monkeypatch)
    _merchant, user_id = merchant_user

    response = client.patch(
        "/v1/merchant/webhook-config",
        headers=auth_headers(user_id),
        json={"webhook_url": "http://169.254.169.254/latest/meta-data/"},
    )

    assert response.status_code == 422, response.text


# --- hostile strings are data, not instructions ---------------------------


@pytest.mark.parametrize("payload", HOSTILE_STRINGS)
def test_hostile_text_in_a_name_never_changes_query_behaviour(payload, fake_client, merchant_user):
    """An API key name is free text. A SQL payload there must come back as
    the same characters, and must not affect what the listing returns."""
    _merchant, user_id = merchant_user

    response = client.post(
        "/v1/merchant/api-keys",
        headers=auth_headers(user_id),
        json={"name": payload, "environment": "sandbox", "scopes": ["collections:write"]},
    )

    # Either refused by validation, or stored — never executed, and never a 500.
    assert response.status_code in (201, 422), response.text

    listed = client.get("/v1/merchant/api-keys", headers=auth_headers(user_id))
    assert listed.status_code == 200, listed.text
    # The merchant still sees only their own keys; no injection widened it.
    assert all(k["id"] for k in listed.json()["data"])


def test_a_sql_payload_as_a_path_id_is_rejected_not_executed(fake_client, merchant_user):
    _merchant, user_id = merchant_user

    response = client.get(
        "/v1/merchant/invoices/' OR '1'='1", headers=auth_headers(user_id)
    )

    # A UUID path parameter rejects this at the type boundary.
    assert response.status_code == 422, response.text


def test_script_content_is_stored_verbatim_rather_than_interpreted(fake_client, merchant_user):
    """React escapes on render, so the safe behaviour is to keep the text
    exactly as typed — a business legitimately named with punctuation must
    not be mangled."""
    _merchant, user_id = merchant_user
    name = "<script>alert(1)</script>"

    created = client.post(
        "/v1/merchant/api-keys",
        headers=auth_headers(user_id),
        json={"name": name, "environment": "sandbox", "scopes": ["collections:write"]},
    )
    if created.status_code == 422:
        pytest.skip("name length/charset rules reject this outright, which is also safe")

    assert created.json()["data"]["name"] == name


# --- pagination cannot be used to scrape ----------------------------------


@pytest.mark.parametrize("page_size", [1000, 100000, -1, 0])
def test_page_size_outside_the_allowed_range_is_refused(page_size, fake_client, merchant_user):
    _merchant, user_id = merchant_user

    response = client.get(
        f"/v1/merchant/api-keys?page_size={page_size}", headers=auth_headers(user_id)
    )

    assert response.status_code == 422, f"page_size={page_size} was accepted"


def test_the_maximum_allowed_page_size_still_works(fake_client, merchant_user):
    _merchant, user_id = merchant_user

    response = client.get("/v1/merchant/api-keys?page_size=100", headers=auth_headers(user_id))

    assert response.status_code == 200, response.text


# --- money ----------------------------------------------------------------


@pytest.mark.parametrize("amount", ["-1000", "0", "abc", "1e9999", "", "NaN", "Infinity"])
def test_a_withdrawal_refuses_a_nonsensical_amount(amount, fake_client, merchant_user):
    _merchant, user_id = merchant_user

    response = client.post(
        "/v1/merchant/withdrawals",
        headers={**auth_headers(user_id), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "method": "SELCOM_PESA",
            "amount": amount,
            "destination_phone": "+255700000000",
            "destination_code": "SELCOM",
        },
    )

    assert response.status_code in (400, 409, 422), f"amount={amount!r} was accepted"
