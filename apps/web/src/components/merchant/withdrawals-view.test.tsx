import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
 * "Request Withdrawal" button is enabled. No recipient name is entered —
 * the field no longer exists. */
async function fillFormAndCheckBalance() {
  fireEvent.change(screen.getByPlaceholderText("+255 7XX XXX XXX or account no."), {
    target: { value: "255657878545" },
  });
  fireEvent.change(screen.getByPlaceholderText("500,000"), { target: { value: "100000" } });
  fireEvent.click(screen.getByText("Check Balance"));
  await waitFor(() => expect(screen.getByText("You receive the full amount.")).toBeInTheDocument());
}

/** Request Withdrawal now opens a review step; the code is only sent once
 * the merchant confirms there. */
async function requestAndConfirmReview() {
  fireEvent.click(screen.getByText("Request Withdrawal"));
  await waitFor(() => expect(screen.getByText("Review your withdrawal details")).toBeInTheDocument());
  fireEvent.click(screen.getByText("Send Verification Code"));
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

  it("shows the withdrawal amount but never a fee or charge breakdown", async () => {
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    fireEvent.change(screen.getByPlaceholderText("+255 7XX XXX XXX or account no."), {
      target: { value: "+255700000000" },
    });
    fireEvent.change(screen.getByPlaceholderText("500,000"), { target: { value: "100000" } });
    fireEvent.click(screen.getByText("Check Balance"));

    await waitFor(() => expect(calculateWithdrawalCharges).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("You receive the full amount.")).toBeInTheDocument());

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
    await requestAndConfirmReview();

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
    await requestAndConfirmReview();

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
    await requestAndConfirmReview();

    await waitFor(() => expect(screen.getByText("Enter the 6-digit code")).toBeInTheDocument());
    // The masked address tells the merchant which inbox to open without
    // disclosing an address they might not already know.
    expect(screen.getByText("o***r@shop.co.tz")).toBeInTheDocument();
    expect(createDisbursement).toHaveBeenCalledWith(
      expect.objectContaining({ amount: "100000", method: "SELCOM_PESA" }),
    );
    // The recipient name is gone from the payload entirely — not sent as
    // an empty string, which would still be a claim about the recipient.
    expect(createDisbursement.mock.calls[0][0]).not.toHaveProperty("destination_name");
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
    await requestAndConfirmReview();
    await waitFor(() => expect(screen.getByText("Enter the 6-digit code")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("6-digit verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByText("Verify and submit"));

    await waitFor(() =>
      expect(
        screen.getByText(
          "Your withdrawal request has been submitted for processing. We'll notify you when processing is complete.",
        ),
      ).toBeInTheDocument(),
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
    await requestAndConfirmReview();
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
    await requestAndConfirmReview();
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

  // --- the recipient name field is gone -----------------------------------

  it("does not ask the merchant to type a recipient name", async () => {
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await waitFor(() => expect(screen.getByText("Request a Withdrawal")).toBeInTheDocument());
    expect(screen.queryByText("Destination Name")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("e.g. Selcom Pesa Merchant Wallet")).not.toBeInTheDocument();
  });

  it("can reach the review step with no name entered anywhere", async () => {
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    fireEvent.click(screen.getByText("Request Withdrawal"));

    await waitFor(() => expect(screen.getByText("Review your withdrawal details")).toBeInTheDocument());
  });

  // --- the review step ------------------------------------------------------

  it("reviews the destination, number and amount before sending any code", async () => {
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    fireEvent.click(screen.getByText("Request Withdrawal"));

    const dialog = await screen.findByRole("dialog", { name: "Review withdrawal" });
    expect(within(dialog).getByText("Selcom Pesa")).toBeInTheDocument();
    expect(within(dialog).getByText("255657878545")).toBeInTheDocument();
    expect(within(dialog).getByText("TZS 100,000.00")).toBeInTheDocument();
    // Still nothing sent — the code goes out only on confirm.
    expect(createDisbursement).not.toHaveBeenCalled();
  });

  it("says the name is unavailable rather than echoing something unverified", async () => {
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    fireEvent.click(screen.getByText("Request Withdrawal"));

    const dialog = await screen.findByRole("dialog", { name: "Review withdrawal" });
    expect(within(dialog).getByText("Name not available")).toBeInTheDocument();
  });

  it("shows no charges and no approval wording on the review step", async () => {
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    fireEvent.click(screen.getByText("Request Withdrawal"));

    const dialog = await screen.findByRole("dialog", { name: "Review withdrawal" });
    const text = dialog.textContent ?? "";
    expect(text).not.toMatch(/approval/i);
    expect(text).not.toMatch(/charge/i);
    expect(text).not.toMatch(/fee/i);
  });

  it("goes back from review without sending a code", async () => {
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    fireEvent.click(screen.getByText("Request Withdrawal"));
    await screen.findByRole("dialog", { name: "Review withdrawal" });

    fireEvent.click(screen.getByText("Back"));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Review withdrawal" })).not.toBeInTheDocument(),
    );
    expect(createDisbursement).not.toHaveBeenCalled();
    // The typed details survive, so nothing has to be re-entered.
    expect(screen.getByDisplayValue("255657878545")).toBeInTheDocument();
  });

  it("only sends the verification code once the review is confirmed", async () => {
    createDisbursement.mockResolvedValueOnce(CHALLENGE);
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    fireEvent.click(screen.getByText("Request Withdrawal"));
    await screen.findByRole("dialog", { name: "Review withdrawal" });
    expect(createDisbursement).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Send Verification Code"));

    await waitFor(() => expect(createDisbursement).toHaveBeenCalledTimes(1));
  });

  // --- merchant-facing wording ---------------------------------------------

  it("never shows approval wording anywhere on the withdrawals page", async () => {
    createDisbursement.mockResolvedValueOnce(CHALLENGE);
    verifyWithdrawalOtp.mockResolvedValueOnce({
      id: "d1",
      method: "SELCOM_PESA",
      amount: "100000.00",
      currency: "TZS",
      destination_name: "255657878545",
      status: "PENDING_ADMIN_APPROVAL",
      auto_approved: false,
      initiated_at: new Date().toISOString(),
    });
    const { WithdrawalsView } = await import("./withdrawals-view");
    const { container } = render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    await requestAndConfirmReview();
    await waitFor(() => expect(screen.getByText("Enter the 6-digit code")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("6-digit verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByText("Verify and submit"));

    await waitFor(() => expect(screen.getByText(/submitted for processing/)).toBeInTheDocument());
    expect(container.textContent ?? "").not.toMatch(/approval/i);
  });

  it("reports a submitted withdrawal the same way whether or not it was automated", async () => {
    // The merchant-visible difference is only how long it takes, and the
    // history row carries the real status. Two different messages here
    // would leak an internal distinction they cannot act on.
    createDisbursement.mockResolvedValueOnce(CHALLENGE);
    verifyWithdrawalOtp.mockResolvedValueOnce({
      id: "d2",
      method: "SELCOM_PESA",
      amount: "100000.00",
      currency: "TZS",
      destination_name: "255657878545",
      status: "PROCESSING",
      auto_approved: true,
      initiated_at: new Date().toISOString(),
    });
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    await requestAndConfirmReview();
    await waitFor(() => expect(screen.getByText("Enter the 6-digit code")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("6-digit verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByText("Verify and submit"));

    await waitFor(() =>
      expect(
        screen.getByText(
          "Your withdrawal request has been submitted for processing. We'll notify you when processing is complete.",
        ),
      ).toBeInTheDocument(),
    );
  });

  // --- bank name and network are implied by the provider -------------------

  it("does not ask for a bank name on a bank withdrawal", async () => {
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await waitFor(() => expect(screen.getByText("Request a Withdrawal")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Withdraw to Bank Account"));

    expect(screen.queryByText("Bank Name")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("e.g. CRDB Bank")).not.toBeInTheDocument();
  });

  it("does not ask for a network on a mobile money withdrawal", async () => {
    // This field was being filled in with a person's name, because the
    // recipient-name box had just been removed from above it.
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await waitFor(() => expect(screen.getByText("Request a Withdrawal")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Withdraw to Mobile Money"));

    expect(screen.queryByText("Network (optional)")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Detected from destination provider")).not.toBeInTheDocument();
  });

  it("sends neither a bank name nor a network", async () => {
    createDisbursement.mockResolvedValueOnce(CHALLENGE);
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await fillFormAndCheckBalance();
    await requestAndConfirmReview();

    await waitFor(() => expect(createDisbursement).toHaveBeenCalledTimes(1));
    const sent = createDisbursement.mock.calls[0][0];
    expect(sent).not.toHaveProperty("bank_name");
    expect(sent).not.toHaveProperty("network");
  });

  it("submits a bank withdrawal with only a provider, account number and amount", async () => {
    createDisbursement.mockResolvedValueOnce(CHALLENGE);
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await waitFor(() => expect(screen.getByText("Request a Withdrawal")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Withdraw to Bank Account"));
    fireEvent.change(screen.getByPlaceholderText("+255 7XX XXX XXX or account no."), {
      target: { value: "0123456789" },
    });
    fireEvent.change(screen.getByPlaceholderText("500,000"), { target: { value: "100000" } });
    fireEvent.click(screen.getByText("Check Balance"));
    await waitFor(() => expect(screen.getByText("You receive the full amount.")).toBeInTheDocument());

    await requestAndConfirmReview();

    await waitFor(() => expect(createDisbursement).toHaveBeenCalledTimes(1));
    expect(createDisbursement.mock.calls[0][0]).toEqual(
      expect.objectContaining({ method: "BANK_ACCOUNT", destination_identifier: "0123456789" }),
    );
  });

  it("names the bank on the review step from the provider that was picked", async () => {
    const { WithdrawalsView } = await import("./withdrawals-view");
    render(<WithdrawalsView />);

    await waitFor(() => expect(screen.getByText("Request a Withdrawal")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Withdraw to Bank Account"));
    fireEvent.change(screen.getByPlaceholderText("+255 7XX XXX XXX or account no."), {
      target: { value: "0123456789" },
    });
    fireEvent.change(screen.getByPlaceholderText("500,000"), { target: { value: "100000" } });
    fireEvent.click(screen.getByText("Check Balance"));
    await waitFor(() => expect(screen.getByText("You receive the full amount.")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Request Withdrawal"));

    const dialog = await screen.findByRole("dialog", { name: "Review withdrawal" });
    // The bank is still stated, just not retyped — it comes from the
    // destination provider the merchant already chose.
    expect(within(dialog).getByText("CRDB Bank")).toBeInTheDocument();
    expect(within(dialog).getByText("Account number")).toBeInTheDocument();
  });
});
