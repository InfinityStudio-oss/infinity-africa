import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Transaction } from "@/lib/portal/types";

const readTransactionsPage = vi.fn();
const fetchAllTransactionsForExport = vi.fn();
const getTransactionTracking = vi.fn();
const listMyRiskAlerts = vi.fn();

/** What the API answers for the page on screen. `total` defaults to the
 * rows given, i.e. a single page. */
function respond(rows: Transaction[], extra: { total?: number; totalPages?: number; error?: string | null } = {}) {
  readTransactionsPage.mockResolvedValue({
    rows,
    total: extra.total ?? rows.length,
    totalPages: extra.totalPages ?? (rows.length ? 1 : 0),
    error: extra.error ?? null,
  });
  fetchAllTransactionsForExport.mockResolvedValue({ rows, total: rows.length, truncated: false, error: null });
}

// The page reads ?search= so the topbar's search box can narrow the
// list server-side.
const searchParams = new URLSearchParams();
const push = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams,
  // The page pushes the search term to the URL rather than holding it,
  // so the page's own box and the topbar box cannot disagree about what
  // is being searched.
  useRouter: () => ({ push, replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
}));

vi.mock("@/lib/portal/api", () => ({
  readTransactionsPage: (...args: unknown[]) => readTransactionsPage(...args),
  fetchAllTransactionsForExport: (...args: unknown[]) => fetchAllTransactionsForExport(...args),
  getTransactionTracking: (...args: unknown[]) => getTransactionTracking(...args),
  listMyRiskAlerts: (...args: unknown[]) => listMyRiskAlerts(...args),
}));

function transaction(overrides: Partial<Transaction> = {}): Transaction {
  return {
    id: "txn-1",
    merchant_id: "merchant-1",
    reference: "TXN-20260822-E7803AE4",
    provider_reference: "SELCOM-REF-1",
    type: "collection",
    method: "DYNAMIC_QR",
    collection_id: "col-1",
    disbursement_id: null,
    gross_amount: "2000.00",
    fee_amount: "30.00",
    net_amount: "1970.00",
    currency: "TZS",
    status: "pending",
    balance_before: "500.00",
    balance_after: "2470.00",
    direction: "credit",
    customer_phone: "+255712345678",
    created_at: "2026-08-23T01:37:00Z",
    ...overrides,
  };
}

describe("Merchant portal TransactionsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listMyRiskAlerts.mockResolvedValue([]);
    respond([]);
    getTransactionTracking.mockResolvedValue({ data: null, error: "Not found", noAccess: true });
    if (!URL.createObjectURL) URL.createObjectURL = vi.fn();
    if (!URL.revokeObjectURL) URL.revokeObjectURL = vi.fn();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-url");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  });

  it("disables the Export CSV button when there are no transactions", async () => {
    respond([]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    await waitFor(() => expect(readTransactionsPage).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: /Export CSV/ })).toBeDisabled();
  });

  it("downloads a CSV containing every visible transaction, including the balance/charge audit fields, when clicked", async () => {
    respond([transaction()]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    const button = await screen.findByRole("button", { name: /Export CSV/ });
    await waitFor(() => expect(button).not.toBeDisabled());

    const clickSpy = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    const createElementSpy = vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = originalCreateElement(tag);
      if (tag === "a") el.click = clickSpy;
      return el;
    });

    fireEvent.click(button);

    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
    const blob = vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob;
    const text = await blob.text();
    expect(text).toContain(
      '"Date","Type","Transaction ID","Reference","Provider Reference","Channel","Customer Phone","Opening Balance","Amount","Charge","Net","Closing Balance","Currency","Direction","Status","InfinityPay Payment ID"',
    );
    expect(text).toContain("TXN-20260822-E7803AE4");
    expect(text).toContain("SELCOM-REF-1");
    expect(text).toContain("DYNAMIC_QR");
    expect(text).toContain("+2000.00");
    expect(text).toContain("500.00");
    expect(text).toContain("2470.00");
    expect(text).toContain('"col-1"');
    expect(clickSpy).toHaveBeenCalledTimes(1);

    createElementSpy.mockRestore();
  });

  it("renders the opening/closing balance and charge columns in the table", async () => {
    respond([transaction()]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    await screen.findByText("TXN-20260822-E7803AE4");
    expect(screen.getByText("Opening Balance")).toBeInTheDocument();
    expect(screen.getByText("Closing Balance")).toBeInTheDocument();
    expect(screen.getByText("Charge")).toBeInTheDocument();
  });

  it("shows 'Not available' instead of a fabricated number for a transaction with no balance snapshot", async () => {
    respond([transaction({ balance_before: null, balance_after: null })]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    await screen.findByText("TXN-20260822-E7803AE4");
    expect(screen.getAllByText("Not available").length).toBeGreaterThan(0);
  });

  it("opens the transaction detail drawer with identifiers and balance breakdown when a row is clicked", async () => {
    respond([transaction()]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    fireEvent.click(await screen.findByText("TXN-20260822-E7803AE4"));

    const dialog = await screen.findByRole("dialog", { name: "Transaction detail" });
    expect(within(dialog).getByText("txn-1")).toBeInTheDocument();
    expect(within(dialog).getAllByText("SELCOM-REF-1").length).toBeGreaterThan(0);
    expect(within(dialog).getByText("Wallet Balance")).toBeInTheDocument();
  });

  it("closes the detail drawer when the close button is clicked", async () => {
    respond([transaction()]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    fireEvent.click(await screen.findByText("TXN-20260822-E7803AE4"));
    await screen.findByRole("dialog", { name: "Transaction detail" });

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Transaction detail" })).not.toBeInTheDocument());
  });

  // --- who paid ------------------------------------------------------------

  it("shows the payer's phone on a collection row", async () => {
    respond([transaction()]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    expect(await screen.findByText("Customer Phone")).toBeInTheDocument();
    expect(screen.getAllByText("+255712345678").length).toBeGreaterThan(0);
  });

  it("shows a dash rather than a guess when there is no payer", async () => {
    // A withdrawal has no customer on the other side.
    respond([
      transaction({ type: "disbursement", collection_id: null, customer_phone: null }),
    ]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    const row = (await screen.findByText("TXN-20260822-E7803AE4")).closest("tr") as HTMLElement;
    expect(within(row).getByText("—")).toBeInTheDocument();
    expect(within(row).queryByText(/\+255/)).not.toBeInTheDocument();
  });

  it("includes the customer phone in the detail drawer", async () => {
    respond([transaction()]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    fireEvent.click(await screen.findByText("TXN-20260822-E7803AE4"));

    const dialog = await screen.findByRole("dialog", { name: "Transaction detail" });
    expect(within(dialog).getByText("Customer Phone")).toBeInTheDocument();
    expect(within(dialog).getByText("+255712345678")).toBeInTheDocument();
  });


  it("passes the search term to the API rather than filtering what is already loaded", async () => {
    // This endpoint is paginated, so narrowing the rows already fetched
    // would report "no results" for a transaction sitting on page two.
    searchParams.set("search", "TXN-FINDME");
    try {
      const { default: TransactionsPage } = await import("./page");
      render(<TransactionsPage />);

      await waitFor(() =>
        expect(readTransactionsPage).toHaveBeenCalledWith(
          expect.objectContaining({ search: "TXN-FINDME" }),
          expect.anything(),
        ),
      );
    } finally {
      searchParams.delete("search");
    }
  });

  // --- the Type / Status / From / To filters ---------------------------------
  //
  // These four were a dropdown each and two date boxes wired to
  // nothing: no value, no handler, and two hardcoded August dates
  // sitting in the date inputs as though a range had been chosen. The
  // page looked filtered and was not, which is worse than having no
  // filters at all.

  it("sends every filter in the URL to the API, not just the search term", async () => {
    searchParams.set("type", "disbursement");
    searchParams.set("status", "failed");
    searchParams.set("date_from", "2026-11-01");
    searchParams.set("date_to", "2026-11-22");
    try {
      const { default: TransactionsPage } = await import("./page");
      render(<TransactionsPage />);

      await waitFor(() =>
        expect(readTransactionsPage).toHaveBeenCalledWith(
          {
            search: "",
            type: "disbursement",
            status: "failed",
            dateFrom: "2026-11-01",
            dateTo: "2026-11-22",
            method: "",
          },
          { page: 1, pageSize: 50 },
        ),
      );
    } finally {
      searchParams.delete("type");
      searchParams.delete("status");
      searchParams.delete("date_from");
      searchParams.delete("date_to");
    }
  });

  it("puts a chosen filter in the URL so the view can be linked to and reloaded", async () => {
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "failed" } });

    expect(push).toHaveBeenCalledWith("/portal/transactions?status=failed");
  });

  it("keeps the other filters when one of them changes", async () => {
    // Setting a filter used to be impossible; setting one that silently
    // dropped the others would be its own kind of wrong.
    searchParams.set("type", "collection");
    try {
      const { default: TransactionsPage } = await import("./page");
      render(<TransactionsPage />);

      fireEvent.change(screen.getByLabelText("Status"), { target: { value: "failed" } });

      expect(push).toHaveBeenCalledWith("/portal/transactions?type=collection&status=failed");
    } finally {
      searchParams.delete("type");
    }
  });

  it("removes a filter from the URL when it is set back to All", async () => {
    searchParams.set("status", "failed");
    try {
      const { default: TransactionsPage } = await import("./page");
      render(<TransactionsPage />);

      fireEvent.change(screen.getByLabelText("Status"), { target: { value: "" } });

      expect(push).toHaveBeenCalledWith("/portal/transactions");
    } finally {
      searchParams.delete("status");
    }
  });

  it("offers every type the ledger can hold, including payouts", async () => {
    // The old dropdown offered three of seven. A missing option is a
    // question the merchant cannot ask, and payouts are live.
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    const options = within(screen.getByLabelText("Type") as HTMLSelectElement)
      .getAllByRole("option")
      .map((option) => (option as HTMLOptionElement).value);

    expect(options).toEqual([
      "",
      "collection",
      "disbursement",
      "payout",
      "fee",
      "refund",
      "reversal",
      "adjustment",
    ]);
  });

  it("does not pre-fill the date boxes with a range nobody chose", async () => {
    // Two hardcoded August dates used to sit here, so the page claimed
    // to be showing 1-13 August while showing everything.
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    expect((screen.getByLabelText("From") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("To") as HTMLInputElement).value).toBe("");
  });

  it("says the filters are why the table is empty, not that there are no transactions", async () => {
    // "No transactions yet" when a filter is hiding them tells a
    // merchant their money is missing.
    respond([]);
    searchParams.set("status", "reversed");
    try {
      const { default: TransactionsPage } = await import("./page");
      render(<TransactionsPage />);

      expect(await screen.findByText("No transactions match these filters.")).toBeInTheDocument();
    } finally {
      searchParams.delete("status");
    }
  });

  it("offers a way back out of a filter that matches nothing", async () => {
    respond([]);
    searchParams.set("status", "reversed");
    try {
      const { default: TransactionsPage } = await import("./page");
      render(<TransactionsPage />);

      fireEvent.click(await screen.findByRole("button", { name: "Clear filters" }));

      expect(push).toHaveBeenCalledWith("/portal/transactions");
    } finally {
      searchParams.delete("status");
    }
  });

  it("shows no Clear filters button when nothing is filtered", async () => {
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  });
});
