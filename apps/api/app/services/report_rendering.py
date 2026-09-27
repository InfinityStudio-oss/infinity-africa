"""Renders an `app/services/reports.py::Report` to a downloadable PDF.

Nothing here queries anything — a renderer that had to know where a
number came from would have to change every time a report type did.

PDF uses fpdf2: pure Python, no system libraries. That matters because
the API runs in a slim container, and the usual alternative (WeasyPrint)
needs cairo and pango installed at the OS level.
"""

from fpdf import FPDF

from app.services.reports import Report

# InfinityPay brand green (apps/web/src/app/globals.css --color-primary).
_BRAND = (4, 51, 42)
_LIGHT_ROW = (245, 245, 245)


def _period(report: Report) -> str:
    return f"{report.start_date.isoformat()} to {report.end_date.isoformat()}"


def _pdf_text(value: str) -> str:
    """fpdf2's built-in fonts are Latin-1 only. Report data is merchant
    input — a name or note can contain anything — so unsupported
    characters are replaced rather than allowed to raise mid-render and
    fail the whole report."""
    return value.encode("latin-1", "replace").decode("latin-1")


def _column_widths(pdf: FPDF, report: Report) -> list[float]:
    """Widths proportional to what each column actually holds.

    Equal widths look tidy until a ten-column report truncates the
    transaction reference — the one value a merchant needs to match a row
    against something else — while "Type" sits half empty. Measured at the
    font the table is drawn in, then scaled to fill the page exactly.
    """
    pdf.set_font("Helvetica", "", 8)
    natural = []
    for index, header in enumerate(report.headers):
        widest = pdf.get_string_width(_pdf_text(header))
        for row in report.rows:
            if index < len(row):
                widest = max(widest, pdf.get_string_width(_pdf_text(str(row[index]))))
        natural.append(widest + 4)  # padding

    usable = pdf.w - pdf.l_margin - pdf.r_margin
    total = sum(natural) or 1
    # Scaled to the page whether the natural widths overflow it (shrink,
    # and the longest values truncate) or fall short (stretch to fill).
    return [width * usable / total for width in natural]


def render_pdf(report: Report) -> bytes:
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*_BRAND)
    pdf.cell(0, 9, _pdf_text(report.title), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(60, 60, 60)
    subtitle = f"{report.merchant_name}"
    if report.merchant_code:
        subtitle += f"  ({report.merchant_code})"
    pdf.cell(0, 6, _pdf_text(subtitle), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, _pdf_text(f"Period: {_period(report)}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    if report.totals:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(0, 0, 0)
        for label, value in report.totals:
            pdf.cell(70, 6, _pdf_text(f"{label}:"), new_x="RIGHT", new_y="TOP")
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 6, _pdf_text(value), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "B", 10)
        pdf.ln(3)

    if not report.rows:
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(0, 8, "No activity in this period.", new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf.output())

    widths = _column_widths(pdf, report)

    def header_row() -> None:
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(*_BRAND)
        pdf.set_text_color(255, 255, 255)
        for header, width in zip(report.headers, widths):
            pdf.cell(width, 7, _pdf_text(header), border=0, fill=True, align="L")
        pdf.ln()

    header_row()

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(0, 0, 0)
    for index, row in enumerate(report.rows):
        # Repeat the header when the row would start a new page, so a
        # multi-page report's later pages are still readable on their own.
        if pdf.get_y() + 6 > pdf.h - pdf.b_margin:
            pdf.add_page()
            header_row()
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(0, 0, 0)

        shaded = index % 2 == 1
        if shaded:
            pdf.set_fill_color(*_LIGHT_ROW)
        for cell, width in zip(row, widths):
            text = _pdf_text(str(cell))
            # Truncate rather than wrap: a fixed row height keeps the
            # columns aligned down the page, and the full value is always
            # available in the CSV.
            while text and pdf.get_string_width(text) > width - 2:
                text = text[:-1]
            pdf.cell(width, 6, text, border=0, fill=shaded, align="L")
        pdf.ln()

    return bytes(pdf.output())


def render_report(report: Report) -> tuple[bytes, str, str]:
    """Returns (content, filename, media type). PDF is the only format.

    A report is a statement a merchant files with or forwards, so it is
    delivered as one fixed, readable document rather than as a choice the
    merchant has to make before they can generate anything. The
    Transactions and Wallet pages still export raw rows (CSV and Excel
    respectively) for anyone who wants the data rather than the statement.
    """
    slug = report.title.lower().replace(" ", "-")
    stem = f"infinitypay-{slug}-{report.start_date.isoformat()}-to-{report.end_date.isoformat()}"
    return render_pdf(report), f"{stem}.pdf", "application/pdf"
