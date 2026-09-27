import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Transaction } from "@/lib/portal/types";

const listTransactions = vi.fn();
const listMyRiskAlerts = vi.fn();

vi.mock("@/lib/portal/api", () => ({
  listTransactions: (...args: unknown[]) => listTransactions(...args),
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
    if (!URL.createObjectURL) URL.createObjectURL = vi.fn();
    if (!URL.revokeObjectURL) URL.revokeObjectURL = vi.fn();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-url");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  });

  it("disables the Export CSV button when there are no transactions", async () => {
    listTransactions.mockResolvedValue([]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    await waitFor(() => expect(listTransactions).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: /Export CSV/ })).toBeDisabled();
  });

  it("downloads a CSV containing every visible transaction, including the balance/charge audit fields, when clicked", async () => {
    listTransactions.mockResolvedValue([transaction()]);
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

    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    const blob = vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob;
    const text = await blob.text();
    expect(text).toContain(
      '"Date","Type","Transaction ID","Reference","Provider Reference","Channel","Customer Phone","Opening Balance","Amount","Charge","Net","Closing Balance","Currency","Direction","Status"',
    );
    expect(text).toContain("TXN-20260822-E7803AE4");
    expect(text).toContain("SELCOM-REF-1");
    expect(text).toContain("DYNAMIC_QR");
    expect(text).toContain("+2000.00");
    expect(text).toContain("500.00");
    expect(text).toContain("2470.00");
    expect(clickSpy).toHaveBeenCalledTimes(1);

    createElementSpy.mockRestore();
  });

  it("renders the opening/closing balance and charge columns in the table", async () => {
    listTransactions.mockResolvedValue([transaction()]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    await screen.findByText("TXN-20260822-E7803AE4");
    expect(screen.getByText("Opening Balance")).toBeInTheDocument();
    expect(screen.getByText("Closing Balance")).toBeInTheDocument();
    expect(screen.getByText("Charge")).toBeInTheDocument();
  });

  it("shows 'Not available' instead of a fabricated number for a transaction with no balance snapshot", async () => {
    listTransactions.mockResolvedValue([transaction({ balance_before: null, balance_after: null })]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    await screen.findByText("TXN-20260822-E7803AE4");
    expect(screen.getAllByText("Not available").length).toBeGreaterThan(0);
  });

  it("opens the transaction detail drawer with identifiers and balance breakdown when a row is clicked", async () => {
    listTransactions.mockResolvedValue([transaction()]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    fireEvent.click(await screen.findByText("TXN-20260822-E7803AE4"));

    const dialog = await screen.findByRole("dialog", { name: "Transaction detail" });
    expect(within(dialog).getByText("txn-1")).toBeInTheDocument();
    expect(within(dialog).getAllByText("SELCOM-REF-1").length).toBeGreaterThan(0);
    expect(within(dialog).getByText("Wallet Balance")).toBeInTheDocument();
  });

  it("closes the detail drawer when the close button is clicked", async () => {
    listTransactions.mockResolvedValue([transaction()]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    fireEvent.click(await screen.findByText("TXN-20260822-E7803AE4"));
    await screen.findByRole("dialog", { name: "Transaction detail" });

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Transaction detail" })).not.toBeInTheDocument());
  });

  // --- who paid ------------------------------------------------------------

  it("shows the payer's phone on a collection row", async () => {
    listTransactions.mockResolvedValue([transaction()]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    expect(await screen.findByText("Customer Phone")).toBeInTheDocument();
    expect(screen.getAllByText("+255712345678").length).toBeGreaterThan(0);
  });

  it("shows a dash rather than a guess when there is no payer", async () => {
    // A withdrawal has no customer on the other side.
    listTransactions.mockResolvedValue([
      transaction({ type: "disbursement", collection_id: null, customer_phone: null }),
    ]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    const row = (await screen.findByText("TXN-20260822-E7803AE4")).closest("tr") as HTMLElement;
    expect(within(row).getByText("—")).toBeInTheDocument();
    expect(within(row).queryByText(/\+255/)).not.toBeInTheDocument();
  });

  it("includes the customer phone in the detail drawer", async () => {
    listTransactions.mockResolvedValue([transaction()]);
    const { default: TransactionsPage } = await import("./page");
    render(<TransactionsPage />);

    fireEvent.click(await screen.findByText("TXN-20260822-E7803AE4"));

    const dialog = await screen.findByRole("dialog", { name: "Transaction detail" });
    expect(within(dialog).getByText("Customer Phone")).toBeInTheDocument();
    expect(within(dialog).getByText("+255712345678")).toBeInTheDocument();
  });
});
