from dataclasses import dataclass

from fastapi import Query

from app.schemas.common import PageMeta

# What a paginated LIST endpoint passes to `.select(..., count=...)`.
#
# `exact` makes PostgREST run a real COUNT over every matching row, on
# every page load. On a table of a hundred rows that is free. On
# collections it is 84,000 rows, on audit_logs 153,000, on
# api_request_logs 514,000 — and measured against production it cost
# between 0.6 and 3.9 seconds depending only on how warm the cache was.
#
# That variance is what made it dangerous rather than merely slow. The
# Super Admin Collections page fires three admin requests at once; put
# three of those counts in flight together and one tips over the
# statement timeout, which surfaces as `APIError: canceling statement due
# to statement timeout` and reaches the browser as a 500. The page then
# showed "No collections have been recorded yet" over 84,000 real rows.
#
# `estimated` asks the planner instead — but only above a threshold.
# Below it PostgREST still does the exact count, which was confirmed
# against production: merchants, api_keys, payment_links, invoices and
# disbursements all returned identical numbers either way. Only the huge
# tables approximate, by 0.1-4.6%.
#
# That trade is right for a list: the number drives a page count, and no
# one is owed four-digit precision on "how many of the 84,000 are there".
# It is NOT right for a figure a person reads as a fact — the dashboard
# cards in services/admin_overview.py and services/merchant_overview.py
# stay `exact` deliberately, and are cheap because they are filtered to a
# day or a month.
LIST_COUNT = "estimated"


@dataclass
class PaginationParams:
    page: int
    page_size: int

    @property
    def start(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def end(self) -> int:
        """Inclusive end index, as required by supabase-py's `.range()`."""
        return self.start + self.page_size - 1


def pagination_params(
    page: int = Query(1, ge=1, description="1-indexed page number"),
    page_size: int = Query(20, ge=1, le=100, description="Rows per page (max 100)"),
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)


def build_page_meta(params: PaginationParams, total: int) -> PageMeta:
    total_pages = (total + params.page_size - 1) // params.page_size if params.page_size else 0
    return PageMeta(page=params.page, page_size=params.page_size, total=total, total_pages=total_pages)
