"""Email OTP verification on merchant withdrawals.

The invariant every test here defends: a withdrawal request creates
*nothing* until the emailed code is verified — no disbursement row, no
reservation, no provider call, no CEO notification — and verifying the code
still only produces a PENDING_ADMIN_APPROVAL withdrawal. An OTP proves who
is asking; it does not authorise a payout.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import resend
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.selcom_business.client import get_selcom_business_client
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
)

client = TestClient(app)

_CODE_BY_HASH = {hashlib.sha256(f"{n:06d}".encode()).hexdigest(): f"{n:06d}" for n in range(1_000_000)}


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("SELCOM_BUSINESS_MODE", "mock")
    monkeypatch.setenv("MOCK_PROVIDER_FAILURE_RATE", "0")
    monkeypatch.setenv("MOCK_PROVIDER_LATENCY_SECONDS", "0")
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    monkeypatch.setenv("CEO_EMAIL", "ceo@infinitypay.me")
    monkeypatch.setenv("SEND_WITHDRAWAL_REQUEST_EMAILS", "true")
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_selcom_business_client.cache_clear()


class _FakeResend:
    def __init__(self):
        self.calls: list[dict] = []

    def send(self, params: dict) -> dict:
        self.calls.append(params)
        return {"id": "resend-test-message-id"}


@pytest.fixture(autouse=True)
def fake_resend(monkeypatch):
    fake = _FakeResend()
    monkeypatch.setattr(resend.Emails, "send", fake.send)
    return fake


def _merchant_and_admin(fake_client, **overrides):
    merchant = create_merchant(fake_client, **overrides)
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    return merchant_id, user_id


def _fund(fake_client, merchant_id, amount="1000000.00"):
    fake_client.seed(
        "ledger_accounts",
        {
            "merchant_id": str(merchant_id),
            "name": "Merchant Wallet (test)",
            "account_type": "liability",
            "purpose": "merchant_wallet",
            "currency": "TZS",
            "balance": amount,
        },
    )


def _body(**overrides):
    return {
        "method": "SELCOM_PESA",
        "amount": "10000",
        "destination_name": "Jane Doe",
        "destination_phone": "+255700000000",
        "destination_code": "SELCOM",
        **overrides,
    }


def _request(user_id, body=None, idem=None):
    return client.post(
        "/v1/merchant/withdrawals",
        headers={**auth_headers(user_id), "Idempotency-Key": idem or str(uuid.uuid4())},
        json=body or _body(),
    )


def _challenge_row(fake_client, challenge_id):
    return next(
        r for r in fake_client.table("merchant_withdrawal_otp_challenges")._table.rows if r["id"] == challenge_id
    )


def _code_for(fake_client, challenge_id):
    """Recovers the code from its hash. Only possible because the space is
    a million wide — the point being that the row itself holds no plaintext."""
    return _CODE_BY_HASH[_challenge_row(fake_client, challenge_id)["otp_hash"]]


def _verify(user_id, challenge_id, code):
    return client.post(
        f"/v1/merchant/withdrawals/{challenge_id}/verify",
        headers=auth_headers(user_id),
        json={"code": code},
    )


def _ceo_emails(fake_resend):
    return [c for c in fake_resend.calls if c["to"] == ["ceo@infinitypay.me"]]


def _otp_emails(fake_resend):
    return [c for c in fake_resend.calls if c["subject"] == "InfinityPay withdrawal verification code"]


# --- Requesting creates nothing payable ---------------------------------------


def test_request_sends_otp_and_creates_no_withdrawal(fake_client, fake_resend):
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    response = _request(user_id)

    assert response.status_code == 202, response.text
    data = response.json()["data"]
    assert data["otp_required"] is True
    # Nothing payable exists yet.
    assert fake_client.table("disbursements")._table.rows == []
    assert len(_otp_emails(fake_resend)) == 1
    assert _otp_emails(fake_resend)[0]["to"] == ["owner@shop.co.tz"]


def test_otp_goes_to_the_merchant_never_the_ceo(fake_client, fake_resend):
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    _request(user_id)

    assert _ceo_emails(fake_resend) == []
    # And the code itself never appears in anything addressed to the CEO.
    assert all("verification code" not in c["subject"].lower() for c in _ceo_emails(fake_resend))


def test_response_never_carries_the_code_or_its_hash(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)

    data = _request(user_id).json()["data"]
    row = _challenge_row(fake_client, data["challenge_id"])

    serialized = str(data)
    assert row["otp_hash"] not in serialized
    assert _CODE_BY_HASH[row["otp_hash"]] not in serialized
    assert "otp_hash" not in serialized


def test_code_is_never_stored_in_plaintext(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)

    data = _request(user_id).json()["data"]
    row = _challenge_row(fake_client, data["challenge_id"])

    code = _CODE_BY_HASH[row["otp_hash"]]
    assert code not in str(row)
    assert row["otp_hash"] == hashlib.sha256(code.encode()).hexdigest()


def test_masked_email_does_not_disclose_the_address(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="accounts@shop.co.tz")
    _fund(fake_client, merchant_id)

    masked = _request(user_id).json()["data"]["masked_email"]

    assert masked.endswith("@shop.co.tz")
    assert "accounts" not in masked
    assert masked.startswith("a")


# --- Verifying creates the withdrawal, pending approval -----------------------


def test_verified_code_creates_a_pending_approval_withdrawal(fake_client, fake_resend):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)
    challenge_id = _request(user_id).json()["data"]["challenge_id"]

    response = _verify(user_id, challenge_id, _code_for(fake_client, challenge_id))

    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert body["status"] == "PENDING_ADMIN_APPROVAL"
    assert body["auto_approved"] is False
    assert body["approved_by"] is None


def test_ceo_is_notified_only_after_verification(fake_client, fake_resend):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)
    challenge_id = _request(user_id).json()["data"]["challenge_id"]

    assert _ceo_emails(fake_resend) == []  # not yet

    _verify(user_id, challenge_id, _code_for(fake_client, challenge_id))

    assert len(_ceo_emails(fake_resend)) == 1


def test_provider_is_not_called_at_any_point_before_approval(fake_client, monkeypatch):
    """Neither requesting nor verifying may reach Selcom. Asserted by making
    any provider call fail the test outright, rather than by inspecting the
    resulting status — a status check would still pass if a payout had been
    attempted and rolled back."""

    class _ExplodingProvider:
        async def process_transaction(self, **kwargs):
            raise AssertionError("Selcom was called before Super Admin approval")

    monkeypatch.setattr("app.services.disbursements.get_selcom_business_client", lambda: _ExplodingProvider())

    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)
    challenge_id = _request(user_id).json()["data"]["challenge_id"]
    response = _verify(user_id, challenge_id, _code_for(fake_client, challenge_id))

    assert response.status_code == 202, response.text


# --- Failure modes ------------------------------------------------------------


def test_wrong_code_is_rejected_and_burns_an_attempt(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)
    challenge_id = _request(user_id).json()["data"]["challenge_id"]
    correct = _code_for(fake_client, challenge_id)
    wrong = "000000" if correct != "000000" else "111111"

    response = _verify(user_id, challenge_id, wrong)

    assert response.status_code == 422, response.text
    assert _challenge_row(fake_client, challenge_id)["attempts"] == 1
    assert fake_client.table("disbursements")._table.rows == []


def test_expired_code_is_rejected(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)
    challenge_id = _request(user_id).json()["data"]["challenge_id"]
    row = _challenge_row(fake_client, challenge_id)
    row["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    response = _verify(user_id, challenge_id, _code_for(fake_client, challenge_id))

    assert response.status_code == 422
    assert fake_client.table("disbursements")._table.rows == []


def test_too_many_attempts_locks_the_challenge(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)
    challenge_id = _request(user_id).json()["data"]["challenge_id"]
    correct = _code_for(fake_client, challenge_id)
    wrong = "000000" if correct != "000000" else "111111"

    for _ in range(5):
        _verify(user_id, challenge_id, wrong)

    assert _challenge_row(fake_client, challenge_id)["locked_at"] is not None
    # Even the right code no longer works once locked.
    assert _verify(user_id, challenge_id, correct).status_code == 422
    assert fake_client.table("disbursements")._table.rows == []


def test_every_failure_returns_the_same_message(fake_client):
    """Wrong, expired and locked must be indistinguishable, or the endpoint
    becomes an oracle for which challenges exist and how far a guessing run
    has got."""
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)

    first = _request(user_id).json()["data"]["challenge_id"]
    wrong_msg = _verify(user_id, first, "000000").json()["error"]["message"]

    second = _request(user_id, idem=str(uuid.uuid4())).json()["data"]["challenge_id"]
    _challenge_row(fake_client, second)["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    ).isoformat()
    expired_msg = _verify(user_id, second, _code_for(fake_client, second)).json()["error"]["message"]

    assert wrong_msg == expired_msg


def test_duplicate_verify_does_not_create_a_second_withdrawal(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)
    challenge_id = _request(user_id).json()["data"]["challenge_id"]
    code = _code_for(fake_client, challenge_id)

    first = _verify(user_id, challenge_id, code)
    second = _verify(user_id, challenge_id, code)

    assert first.status_code == 202
    assert second.status_code == 422  # single-use
    assert len(fake_client.table("disbursements")._table.rows) == 1


def test_a_merchant_cannot_verify_another_merchants_challenge(fake_client):
    merchant_a, user_a = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_a)
    challenge_id = _request(user_a).json()["data"]["challenge_id"]
    code = _code_for(fake_client, challenge_id)

    _merchant_b, user_b = _merchant_and_admin(fake_client)
    response = _verify(user_b, challenge_id, code)

    # Not found, not forbidden — user B must not learn the challenge exists.
    assert response.status_code == 404
    assert fake_client.table("disbursements")._table.rows == []


def test_requesting_again_supersedes_the_previous_code(fake_client):
    """Only one code may be live at a time, or an older code issued for a
    different amount would stay usable alongside the new one."""
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)

    first = _request(user_id).json()["data"]["challenge_id"]
    first_code = _code_for(fake_client, first)
    _request(user_id, _body(amount="50000"))

    assert _challenge_row(fake_client, first)["locked_at"] is not None
    assert _verify(user_id, first, first_code).status_code == 422


def test_the_created_withdrawal_matches_the_requested_payload(fake_client):
    """The withdrawal is replayed from the challenge, so the amount and
    destination that were validated and emailed are the ones created — a
    verified code cannot be applied to a different request."""
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)
    challenge_id = _request(
        user_id, _body(amount="12345", destination_name="Exact Name", destination_phone="+255711111111")
    ).json()["data"]["challenge_id"]

    body = _verify(user_id, challenge_id, _code_for(fake_client, challenge_id)).json()["data"]

    assert str(body["amount"]).startswith("12345")
    assert body["destination_name"] == "Exact Name"
    # The + is stripped by phone normalisation; the digits must match.
    assert body["destination_identifier"].lstrip("+") == "255711111111"


# --- Resend -------------------------------------------------------------------


def test_resend_is_refused_inside_the_cooldown(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)
    challenge_id = _request(user_id).json()["data"]["challenge_id"]

    response = client.post(
        f"/v1/merchant/withdrawals/{challenge_id}/resend", headers=auth_headers(user_id)
    )

    assert response.status_code == 409, response.text


def test_resend_issues_a_new_code_and_invalidates_the_old_one(fake_client, fake_resend):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)
    challenge_id = _request(user_id).json()["data"]["challenge_id"]
    old_code = _code_for(fake_client, challenge_id)

    # Step past the cooldown.
    row = _challenge_row(fake_client, challenge_id)
    row["last_sent_at"] = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()

    response = client.post(
        f"/v1/merchant/withdrawals/{challenge_id}/resend", headers=auth_headers(user_id)
    )

    assert response.status_code == 200, response.text
    new_code = _code_for(fake_client, challenge_id)
    assert new_code != old_code
    assert len(_otp_emails(fake_resend)) == 2
    assert _verify(user_id, challenge_id, old_code).status_code == 422


def test_resend_resets_the_attempt_budget(fake_client):
    """A new code deserves its own attempts — being locked out of a code you
    have not seen yet would be nonsense."""
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id)
    challenge_id = _request(user_id).json()["data"]["challenge_id"]
    for _ in range(3):
        _verify(user_id, challenge_id, "000000")
    assert _challenge_row(fake_client, challenge_id)["attempts"] >= 1

    row = _challenge_row(fake_client, challenge_id)
    row["last_sent_at"] = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    client.post(f"/v1/merchant/withdrawals/{challenge_id}/resend", headers=auth_headers(user_id))

    assert _challenge_row(fake_client, challenge_id)["attempts"] == 0


# --- Standing gates still apply before a code is ever sent --------------------


def test_unverified_merchant_gets_no_code(fake_client, fake_resend):
    merchant_id, user_id = _merchant_and_admin(fake_client, status="pending", kyc_status="unverified")
    _fund(fake_client, merchant_id)

    response = _request(user_id)

    assert response.status_code in (403, 409, 422), response.text
    assert _otp_emails(fake_resend) == []
    assert fake_client.table("merchant_withdrawal_otp_challenges")._table.rows == []


def test_insufficient_balance_gets_no_code(fake_client, fake_resend):
    merchant_id, user_id = _merchant_and_admin(fake_client)
    _fund(fake_client, merchant_id, "100.00")

    response = _request(user_id)

    assert response.status_code == 409, response.text
    assert _otp_emails(fake_resend) == []


# --- the merchant no longer supplies a recipient name ----------------------


def test_a_withdrawal_can_be_requested_with_no_destination_name(fake_client):
    """The portal stopped asking for one. A request that omits it entirely
    must be accepted, not 422'd."""
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    body = _body()
    del body["destination_name"]

    response = _request(user_id, body)

    assert response.status_code == 202, response.text


def test_the_stored_challenge_falls_back_to_the_destination_rather_than_a_blank_name(fake_client):
    """execute_disbursement and the Selcom payload both want a non-empty
    recipient name. With no name typed and no provider lookup to resolve
    one, the destination itself is the only honest label available — it
    must never end up empty."""
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    body = _body()
    del body["destination_name"]
    response = _request(user_id, body)

    stored = _challenge_row(fake_client, response.json()["data"]["challenge_id"])["withdrawal_payload"]
    assert stored["destination_name"]
    # Normalised on the way in, so no leading "+".
    assert stored["destination_name"] == "255700000000"


def test_a_withdrawal_submitted_without_a_name_still_creates_a_normal_withdrawal(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    body = _body()
    del body["destination_name"]
    challenge_id = _request(user_id, body).json()["data"]["challenge_id"]

    verified = _verify(user_id, challenge_id, _code_for(fake_client, challenge_id))

    assert verified.status_code == 202, verified.text
    assert verified.json()["data"]["status"] == "PENDING_ADMIN_APPROVAL"
    assert verified.json()["data"]["destination_name"]


def test_an_older_client_still_sending_a_name_is_not_broken(fake_client):
    """The field stayed optional rather than being removed, so the
    /v1/disbursements routes and any integrator still posting one keep
    working."""
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    response = _request(user_id, _body(destination_name="Jane Doe"))

    assert response.status_code == 202, response.text
    stored = _challenge_row(fake_client, response.json()["data"]["challenge_id"])["withdrawal_payload"]
    assert stored["destination_name"] == "Jane Doe"


# --- audit trail ------------------------------------------------------------


def _audit_actions(fake_client) -> list[str]:
    return [r.get("action") for r in fake_client.table("audit_logs")._table.rows]


def _audit_row(fake_client, action: str) -> dict:
    return next(r for r in fake_client.table("audit_logs")._table.rows if r.get("action") == action)


def test_requesting_a_code_is_audited_without_the_code_or_the_full_destination(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    response = _request(user_id)
    code = _code_for(fake_client, response.json()["data"]["challenge_id"])

    row = _audit_row(fake_client, "withdrawal.otp_requested")
    serialised = str(row)
    assert code not in serialised
    assert "255700000000" not in serialised


def test_a_failed_validation_is_audited(fake_client):
    """A merchant repeatedly hitting a limit or a hold should be visible
    without them having to report it."""
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id, amount="1.00")

    response = _request(user_id, _body(amount="999999"))

    assert response.status_code >= 400
    assert "withdrawal.validation_failed" in _audit_actions(fake_client)
    # Masked, never the full number (stored normalised, without the "+").
    assert "255700000000" not in str(_audit_row(fake_client, "withdrawal.validation_failed"))


def test_reviewing_a_withdrawal_is_audited_with_a_masked_destination(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    response = client.post(
        "/v1/merchant/withdrawals/quote",
        headers=auth_headers(user_id),
        json={
            "amount": "10000",
            "method": "SELCOM_PESA",
            "destination_code": "SELCOM",
            "destination_identifier": "+255700000000",
        },
    )

    assert response.status_code == 200, response.text
    row = _audit_row(fake_client, "withdrawal.reviewed")
    assert "255700000000" not in str(row)
    assert row["metadata"]["destination_masked"]


def test_a_second_verify_of_a_used_challenge_is_audited_as_a_duplicate(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    challenge_id = _request(user_id).json()["data"]["challenge_id"]
    code = _code_for(fake_client, challenge_id)
    assert _verify(user_id, challenge_id, code).status_code == 202

    second = _verify(user_id, challenge_id, code)

    assert second.status_code >= 400
    assert "withdrawal.duplicate_submission_blocked" in _audit_actions(fake_client)


def test_no_audit_log_anywhere_in_the_flow_contains_the_code(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    challenge_id = _request(user_id).json()["data"]["challenge_id"]
    code = _code_for(fake_client, challenge_id)
    _verify(user_id, challenge_id, "000000")
    _verify(user_id, challenge_id, code)

    everything = str(fake_client.table("audit_logs")._table.rows)
    assert code not in everything


def _break_audit_writes(monkeypatch) -> None:
    """Make every audit write raise, by whichever name it is reached.

    `merchant_portal` does `from app.services.audit import write_audit_log`,
    so it holds its own reference; `write_audit_log_best_effort` resolves
    the one inside `app.services.audit`. Patching only one of them leaves
    the other working and the test passes no matter what the code does.
    """
    import app.services.audit as audit_module
    from app.routers import merchant_portal

    def _boom(*_args, **_kwargs):
        raise RuntimeError("audit_logs unavailable")

    monkeypatch.setattr(audit_module, "write_audit_log", _boom)
    monkeypatch.setattr(merchant_portal, "write_audit_log", _boom)


def test_a_failing_audit_write_cannot_block_a_balance_check(fake_client, monkeypatch):
    """The review log sits on a read-only endpoint, and the portal gates
    Request Withdrawal on a fresh quote — so if an audit insert could fail
    the quote, it could stop withdrawals entirely."""
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)
    _break_audit_writes(monkeypatch)

    response = client.post(
        "/v1/merchant/withdrawals/quote",
        headers=auth_headers(user_id),
        json={
            "amount": "10000",
            "method": "SELCOM_PESA",
            "destination_code": "SELCOM",
            "destination_identifier": "+255700000000",
        },
    )

    assert response.status_code == 200, response.text


def test_a_failing_audit_write_does_not_mask_the_real_validation_error(fake_client, monkeypatch):
    """A merchant who is over their balance must still be told that, not
    handed a 500 from the audit insert behind it."""
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id, amount="1.00")
    _break_audit_writes(monkeypatch)

    response = _request(user_id, _body(amount="999999"))

    assert response.status_code < 500, response.text


# --- bank name and network are derived, not typed --------------------------


def _bank_body(**overrides):
    return {
        "method": "BANK_ACCOUNT",
        "amount": "10000",
        "destination_code": "CRDB",
        "bank_account_number": "0123456789",
        **overrides,
    }


def test_a_bank_withdrawal_needs_no_bank_name(fake_client):
    """destination_code already identifies the bank, so the portal stopped
    asking. A request omitting bank_name must be accepted."""
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    response = _request(user_id, _bank_body())

    assert response.status_code == 202, response.text


def test_the_bank_name_is_derived_from_the_chosen_provider(fake_client):
    """The disbursements CHECK constraint requires a bank_name for this
    method, and a real payout stores it — so it must be the bank the
    merchant actually picked, never blank."""
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    response = _request(user_id, _bank_body(destination_code="NMB"))

    stored = _challenge_row(fake_client, response.json()["data"]["challenge_id"])["withdrawal_payload"]
    assert stored["bank_name"] == "NMB Bank"


def test_a_derived_bank_name_survives_to_the_created_withdrawal(fake_client):
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    challenge_id = _request(user_id, _bank_body()).json()["data"]["challenge_id"]
    verified = _verify(user_id, challenge_id, _code_for(fake_client, challenge_id))

    assert verified.status_code == 202, verified.text
    row = next(
        r for r in fake_client.table("disbursements")._table.rows if r["id"] == verified.json()["data"]["id"]
    )
    assert row["bank_name"] == "CRDB Bank"


def test_an_explicit_bank_name_still_wins(fake_client):
    """The field stayed accepted so /v1/disbursements/* and any integrator
    sending one keep working."""
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    response = _request(user_id, _bank_body(bank_name="CRDB Bank PLC, Mwanza branch"))

    stored = _challenge_row(fake_client, response.json()["data"]["challenge_id"])["withdrawal_payload"]
    assert stored["bank_name"] == "CRDB Bank PLC, Mwanza branch"


def test_a_bank_withdrawal_still_needs_an_account_number(fake_client):
    """Unlike the bank name, nothing derives this one."""
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    body = _bank_body()
    del body["bank_account_number"]

    assert _request(user_id, body).status_code == 422


def test_the_network_is_derived_from_the_chosen_provider(fake_client):
    """The Network box was being filled in with a person's name after the
    recipient-name field above it was removed. It is the provider."""
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    response = _request(
        user_id,
        {
            "method": "MOBILE_MONEY",
            "amount": "10000",
            "destination_code": "MPESA",
            "destination_phone": "+255700000000",
        },
    )

    assert response.status_code == 202, response.text
    stored = _challenge_row(fake_client, response.json()["data"]["challenge_id"])["withdrawal_payload"]
    assert stored["network"] == "M-Pesa"


def test_a_selcom_pesa_withdrawal_carries_neither(fake_client):
    """Neither concept applies, and inventing a value would put a bank name
    on something that is not a bank transfer."""
    merchant_id, user_id = _merchant_and_admin(fake_client, contact_email="owner@shop.co.tz")
    _fund(fake_client, merchant_id)

    body = _body()
    del body["destination_name"]
    response = _request(user_id, body)

    stored = _challenge_row(fake_client, response.json()["data"]["challenge_id"])["withdrawal_payload"]
    assert stored["bank_name"] is None
    assert stored["network"] is None
