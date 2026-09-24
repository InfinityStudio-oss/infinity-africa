import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminTransactionRow } from "@/lib/admin/types";

import { ExportTransactionsCsvButton } from "./export-transactions-csv-button";

function transaction(overrides: Partial<AdminTransactionRow> = {}): AdminTransactionRow {
  return {
    transaction_id: "txn-1",
    merchant_id: "merchant-1",
    merchant_name: "Juma Traders Ltd",
    merchant_code: "27048391",
    type: "collection",
    reference: "TXN-20260822-E7803AE4",
    provider_reference: "SELCOM-REF-1",
    method: "DYNAMIC_QR",
    gross_amount: "2000.00",
    fee_amount: "30.00",
    net_amount: "1970.00",
    currency: "TZS",
    status: "pending",
    balance_before: "500.00",
    balance_after: "2470.00",
    direction: "credit",
    created_at: "2026-08-23T01:37:00Z",
    ...overrides,
  };
}

describe("ExportTransactionsCsvButton", () => {
  beforeEach(() => {
    if (!URL.createObjectURL) URL.createObjectURL = vi.fn();
    if (!URL.revokeObjectURL) URL.revokeObjectURL = vi.fn();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-url");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  });

  it("is disabled with no transactions", () => {
    render(<ExportTransactionsCsvButton transactions={[]} />);
    expect(screen.getByRole("button", { name: /Export CSV/ })).toBeDisabled();
  });

  it("downloads a CSV containing every merchant's transactions when clicked", async () => {
    render(<ExportTransactionsCsvButton transactions={[transaction()]} />);
    const button = screen.getByRole("button", { name: /Export CSV/ });
    expect(button).not.toBeDisabled();

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
      '"Date","Business","ID","Type","Transaction ID","Reference","Provider Reference","Method","Opening Balance","Amount","Charge","Net","Closing Balance","Currency","Direction","Status"',
    );
    expect(text).toContain("Juma Traders Ltd");
    expect(text).toContain("27048391");
    expect(text).toContain("TXN-20260822-E7803AE4");
    expect(text).toContain("SELCOM-REF-1");
    expect(text).toContain("500.00");
    expect(text).toContain("2470.00");
    expect(clickSpy).toHaveBeenCalledTimes(1);

    createElementSpy.mockRestore();
  });
});
