"""Merchant reports: the four report types offered at /portal/reports.

Each report is a title, a set of column headers, a list of rows, and a
few summary totals. Rendering (CSV, PDF) and delivery (email) are
deliberately elsewhere — `app/services/report_rendering.py` and
`app/services/email.py` — so a new report type only has to describe its
data, and a new format only has to render this one shape.

Everything reads real merchant data through the merchant-scoped tables.
There is no aggregate table behind these: each report queries the same
rows the portal already shows, filtered to the requested date range, so
a report can never disagree with the screen it was generated from.

Amounts are rendered as plain decimal strings, not floats — these are
money figures a merchant may file with, and a float would silently
round them.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from supabase import Client

from app.core.time import dar_es_salaam_day_bounds_utc
from app.schemas.enums import ReportType
from app.services.customer_lookup import customer_phones_for_collections


@dataclass
class Report:
    """One generated report, ready to render in any format."""

    title: str
    merchant_name: str
    merchant_code: str
    start_date: date
    end_date: date
    headers: list[str]
    rows: list[list[str]]
    # Label -> value, shown as a summary block above the table. Ordered.
    totals: list[tuple[str, str]] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)


def _money(value: object) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(str(value)):.2f}"


def _in_range(rows: list[dict], *, column: str, start: date, end: date) -> list[dict]:
    """Filters to the requested days in Dar es Salaam time.

    The same day-bounds helper the wallet ledger export uses, so "1st to
    31st" means the same span in both places — a report that quietly used
    UTC days would drop or add the edge transactions of each month.
    """
    start_utc, end_utc = dar_es_salaam_day_bounds_utc(start, end)
    kept = []
    for row in rows:
        raw = row.get(column)
        if not raw:
            continue
        # Parsed, never string-compared: stored timestamps use both "Z" and
        # "+00:00", which sort differently as text but are the same instant.
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if start_utc is not None and moment < start_utc:
            continue
        if end_utc is not None and moment >= end_utc:
            continue
        kept.append(row)
    return kept


def _fetch(client: Client, table: str, merchant_id: uuid.UUID) -> list[dict]:
    return (
        client.table(table).select("*").eq("merchant_id", str(merchant_id)).execute().data or []
    )


def _sorted_newest_first(rows: list[dict], column: str) -> list[dict]:
    return sorted(rows, key=lambda r: r.get(column) or "", reverse=True)


# --- the four report types --------------------------------------------------


def _transactions_summary(client: Client, merchant_id: uuid.UUID, start: date, end: date) -> tuple[list[str], list[list[str]], list[tuple[str, str]]]:
    rows = _in_range(_fetch(client, "transactions", merchant_id), column="created_at", start=start, end=end)
    rows = _sorted_newest_first(rows, "created_at")
    phones = customer_phones_for_collections(client, {r.get("collection_id") for r in rows})

    headers = [
        "Date",
        "Type",
        "Reference",
        "Provider Reference",
        "Method",
        "Customer Phone",
        "Amount",
        "Charge",
        "Net",
        "Status",
    ]
    table = [
        [
            (r.get("created_at") or "")[:19].replace("T", " "),
            r.get("type") or "",
            r.get("reference") or "",
            r.get("provider_reference") or "",
            r.get("method") or "",
            phones.get(r.get("collection_id")) or "",
            _money(r.get("gross_amount")),
            _money(r.get("fee_amount")),
            _money(r.get("net_amount")),
            r.get("status") or "",
        ]
        for r in rows
    ]

    successful = [r for r in rows if r.get("status") == "successful"]
    collected = sum(Decimal(str(r.get("gross_amount") or 0)) for r in successful if r.get("type") == "collection")
    paid_out = sum(Decimal(str(r.get("gross_amount") or 0)) for r in successful if r.get("type") == "disbursement")
    totals = [
        ("Transactions", str(len(rows))),
        ("Successful", str(len(successful))),
        ("Collected (successful)", _money(collected)),
        ("Paid out (successful)", _money(paid_out)),
    ]
    return headers, table, totals


def _withdrawals_summary(client: Client, merchant_id: uuid.UUID, start: date, end: date) -> tuple[list[str], list[list[str]], list[tuple[str, str]]]:
    rows = _in_range(_fetch(client, "disbursements", merchant_id), column="created_at", start=start, end=end)
    rows = _sorted_newest_first(rows, "created_at")

    headers = [
        "Date",
        "Method",
        "Destination Name",
        "Destination",
        "Bank",
        "Amount",
        "Status",
        "Provider Reference",
        "Completed",
    ]
    table = [
        [
            (r.get("created_at") or "")[:19].replace("T", " "),
            r.get("method") or "",
            r.get("destination_name") or "",
            r.get("destination_identifier") or "",
            r.get("bank_name") or "",
            _money(r.get("amount")),
            r.get("status") or "",
            r.get("provider_reference") or "",
            (r.get("completed_at") or "")[:19].replace("T", " "),
        ]
        for r in rows
    ]

    successful = [r for r in rows if r.get("status") == "successful"]
    pending = [r for r in rows if r.get("status") in ("pending", "processing")]
    totals = [
        ("Withdrawals", str(len(rows))),
        ("Successful", str(len(successful))),
        ("Still in progress", str(len(pending))),
        (
            "Total withdrawn (successful)",
            _money(sum(Decimal(str(r.get("amount") or 0)) for r in successful)),
        ),
    ]
    return headers, table, totals


def _fees_summary(client: Client, merchant_id: uuid.UUID, start: date, end: date) -> tuple[list[str], list[list[str]], list[tuple[str, str]]]:
    """Only charges actually taken. A failed transaction charges nothing,
    so including it would overstate what the merchant paid."""
    rows = _in_range(_fetch(client, "transactions", merchant_id), column="created_at", start=start, end=end)
    charged = [
        r for r in rows if r.get("status") == "successful" and Decimal(str(r.get("fee_amount") or 0)) > 0
    ]
    charged = _sorted_newest_first(charged, "created_at")

    headers = ["Date", "Type", "Reference", "Method", "Amount", "Charge", "Effective Rate", "Net"]
    table = []
    for r in charged:
        gross = Decimal(str(r.get("gross_amount") or 0))
        fee = Decimal(str(r.get("fee_amount") or 0))
        rate = f"{(fee / gross * 100):.3f}%" if gross > 0 else "—"
        table.append(
            [
                (r.get("created_at") or "")[:19].replace("T", " "),
                r.get("type") or "",
                r.get("reference") or "",
                r.get("method") or "",
                _money(gross),
                _money(fee),
                rate,
                _money(r.get("net_amount")),
            ]
        )

    total_fees = sum(Decimal(str(r.get("fee_amount") or 0)) for r in charged)
    total_gross = sum(Decimal(str(r.get("gross_amount") or 0)) for r in charged)
    totals = [
        ("Charged transactions", str(len(charged))),
        ("Total charges", _money(total_fees)),
        ("Value charged on", _money(total_gross)),
        (
            "Blended rate",
            f"{(total_fees / total_gross * 100):.3f}%" if total_gross > 0 else "—",
        ),
    ]
    return headers, table, totals


def _customer_statement(client: Client, merchant_id: uuid.UUID, start: date, end: date) -> tuple[list[str], list[list[str]], list[tuple[str, str]]]:
    """One line per paying customer, grouped by the phone that paid.

    Grouped by phone rather than by a customers row because a collection
    always records the phone, while a linked customer record is optional
    — grouping on the customer id would silently drop most payments.
    """
    rows = _in_range(_fetch(client, "collections", merchant_id), column="created_at", start=start, end=end)
    successful = [r for r in rows if r.get("status") == "successful"]

    grouped: dict[str, dict] = {}
    for r in successful:
        phone = r.get("customer_phone") or "Not captured (QR)"
        entry = grouped.setdefault(
            phone, {"count": 0, "total": Decimal(0), "first": None, "last": None, "methods": set()}
        )
        entry["count"] += 1
        entry["total"] += Decimal(str(r.get("amount") or 0))
        entry["methods"].add(r.get("method") or "")
        created = r.get("created_at") or ""
        if entry["first"] is None or created < entry["first"]:
            entry["first"] = created
        if entry["last"] is None or created > entry["last"]:
            entry["last"] = created

    headers = ["Customer Phone", "Payments", "Total Paid", "Methods", "First Payment", "Last Payment"]
    table = [
        [
            phone,
            str(entry["count"]),
            _money(entry["total"]),
            ", ".join(sorted(m for m in entry["methods"] if m)),
            (entry["first"] or "")[:19].replace("T", " "),
            (entry["last"] or "")[:19].replace("T", " "),
        ]
        for phone, entry in sorted(grouped.items(), key=lambda kv: kv[1]["total"], reverse=True)
    ]

    totals = [
        ("Paying customers", str(len(grouped))),
        ("Successful payments", str(len(successful))),
        ("Total received", _money(sum(e["total"] for e in grouped.values()))),
    ]
    return headers, table, totals


_BUILDERS = {
    ReportType.TRANSACTIONS_SUMMARY: ("Transactions Summary", _transactions_summary),
    ReportType.WITHDRAWALS_SUMMARY: ("Withdrawals Summary", _withdrawals_summary),
    ReportType.FEES_SUMMARY: ("Fees Summary", _fees_summary),
    ReportType.CUSTOMER_STATEMENT: ("Customer Statement", _customer_statement),
}


def build_report(
    client: Client,
    *,
    merchant: dict,
    report_type: ReportType,
    start_date: date,
    end_date: date,
) -> Report:
    title, builder = _BUILDERS[report_type]
    headers, rows, totals = builder(client, uuid.UUID(merchant["id"]), start_date, end_date)
    return Report(
        title=title,
        merchant_name=merchant.get("business_name") or "",
        merchant_code=merchant.get("merchant_code") or "",
        start_date=start_date,
        end_date=end_date,
        headers=headers,
        rows=rows,
        totals=totals,
    )
