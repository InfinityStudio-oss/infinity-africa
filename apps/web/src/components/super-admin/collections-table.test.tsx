import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AdminCollectionRow } from "@/lib/admin/types";

const refreshAdminCollectionStatusClient = vi.fn();

vi.mock("@/lib/admin/refresh-collection-status-client", () => ({
  refreshAdminCollectionStatusClient: (...args: unknown[]) => refreshAdminCollectionStatusClient(...args),
}));

function row(overrides: Partial<AdminCollectionRow>): AdminCollectionRow {
  return {
    collection_id: "col-1",
    merchant_id: "merchant-1",
    merchant_name: "Juma Traders Ltd",
    merchant_code: "27048391",
    source: "PAYMENT_LINK",
    method: "STK_PUSH",
    amount: "1000.00",
    currency: "TZS",
    fee_amount: null,
    net_amount: null,
    phone: "255762474101",
    merchant_reference: null,
    provider_reference: "S123",
    api_key_id: null,
    payment_link_id: null,
    invoice_id: null,
    status: "processing",
    created_at: "2026-08-22T21:20:00Z",
    order_id: "ORD-1",
    provider_transid: "TXN-1",
    channel: null,
    provider_payment_status: null,
    failure_reason: null,
    webhook_delivery_status: null,
    webhook_response_code: null,
    ...overrides,
  };
}

describe("CollectionsTable", () => {
  it("shows Refresh status for a processing collection", async () => {
    const { CollectionsTable } = await import("./collections-table");
    render(<CollectionsTable collections={[row({ status: "processing" })]} />);

    expect(screen.getByRole("button", { name: "Refresh status" })).toBeInTheDocument();
  });

  it("does not show Refresh status for a successful collection", async () => {
    const { CollectionsTable } = await import("./collections-table");
    render(<CollectionsTable collections={[row({ status: "successful" })]} />);

    expect(screen.queryByRole("button", { name: "Refresh status" })).not.toBeInTheDocument();
  });

  it("does not show Refresh status for a failed collection", async () => {
    const { CollectionsTable } = await import("./collections-table");
    render(<CollectionsTable collections={[row({ status: "failed", failure_reason: "Rejected by customer" })]} />);

    expect(screen.queryByRole("button", { name: "Refresh status" })).not.toBeInTheDocument();
    expect(screen.getByText("Rejected by customer")).toBeInTheDocument();
  });

  it("calls refreshAdminCollectionStatusClient with this row's collection_id, then updates the row in place", async () => {
    refreshAdminCollectionStatusClient.mockResolvedValue(row({ status: "successful", collection_id: "col-1" }));
    const { CollectionsTable } = await import("./collections-table");
    render(<CollectionsTable collections={[row({ status: "processing", collection_id: "col-1" })]} />);

    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));

    await waitFor(() => expect(refreshAdminCollectionStatusClient).toHaveBeenCalledWith("col-1"));
    expect(await screen.findByText("Payment completed")).toBeInTheDocument();
  });

  // Super Admin is who gets asked "my customer paid and was never
  // connected". Until 2026-10-27 this screen could not answer it — the
  // merchant saw the delivery failure on their own page, the person
  // fielding the complaint did not.

  it("shows the error code when the merchant's system never received the payment", async () => {
    const { CollectionsTable } = await import("./collections-table");
    render(
      <CollectionsTable
        collections={[row({ status: "successful", webhook_delivery_status: "failed", webhook_response_code: 500 })]}
      />,
    );

    expect(await screen.findByText(/Not received/)).toBeInTheDocument();
    expect(screen.getByText(/HTTP 500/)).toBeInTheDocument();
  });

  it("shows Delivered when the merchant was told", async () => {
    const { CollectionsTable } = await import("./collections-table");
    render(
      <CollectionsTable
        collections={[row({ status: "successful", webhook_delivery_status: "delivered", webhook_response_code: 200 })]}
      />,
    );

    expect(await screen.findByText("Delivered")).toBeInTheDocument();
  });

  it("says nothing for a merchant with no webhook configured", async () => {
    // Most merchants have no endpoint at all — they must not grow a
    // column full of warnings about something that was never set up.
    const { CollectionsTable } = await import("./collections-table");
    render(<CollectionsTable collections={[row({ status: "successful" })]} />);

    await screen.findByText("Juma Traders Ltd");
    expect(screen.queryByText(/Not received/)).not.toBeInTheDocument();
    expect(screen.queryByText("Delivered")).not.toBeInTheDocument();
  });

  it("does not raise alarm while delivery is still inside its retry window", async () => {
    // A payment still being retried is not yet news; only success and
    // error are worth a Super Admin's attention.
    const { CollectionsTable } = await import("./collections-table");
    render(
      <CollectionsTable
        collections={[row({ status: "successful", webhook_delivery_status: "retrying", webhook_response_code: 500 })]}
      />,
    );

    expect(await screen.findByText(/Sending/)).toBeInTheDocument();
    expect(screen.queryByText(/Not received/)).not.toBeInTheDocument();
  });
});
