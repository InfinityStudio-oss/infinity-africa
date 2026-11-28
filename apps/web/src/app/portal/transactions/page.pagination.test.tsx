import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Transaction } from "@/lib/portal/types";

// The customer report: "filtering Successful and Failed does not work".
// The API filtered correctly; this page did not show it. It fetched page
// 1 only, exported only that page, and rendered a failed request as "No
// transactions match these filters". These pin each of those.

const readTransactionsPage = vi.fn();
const fetchAllTransactionsForExport = vi.fn();
const getTransactionTracking = vi.fn();
const listMyRiskAlerts = vi.fn();

let searchParams = new URLSearchParams();
const push = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams,
  useRouter: () => ({ push, replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
}));

vi.mock("@/lib/portal/api", () => ({
  readTransactionsPage: (...args: unknown[]) => readTransactionsPage(...args),
  fetchAllTransactionsForExport: (...args: unknown[]) => fetchAllTransactionsForExport(...args),
  getTransactionTracking: (...args: unknown[]) => getTransactionTracking(...args),
  listMyRiskAlerts: (...args: unknown[]) => listMyRiskAlerts(...args),
}));

function txn(i: number, overrides: Partial<Transaction> = {}): Transaction {
  return {
    id: `txn-${i}`,
    merchant_id: "merchant-1",
    reference: `TXN-ROW-${i}`,
    provider_reference: null,
    type: "collection",
    method: "MOBILE_MONEY",
    collection_id: `col-${i}`,
    disbursement_id: null,
    gross_amount: "1000.00",
    fee_amount: "0.00",
    net_amount: "1000.00",
    currency: "TZS",
    status: "successful",
    balance_before: null,
    balance_after: null,
    direction: null,
    customer_phone: null,
    created_at: "2026-11-22T10:00:00Z",
    ...overrides,
  };
}

async function renderPage(query = "") {
  searchParams = new URLSearchParams(query);
  const { default: TransactionsPage } = await import("./page");
  return render(<TransactionsPage />);
}

describe("Transactions page — filters across pages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listMyRiskAlerts.mockResolvedValue([]);
    getTransactionTracking.mockResolvedValue({ data: null, error: null, noAccess: true });
    readTransactionsPage.mockResolvedValue({ rows: [], total: 0, totalPages: 0, error: null });
  });

  it("asks the API for the page in the URL, with the filters, not just page 1", async () => {
    readTransactionsPage.mockResolvedValue({ rows: [txn(51)], total: 120, totalPages: 3, error: null });

    await renderPage("status=successful&page=2");

    await waitFor(() =>
      expect(readTransactionsPage).toHaveBeenCalledWith(
        expect.objectContaining({ status: "successful" }),
        { page: 2, pageSize: 50 },
      ),
    );
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
  });

  it("shows the filtered total from the API, not the length of the page", async () => {
    readTransactionsPage.mockResolvedValue({
      rows: Array.from({ length: 50 }, (_, i) => txn(i)),
      total: 120,
      totalPages: 3,
      error: null,
    });

    await renderPage("status=failed");

    expect(await screen.findByText("Showing 1–50 of 120 transactions")).toBeInTheDocument();
  });

  it("moves to the next page keeping every filter", async () => {
    readTransactionsPage.mockResolvedValue({ rows: [txn(1)], total: 120, totalPages: 3, error: null });

    await renderPage("status=successful&type=collection");
    fireEvent.click(await screen.findByRole("button", { name: /Next/ }));

    expect(push).toHaveBeenCalledWith("/portal/transactions?status=successful&type=collection&page=2");
  });

  it("goes back to page 1 when a filter changes", async () => {
    readTransactionsPage.mockResolvedValue({ rows: [txn(1)], total: 120, totalPages: 3, error: null });

    await renderPage("status=successful&page=3");
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "failed" } });

    expect(push).toHaveBeenCalledWith("/portal/transactions?status=failed");
  });

  it("says the request failed instead of claiming nothing matched", async () => {
    // This is how "Successful does not work" looked from the outside: a
    // failed request rendered exactly like a filter with no matches.
    readTransactionsPage.mockResolvedValue({ rows: [], total: 0, totalPages: 0, error: "Service unavailable" });

    await renderPage("status=successful");

    expect(await screen.findByRole("alert")).toHaveTextContent("Transactions could not be loaded. Service unavailable");
    expect(screen.queryByText("No transactions match these filters.")).not.toBeInTheDocument();
    // The filter stays chosen - it is not silently reset to All.
    expect((screen.getByLabelText("Status") as HTMLSelectElement).value).toBe("successful");
  });

  it("retries the same filtered request", async () => {
    readTransactionsPage.mockResolvedValueOnce({ rows: [], total: 0, totalPages: 0, error: "Timeout" });
    readTransactionsPage.mockResolvedValueOnce({ rows: [txn(1)], total: 1, totalPages: 1, error: null });

    await renderPage("status=failed");
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByText("TXN-ROW-1")).toBeInTheDocument();
    expect(readTransactionsPage).toHaveBeenLastCalledWith(expect.objectContaining({ status: "failed" }), {
      page: 1,
      pageSize: 50,
    });
  });

  it("explains a status the API does not know, rather than sending it", async () => {
    // "Success" is the friendly word; the stored value is "successful".
    await renderPage("status=Success");

    expect(await screen.findByRole("alert")).toHaveTextContent("“Success” isn't a status InfinityPay records");
    expect(readTransactionsPage).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
  });

  it("maps every friendly status label to the backend's own value", async () => {
    await renderPage();
    const options = Array.from((screen.getByLabelText("Status") as HTMLSelectElement).options).map((o) => [
      o.textContent,
      o.value,
    ]);
    expect(options).toEqual([
      ["All Statuses", ""],
      ["Pending", "pending"],
      ["Processing", "processing"],
      ["Successful", "successful"],
      ["Failed", "failed"],
      ["Reversed", "reversed"],
      ["Cancelled", "cancelled"],
    ]);
  });

  it("honours the Overview chart's method and start_date/end_date link", async () => {
    // These links used to open an unfiltered ledger.
    await renderPage("method=MOBILE_MONEY&start_date=2026-11-01&end_date=2026-11-22");

    await waitFor(() =>
      expect(readTransactionsPage).toHaveBeenCalledWith(
        expect.objectContaining({ method: "MOBILE_MONEY", dateFrom: "2026-11-01", dateTo: "2026-11-22" }),
        expect.anything(),
      ),
    );
    expect(screen.getByRole("button", { name: /Remove method filter Mobile money/ })).toBeInTheDocument();
    expect((screen.getByLabelText("From") as HTMLInputElement).value).toBe("2026-11-01");
  });

  it("keeps the other filters when searching", async () => {
    await renderPage("status=failed");

    fireEvent.change(screen.getByLabelText(/Search transactions/), { target: { value: "0755123456" } });
    fireEvent.submit(screen.getByRole("search"));

    expect(push).toHaveBeenCalledWith("/portal/transactions?status=failed&search=0755123456");
  });

  it("exports every matching page with the same filters, and says when it had to stop", async () => {
    readTransactionsPage.mockResolvedValue({ rows: [txn(1)], total: 12_000, totalPages: 240, error: null });
    fetchAllTransactionsForExport.mockResolvedValue({
      rows: Array.from({ length: 3 }, (_, i) => txn(i)),
      total: 12_000,
      truncated: true,
      error: null,
    });
    if (!URL.createObjectURL) URL.createObjectURL = vi.fn();
    if (!URL.revokeObjectURL) URL.revokeObjectURL = vi.fn();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

    await renderPage("status=successful&date_from=2026-11-01");
    const button = await screen.findByRole("button", { name: /Export CSV/ });
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);

    await waitFor(() =>
      expect(fetchAllTransactionsForExport).toHaveBeenCalledWith(
        expect.objectContaining({ status: "successful", dateFrom: "2026-11-01" }),
      ),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Exported the newest 3 of 12,000 matching transactions");
  });

  it("does not export when the load failed", async () => {
    readTransactionsPage.mockResolvedValue({ rows: [], total: 0, totalPages: 0, error: "Boom" });
    await renderPage("status=failed");
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: /Export CSV/ })).toBeDisabled();
  });
});
