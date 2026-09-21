import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CollectionMethod, PaymentLinkStatus } from "@infinity/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PaymentLink } from "@/lib/portal/types";

const link: PaymentLink = {
  id: "link-1",
  merchant_id: "merchant-1",
  customer_id: null,
  amount: "25000.00",
  currency: "TZS",
  customer_name: "Grace Mwakalinga",
  customer_phone: null,
  customer_email: null,
  description: "Invoice for services",
  allowed_payment_methods: [CollectionMethod.USSD_PUSH, CollectionMethod.STK_PUSH],
  expires_at: null,
  status: PaymentLinkStatus.ACTIVE,
  public_slug: "abc123",
  public_url: "https://infinitypay.me/pay/abc123",
  merchant_reference: null,
  success_redirect_url: null,
  failure_redirect_url: null,
  paid_at: null,
  attempt_count: 0,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-01T10:00:00Z",
  customer_email_sent: null,
};

vi.mock("@/lib/portal/api", () => ({
  listPaymentLinks: vi.fn().mockResolvedValue([link]),
  createPaymentLink: vi.fn(),
  cancelPaymentLink: vi.fn(),
}));

describe("PaymentLinksView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a Copy Link button for the most recently created link", async () => {
    const { PaymentLinksView } = await import("./payment-links-view");
    render(<PaymentLinksView />);

    await waitFor(() => expect(screen.getAllByTitle("Copy link").length).toBeGreaterThan(0));
  });

  it("does not render an Allowed Payment Channels checkbox section", async () => {
    const { PaymentLinksView } = await import("./payment-links-view");
    render(<PaymentLinksView />);

    expect(screen.queryByText("Allowed Payment Channels")).not.toBeInTheDocument();
    expect(screen.queryByText("USSD Push")).not.toBeInTheDocument();
    expect(screen.queryByText("Dynamic QR")).not.toBeInTheDocument();
  });

  it("shows the hosted-checkout explanation copy", async () => {
    const { PaymentLinksView } = await import("./payment-links-view");
    render(<PaymentLinksView />);

    expect(
      screen.getByText("Secure Selcom hosted checkout — the customer chooses their payment method on checkout."),
    ).toBeInTheDocument();
  });

  it("submits a new link without an allowed_payment_methods field", async () => {
    const { createPaymentLink } = await import("@/lib/portal/api");
    vi.mocked(createPaymentLink).mockResolvedValue({ ...link, id: "link-2" });
    const { PaymentLinksView } = await import("./payment-links-view");
    render(<PaymentLinksView />);

    fireEvent.change(screen.getByPlaceholderText("25,000"), { target: { value: "10000" } });
    fireEvent.click(screen.getByRole("button", { name: /Generate Payment Link/ }));

    await waitFor(() => expect(createPaymentLink).toHaveBeenCalled());
    expect(vi.mocked(createPaymentLink).mock.calls[0][0]).not.toHaveProperty("allowed_payment_methods");
  });
});
