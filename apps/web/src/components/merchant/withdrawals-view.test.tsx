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

const verifyWithdrawalOtp = vi.fn();
const resendWithdrawalOtp = vi.fn();

vi.mock("@/lib/portal/api", () => ({
  listDisbursements: vi.fn().mockResolvedValue([]),
  getAvailableBalance: vi.fn().mockResolvedValue("500000.00"),
  calculateWithdrawalCharges,
  createDisbursement,
  verifyWithdrawalOtp: (...args: unknown[]) => verifyWithdrawalOtp(...args),
  resendWithdrawalOtp: (...args: unknown[]) => resendWithdrawalOtp(...args),
  InsufficientBalanceError: class InsufficientBalanceError extends Error {},
}));

/** POST /withdrawals returns an OTP challenge now, not a withdrawal. */
const CHALLENGE = {
  otp_required: true,
  challenge_id: "c1",
  masked_email: "o***r@shop.co.tz",
  expires_at: new Date(Date.now() + 600_000).toISOString(),
  resend_cooldown_seconds: 60,
  max_attempts: 5,
};

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

  it("opens the OTP step instead of submitting the withdrawal outright", async () => {
    createDisbursement.mockResolvedValueOnce(CHALLENGE);
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    fireEvent.click(screen.getByText("Request Withdrawal"));

    await waitFor(() => expect(screen.getByText("Enter the 6-digit code")).toBeInTheDocument());
    // The masked address tells the merchant which inbox to open without
    // disclosing an address they might not already know.
    expect(screen.getByText("o***r@shop.co.tz")).toBeInTheDocument();
    expect(createDisbursement).toHaveBeenCalledWith(
      expect.objectContaining({ amount: "100000", method: "SELCOM_PESA", destination_name: "Masanja" }),
    );
    // Nothing is submitted yet.
    expect(verifyWithdrawalOtp).not.toHaveBeenCalled();
  });

  it("submits the withdrawal once the code verifies", async () => {
    createDisbursement.mockResolvedValueOnce(CHALLENGE);
    verifyWithdrawalOtp.mockResolvedValueOnce({
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
    await waitFor(() => expect(screen.getByText("Enter the 6-digit code")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("6-digit verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByText("Verify and submit"));

    await waitFor(() =>
      expect(screen.getByText("Withdrawal request submitted. It is pending approval.")).toBeInTheDocument(),
    );
    expect(verifyWithdrawalOtp).toHaveBeenCalledWith("c1", "123456");
  });

  it("keeps the OTP step open and shows the backend's message when the code is wrong", async () => {
    createDisbursement.mockResolvedValueOnce(CHALLENGE);
    verifyWithdrawalOtp.mockRejectedValueOnce(
      new Error("That code isn't valid. Request a new one and try again."),
    );
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    fireEvent.click(screen.getByText("Request Withdrawal"));
    await waitFor(() => expect(screen.getByText("Enter the 6-digit code")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("6-digit verification code"), { target: { value: "000000" } });
    fireEvent.click(screen.getByText("Verify and submit"));

    await waitFor(() =>
      expect(screen.getByText("That code isn't valid. Request a new one and try again.")).toBeInTheDocument(),
    );
    // Still on the OTP step, so the merchant can retry.
    expect(screen.getByText("Enter the 6-digit code")).toBeInTheDocument();
  });

  it("disables Resend until the cooldown has elapsed", async () => {
    createDisbursement.mockResolvedValueOnce(CHALLENGE);
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    fireEvent.click(screen.getByText("Request Withdrawal"));
    await waitFor(() => expect(screen.getByText("Enter the 6-digit code")).toBeInTheDocument());

    const resend = screen.getByText(/Resend code in \d+s/);
    expect(resend).toBeDisabled();
    fireEvent.click(resend);
    expect(resendWithdrawalOtp).not.toHaveBeenCalled();
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
