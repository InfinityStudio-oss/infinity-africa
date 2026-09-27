import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GeneratedReport } from "@/lib/portal/types";

const generateReport = vi.fn();

vi.mock("@/lib/portal/api", () => ({
  generateReport: (...args: unknown[]) => generateReport(...args),
}));

function generated(overrides: Partial<GeneratedReport> = {}): GeneratedReport {
  return {
    report_type: "TRANSACTIONS_SUMMARY",
    title: "Transactions Summary",
    start_date: "2026-09-01",
    end_date: "2026-09-27",
    filename: "infinitypay-transactions-summary-2026-09-01-to-2026-09-27.pdf",
    row_count: 12,
    totals: { Transactions: "12" },
    emailed_to: ["owner@example.com"],
    ...overrides,
  };
}

describe("Merchant portal ReportsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    generateReport.mockResolvedValue(generated());
  });

  it("calls the real endpoint rather than only simulating a delay", async () => {
    // The page used to be a setTimeout that reported success without
    // generating anything. This is the assertion that keeps it honest.
    const { default: ReportsPage } = await import("./page");
    render(<ReportsPage />);

    fireEvent.click(screen.getByRole("button", { name: /Generate Report/ }));

    await waitFor(() => expect(generateReport).toHaveBeenCalledTimes(1));
  });

  it("sends the chosen report type and range", async () => {
    const { default: ReportsPage } = await import("./page");
    render(<ReportsPage />);

    fireEvent.change(screen.getByLabelText("Report Type"), { target: { value: "FEES_SUMMARY" } });
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-08-31" } });
    fireEvent.click(screen.getByRole("button", { name: /Generate Report/ }));

    await waitFor(() => expect(generateReport).toHaveBeenCalledTimes(1));
    expect(generateReport).toHaveBeenCalledWith({
      report_type: "FEES_SUMMARY",
      start_date: "2026-08-01",
      end_date: "2026-08-31",
      recipients: [],
    });
  });

  it("offers no format choice — a report is always a PDF", async () => {
    const { default: ReportsPage } = await import("./page");
    render(<ReportsPage />);

    await waitFor(() => expect(screen.getByLabelText("Report Type")).toBeInTheDocument());
    expect(screen.queryByText("Format")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "CSV" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "PDF" })).not.toBeInTheDocument();
  });

  it("splits typed extra recipients into a list", async () => {
    const { default: ReportsPage } = await import("./page");
    render(<ReportsPage />);

    fireEvent.change(screen.getByLabelText(/Also email to/), {
      target: { value: "accountant@example.com,  auditor@example.com " },
    });
    fireEvent.click(screen.getByRole("button", { name: /Generate Report/ }));

    await waitFor(() => expect(generateReport).toHaveBeenCalledTimes(1));
    expect(generateReport.mock.calls[0][0].recipients).toEqual([
      "accountant@example.com",
      "auditor@example.com",
    ]);
  });

  it("does not send an empty recipient when the box is left blank", async () => {
    const { default: ReportsPage } = await import("./page");
    render(<ReportsPage />);

    fireEvent.click(screen.getByRole("button", { name: /Generate Report/ }));

    await waitFor(() => expect(generateReport).toHaveBeenCalledTimes(1));
    expect(generateReport.mock.calls[0][0].recipients).toEqual([]);
  });

  it("confirms who the report was actually emailed to", async () => {
    generateReport.mockResolvedValue(
      generated({ emailed_to: ["owner@example.com", "accountant@example.com"], row_count: 3 }),
    );
    const { default: ReportsPage } = await import("./page");
    render(<ReportsPage />);

    fireEvent.click(screen.getByRole("button", { name: /Generate Report/ }));

    await waitFor(() =>
      expect(
        screen.getByText(/sent as PDF to owner@example.com, accountant@example.com/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/3 rows/)).toBeInTheDocument();
  });

  it("surfaces a failed send instead of claiming the report went out", async () => {
    generateReport.mockRejectedValue(new Error("Couldn't send the email — the email provider rejected the request."));
    const { default: ReportsPage } = await import("./page");
    render(<ReportsPage />);

    fireEvent.click(screen.getByRole("button", { name: /Generate Report/ }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("the email provider rejected the request"),
    );
    expect(screen.queryByText(/sent as/)).not.toBeInTheDocument();
  });

  it("re-enables the button after a failure so the merchant can retry", async () => {
    generateReport.mockRejectedValue(new Error("Something went wrong"));
    const { default: ReportsPage } = await import("./page");
    render(<ReportsPage />);

    fireEvent.click(screen.getByRole("button", { name: /Generate Report/ }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Generate Report/ })).not.toBeDisabled();
  });

  it("shows a singular row count without an 's'", async () => {
    generateReport.mockResolvedValue(generated({ row_count: 1 }));
    const { default: ReportsPage } = await import("./page");
    render(<ReportsPage />);

    fireEvent.click(screen.getByRole("button", { name: /Generate Report/ }));

    await waitFor(() => expect(screen.getByText(/1 row,/)).toBeInTheDocument());
  });
});
