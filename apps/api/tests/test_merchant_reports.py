"""Merchant reports: POST /v1/merchant/reports.

This endpoint replaced a frontend `setTimeout` that never called anything
— the page reported "report generated" without generating a report. So
the things worth pinning are that the numbers come from real rows, that
the file is actually attached to the email, and that the merchant's own
account email always receives it.

The money figures matter most: a merchant may file with these. A report
that quietly counted a failed payment, or a fee that was never charged,
would be worse than no report at all.
"""

import uuid
from datetime import date
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.schemas.enums import ReportFormat, ReportType
from app.services.report_rendering import render_csv, render_pdf, render_report
from app.services.reports import build_report
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_merchant_member,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key-do-not-use-in-production")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def merchant_user(fake_client):
    merchant = create_merchant(fake_client, contact_email="owner@example.com")
    merchant_id = uuid.UUID(merchant["id"])
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    return merchant, user_id


def _collection(fake_client, merchant_id, *, phone, amount="1000", status="successful", created_at="2026-09-10T09:00:00+00:00"):
    return fake_client.seed(
        "collections",
        {
            "merchant_id": str(merchant_id),
            "method": "STK_PUSH",
            "amount": amount,
            "currency": "TZS",
            "customer_phone": phone,
            "status": status,
            "created_at": created_at,
        },
    )


def _transaction(fake_client, merchant_id, *, reference, gross="1000", fee="0", status="successful", type_="collection", collection_id=None, created_at="2026-09-10T09:00:00+00:00"):
    net = str(float(gross) - float(fee))
    return fake_client.seed(
        "transactions",
        {
            "merchant_id": str(merchant_id),
            "reference": reference,
            "type": type_,
            "method": "STK_PUSH" if type_ == "collection" else "SELCOM_PESA",
            "collection_id": collection_id,
            "gross_amount": gross,
            "fee_amount": fee,
            "net_amount": net,
            "currency": "TZS",
            "status": status,
            "metadata": {},
            "created_at": created_at,
        },
    )


def _generate(user_id, **overrides):
    payload = {
        "report_type": "TRANSACTIONS_SUMMARY",
        "start_date": "2026-09-01",
        "end_date": "2026-09-30",
        "format": "CSV",
    }
    payload.update(overrides)
    return client.post("/v1/merchant/reports", headers=auth_headers(user_id), json=payload)


# --- it emails a real file ------------------------------------------------


def test_generating_a_report_emails_it_with_the_file_attached(fake_client, merchant_user):
    merchant, user_id = merchant_user
    _transaction(fake_client, merchant["id"], reference="TXN-1", gross="2000", fee="40")

    with patch("app.services.email.send_email", return_value="msg-1") as send:
        response = _generate(user_id)

    assert response.status_code == 200, response.text
    assert send.call_count == 1
    attachments = send.call_args.kwargs["attachments"]
    assert len(attachments) == 1
    filename, content = attachments[0]
    assert filename.endswith(".csv")
    assert b"TXN-1" in content


def test_the_report_goes_to_the_merchants_own_account_email(fake_client, merchant_user):
    """Not only to whatever address was typed into the form — a report
    about an account's money must reach the account holder."""
    _merchant, user_id = merchant_user

    with patch("app.services.email.send_email", return_value="msg-1") as send:
        response = _generate(user_id, recipients=["accountant@example.com"])

    assert response.status_code == 200, response.text
    assert send.call_args.kwargs["to"] == ["owner@example.com", "accountant@example.com"]
    assert response.json()["data"]["emailed_to"] == ["owner@example.com", "accountant@example.com"]


def test_the_account_email_is_not_duplicated_when_also_typed_in(fake_client, merchant_user):
    _merchant, user_id = merchant_user

    with patch("app.services.email.send_email", return_value="msg-1") as send:
        _generate(user_id, recipients=["OWNER@example.com"])

    assert send.call_args.kwargs["to"] == ["owner@example.com"]


def test_a_failed_send_fails_the_request_rather_than_reporting_success(fake_client, merchant_user):
    """The merchant must not be told their report was sent and then wait
    for an email that is never coming."""
    from app.core.errors import EmailDeliveryError

    _merchant, user_id = merchant_user

    with patch("app.services.email.send_email", side_effect=EmailDeliveryError("provider down")):
        response = _generate(user_id)

    assert response.status_code >= 400, "a failed send was reported as success"
    assert "emailed_to" not in response.text


def test_a_pdf_report_attaches_a_real_pdf(fake_client, merchant_user):
    _merchant, user_id = merchant_user
    _transaction(fake_client, _merchant["id"], reference="TXN-PDF")

    with patch("app.services.email.send_email", return_value="msg-1") as send:
        response = _generate(user_id, format="PDF")

    assert response.status_code == 200, response.text
    filename, content = send.call_args.kwargs["attachments"][0]
    assert filename.endswith(".pdf")
    assert content.startswith(b"%PDF-")


# --- the numbers are the real ones ----------------------------------------


def test_only_successful_transactions_count_towards_the_collected_total(fake_client, merchant_user):
    merchant, _user_id = merchant_user
    _transaction(fake_client, merchant["id"], reference="TXN-OK", gross="1000")
    _transaction(fake_client, merchant["id"], reference="TXN-FAILED", gross="9999", status="failed")

    report = build_report(
        fake_client,
        merchant=merchant,
        report_type=ReportType.TRANSACTIONS_SUMMARY,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )

    totals = dict(report.totals)
    assert totals["Collected (successful)"] == "1000.00"
    assert totals["Transactions"] == "2"  # both listed
    assert totals["Successful"] == "1"


def test_a_transaction_outside_the_range_is_excluded(fake_client, merchant_user):
    merchant, _user_id = merchant_user
    _transaction(fake_client, merchant["id"], reference="TXN-IN", created_at="2026-09-10T09:00:00+00:00")
    _transaction(fake_client, merchant["id"], reference="TXN-OUT", created_at="2026-08-10T09:00:00+00:00")

    report = build_report(
        fake_client,
        merchant=merchant,
        report_type=ReportType.TRANSACTIONS_SUMMARY,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )

    references = [row[2] for row in report.rows]
    assert references == ["TXN-IN"]


def test_a_z_suffixed_timestamp_is_compared_as_an_instant_not_as_text(fake_client, merchant_user):
    """Stored timestamps use both "Z" and "+00:00". Sorted as text those
    order differently, so the range filter parses them instead."""
    merchant, _user_id = merchant_user
    _transaction(fake_client, merchant["id"], reference="TXN-Z", created_at="2026-09-15T09:00:00Z")

    report = build_report(
        fake_client,
        merchant=merchant,
        report_type=ReportType.TRANSACTIONS_SUMMARY,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )

    assert [row[2] for row in report.rows] == ["TXN-Z"]


def test_the_fees_report_excludes_charges_that_were_never_taken(fake_client, merchant_user):
    """A failed transaction charges nothing. Counting its fee would
    overstate what the merchant actually paid."""
    merchant, _user_id = merchant_user
    _transaction(fake_client, merchant["id"], reference="TXN-CHARGED", gross="1000", fee="20")
    _transaction(fake_client, merchant["id"], reference="TXN-FAILED", gross="1000", fee="20", status="failed")
    _transaction(fake_client, merchant["id"], reference="TXN-FREE", gross="1000", fee="0")

    report = build_report(
        fake_client,
        merchant=merchant,
        report_type=ReportType.FEES_SUMMARY,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )

    totals = dict(report.totals)
    assert totals["Charged transactions"] == "1"
    assert totals["Total charges"] == "20.00"
    assert [row[2] for row in report.rows] == ["TXN-CHARGED"]


def test_the_transactions_report_names_the_payer(fake_client, merchant_user):
    merchant, _user_id = merchant_user
    collection = _collection(fake_client, merchant["id"], phone="+255712345678")
    _transaction(fake_client, merchant["id"], reference="TXN-P", collection_id=collection["id"])

    report = build_report(
        fake_client,
        merchant=merchant,
        report_type=ReportType.TRANSACTIONS_SUMMARY,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )

    assert report.rows[0][5] == "+255712345678"


def test_the_customer_statement_groups_payments_by_payer(fake_client, merchant_user):
    merchant, _user_id = merchant_user
    _collection(fake_client, merchant["id"], phone="+255700000001", amount="1000")
    _collection(fake_client, merchant["id"], phone="+255700000001", amount="500")
    _collection(fake_client, merchant["id"], phone="+255700000002", amount="300")
    _collection(fake_client, merchant["id"], phone="+255700000002", amount="200", status="failed")

    report = build_report(
        fake_client,
        merchant=merchant,
        report_type=ReportType.CUSTOMER_STATEMENT,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )

    by_phone = {row[0]: row for row in report.rows}
    assert by_phone["+255700000001"][1] == "2"
    assert by_phone["+255700000001"][2] == "1500.00"
    # The failed payment is not counted, so this customer shows one.
    assert by_phone["+255700000002"][1] == "1"
    assert dict(report.totals)["Total received"] == "1800.00"


def test_a_report_never_includes_another_merchants_rows(fake_client, merchant_user):
    merchant, user_id = merchant_user
    other = create_merchant(fake_client, contact_email="other@example.com")
    _transaction(fake_client, other["id"], reference="TXN-NOT-MINE", gross="9999")
    _transaction(fake_client, merchant["id"], reference="TXN-MINE")

    with patch("app.services.email.send_email", return_value="msg-1") as send:
        response = _generate(user_id)

    assert response.status_code == 200, response.text
    _filename, content = send.call_args.kwargs["attachments"][0]
    assert b"TXN-MINE" in content
    assert b"TXN-NOT-MINE" not in content


# --- input bounds ----------------------------------------------------------


def test_an_inverted_date_range_is_refused(fake_client, merchant_user):
    _merchant, user_id = merchant_user

    response = _generate(user_id, start_date="2026-09-30", end_date="2026-09-01")

    assert response.status_code == 422, response.text


def test_an_unbounded_range_is_refused(fake_client, merchant_user):
    """The report is built in memory and attached to an email; an
    open-ended range is how one request exhausts the container."""
    _merchant, user_id = merchant_user

    response = _generate(user_id, start_date="2020-01-01", end_date="2026-12-31")

    assert response.status_code == 422, response.text


@pytest.mark.parametrize("bad", ["not-an-email", "a@b", "@example.com", "spaces in@example.com"])
def test_an_invalid_extra_recipient_is_refused(bad, fake_client, merchant_user):
    _merchant, user_id = merchant_user

    response = _generate(user_id, recipients=[bad])

    assert response.status_code == 422, f"{bad!r} was accepted"


def test_too_many_extra_recipients_are_refused(fake_client, merchant_user):
    _merchant, user_id = merchant_user

    response = _generate(
        user_id, recipients=[f"person{i}@example.com" for i in range(6)]
    )

    assert response.status_code == 422, response.text


def test_another_merchants_member_cannot_generate_a_report_for_this_merchant(fake_client, merchant_user):
    _merchant, _user_id = merchant_user
    outsider = uuid.uuid4()

    response = _generate(outsider)

    assert response.status_code in (401, 403, 404), response.text


# --- rendering -------------------------------------------------------------


def test_the_csv_quotes_a_value_containing_a_comma(fake_client, merchant_user):
    """A destination or business name with a comma must not shift the
    columns of every row after it."""
    merchant, _user_id = merchant_user
    fake_client.seed(
        "disbursements",
        {
            "merchant_id": merchant["id"],
            "method": "BANK_ACCOUNT",
            "amount": "1000",
            "currency": "TZS",
            "destination_name": "Juma, Traders Ltd",
            "destination_identifier": "0123456789",
            "bank_name": "CRDB",
            "status": "successful",
            "created_at": "2026-09-10T09:00:00+00:00",
        },
    )
    report = build_report(
        fake_client,
        merchant=merchant,
        report_type=ReportType.WITHDRAWALS_SUMMARY,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )

    text = render_csv(report).decode("utf-8-sig")
    assert '"Juma, Traders Ltd"' in text


def test_a_pdf_renders_even_with_no_rows(fake_client, merchant_user):
    """An empty period is a normal answer, not an error."""
    merchant, _user_id = merchant_user
    report = build_report(
        fake_client,
        merchant=merchant,
        report_type=ReportType.TRANSACTIONS_SUMMARY,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )

    assert report.row_count == 0
    assert render_pdf(report).startswith(b"%PDF-")


def test_a_pdf_renders_a_name_outside_latin_1_instead_of_failing(fake_client):
    """Report data is merchant input. An unsupported character must not
    take down the whole report."""
    merchant = create_merchant(fake_client, business_name="Café Dar — 全球", contact_email="c@example.com")
    report = build_report(
        fake_client,
        merchant=merchant,
        report_type=ReportType.TRANSACTIONS_SUMMARY,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )

    assert render_pdf(report).startswith(b"%PDF-")


@pytest.mark.parametrize("report_type", list(ReportType))
def test_every_report_type_builds_and_renders_in_both_formats(report_type, fake_client, merchant_user):
    merchant, _user_id = merchant_user
    collection = _collection(fake_client, merchant["id"], phone="+255700000001")
    _transaction(fake_client, merchant["id"], reference="TXN-X", fee="15", collection_id=collection["id"])

    report = build_report(
        fake_client,
        merchant=merchant,
        report_type=report_type,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )

    for fmt in ReportFormat:
        content, filename, media_type = render_report(report, report_format=fmt.value)
        assert content, f"{report_type} produced an empty {fmt} file"
        assert filename.endswith(".csv" if fmt is ReportFormat.CSV else ".pdf")
        assert media_type in ("text/csv", "application/pdf")


def test_the_filename_says_which_report_and_which_period(fake_client, merchant_user):
    merchant, _user_id = merchant_user
    report = build_report(
        fake_client,
        merchant=merchant,
        report_type=ReportType.FEES_SUMMARY,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )

    _content, filename, _media = render_report(report, report_format="CSV")

    assert filename == "infinitypay-fees-summary-2026-09-01-to-2026-09-30.csv"


def test_report_generation_is_rate_limited_per_merchant(fake_client, merchant_user):
    """Each call reads the whole range and sends an email, so the cost is
    the merchant's however many of their staff click the button."""
    # conftest's autouse fixture clears the limiter's state in place
    # between tests, so this starts from an empty window.
    _merchant, user_id = merchant_user

    with patch("app.services.email.send_email", return_value="msg-1"):
        statuses = [_generate(user_id).status_code for _ in range(11)]

    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429, "the 11th report in an hour was not refused"
