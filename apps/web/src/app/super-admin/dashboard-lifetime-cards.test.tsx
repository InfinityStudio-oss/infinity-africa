import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AdminOverview } from "@/lib/admin/types";

const getAdminOverview = vi.fn();
const listAdminAuditLogs = vi.fn(async () => []);

vi.mock("@/lib/admin/live-api", () => ({
  getAdminOverview: () => getAdminOverview(),
  listAdminAuditLogs: () => listAdminAuditLogs(),
}));

/** The Command Center page is an async Server Component. Rendering it in
 * jsdom means awaiting it and handing React the resolved element. */
async function renderDashboard(overview: AdminOverview | null) {
  getAdminOverview.mockResolvedValue(overview);
  const { default: Page } = await import("./page");
  render(await Page());
}

const overview: AdminOverview = {
  total_merchants: 103,
  collections_today: "1724886.00",
  collections_this_month: "22675873.00",
  withdrawals_today: "1969021.00",
  active_payment_links: 64,
  paid_invoices_today: 0,
  outstanding_invoice_value: "0.00",
  failed_transactions: 1005,
  platform_revenue_today: "39672.39",
  platform_revenue: "523226.80",
  collections_total: "81234567.89",
  revenue_total: "1869432.15",
  pending_onboarding_requests: 0,
  pending_withdrawals: 0,
};

describe("lifetime totals on the Command Center", () => {
  it("shows Collections Total as money, all time", async () => {
    await renderDashboard(overview);

    expect(screen.getByText("Collections Total")).toBeInTheDocument();
    expect(screen.getByText("TZS 81,234,567.89")).toBeInTheDocument();
  });

  it("shows Revenue Total as money, all time", async () => {
    await renderDashboard(overview);

    expect(screen.getByText("Revenue Total")).toBeInTheDocument();
    expect(screen.getByText("TZS 1,869,432.15")).toBeInTheDocument();
  });

  it("labels both of them All time", async () => {
    await renderDashboard(overview);

    expect(screen.getAllByText("All time")).toHaveLength(2);
  });

  it("shows amounts, not counts", async () => {
    // The brief's one shouted requirement. "1,005" and "64" were counts;
    // a card that still rendered one would be the specific mistake here.
    await renderDashboard(overview);

    expect(screen.queryByText("Failed Transactions")).not.toBeInTheDocument();
    expect(screen.queryByText("Active Payment Links")).not.toBeInTheDocument();
    expect(screen.queryByText("1,005")).not.toBeInTheDocument();
    expect(screen.queryByText("64")).not.toBeInTheDocument();
  });

  it("leaves every other card alone", async () => {
    await renderDashboard(overview);

    for (const label of [
      "Total Businesses",
      "Collections Today",
      "Withdrawals Today",
      "Collections This Month",
      "Revenue Today",
      "Revenue This Month",
      "Pending Onboarding",
      "Pending Withdrawals",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("TZS 1,724,886.00")).toBeInTheDocument();
    expect(screen.getByText("TZS 39,672.39")).toBeInTheDocument();
  });

  it("never shows TZS 0.00 for a total it could not load", async () => {
    // A lifetime total of zero reads as "this platform has never taken a
    // payment" — the most alarming and least likely thing this dashboard
    // could say, and exactly what a missing value would look like.
    await renderDashboard({ ...overview, collections_total: null, revenue_total: null });

    expect(screen.getAllByText("—")).toHaveLength(2);
    expect(screen.getAllByText("Couldn't load")).toHaveLength(2);
    expect(screen.queryByText("TZS 0.00")).not.toBeInTheDocument();
  });

  it("shows TZS 0.00 when the answer really is zero", async () => {
    await renderDashboard({ ...overview, collections_total: "0.00", revenue_total: "0.00" });

    expect(screen.getAllByText("TZS 0.00")).toHaveLength(2);
    expect(screen.queryByText("—")).not.toBeInTheDocument();
    expect(screen.getAllByText("All time")).toHaveLength(2);
  });

  it("degrades to the existing message when the whole overview fails", async () => {
    await renderDashboard(null);

    expect(screen.getByText(/Couldn't reach InfinityPay to load platform metrics/)).toBeInTheDocument();
    expect(screen.queryByText("Collections Total")).not.toBeInTheDocument();
  });

  it("keeps a large total exact through the money formatter", async () => {
    // Number() sits inside formatCurrency. At lifetime scale that has to
    // stay lossless, and it does well past any figure this platform will
    // reach — checked rather than assumed.
    await renderDashboard({ ...overview, collections_total: "123456789012.34" });

    expect(screen.getByText("TZS 123,456,789,012.34")).toBeInTheDocument();
  });
});
