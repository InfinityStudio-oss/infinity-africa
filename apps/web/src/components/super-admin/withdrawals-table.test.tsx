import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminWithdrawalRow } from "@/lib/admin/types";

const approveWithdrawalAction = vi.fn();
const rejectWithdrawalAction = vi.fn();
const requestInfoWithdrawalAction = vi.fn();
const refreshWithdrawalStatusAction = vi.fn();
const reconcilePendingWithdrawalsAction = vi.fn();
const retryWithdrawalPayoutAction = vi.fn();

vi.mock("@/lib/admin/live-actions", () => ({
  approveWithdrawalAction: (...args: unknown[]) => approveWithdrawalAction(...args),
  rejectWithdrawalAction: (...args: unknown[]) => rejectWithdrawalAction(...args),
  requestInfoWithdrawalAction: (...args: unknown[]) => requestInfoWithdrawalAction(...args),
  refreshWithdrawalStatusAction: (...args: unknown[]) => refreshWithdrawalStatusAction(...args),
  reconcilePendingWithdrawalsAction: (...args: unknown[]) => reconcilePendingWithdrawalsAction(...args),
  retryWithdrawalPayoutAction: (...args: unknown[]) => retryWithdrawalPayoutAction(...args),
}));

const pendingRow: AdminWithdrawalRow = {
  withdrawal_id: "wd-1",
  merchant_id: "merchant-1",
  merchant_name: "Juma Traders Ltd",
  merchant_code: "27048391",
  method: "MOBILE_MONEY",
  amount: "100000.00",
  currency: "TZS",
  destination: "Jane Doe",
  destination_code: "MPESA",
  destination_identifier: "+255700000000",
  status: "PENDING_ADMIN_APPROVAL",
  requires_approval: true,
  auto_approved: false,
  auto_decision_reason: null,
  provider_reference: null,
  total_charges: "1800.00",
  total_reserved_amount: "101800.00",
  recipient_net_amount: "100000.00",
  available_balance: "500000.00",
  pricing_rule_id: null,
  rejection_reason: null,
  admin_status_reason: null,
  created_at: "2026-08-13T09:12:00Z",
  request_email_status: null,
  success_email_status: null,
};

describe("WithdrawalsTable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows Approve, Reject, and Request Info in the approval queue", async () => {
    const { WithdrawalsTable } = await import("./withdrawals-table");
    render(<WithdrawalsTable rows={[pendingRow]} queue={[pendingRow]} />);

    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Request Info" })).toBeInTheDocument();
  });

  it("confirms after a successful approval", async () => {
    approveWithdrawalAction.mockResolvedValue({ error: null, ok: true, message: "Approved — sent to the provider." });
    const { WithdrawalsTable } = await import("./withdrawals-table");
    render(<WithdrawalsTable rows={[pendingRow]} queue={[pendingRow]} />);

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(approveWithdrawalAction).toHaveBeenCalledTimes(1));
    expect(approveWithdrawalAction.mock.calls[0][0]).toBe("wd-1");
    await waitFor(() =>
      expect(screen.getByText("Approved — sent to the provider.")).toBeInTheDocument(),
    );
  });

  it("surfaces a failed approval's error instead of failing silently", async () => {
    approveWithdrawalAction.mockResolvedValue({
      error: "This withdrawal isn't awaiting approval",
      ok: false,
      message: null,
    });
    const { WithdrawalsTable } = await import("./withdrawals-table");
    render(<WithdrawalsTable rows={[pendingRow]} queue={[pendingRow]} />);

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(screen.getByText("This withdrawal isn't awaiting approval")).toBeInTheDocument(),
    );
  });

  it("shows the reconcile summary returned by the action", async () => {
    reconcilePendingWithdrawalsAction.mockResolvedValue({
      error: null,
      ok: true,
      message: "Checked 3 · resolved 1 · still pending 2.",
    });
    const { WithdrawalsTable } = await import("./withdrawals-table");
    render(<WithdrawalsTable rows={[pendingRow]} queue={[pendingRow]} />);

    fireEvent.click(screen.getByRole("button", { name: "Reconcile Pending" }));

    await waitFor(() => expect(reconcilePendingWithdrawalsAction).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByText("Checked 3 · resolved 1 · still pending 2.")).toBeInTheDocument(),
    );
  });

  it("shows an Auto-Processing badge and the decision reason for an auto-approved withdrawal", async () => {
    const autoRow: AdminWithdrawalRow = {
      ...pendingRow,
      withdrawal_id: "wd-2",
      status: "PROCESSING",
      auto_approved: true,
      auto_decision_reason: "Eligible: verified merchant, no open high-risk alerts, within auto-withdrawal limits.",
    };
    const { WithdrawalsTable } = await import("./withdrawals-table");
    render(<WithdrawalsTable rows={[autoRow]} queue={[]} />);

    expect(screen.getByText("Auto-Processing")).toBeInTheDocument();
    expect(
      screen.getByText("Eligible: verified merchant, no open high-risk alerts, within auto-withdrawal limits."),
    ).toBeInTheDocument();
  });

  it("shows plain Processing (no auto label) for a manually-approved withdrawal", async () => {
    const manualRow: AdminWithdrawalRow = {
      ...pendingRow,
      withdrawal_id: "wd-3",
      status: "PROCESSING",
      auto_approved: false,
    };
    const { WithdrawalsTable } = await import("./withdrawals-table");
    render(<WithdrawalsTable rows={[manualRow]} queue={[]} />);

    // Scoped to the table: "Processing" is also one of the status-filter
    // button labels above it, so an unscoped getByText matches both.
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Processing")).toBeInTheDocument();
    expect(table.queryByText("Auto-Processing")).not.toBeInTheDocument();
  });
});

describe("retrying a payout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    retryWithdrawalPayoutAction.mockResolvedValue({ error: null, ok: true, message: "Retried." });
  });

  function rowWithStatus(status: AdminWithdrawalRow["status"]): AdminWithdrawalRow {
    return { ...pendingRow, withdrawal_id: "wd-retry", status, requires_approval: false };
  }

  it("offers a retry on a failed withdrawal, which previously had no way forward", async () => {
    const { WithdrawalsTable } = await import("./withdrawals-table");
    render(<WithdrawalsTable rows={[rowWithStatus("FAILED")]} queue={[]} />);
    expect(screen.getByRole("button", { name: "Retry Payout" })).toBeInTheDocument();
  });

  it.each(["BLOCKED_IP_WHITELIST", "NEEDS_ADMIN_ATTENTION"] as const)(
    "offers a retry on %s, where the merchant's funds are still held",
    async (status) => {
      const { WithdrawalsTable } = await import("./withdrawals-table");
      render(<WithdrawalsTable rows={[rowWithStatus(status)]} queue={[]} />);
      expect(screen.getByRole("button", { name: "Retry Payout" })).toBeInTheDocument();
    },
  );

  it.each(["SUCCESS", "PROCESSING", "REJECTED", "PENDING_ADMIN_APPROVAL"] as const)(
    "offers no retry on %s",
    async (status) => {
      const { WithdrawalsTable } = await import("./withdrawals-table");
      render(<WithdrawalsTable rows={[rowWithStatus(status)]} queue={[]} />);
      expect(screen.queryByRole("button", { name: "Retry Payout" })).not.toBeInTheDocument();
    },
  );

  it("does not fire the action on the first click — a payout needs confirming", async () => {
    const { WithdrawalsTable } = await import("./withdrawals-table");
    render(<WithdrawalsTable rows={[rowWithStatus("FAILED")]} queue={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry Payout" }));
    expect(retryWithdrawalPayoutAction).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Confirm Retry" })).toBeInTheDocument();
  });

  it("says the money comes out of the wallet again when the withdrawal was reversed", async () => {
    const { WithdrawalsTable } = await import("./withdrawals-table");
    render(<WithdrawalsTable rows={[rowWithStatus("FAILED")]} queue={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry Payout" }));
    expect(screen.getByText(/taking the amount from the merchant's wallet/i)).toBeInTheDocument();
  });

  it("says the funds are already reserved when they were never released", async () => {
    const { WithdrawalsTable } = await import("./withdrawals-table");
    render(<WithdrawalsTable rows={[rowWithStatus("BLOCKED_IP_WHITELIST")]} queue={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry Payout" }));
    expect(screen.getByText(/already reserved for this withdrawal/i)).toBeInTheDocument();
  });

  it("can be backed out of without retrying", async () => {
    const { WithdrawalsTable } = await import("./withdrawals-table");
    render(<WithdrawalsTable rows={[rowWithStatus("FAILED")]} queue={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry Payout" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Confirm Retry" })).not.toBeInTheDocument();
    expect(retryWithdrawalPayoutAction).not.toHaveBeenCalled();
  });

  it("retries the withdrawal that was confirmed, once", async () => {
    const { WithdrawalsTable } = await import("./withdrawals-table");
    render(<WithdrawalsTable rows={[rowWithStatus("FAILED")]} queue={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry Payout" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm Retry" }));
    await waitFor(() => expect(retryWithdrawalPayoutAction).toHaveBeenCalledTimes(1));
    expect(retryWithdrawalPayoutAction.mock.calls[0][0]).toBe("wd-retry");
  });
});
