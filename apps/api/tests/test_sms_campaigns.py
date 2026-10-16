"""Super Admin announcements, and the provider's delivery callbacks.

The rule worth the most here is the dullest: a draft never sends. Every
other safeguard in this feature is about not sending a message twice; this
one is about not sending it at all until a person has said to.

Announcements are also the path where one mistake reaches every merchant
at once, so recipient resolution is tested for who it leaves out as much
as for who it includes.
"""

import hashlib
import hmac
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.sms_campaigns import (
    EXCLUDED_DUPLICATE_NUMBER,
    EXCLUDED_NOT_ACTIVE,
    EXCLUDED_OPTED_OUT,
    create_draft,
    dispatch_campaign,
    preview_campaign,
    resolve_recipients,
)
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_super_admin,
)

client = TestClient(app)
_SECRET = "test-callback-secret-not-real"


@pytest.fixture(autouse=True)
def _sms_on(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("OASIS_SMS_ENABLED", "true")
    monkeypatch.setenv("OASIS_SMS_SENDER_ID", "INFINITYPAY")
    monkeypatch.setenv("OASIS_SMS_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OASIS_SMS_WEBHOOK_SECRET", _SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_provider_calls(monkeypatch):
    """No test may reach a real gateway. get_balance is the one call the
    admin screens make on their own."""
    monkeypatch.setattr("app.routers.admin_sms.get_balance", lambda: 1234.0)


def _merchant(fake_client, name, phone, *, status="active", announcements=True):
    merchant = create_merchant(
        fake_client, business_name=name, contact_phone=phone, status=status
    )
    fake_client.seed(
        "merchant_notification_settings",
        {
            "merchant_id": merchant["id"],
            "collection_sms_enabled": True,
            "announcement_sms_enabled": announcements,
            "sms_notification_phone": phone,
        },
    )
    return merchant


def _admin(fake_client):
    admin_id = uuid.uuid4()
    make_super_admin(fake_client, admin_id)
    return auth_headers(admin_id)


def _messages(fake_client):
    return fake_client.table("sms_messages")._table.rows


# --- who an announcement reaches ---------------------------------------


def test_only_active_merchants_are_included(fake_client):
    _merchant(fake_client, "Trading", "255712000001")
    _merchant(fake_client, "Suspended", "255712000002", status="suspended")

    resolved = resolve_recipients(fake_client, merchant_ids=None)

    assert [r["business_name"] for r in resolved["recipients"]] == ["Trading"]
    assert resolved["excluded"][0]["reason"] == EXCLUDED_NOT_ACTIVE


def test_an_opted_out_merchant_is_excluded_even_if_explicitly_selected(fake_client):
    """The opt-out is the merchant's decision; selecting them is ours."""
    opted_out = _merchant(fake_client, "No thanks", "255712000003", announcements=False)

    resolved = resolve_recipients(fake_client, merchant_ids=[opted_out["id"]])

    assert resolved["recipients"] == []
    assert resolved["excluded"][0]["reason"] == EXCLUDED_OPTED_OUT


def test_a_shared_number_receives_one_message(fake_client):
    """Five businesses shared phone numbers on this platform until
    recently. Sending one person the same announcement three times is
    both a cost and an annoyance."""
    _merchant(fake_client, "Alpha", "255712000004")
    _merchant(fake_client, "Beta", "255712000004")

    resolved = resolve_recipients(fake_client, merchant_ids=None)

    assert len(resolved["recipients"]) == 1
    assert EXCLUDED_DUPLICATE_NUMBER in resolved["excluded"][0]["reason"]


def test_announcement_opt_out_does_not_affect_lifecycle_messages(fake_client):
    """Separate preferences, on purpose: a merchant who stops wanting
    announcements must not thereby lose their welcome or their payout
    confirmations. Those are transactional and Super-Admin-controlled;
    announcements are marketing and merchant-controlled."""
    merchant = _merchant(fake_client, "Quiet", "255712000005", announcements=False)
    from app.services.sms_messages import resolve_recipient

    phone, reason = resolve_recipient(fake_client, uuid.UUID(merchant["id"]))
    assert reason is None
    assert phone == "255712000005", "still reachable for transactional messages"

def test_the_preview_reports_cost_as_an_estimate(fake_client):
    _merchant(fake_client, "Alpha", "255712000006")
    _merchant(fake_client, "Beta", "255712000007")

    preview = preview_campaign(fake_client, body="Habari njema", merchant_ids=None)

    assert preview["recipient_count"] == 2
    assert preview["segments_per_message"] == 1
    assert preview["estimated_credits"] == 2
    assert preview["estimate_only"] is True


# --- a draft never sends -----------------------------------------------


def test_saving_a_draft_queues_nothing(fake_client):
    _merchant(fake_client, "Alpha", "255712000008")

    create_draft(
        fake_client, title="Maintenance", body="Habari", created_by=uuid.uuid4(), filters={}
    )

    assert _messages(fake_client) == []


def test_editing_a_draft_queues_nothing(fake_client):
    _merchant(fake_client, "Alpha", "255712000009")
    headers = _admin(fake_client)
    created = client.post(
        "/v1/admin/sms/campaigns",
        json={"title": "Draft", "body": "First"},
        headers=headers,
    ).json()["data"]

    client.patch(
        f"/v1/admin/sms/campaigns/{created['id']}",
        json={"title": "Draft", "body": "Second"},
        headers=headers,
    )

    assert _messages(fake_client) == []


def test_a_sent_campaign_cannot_be_edited_back_into_a_draft(fake_client):
    """A sent campaign that stayed editable is how a second send
    happens."""
    _merchant(fake_client, "Alpha", "255712000010")
    headers = _admin(fake_client)
    created = client.post(
        "/v1/admin/sms/campaigns", json={"title": "Once", "body": "Habari"}, headers=headers
    ).json()["data"]
    client.post(f"/v1/admin/sms/campaigns/{created['id']}/send", headers=headers)

    response = client.patch(
        f"/v1/admin/sms/campaigns/{created['id']}",
        json={"title": "Again", "body": "Habari"},
        headers=headers,
    )

    assert response.status_code == 409


def test_a_sent_campaign_cannot_be_deleted(fake_client):
    _merchant(fake_client, "Alpha", "255712000011")
    headers = _admin(fake_client)
    created = client.post(
        "/v1/admin/sms/campaigns", json={"title": "Once", "body": "Habari"}, headers=headers
    ).json()["data"]
    client.post(f"/v1/admin/sms/campaigns/{created['id']}/send", headers=headers)

    assert (
        client.delete(f"/v1/admin/sms/campaigns/{created['id']}", headers=headers).status_code
        == 409
    )


def test_duplicating_a_sent_campaign_makes_a_new_draft(fake_client):
    """How a sent campaign is reused without the original becoming
    editable again."""
    _merchant(fake_client, "Alpha", "255712000012")
    headers = _admin(fake_client)
    created = client.post(
        "/v1/admin/sms/campaigns", json={"title": "Once", "body": "Habari"}, headers=headers
    ).json()["data"]
    client.post(f"/v1/admin/sms/campaigns/{created['id']}/send", headers=headers)

    copy = client.post(
        f"/v1/admin/sms/campaigns/{created['id']}/duplicate", headers=headers
    ).json()["data"]

    assert copy["status"] == "draft"
    assert copy["id"] != created["id"]
    assert copy["body"] == "Habari"


# --- dispatch ----------------------------------------------------------


def test_dispatch_freezes_one_message_per_recipient(fake_client):
    _merchant(fake_client, "Alpha", "255712000013")
    _merchant(fake_client, "Beta", "255712000014")
    draft = create_draft(
        fake_client, title="Notice", body="Habari njema", created_by=uuid.uuid4(), filters={}
    )

    dispatch_campaign(fake_client, campaign_id=uuid.UUID(draft["id"]), dispatched_by=uuid.uuid4())

    queued = _messages(fake_client)
    assert len(queued) == 2
    assert {m["body"] for m in queued} == {"Habari njema"}
    assert all(m["purpose"] == "announcement" for m in queued)
    assert all(m["status"] == "queued" for m in queued)


def test_a_second_send_click_queues_nothing_more(fake_client):
    """A double-submitting button, a retried request, an impatient
    operator - all the same thing, and all refused."""
    _merchant(fake_client, "Alpha", "255712000015")
    headers = _admin(fake_client)
    created = client.post(
        "/v1/admin/sms/campaigns", json={"title": "Once", "body": "Habari"}, headers=headers
    ).json()["data"]

    first = client.post(f"/v1/admin/sms/campaigns/{created['id']}/send", headers=headers)
    second = client.post(f"/v1/admin/sms/campaigns/{created['id']}/send", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 409
    assert len(_messages(fake_client)) == 1


def test_recipients_are_resolved_server_side_not_supplied(fake_client):
    """The client sends merchant ids at most. A request cannot name a
    phone number, which is what keeps a payer unreachable by this path."""
    merchant = _merchant(fake_client, "Alpha", "255712000016")
    headers = _admin(fake_client)
    created = client.post(
        "/v1/admin/sms/campaigns",
        json={"title": "Targeted", "body": "Habari", "merchant_ids": [merchant["id"]]},
        headers=headers,
    ).json()["data"]

    client.post(f"/v1/admin/sms/campaigns/{created['id']}/send", headers=headers)

    assert [m["recipient_phone"] for m in _messages(fake_client)] == ["255712000016"]


# --- permissions -------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/v1/admin/sms/overview"),
        ("get", "/v1/admin/sms/messages"),
        ("get", "/v1/admin/sms/campaigns"),
        ("get", "/v1/admin/sms/settings"),
    ],
)
def test_a_non_admin_cannot_read_sms(fake_client, method, path):
    """These lists carry merchant phone numbers and message bodies."""
    merchant = _merchant(fake_client, "Alpha", "255712000017")
    response = getattr(client, method)(path, headers=auth_headers(uuid.UUID(merchant["id"])))
    assert response.status_code in (401, 403)


def test_a_non_admin_cannot_send(fake_client):
    _merchant(fake_client, "Alpha", "255712000018")
    draft = create_draft(
        fake_client, title="X", body="Habari", created_by=uuid.uuid4(), filters={}
    )

    response = client.post(
        f"/v1/admin/sms/campaigns/{draft['id']}/send", headers=auth_headers(uuid.uuid4())
    )

    assert response.status_code in (401, 403)
    assert _messages(fake_client) == []


def test_the_settings_endpoint_never_returns_key_material(fake_client):
    headers = _admin(fake_client)

    body = client.get("/v1/admin/sms/settings", headers=headers).json()["data"]

    assert body["api_key_configured"] is True
    assert "test-key-not-real" not in json.dumps(body)
    assert _SECRET not in json.dumps(body)


def test_the_message_list_masks_phone_numbers(fake_client):
    """60 merchants' numbers should not all be on one screen in full."""
    merchant = _merchant(fake_client, "Alpha", "255712345678")
    fake_client.seed(
        "sms_messages",
        {
            "merchant_id": merchant["id"],
            "purpose": "collection_alert",
            "recipient_phone": "255712345678",
            "sender_id": "INFINITYPAY",
            "body": "x",
            "status": "sent",
            "idempotency_key": f"ipay-c-{uuid.uuid4().hex}",
        },
    )

    rows = client.get("/v1/admin/sms/messages", headers=_admin(fake_client)).json()["data"]

    assert rows[0]["recipient_phone"] == "2557****5678"


# --- provider callbacks ------------------------------------------------


def _signed(body: dict, *, secret=_SECRET, event="sms.delivered", event_id="evt-1"):
    raw = json.dumps(body).encode()
    return raw, {
        "X-BulkSMS-Signature": hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(),
        "X-BulkSMS-Event": event,
        "X-BulkSMS-Event-Id": event_id,
        "Content-Type": "application/json",
    }


def _message(fake_client, *, log_id="log-1", status="sent"):
    merchant = _merchant(fake_client, "Alpha", f"25571200{uuid.uuid4().int % 10000:04d}")
    return fake_client.seed(
        "sms_messages",
        {
            "merchant_id": merchant["id"],
            "purpose": "collection_alert",
            "recipient_phone": "255712000099",
            "sender_id": "INFINITYPAY",
            "body": "x",
            "status": status,
            "provider_sms_log_id": log_id,
            "idempotency_key": f"ipay-c-{uuid.uuid4().hex}",
        },
    )


def test_a_valid_callback_is_accepted(fake_client):
    _message(fake_client, log_id="log-7")
    raw, headers = _signed({"sms_log_id": "log-7"}, event_id="evt-7")

    response = client.post("/v1/sms/callbacks/oasis", content=raw, headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "accepted"


def test_an_invalid_signature_is_rejected(fake_client):
    _message(fake_client, log_id="log-8")
    raw, headers = _signed({"sms_log_id": "log-8"}, secret="wrong-secret", event_id="evt-8")

    response = client.post("/v1/sms/callbacks/oasis", content=raw, headers=headers)

    assert response.status_code == 422
    assert fake_client.table("sms_provider_events")._table.rows == []


def test_a_repeated_event_id_is_acknowledged_once(fake_client):
    """The provider retries at 1min, 5min, 30min, 2h and 12h, so the same
    event arrives repeatedly by design."""
    _message(fake_client, log_id="log-9")
    raw, headers = _signed({"sms_log_id": "log-9"}, event_id="evt-9")

    first = client.post("/v1/sms/callbacks/oasis", content=raw, headers=headers)
    second = client.post("/v1/sms/callbacks/oasis", content=raw, headers=headers)

    assert first.json()["data"]["status"] == "accepted"
    assert second.json()["data"]["status"] == "duplicate"
    assert len(fake_client.table("sms_provider_events")._table.rows) == 1


def test_a_callback_for_an_unknown_message_is_still_stored(fake_client):
    """Callbacks can overtake the send response. Storing the event means
    nothing is lost when the row does not exist yet."""
    raw, headers = _signed({"sms_log_id": "not-saved-yet"}, event_id="evt-10")

    response = client.post("/v1/sms/callbacks/oasis", content=raw, headers=headers)

    assert response.status_code == 200
    assert len(fake_client.table("sms_provider_events")._table.rows) == 1


def test_an_older_event_does_not_overwrite_newer_state(fake_client):
    """The provider retries for up to 12 hours, so a stale 'pending' can
    easily arrive after the 'failed' that superseded it."""
    message = _message(fake_client, log_id="log-11")
    raw, headers = _signed({"sms_log_id": "log-11"}, event="sms.failed", event_id="evt-11a")
    client.post("/v1/sms/callbacks/oasis", content=raw, headers=headers)

    raw2, headers2 = _signed({"sms_log_id": "log-11"}, event="sms.pending", event_id="evt-11b")
    client.post("/v1/sms/callbacks/oasis", content=raw2, headers=headers2)

    saved = next(
        r for r in fake_client.table("sms_messages")._table.rows if r["id"] == message["id"]
    )
    assert saved["status"] == "failed"


def test_callbacks_are_refused_when_no_secret_is_configured(fake_client, monkeypatch):
    """An endpoint whose job is to accept unauthenticated POSTs must fail
    closed when it cannot tell a real caller from anyone."""
    monkeypatch.setenv("OASIS_SMS_WEBHOOK_SECRET", "")
    get_settings.cache_clear()
    raw, headers = _signed({"sms_log_id": "log-12"}, event_id="evt-12")

    response = client.post("/v1/sms/callbacks/oasis", content=raw, headers=headers)

    assert response.status_code == 422


def test_a_callback_never_changes_a_payment(fake_client):
    message = _message(fake_client, log_id="log-13")
    raw, headers = _signed({"sms_log_id": "log-13"}, event="sms.failed", event_id="evt-13")

    client.post("/v1/sms/callbacks/oasis", content=raw, headers=headers)

    for table in ("transactions", "collections", "ledger_entries", "ledger_accounts"):
        assert fake_client.table(table)._table.rows == []
    assert message["merchant_id"]
