import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AdminTransactionRow } from "@/lib/admin/types";

import { TransactionsTable } from "./transactions-table";

function row(overrides: Partial<AdminTransactionRow> = {}): AdminTransactionRow {
  return {
    transaction_id: "11111111-2222-3333-4444-555555555555",
    merchant_id: "merchant-1",
    merchant_name: "Kilimanjaro Cafe",
    merchant_code: "27048391",
    type: "collection",
    reference: "TXN-1",
    provider_reference: "SELCOM-REF-1",
    method: "USSD_PUSH",
    customer_phone: "255762474101",
    gross_amount: "10000.00",
    fee_amount: "200.00",
    net_amount: "9800.00",
    currency: "TZS",
    status: "successful",
    balance_before: "0.00",
    balance_after: "9800.00",
    direction: "credit",
    created_at: "2026-08-23T01:37:00Z",
    ...overrides,
  };
}

describe("Super Admin TransactionsTable", () => {
  it("shows the merchant name, audit identifiers, and balance snapshot", () => {
    render(<TransactionsTable transactions={[row()]} />);

    expect(screen.getByText("Kilimanjaro Cafe")).toBeInTheDocument();
    expect(screen.getByText("SELCOM-REF-1")).toBeInTheDocument();
    expect(screen.getByText("Credit")).toBeInTheDocument();
  });

  it("shows 'Not available' rather than a fabricated number when the balance snapshot is missing", () => {
    render(<TransactionsTable transactions={[row({ balance_before: null, balance_after: null, direction: null })]} />);

    expect(screen.getAllByText("Not available").length).toBe(2);
  });

  it("shows an empty state when no transactions match the filters", () => {
    render(<TransactionsTable transactions={[]} />);

    expect(screen.getByText("No transactions match these filters.")).toBeInTheDocument();
  });
});
