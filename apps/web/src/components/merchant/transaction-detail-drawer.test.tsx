import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PaymentTracking, Transaction } from "@/lib/portal/types";

const getTransactionTracking = vi.fn();

vi.mock("@/lib/portal/api", () => ({
  getTransactionTracking: (...args: unknown[]) => getTransactionTracking(...args),
}));

const transaction: Transaction = {
  id: "txn-1",
  merchant_id: "merchant-1",
  reference: "TXN-20261122-ABCD1234",
  provider_reference: "SEL-998877",
  type: "collection",
  method: "USSD_PUSH",
  collection_id: "6f1c2b9e-0000-4000-8000-000000000001",
  disbursement_id: null,
  gross_amount: "15000.00",
  fee_amount: "0.00",
  net_amount: "15000.00",
  currency: "TZS",
  status: "successful",
  balance_before: null,
  balance_after: null,
  direction: null,
  customer_phone: null,
  created_at: "2026-11-22T08:00:00Z",
};

function tracking(overrides: Partial<PaymentTracking> = {}): PaymentTracking {
  return {
    transaction_id: "txn-1",
    identifiers: {
      payment_id: "6f1c2b9e-0000-4000-8000-000000000001",
      merchant_reference: "SUB-4471-NOV",
      transaction_reference: "TXN-20261122-ABCD1234",
      provider_reference: "SEL-998877",
    },
    payment: [
      { code: "initiated", label: "Payment initiated", state: "done", at: "2026-11-22T08:00:00Z", detail: null },
      { code: "confirmed", label: "Payment confirmed", state: "done", at: "2026-11-22T08:01:10Z", detail: null },
    ],
    webhooks: {
      applicable: true,
      configured: true,
      available: true,
      deliveries: [
        {
          event_name: "collection.success",
          state: "exhausted",
          label: "Webhook delivery exhausted",
          attempts: 5,
          max_attempts: 5,
          queued_at: "2026-11-22T08:01:10Z",
          last_attempt_at: "2026-11-22T08:11:10Z",
          delivered_at: null,
          response_status: 500,
          next_retry_at: null,
        },
      ],
    },
    service_activation: {
      status: "not_confirmed",
      label: "Service activation not confirmed",
      detail: "Activation is controlled by your billing system.",
    },
    ...overrides,
  };
}

async function renderDrawer() {
  const { TransactionDetailDrawer } = await import("./transaction-detail-drawer");
  render(<TransactionDetailDrawer transaction={transaction} onClose={() => {}} />);
  return screen.findByRole("list", { name: "Payment timeline" });
}

describe("TransactionDetailDrawer tracking", () => {
  beforeEach(() => vi.clearAllMocks());

  it("labels the shared payment id separately from the merchant's own reference and the provider's", async () => {
    getTransactionTracking.mockResolvedValue({ data: tracking(), error: null, noAccess: false });
    await renderDrawer();

    expect(screen.getByText("InfinityPay Payment ID")).toBeInTheDocument();
    expect(screen.getByText("6f1c2b9e-0000-4000-8000-000000000001")).toBeInTheDocument();
    expect(screen.getByText("Your order reference")).toBeInTheDocument();
    expect(screen.getByText("SUB-4471-NOV")).toBeInTheDocument();
    expect(screen.getByText(/collection_id in API responses and webhooks/)).toBeInTheDocument();
    expect(screen.getByText("Provider Reference")).toBeInTheDocument();
  });

  it("shows a confirmed payment, a failed delivery and unknown activation as three different things", async () => {
    getTransactionTracking.mockResolvedValue({ data: tracking(), error: null, noAccess: false });
    const timeline = await renderDrawer();

    expect(within(timeline).getByText("Payment confirmed")).toBeInTheDocument();
    expect(within(timeline).getByText("Webhook delivery exhausted")).toBeInTheDocument();
    expect(within(timeline).getByText(/your server answered HTTP 500/)).toBeInTheDocument();
    expect(within(timeline).getByText("No further automatic attempts will be made.")).toBeInTheDocument();
    expect(within(timeline).getByText("Service activation not confirmed")).toBeInTheDocument();
  });

  it("never turns a delivered webhook into confirmed activation", async () => {
    const delivered = tracking();
    delivered.webhooks.deliveries = [
      {
        ...delivered.webhooks.deliveries[0],
        state: "delivered",
        label: "Webhook delivered",
        attempts: 1,
        response_status: 200,
        delivered_at: "2026-11-22T08:01:12Z",
      },
    ];
    getTransactionTracking.mockResolvedValue({ data: delivered, error: null, noAccess: false });
    const timeline = await renderDrawer();

    expect(within(timeline).getByText("Webhook delivered")).toBeInTheDocument();
    expect(within(timeline).getByText("Service activation not confirmed")).toBeInTheDocument();
    expect(within(timeline).getByText(/not that the customer's service was activated/)).toBeInTheDocument();
    expect(within(timeline).queryByText(/activation confirmed/i)).not.toBeInTheDocument();
  });

  it("shows the next retry time when one is scheduled", async () => {
    const retrying = tracking();
    retrying.webhooks.deliveries = [
      {
        ...retrying.webhooks.deliveries[0],
        state: "retrying",
        label: "Webhook delivery retrying",
        attempts: 2,
        response_status: 503,
        next_retry_at: "2026-11-22T08:02:42Z",
      },
    ];
    getTransactionTracking.mockResolvedValue({ data: retrying, error: null, noAccess: false });
    const timeline = await renderDrawer();

    expect(within(timeline).getByText("Webhook delivery retrying")).toBeInTheDocument();
    expect(within(timeline).getByText(/Next attempt around/)).toBeInTheDocument();
  });

  it("says when there is no delivery record instead of implying one", async () => {
    const none = tracking();
    none.webhooks.deliveries = [];
    none.webhooks.configured = false;
    getTransactionTracking.mockResolvedValue({ data: none, error: null, noAccess: false });
    const timeline = await renderDrawer();

    expect(within(timeline).getByText("No webhook endpoint configured")).toBeInTheDocument();
  });

  it("offers no retry or resend action", async () => {
    getTransactionTracking.mockResolvedValue({ data: tracking(), error: null, noAccess: false });
    await renderDrawer();

    const dialog = screen.getByRole("dialog", { name: "Transaction detail" });
    expect(within(dialog).queryByRole("button", { name: /retry|resend|replay/i })).not.toBeInTheDocument();
  });

  it("is a solid panel, not the translucent card colour the table shows through", async () => {
    getTransactionTracking.mockResolvedValue({ data: tracking(), error: null, noAccess: false });
    await renderDrawer();

    const dialog = screen.getByRole("dialog", { name: "Transaction detail" });
    expect(dialog.className).toContain("app-drawer-surface");
    expect(dialog.className).not.toMatch(/bg-surface/);
  });

  it("marks a sandbox payout as sandbox and says no real money moved", async () => {
    getTransactionTracking.mockResolvedValue({
      data: tracking({ environment: "sandbox" }),
      error: null,
      noAccess: false,
    });
    await renderDrawer();

    expect(screen.getByText("Sandbox")).toBeInTheDocument();
    expect(screen.getByText(/No real money moved/)).toBeInTheDocument();
  });

  it("marks a live payout as live", async () => {
    getTransactionTracking.mockResolvedValue({ data: tracking({ environment: "live" }), error: null, noAccess: false });
    await renderDrawer();

    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.queryByText("Sandbox")).not.toBeInTheDocument();
  });

  it("claims no environment when none is recorded", async () => {
    getTransactionTracking.mockResolvedValue({ data: tracking({ environment: null }), error: null, noAccess: false });
    await renderDrawer();

    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText("Sandbox")).not.toBeInTheDocument();
  });
});
