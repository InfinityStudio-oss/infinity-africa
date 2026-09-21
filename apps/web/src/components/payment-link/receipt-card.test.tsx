import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PublicCollectionReceipt } from "@/lib/payment-links";

import { ReceiptCard } from "./receipt-card";

const receipt: PublicCollectionReceipt = {
  collection_id: "11111111-1111-1111-1111-111111111111",
  transaction_id: "22222222-2222-2222-2222-222222222222",
  merchant_name: "Salome Mponeja Shop",
  merchant_code: "27048391",
  amount: "2500.00",
  currency: "TZS",
  description: "Order #482",
  customer_name: "Grace",
  customer_phone: "255747730270",
  method: "Mobile Money Push",
  merchant_reference: "INV-2026-0042",
  provider_reference: "S20690471578",
  provider_transid: "TXN-ABC123",
  channel: "TIGOPESA",
  completed_at: "2026-08-24T10:15:00Z",
};

describe("ReceiptCard", () => {
  it("shows the confirmed payment values", () => {
    render(<ReceiptCard receipt={receipt} slug="test-slug" />);

    expect(screen.getByText("TZS 2,500.00")).toBeInTheDocument();
    expect(screen.getByText("Salome Mponeja Shop")).toBeInTheDocument();
    expect(screen.getByText("Order #482")).toBeInTheDocument();
    expect(screen.getByText("Mobile Money Push")).toBeInTheDocument();
    expect(screen.getByText("TIGOPESA")).toBeInTheDocument();
    expect(screen.getByText("S20690471578")).toBeInTheDocument();
  });

  it("shows the InfinityPay logo mark (icon + wordmark), not plain text alone", () => {
    render(<ReceiptCard receipt={receipt} slug="test-slug" />);

    expect(screen.getByText("all_inclusive")).toBeInTheDocument();
    expect(screen.getByText("InfinityPay")).toBeInTheDocument();
  });

  it("does not show internal record IDs or the processor's name — customer-facing only", () => {
    render(<ReceiptCard receipt={receipt} slug="test-slug" />);

    expect(screen.queryByText(receipt.collection_id)).not.toBeInTheDocument();
    expect(screen.queryByText(receipt.transaction_id as string)).not.toBeInTheDocument();
    expect(screen.queryByText("TXN-ABC123")).not.toBeInTheDocument();
    expect(screen.queryByText("INV-2026-0042")).not.toBeInTheDocument();
    expect(screen.queryByText("Collection ID")).not.toBeInTheDocument();
    expect(screen.queryByText("Transaction ID")).not.toBeInTheDocument();
    expect(screen.queryByText("Provider Transaction ID")).not.toBeInTheDocument();
    expect(screen.queryByText("Merchant reference")).not.toBeInTheDocument();
    expect(screen.queryByText(/confirmed by Selcom/i)).not.toBeInTheDocument();
  });

  it("shows a Successful status row and a friendly receipt number", () => {
    render(<ReceiptCard receipt={receipt} slug="test-slug" />);

    expect(screen.getByText("Successful")).toBeInTheDocument();
    expect(screen.getByText("RCPT-11111111")).toBeInTheDocument();
  });

  it("masks the customer phone number, never showing it in full", () => {
    render(<ReceiptCard receipt={receipt} slug="test-slug" />);

    expect(screen.queryByText(/255747730270/)).not.toBeInTheDocument();
    expect(screen.getByText(/•••• 0270/)).toBeInTheDocument();
  });

  it("never renders raw provider payload or secret-shaped values", () => {
    render(<ReceiptCard receipt={receipt} slug="test-slug" />);

    expect(screen.queryByText(/raw_response/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/api_key/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/private_key/i)).not.toBeInTheDocument();
  });

  it("omits optional rows entirely when the backend didn't return them", () => {
    render(
      <ReceiptCard
        receipt={{ ...receipt, description: null, channel: null, merchant_code: null }}
        slug="test-slug"
      />,
    );

    expect(screen.queryByText("Order #482")).not.toBeInTheDocument();
    expect(screen.queryByText("Channel")).not.toBeInTheDocument();
    expect(screen.queryByText("Merchant ID")).not.toBeInTheDocument();
  });

  it("shows the Merchant ID row when the backend returns one", () => {
    render(<ReceiptCard receipt={receipt} slug="test-slug" />);

    expect(screen.getByText("27048391")).toBeInTheDocument();
  });

  it("the Download Receipt PDF and Print Receipt buttons both trigger the browser print dialog", () => {
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    render(<ReceiptCard receipt={receipt} slug="test-slug" />);

    screen.getByRole("button", { name: "Download Receipt PDF" }).click();
    screen.getByRole("button", { name: "Print Receipt" }).click();

    expect(printSpy).toHaveBeenCalledTimes(2);
    printSpy.mockRestore();
  });

  it("links back to the payment status page for this slug", () => {
    render(<ReceiptCard receipt={receipt} slug="test-slug" />);

    expect(screen.getByRole("link", { name: "Back to payment status" })).toHaveAttribute("href", "/pay/test-slug");
  });
});
