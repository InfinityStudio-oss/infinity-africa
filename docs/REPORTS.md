# Merchant Reports

`POST /v1/merchant/reports` and the page at `/portal/reports`. A merchant
picks a report type and a date range; the backend builds the report from
their own rows and emails it to them as a PDF attachment.

## Before 2026-09-27 this page generated nothing

The Reports page was a `setTimeout` that incremented a counter. It never
called an API — there was no reports endpoint — so "2 reports generated
this session" was literally true and completely empty: no file existed
and nothing was sent. That is now a real endpoint against real data.

## Report types

| Type | Source | One row per |
|---|---|---|
| `TRANSACTIONS_SUMMARY` | `transactions` | transaction, with the customer's phone |
| `WITHDRAWALS_SUMMARY` | `disbursements` | withdrawal, with destination and status |
| `FEES_SUMMARY` | `transactions` | transaction that was actually charged |
| `CUSTOMER_STATEMENT` | `collections` | paying customer, grouped by phone |

Each also carries a short totals block, which appears in the email body,
at the top of the file, and in the API response.

Two deliberate choices about what counts:

- **Fees Summary counts only charges actually taken** — successful
  transactions with a non-zero fee. A failed payment charges nothing, so
  including it would overstate what the merchant paid.
- **Customer Statement groups by phone, not by customer record.** A
  collection always records the phone; a linked `customers` row is
  optional, so grouping on the customer id would silently drop most
  payments.

Date ranges are interpreted in Africa/Dar_es_Salaam, using the same
day-bounds helper as the wallet ledger export, so "1 to 30 September"
means the same span in both. Timestamps are parsed before comparison,
never compared as text — stored values use both `Z` and `+00:00`, which
sort differently as strings but are the same instant.

## Delivery

The report is emailed through Resend with the file attached
(`app/services/email.py::send_report_email`). `send_email` gained an
`attachments` parameter, which base64-encodes the content for Resend.

**The merchant's account email (`merchants.contact_email`) is always a
recipient and cannot be removed.** Extra addresses can be added in the
form, up to five, but a report about an account's money must reach the
person who owns the account — not only an address someone typed in.

**A failed send fails the request.** Report generation is not "best
effort" like a receipt or welcome email: a merchant who was told their
report was sent must not be left waiting for an email that is never
coming. One `email_deliveries` row is written per recipient, sharing the
provider message id, because "did this person get their report" is the
question support actually asks.

## Limits

| Limit | Value | Why |
|---|---|---|
| Date range | 366 days | The report is built in memory and attached to an email; an unbounded range is how one request exhausts the container for every merchant. |
| Extra recipients | 5 | A report-delivery feature, not a mailing list. |
| Rate | 10 per merchant per hour | Each call reads the whole range and sends an email. Scoped per merchant, not per user — the cost is the merchant's however many of their staff click the button. |

Emails are validated with the same regex pattern the rest of the API
uses (`app/schemas/auth.py`, `app/schemas/pay_by_link.py`), deliberately
not pydantic's `EmailStr`, which would pull in `email-validator`.

## Rendering

`app/services/report_rendering.py` turns one `Report` into a file.
Nothing in it queries anything, so a new report type only describes its
data and a new format only renders this one shape.

**PDF is the only format** (2026-09-27; CSV was removed). A report is a
statement a merchant files with or forwards, not a data dump, and making
them choose a format before they could generate anything added a decision
without adding an option worth having. Anyone who wants the raw rows still
has the Transactions page's CSV export and the Wallet page's Excel export,
both of which carry full untruncated values.

- **PDF** — `fpdf2`, added as a dependency for this. Chosen because it
  is pure Python with no system libraries; WeasyPrint would have needed
  cairo and pango installed in the API container. Landscape A4, repeating
  header row on each page, zebra striping. Cell values are truncated
  rather than wrapped so columns stay aligned down the page. Column widths
  are proportional to content, so truncation is rare; when a value is too
  long for any layout, the Transactions CSV export has it in full.
  Characters outside Latin-1 are replaced
  rather than allowed to raise, because report data is merchant input and
  one unusual character must not take down the whole report.

## What this does not do

- **No stored report history.** The page lists what was generated in the
  current session only. Nothing is written to a reports table and no
  file is retained server-side — the email attachment is the artifact.
  Adding history would mean a table and a retention policy, which is a
  separate decision.
- **No scheduled or recurring reports.** Every report is generated by an
  explicit click.
- **No download-in-browser path.** The report is delivered by email. The
  wallet ledger export (`GET /v1/merchant/wallet/ledger/export`) remains
  the direct-download route for ledger data specifically.
- **No format choice.** `format` was removed from the request and the
  response; a stale client still posting `format=CSV` gets a PDF rather
  than an error.
