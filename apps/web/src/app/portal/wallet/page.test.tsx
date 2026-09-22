import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WalletLedgerEntry } from "@/lib/portal/types";

const getAvailableBalance = vi.fn();
const listWalletLedger = vi.fn();
const getMyMerchant = vi.fn();
const exportWalletLedger = vi.fn();

vi.mock("@/lib/portal/api", () => ({
  getAvailableBalance: (...args: unknown[]) => getAvailableBalance(...args),
  listWalletLedger: (...args: unknown[]) => listWalletLedger(...args),
  getMyMerchant: (...args: unknown[]) => getMyMerchant(...args),
  exportWalletLedger: (...args: unknown[]) => exportWalletLedger(...args),
}));

function ledgerEntry(overrides: Partial<WalletLedgerEntry> = {}): WalletLedgerEntry {
  return {
    id: "entry-1",
    transaction_id: "txn-1",
    date: "2026-08-23T01:37:00Z",
    description: "Merchant wallet credited (net of fee)",
    direction: "credit",
    amount: "1970.00",
    balance_before: "500.00",
    balance_after: "2470.00",
    type: "collection",
    reference: "TXN-REF-1",
    provider_reference: "SELCOM-1",
    method: "USSD_PUSH",
    fee_amount: "30.00",
    net_amount: "1970.00",
    status: "successful",
    ...overrides,
  };
}

describe("Merchant portal WalletPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getAvailableBalance.mockResolvedValue("2470.00");
    getMyMerchant.mockResolvedValue({ merchant_code: "27048391" });
    listWalletLedger.mockResolvedValue([]);
  });

  it("renders the opening/closing balance, charge, and transaction ID columns", async () => {
    listWalletLedger.mockResolvedValue([ledgerEntry()]);
    const { default: WalletPage } = await import("./page");
    render(<WalletPage />);

    await waitFor(() => expect(listWalletLedger).toHaveBeenCalled());
    expect(screen.getByText("Opening Balance")).toBeInTheDocument();
    expect(screen.getByText("Closing Balance")).toBeInTheDocument();
    expect(screen.getByText("Transaction ID")).toBeInTheDocument();
    expect(screen.getByText("Charge / Fee")).toBeInTheDocument();
    expect(screen.getByText("Net Amount")).toBeInTheDocument();
    expect(screen.getByText("Type")).toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();
  });

  it("shows an empty state, not an error, when there is no wallet activity yet", async () => {
    const { default: WalletPage } = await import("./page");
    render(<WalletPage />);

    expect(await screen.findByText("No wallet activity yet.")).toBeInTheDocument();
  });

  it("shows the merchant's ID in the page header", async () => {
    const { default: WalletPage } = await import("./page");
    render(<WalletPage />);

    expect(await screen.findByText("27048391")).toBeInTheDocument();
  });

  it("renders the date filters, quick filters, Apply, Reset, and Export controls", async () => {
    const { default: WalletPage } = await import("./page");
    render(<WalletPage />);

    expect(await screen.findByText("Start Date")).toBeInTheDocument();
    expect(screen.getByText("End Date")).toBeInTheDocument();
    for (const label of ["Today", "Yesterday", "Last 7 Days", "Last 30 Days", "This Month", "Last Month"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Apply Filter" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Export Excel/ })).toBeInTheDocument();
  });

  it("clicking a quick filter sets both dates and refetches the ledger", async () => {
    const { default: WalletPage } = await import("./page");
    render(<WalletPage />);
    await waitFor(() => expect(listWalletLedger).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Today" }));

    await waitFor(() => expect(listWalletLedger).toHaveBeenCalledTimes(2));
    const lastCallArgs = listWalletLedger.mock.calls[1][0];
    expect(lastCallArgs.start_date).toBe(lastCallArgs.end_date);
    expect(lastCallArgs.start_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);

    const startInput = screen.getByLabelText("Start Date") as HTMLInputElement;
    const endInput = screen.getByLabelText("End Date") as HTMLInputElement;
    expect(startInput.value).toBe(lastCallArgs.start_date);
    expect(endInput.value).toBe(lastCallArgs.end_date);
  });

  it("Apply Filter refreshes the ledger using the typed date range", async () => {
    const { default: WalletPage } = await import("./page");
    render(<WalletPage />);
    await waitFor(() => expect(listWalletLedger).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Start Date"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("End Date"), { target: { value: "2026-08-15" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply Filter" }));

    await waitFor(() => expect(listWalletLedger).toHaveBeenCalledTimes(2));
    expect(listWalletLedger).toHaveBeenLastCalledWith({ start_date: "2026-08-01", end_date: "2026-08-15" });
  });

  it("Reset clears the date filters and refetches unfiltered", async () => {
    const { default: WalletPage } = await import("./page");
    render(<WalletPage />);
    await waitFor(() => expect(listWalletLedger).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Last 7 Days" }));
    await waitFor(() => expect(listWalletLedger).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(listWalletLedger).toHaveBeenCalledTimes(3));
    expect(listWalletLedger).toHaveBeenLastCalledWith({ start_date: undefined, end_date: undefined });

    const startInput = screen.getByLabelText("Start Date") as HTMLInputElement;
    expect(startInput.value).toBe("");
  });

  it("shows the date-range-specific empty message once a filter is applied and returns nothing", async () => {
    const { default: WalletPage } = await import("./page");
    render(<WalletPage />);
    await waitFor(() => expect(listWalletLedger).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Today" }));

    expect(await screen.findByText("No wallet ledger entries found for this date range.")).toBeInTheDocument();
  });

  it("Export Excel calls the backend export endpoint and downloads the returned file", async () => {
    if (!URL.createObjectURL) URL.createObjectURL = vi.fn();
    if (!URL.revokeObjectURL) URL.revokeObjectURL = vi.fn();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-url");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const fakeBlob = new Blob(["xlsx-bytes"], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    exportWalletLedger.mockResolvedValue(fakeBlob);

    const { default: WalletPage } = await import("./page");
    render(<WalletPage />);
    await waitFor(() => expect(listWalletLedger).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Start Date"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("End Date"), { target: { value: "2026-08-15" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply Filter" }));
    await waitFor(() => expect(listWalletLedger).toHaveBeenCalledTimes(2));

    const clickSpy = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    const createElementSpy = vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = originalCreateElement(tag);
      if (tag === "a") el.click = clickSpy;
      return el;
    });

    fireEvent.click(screen.getByRole("button", { name: /Export Excel/ }));

    await waitFor(() => expect(exportWalletLedger).toHaveBeenCalledWith({ start_date: "2026-08-01", end_date: "2026-08-15" }));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledWith(fakeBlob));
    expect(clickSpy).toHaveBeenCalledTimes(1);

    // Filters stay exactly as the merchant left them after exporting.
    expect((screen.getByLabelText("Start Date") as HTMLInputElement).value).toBe("2026-08-01");
    expect((screen.getByLabelText("End Date") as HTMLInputElement).value).toBe("2026-08-15");

    createElementSpy.mockRestore();
  });

  it("shows an error banner, not a raw response, when export fails", async () => {
    exportWalletLedger.mockRejectedValue(new Error("Couldn't export the wallet ledger. Please try again."));

    const { default: WalletPage } = await import("./page");
    render(<WalletPage />);
    await waitFor(() => expect(listWalletLedger).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: /Export Excel/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't export the wallet ledger. Please try again.");
  });
});
