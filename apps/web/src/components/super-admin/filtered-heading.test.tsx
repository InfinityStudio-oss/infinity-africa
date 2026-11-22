import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AdminCollectionRow, AdminTransactionRow } from "@/lib/admin/types";

import { CollectionsTable } from "./collections-table";
import { TransactionsTable } from "./transactions-table";

/**
 * A filtered list must say it is filtered.
 *
 * This is not cosmetics. The Super Admin Collections phone filter was
 * reported as "not working" while it was working perfectly: a search
 * for +255686098822 returned exactly the right five collections, and
 * the page still said "All Collections" over a platform-wide
 * "Collections Today" figure that does not move. Everything visible
 * above the fold looked like a page that had ignored the filter.
 *
 * So the heading carries the state, and the row count with it - the
 * fastest way to confirm a filter did something is a number that
 * changed.
 */

function collection(overrides: Partial<AdminCollectionRow> = {}): AdminCollectionRow {
  return {
    collection_id: "col-1",
    merchant_id: "merchant-1",
    merchant_name: "Kilimanjaro Cafe",
    merchant_code: "27048391",
    customer_phone: "255686098822",
    amount: "500.00",
    currency: "TZS",
    status: "successful",
    method: "USSD_PUSH",
    created_at: "2026-11-22T18:07:08Z",
    ...overrides,
  } as AdminCollectionRow;
}

function transaction(overrides: Partial<AdminTransactionRow> = {}): AdminTransactionRow {
  return {
    transaction_id: "txn-1",
    merchant_id: "merchant-1",
    merchant_name: "Kilimanjaro Cafe",
    merchant_code: "27048391",
    type: "collection",
    reference: "TXN-1",
    provider_reference: null,
    method: "USSD_PUSH",
    customer_phone: "255686098822",
    gross_amount: "500.00",
    fee_amount: "0.00",
    net_amount: "500.00",
    currency: "TZS",
    status: "successful",
    balance_before: null,
    balance_after: null,
    direction: "credit",
    created_at: "2026-11-22T18:07:08Z",
    ...overrides,
  } as AdminTransactionRow;
}

describe("a filtered Super Admin list says so", () => {
  it("heads the collections list 'All Collections' when nothing is filtered", () => {
    render(<CollectionsTable collections={[collection()]} />);

    expect(screen.getByRole("heading", { name: "All Collections" })).toBeInTheDocument();
  });

  it("heads it 'Matching Collections' with a count when a filter is on", () => {
    render(
      <CollectionsTable
        collections={[collection(), collection({ collection_id: "col-2" })]}
        filtered
      />,
    );

    expect(screen.getByRole("heading", { name: "Matching Collections (2)" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "All Collections" })).not.toBeInTheDocument();
  });

  it("warns that Collections Today is platform-wide and will not move", () => {
    // The other half of what made a working filter look broken: a
    // headline money figure that is deliberately not filtered.
    render(<CollectionsTable collections={[collection()]} filtered />);

    // [\s\S] rather than the /s flag, which this TS target rejects.
    expect(screen.getByText(/Collections Today[\s\S]*platform-wide/)).toBeInTheDocument();
  });

  it("says no collections MATCH, rather than none exist, when filtered", () => {
    // "None recorded yet" while a filter hides 149,000 of them is a
    // flat untruth about the platform.
    render(<CollectionsTable collections={[]} filtered />);

    expect(screen.getByText("No collections match these filters.")).toBeInTheDocument();
  });

  it("still says none have been recorded when genuinely empty", () => {
    render(<CollectionsTable collections={[]} />);

    expect(screen.getByText("No collections have been recorded yet.")).toBeInTheDocument();
  });

  it("does not claim an empty list when the request actually failed", () => {
    // Pre-existing behaviour that must survive: a failure is not an
    // empty list, and this page has twice shown a reassuring empty
    // state over a real fault.
    render(<CollectionsTable collections={[]} loadFailure="HTTP 500" filtered />);

    expect(screen.getByText("Collections could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText("No collections match these filters.")).not.toBeInTheDocument();
  });

  it("heads the transactions list the same way", () => {
    const { rerender } = render(<TransactionsTable transactions={[transaction()]} />);
    expect(screen.getByRole("heading", { name: "All Transactions" })).toBeInTheDocument();

    rerender(<TransactionsTable transactions={[transaction()]} filtered />);
    expect(screen.getByRole("heading", { name: "Matching Transactions (1)" })).toBeInTheDocument();
  });
});
