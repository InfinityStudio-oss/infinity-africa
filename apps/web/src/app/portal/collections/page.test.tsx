import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CollectionMethod, PaymentLinkStatus } from "@infinity/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Collection, PaymentLink } from "@/lib/portal/types";

const listCollections = vi.fn();
const createCollectionRequest = vi.fn();
const refreshCollectionStatus = vi.fn();

vi.mock("@/lib/portal/api", () => ({
  listCollections: (...args: unknown[]) => listCollections(...args),
  createCollectionRequest: (...args: unknown[]) => createCollectionRequest(...args),
  refreshCollectionStatus: (...args: unknown[]) => refreshCollectionStatus(...args),
}));

function paymentLink(overrides: Partial<PaymentLink>): PaymentLink {
  return {
    id: "link-1",
    merchant_id: "merchant-1",
    customer_id: null,
    amount: "5000",
    currency: "TZS",
    customer_name: null,
    customer_phone: null,
    customer_email: null,
    description: null,
    allowed_payment_methods: [CollectionMethod.STK_PUSH, CollectionMethod.SELCOM_PESA_PUSH, CollectionMethod.DYNAMIC_QR],
    expires_at: null,
    status: PaymentLinkStatus.ACTIVE,
    public_slug: "abc123",
    public_url: "https://pay.infinitypay.me/pay/abc123",
    merchant_reference: null,
    success_redirect_url: null,
    failure_redirect_url: null,
    paid_at: null,
    attempt_count: 0,
    created_at: "2026-08-24T10:00:00Z",
    updated_at: "2026-08-24T10:00:00Z",
    customer_email_sent: null,
    ...overrides,
  };
}

function collection(overrides: Partial<Collection>): Collection {
  return {
    id: "col-1",
    merchant_id: "merchant-1",
    customer_id: null,
    payment_link_id: null,
    invoice_id: null,
    merchant_reference: null,
    method: CollectionMethod.STK_PUSH,
    amount: "1000.00",
    currency: "TZS",
    customer_phone: "255762474101",
    status: "processing",
    provider: "selcom",
    provider_reference: "S123",
    transaction_reference: null,
    message: null,
    expires_at: null,
    initiated_at: "2026-08-22T21:20:00Z",
    completed_at: null,
    created_at: "2026-08-22T21:20:00Z",
    updated_at: "2026-08-22T21:20:00Z",
    failure_reason: null,
    checkout_order_id: "order-1",
    provider_transid: "TXN-1",
    provider_resultcode: null,
    provider_result: null,
    provider_payment_status: null,
    channel: null,
    webhook_delivery_status: null,
    webhook_response_code: null,
    webhook_attempts: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  listCollections.mockResolvedValue([]);
});

describe("Merchant portal CollectionsPage — Request Collection form", () => {
  it("does not render a channel/method selector", async () => {
    const { default: CollectionsPage } = await import("./page");
    render(<CollectionsPage />);

    expect(screen.queryByLabelText("Channel")).not.toBeInTheDocument();
    expect(screen.queryByText("USSD Push")).not.toBeInTheDocument();
    expect(screen.queryByText("Allowed Payment Channels")).not.toBeInTheDocument();
  });

  it("does not require a phone number to submit — the customer picks a method on their own page", async () => {
    const { default: CollectionsPage } = await import("./page");
    render(<CollectionsPage />);

    expect(screen.getByLabelText(/Phone Number/)).not.toBeRequired();
  });

  it("submits customer details to createCollectionRequest without a method, then shows the shareable payment link", async () => {
    createCollectionRequest.mockResolvedValue(paymentLink({ public_url: "https://pay.infinitypay.me/pay/xyz789" }));
    const { default: CollectionsPage } = await import("./page");
    render(<CollectionsPage />);

    fireEvent.change(screen.getByLabelText(/Customer Name/), { target: { value: "Grace" } });
    fireEvent.change(screen.getByLabelText(/Phone Number/), { target: { value: "255747730270" } });
    fireEvent.change(screen.getByLabelText("Amount in TZS"), { target: { value: "5000" } });
    fireEvent.click(screen.getByRole("button", { name: /Request Collection/ }));

    await waitFor(() =>
      expect(createCollectionRequest).toHaveBeenCalledWith(
        expect.objectContaining({ customer_name: "Grace", customer_phone: "255747730270", amount: "5000" }),
      ),
    );
    expect(createCollectionRequest.mock.calls[0][0]).not.toHaveProperty("method");

    expect(await screen.findByText("Payment page ready")).toBeInTheDocument();
    expect(screen.getByDisplayValue("https://pay.infinitypay.me/pay/xyz789")).toBeInTheDocument();
  });
});

describe("Merchant portal CollectionsPage — refresh status", () => {
  it("shows Refresh status only for a processing collection", async () => {
    listCollections.mockResolvedValue([collection({ id: "col-1", status: "processing" })]);
    const { default: CollectionsPage } = await import("./page");
    render(<CollectionsPage />);

    expect(await screen.findByRole("button", { name: "Refresh status" })).toBeInTheDocument();
  });

  it("does not show Refresh status for a successful collection", async () => {
    listCollections.mockResolvedValue([collection({ id: "col-2", status: "successful" })]);
    const { default: CollectionsPage } = await import("./page");
    render(<CollectionsPage />);

    await waitFor(() => expect(listCollections).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Refresh status" })).not.toBeInTheDocument();
  });

  it("calls refreshCollectionStatus with this collection's id and reflects the completed result", async () => {
    listCollections.mockResolvedValue([collection({ id: "col-3", status: "processing" })]);
    refreshCollectionStatus.mockResolvedValue(collection({ id: "col-3", status: "successful" }));
    const { default: CollectionsPage } = await import("./page");
    render(<CollectionsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Refresh status" }));

    await waitFor(() => expect(refreshCollectionStatus).toHaveBeenCalledWith("col-3"));
    expect(await screen.findByText("Payment completed")).toBeInTheDocument();
  });

  it("shows the failure reason for a failed collection", async () => {
    listCollections.mockResolvedValue([
      collection({ id: "col-4", status: "failed", failure_reason: "Customer cancelled the prompt" }),
    ]);
    const { default: CollectionsPage } = await import("./page");
    render(<CollectionsPage />);

    expect(await screen.findByText("Customer cancelled the prompt")).toBeInTheDocument();
  });

  // A payment can be entirely successful here while the merchant's own
  // endpoint never received the notification, so their system shows
  // nothing and the customer is never activated. That used to be visible
  // only to us; on 2026-10-23 it cost one partner nine customers in a day.
  it("warns when a payment succeeded but the merchant's own system never received it", async () => {
    listCollections.mockResolvedValue([
      collection({
        id: "col-5",
        status: "successful",
        webhook_delivery_status: "failed",
        webhook_response_code: 500,
        webhook_attempts: 5,
      }),
    ]);
    const { default: CollectionsPage } = await import("./page");
    render(<CollectionsPage />);

    expect(
      await screen.findByText("Your system did not receive this (HTTP 500 after 5 tries)."),
    ).toBeInTheDocument();
  });

  it("still shows the payment itself as successful when their endpoint failed", async () => {
    // The guarantee: a merchant's broken endpoint must never make a
    // payment we completed look like it did not happen. The money moved.
    listCollections.mockResolvedValue([
      collection({
        id: "col-6",
        status: "successful",
        webhook_delivery_status: "failed",
        webhook_response_code: 500,
      }),
    ]);
    const { default: CollectionsPage } = await import("./page");
    render(<CollectionsPage />);

    expect(await screen.findByText("Success")).toBeInTheDocument();
  });

  it("says it is still retrying while delivery has not given up", async () => {
    listCollections.mockResolvedValue([
      collection({
        id: "col-7",
        status: "successful",
        webhook_delivery_status: "retrying",
        webhook_response_code: 302,
      }),
    ]);
    const { default: CollectionsPage } = await import("./page");
    render(<CollectionsPage />);

    expect(
      await screen.findByText("Your system has not accepted this yet (HTTP 302) — still retrying."),
    ).toBeInTheDocument();
  });

  it("says nothing when the notification was delivered", async () => {
    // Most merchants have no endpoint at all. They must not grow a new
    // column of warnings about something that worked.
    listCollections.mockResolvedValue([
      collection({ id: "col-8", status: "successful", webhook_delivery_status: "delivered", webhook_response_code: 200 }),
    ]);
    const { default: CollectionsPage } = await import("./page");
    render(<CollectionsPage />);

    await screen.findByText("Success");
    expect(screen.queryByText(/did not receive this/)).not.toBeInTheDocument();
    expect(screen.queryByText(/still retrying/)).not.toBeInTheDocument();
  });

  it("says nothing when the merchant has no webhook configured", async () => {
    listCollections.mockResolvedValue([collection({ id: "col-9", status: "successful" })]);
    const { default: CollectionsPage } = await import("./page");
    render(<CollectionsPage />);

    await screen.findByText("Success");
    expect(screen.queryByText(/did not receive this/)).not.toBeInTheDocument();
  });
});
