import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AdminOverview } from "@/lib/admin/types";

const getAdminOverview = vi.fn();
const listAdminAuditLogs = vi.fn(async () => []);

// The page reads the signed-in admin's name for its welcome header, and
// both of those modules are `import "server-only"`. jsdom is a client
// environment, so importing the page pulls server-only in and it throws
// before a single assertion runs. Neither module has anything to do with
// the lifetime totals this file is about.
vi.mock("@/lib/auth/ui-preview", () => ({ uiPreviewEnabled: () => true }));
vi.mock("@/lib/supabase/protected-route", () => ({ requireSuperAdmin: async () => null }));

vi.mock("@/lib/admin/live-api", () => ({
  getAdminOverview: () => getAdminOverview(),
  listAdminAuditLogs: () => listAdminAuditLogs(),
  // The dashboard now also counts active businesses and today's
  // successful collections for its headline row. Neither is what this
  // file is about, so both resolve to a fixed value and stay out of the
  // way of the lifetime-total assertions below.
  getAdminActiveMerchantCount: async () => 42,
  getAdminSuccessfulCollectionsToday: async () => 7,
  getAdminDailyCollectionCounts: async () => [],
  getAdminCollectionStatusCounts: async () => [],
  listAdminCollectionsResult: async () => ({ rows: [], failure: null }),
  ADMIN_COLLECTION_STATUSES: [],
}));

/** Renders the cards the way the page does.
 *
 * MetricsSection rather than the page's default export: the page is now
 * a synchronous shell of Suspense boundaries whose data is fetched by
 * the async sections inside it, so  returns a tree with
 * these cards still unresolved and every assertion below would pass
 * vacuously against an empty render. Awaiting the section is what
 * actually exercises the card markup.
 *
 * The section is still a real async Server Component, so this is the
 * same shape of test as before. */
async function renderDashboard(overview: AdminOverview | null) {
  getAdminOverview.mockResolvedValue(overview);
  const { MetricsSection } = await import("./page");
  render(await MetricsSection());
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

    // The redesign added a four-card headline row and moved the rest
    // below it. Every metric that existed before is still here - this
    // list is the proof, and is why the redesign is a rearrangement
    // rather than a quiet deletion of figures someone relied on.
    for (const label of [
      "Collection Volume",
      "Successful Transactions",
      "Active Businesses",
      "Pending Withdrawals",
      "Collections This Month",
      "Revenue This Month",
      "Revenue Today",
      "Withdrawals Today",
      "Pending Onboarding",
      "Total Businesses",
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
