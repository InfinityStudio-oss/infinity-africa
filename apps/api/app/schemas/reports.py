import re
from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.enums import ReportFormat, ReportType

# Same pattern as app/schemas/auth.py and app/schemas/pay_by_link.py —
# deliberately not pydantic's EmailStr, which needs the email-validator
# package this codebase doesn't otherwise depend on.
_EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"

# A report is generated in memory and attached to an email, so the range a
# merchant can ask for in one go is bounded. A year of daily activity is
# well within what fits; an unbounded range is how one request exhausts the
# container for everyone.
MAX_REPORT_DAYS = 366

# Beyond the merchant's own account email. Small on purpose: this is a
# report-delivery feature, not a mailing list.
MAX_EXTRA_RECIPIENTS = 5


class ReportRequest(BaseModel):
    report_type: ReportType
    start_date: date
    end_date: date
    format: ReportFormat = ReportFormat.PDF
    # Who to send it to in addition to the merchant's account email. The
    # account email is always included by the endpoint and cannot be
    # removed, so a report can never be delivered only to an address the
    # account holder never sees.
    recipients: list[str] = Field(default_factory=list, max_length=MAX_EXTRA_RECIPIENTS)

    @model_validator(mode="after")
    def _check_range(self) -> "ReportRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        if (self.end_date - self.start_date).days + 1 > MAX_REPORT_DAYS:
            raise ValueError(f"A report can cover at most {MAX_REPORT_DAYS} days")
        return self

    @field_validator("recipients")
    @classmethod
    def _validate_and_dedupe(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for raw in value:
            email = raw.strip()
            if not re.match(_EMAIL_PATTERN, email):
                raise ValueError(f"{raw!r} is not a valid email address")
            if email.lower() not in {e.lower() for e in seen}:
                seen.append(email)
        return seen


class ReportResponse(BaseModel):
    report_type: ReportType
    title: str
    start_date: date
    end_date: date
    format: ReportFormat
    filename: str
    row_count: int
    totals: dict[str, str]
    # Exactly who the email went to, echoed back so the merchant sees it
    # rather than having to trust that "sent" meant the right addresses.
    emailed_to: list[str]
