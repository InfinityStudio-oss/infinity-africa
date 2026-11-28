import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminFraudAlertRow } from "@/lib/admin/types";

const updateRiskAlertStatusAction = vi.fn();
const addRiskAlertNoteAction = vi.fn();
const requestDocumentsForAlertAction = vi.fn();

vi.mock("@/lib/admin/live-actions", () => ({
  updateRiskAlertStatusAction: (...args: unknown[]) => updateRiskAlertStatusAction(...args),
  addRiskAlertNoteAction: (...args: unknown[]) => addRiskAlertNoteAction(...args),
  requestDocumentsForAlertAction: (...args: unknown[]) => requestDocumentsForAlertAction(...args),
}));

const alert: AdminFraudAlertRow = {
  alert_id: "alert-1",
  merchant_id: "merchant-1",
  merchant_name: "Masanja Traders",
  merchant_code: "27000006",
  transaction_id: null,
  customer_phone: "255747730270",
  rule_code: "SELF_PAYMENT_OWN_TILL",
  risk_level: "CRITICAL",
  reason: "Payer phone matches the merchant's own registered contact phone.",
  status: "OPEN",
  metadata: {},
  created_at: "2026-09-04T17:46:42Z",
  updated_at: "2026-09-04T17:46:42Z",
};

async function renderExpanded() {
  const { RiskMonitoringTable } = await import("./risk-monitoring-table");
  render(<RiskMonitoringTable rows={[alert]} />);
  fireEvent.click(screen.getByRole("button", { name: /Manage/ }));
}

describe("Super Admin RiskMonitoringTable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("submits the selected status to updateRiskAlertStatusAction and confirms on success", async () => {
    updateRiskAlertStatusAction.mockResolvedValue({ error: null, ok: true });
    await renderExpanded();

    fireEvent.change(screen.getByDisplayValue("OPEN"), { target: { value: "CLEARED" } });
    fireEvent.click(screen.getByRole("button", { name: "Update Status" }));

    await waitFor(() => expect(updateRiskAlertStatusAction).toHaveBeenCalledTimes(1));
    const [alertId, , formData] = updateRiskAlertStatusAction.mock.calls[0] as [string, unknown, FormData];
    expect(alertId).toBe("alert-1");
    expect(formData.get("status")).toBe("CLEARED");
    await waitFor(() => expect(screen.getByText(/Status set to/)).toBeInTheDocument());
  });

  it("shows the backend error when the status update fails", async () => {
    updateRiskAlertStatusAction.mockResolvedValue({ error: "This withdrawal isn't awaiting approval", ok: false });
    await renderExpanded();

    fireEvent.click(screen.getByRole("button", { name: "Update Status" }));

    await waitFor(() =>
      expect(screen.getByText("This withdrawal isn't awaiting approval")).toBeInTheDocument(),
    );
  });

  it("confirms after a note is added", async () => {
    addRiskAlertNoteAction.mockResolvedValue({ error: null, ok: true });
    await renderExpanded();

    fireEvent.change(screen.getByPlaceholderText("Add an internal note"), { target: { value: "Confirmed legit test" } });
    fireEvent.click(screen.getByRole("button", { name: "Add Note" }));

    await waitFor(() => expect(addRiskAlertNoteAction).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText("Note added")).toBeInTheDocument());
  });
});
