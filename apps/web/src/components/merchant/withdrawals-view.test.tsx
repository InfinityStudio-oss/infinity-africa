import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FeeBreakdown } from "@/lib/portal/types";

// MVP policy (2026-08-31): withdrawals never charge a merchant fee — the
// backend always returns a zero breakdown now (see
// apps/api/app/services/withdrawals/fee_calculator.py). This mock mirrors
// that real shape rather than a hypothetical fee-bearing one.
const breakdown: FeeBreakdown = {
  withdrawal_amount: "100000.00",
  processor_charge: "0",
  infinity_fee: "0",
  percentage_fee: "0",
  flat_fee: "0",
  total_charges: "0",
  total_reserved_amount: "100000.00",
  recipient_net_amount: "100000.00",
  channel: "SELCOM_PESA",
  destination_code: "SELCOM",
  pricing_rule_id: null,
  pricing_rule_label: null,
  processor_fee_pass_through: false,
  is_platform_fallback: false,
};

const calculateWithdrawalCharges = vi.fn().mockResolvedValue(breakdown);
const createDisbursement = vi.fn();

vi.mock("@/lib/portal/api", () => ({
  listDisbursements: vi.fn().mockResolvedValue([]),
  getAvailableBalance: vi.fn().mockResolvedValue("500000.00"),
  calculateWithdrawalCharges,
  createDisbursement,
  InsufficientBalanceError: class InsufficientBalanceError extends Error {},
}));

/** Fill the form and get past the mandatory "Check Balance" gate so the
 * "Request Withdrawal" button is enabled. */
async function fillFormAndCheckBalance() {
  fireEvent.change(screen.getByPlaceholderText("+255 7XX XXX XXX or account no."), {
    target: { value: "255657878545" },
  });
  fireEvent.change(screen.getByPlaceholderText("e.g. Selcom Pesa Merchant Wallet"), {
    target: { value: "Masanja" },
  });
  fireEvent.change(screen.getByPlaceholderText("500,000"), { target: { value: "100000" } });
  fireEvent.click(screen.getByText("Check Balance"));
  await waitFor(() =>
    expect(screen.getByText("No merchant withdrawal fee — you receive the full amount.")).toBeInTheDocument(),
  );
}

describe("WithdrawalsView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a Check Balance button", async () => {
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await waitFor(() => expect(screen.getByText("Check Balance")).toBeInTheDocument());
  });

  it("shows the withdrawal amount and a no-fee notice, never a fee/charge breakdown", async () => {
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    fireEvent.change(screen.getByPlaceholderText("+255 7XX XXX XXX or account no."), {
      target: { value: "+255700000000" },
    });
    fireEvent.change(screen.getByPlaceholderText("500,000"), { target: { value: "100000" } });
    fireEvent.click(screen.getByText("Check Balance"));

    await waitFor(() => expect(calculateWithdrawalCharges).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText("No merchant withdrawal fee — you receive the full amount.")).toBeInTheDocument(),
    );

    // The old fee-breakdown rows must be gone entirely — this is the
    // point of the MVP pricing change, not just an added message.
    expect(screen.queryByText("InfinityPay Fee")).not.toBeInTheDocument();
    expect(screen.queryByText("Processor Charge")).not.toBeInTheDocument();
    expect(screen.queryByText("Total Charges")).not.toBeInTheDocument();
    expect(screen.queryByText("Total to Be Deducted")).not.toBeInTheDocument();
    expect(screen.queryByText("Recipient Receives")).not.toBeInTheDocument();
    expect(screen.queryByText(/pricing rule applied/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/platform fallback/i)).not.toBeInTheDocument();
  });

  it("shows the backend's safe message when a withdrawal is blocked by a fraud-review hold", async () => {
    const restricted = Object.assign(
      new Error("Withdrawals are temporarily restricted while a high-risk transaction on this account is under review."),
      { code: "withdrawal_restricted" },
    );
    createDisbursement.mockRejectedValueOnce(restricted);
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    fireEvent.click(screen.getByText("Request Withdrawal"));

    await waitFor(() =>
      expect(
        screen.getByText(
          "Withdrawals are temporarily restricted while a high-risk transaction on this account is under review.",
        ),
      ).toBeInTheDocument(),
    );
    // The old blanket message must never appear for a structured error.
    expect(screen.queryByText("Something went wrong requesting this withdrawal.")).not.toBeInTheDocument();
  });

  it("falls back to a generic message for an unexpected (unstructured) failure", async () => {
    createDisbursement.mockRejectedValueOnce(new Error("kaboom: postgres exception at line 42"));
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    fireEvent.click(screen.getByText("Request Withdrawal"));

    await waitFor(() =>
      expect(
        screen.getByText(/Something went wrong requesting this withdrawal\. Please try again or contact support\./),
      ).toBeInTheDocument(),
    );
    // Never leak the raw error text.
    expect(screen.queryByText(/postgres exception/)).not.toBeInTheDocument();
  });

  it("shows the review-pending success message (not auto-processed) and does not surface any payout detail", async () => {
    createDisbursement.mockResolvedValueOnce({
      id: "d1",
      method: "SELCOM_PESA",
      amount: "100000.00",
      currency: "TZS",
      destination_name: "Masanja",
      status: "PENDING_ADMIN_APPROVAL",
      auto_approved: false,
      initiated_at: new Date().toISOString(),
    });
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    fireEvent.click(screen.getByText("Request Withdrawal"));

    await waitFor(() => expect(screen.getByText("Withdrawal submitted for review.")).toBeInTheDocument());
    expect(createDisbursement).toHaveBeenCalledWith(
      expect.objectContaining({ amount: "100000", method: "SELCOM_PESA", destination_name: "Masanja" }),
    );
  });

  it("shows the processing success message when the withdrawal was auto-approved", async () => {
    createDisbursement.mockResolvedValueOnce({
      id: "d1",
      method: "SELCOM_PESA",
      amount: "100000.00",
      currency: "TZS",
      destination_name: "Masanja",
      status: "PROCESSING",
      auto_approved: true,
      initiated_at: new Date().toISOString(),
    });
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    fireEvent.click(screen.getByText("Request Withdrawal"));

    await waitFor(() => expect(screen.getByText("Withdrawal submitted for processing.")).toBeInTheDocument());
  });

  it("never mentions CEO or email approval in withdrawal-facing text", async () => {
    const { WithdrawalsView } = await import("./withdrawals-view");
    const { container } = render(<WithdrawalsView />);

    await waitFor(() => expect(screen.getByText("Withdrawals")).toBeInTheDocument());
    expect(container.textContent).not.toMatch(/CEO/i);
    expect(container.textContent).not.toMatch(/email approval/i);
  });

  it("never shows the literal word 'Disbursement' in merchant-facing text", async () => {
    const { WithdrawalsView } = await import("./withdrawals-view");
    const { container } = render(<WithdrawalsView />);

    await waitFor(() => expect(screen.getByText("Withdrawals")).toBeInTheDocument());
    expect(container.textContent).not.toMatch(/Disbursement/i);
  });
});
