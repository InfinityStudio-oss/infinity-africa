import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN_NAV_ITEMS, ADMIN_NAV_SECTIONS } from "./nav-items";

const pathname = vi.hoisted(() => ({ current: "/super-admin" }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.current,
}));

async function renderAt(path: string) {
  pathname.current = path;
  const { AdminSidebar } = await import("./sidebar");
  return render(<AdminSidebar open onClose={() => {}} />);
}

afterEach(() => {
  pathname.current = "/super-admin";
});

describe("AdminSidebar grouping", () => {
  const EXPECTED_SECTIONS = [
    "Overview",
    "Businesses",
    "Payments & Settlements",
    "Risk & Compliance",
    "Integrations",
    "Platform Settings",
  ];

  it("draws the six section headings in order", async () => {
    const { container } = await renderAt("/super-admin");

    const headings = [...container.querySelectorAll("nav h2")].map((h) => h.textContent);
    expect(headings).toEqual(EXPECTED_SECTIONS);
  });

  it("renders the headings as plain labels, not links", async () => {
    await renderAt("/super-admin");

    for (const heading of EXPECTED_SECTIONS) {
      // "Businesses" is both a heading and a link, so the check is that
      // the *heading* element is not itself an anchor.
      const el = screen.getByRole("heading", { name: heading });
      expect(el.tagName).toBe("H2");
      expect(el.closest("a")).toBeNull();
    }
  });

  it("puts the three daily screens first in Payments & Settlements", async () => {
    // Collections, Transactions and Withdrawals are what this page is
    // opened for; the point of the regrouping was to stop them being
    // scattered down an eighteen-item list.
    const payments = ADMIN_NAV_SECTIONS.find((s) => s.heading === "Payments & Settlements");
    expect(payments?.items.slice(0, 3).map((i) => i.label)).toEqual([
      "Collections",
      "Transactions",
      "Withdrawals",
    ]);
  });

  it("links every destination exactly once", async () => {
    await renderAt("/super-admin");

    const hrefs = ADMIN_NAV_ITEMS.map((i) => i.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);

    for (const item of ADMIN_NAV_ITEMS) {
      const links = screen.getAllByRole("link").filter((a) => a.getAttribute("href") === item.href);
      // /super-admin is the wordmark as well as Dashboard, hence two.
      expect(links.length).toBe(item.href === "/super-admin" ? 2 : 1);
    }
  });

  it("keeps the hrefs the sidebar has always used", async () => {
    await renderAt("/super-admin");

    const byLabel: Record<string, string> = {
      Dashboard: "/super-admin",
      Businesses: "/super-admin/merchants",
      "Business Users": "/super-admin/merchant-users",
      Customers: "/super-admin/customers",
      Referrals: "/super-admin/referrals",
      Collections: "/super-admin/collections",
      Transactions: "/super-admin/transactions",
      Withdrawals: "/super-admin/withdrawals",
      "Pay by Link": "/super-admin/pay-by-link",
      Invoices: "/super-admin/invoices",
      "Onboarding & Compliance": "/super-admin/onboarding",
      "Risk Monitoring": "/super-admin/risk-monitoring",
      "Audit Logs": "/super-admin/audit-logs",
      "API Keys": "/super-admin/api-keys",
      "Webhooks & Reconciliation": "/super-admin/webhooks",
      "Pricing Rules": "/super-admin/pricing-rules",
      Notifications: "/super-admin/notifications",
      // Still under /admin, not /super-admin. Deliberate: this was a
      // navigation change, not a route migration.
      Settings: "/admin/settings",
    };

    expect(Object.keys(byLabel).length).toBe(ADMIN_NAV_ITEMS.length);
    for (const [label, href] of Object.entries(byLabel)) {
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
  });

  it("shows the long labels in full, with no ellipsis class", async () => {
    await renderAt("/super-admin");

    for (const label of ["Onboarding & Compliance", "Webhooks & Reconciliation"]) {
      const span = screen.getByText(label);
      expect(span.className).not.toMatch(/truncate/);
    }
  });
});

describe("AdminSidebar active page", () => {
  // The icon glyph is a font ligature, so a link's textContent is
  // "paymentsCollections" — read the label span, which is the one that is
  // not aria-hidden.
  function current(container: HTMLElement): string[] {
    return [...container.querySelectorAll('a[aria-current="page"]')].map(
      (a) => a.querySelector("span:not([aria-hidden])")?.textContent?.trim() ?? "",
    );
  }

  it("marks only Dashboard on /super-admin", async () => {
    const { container } = await renderAt("/super-admin");
    expect(current(container)).toEqual(["Dashboard"]);
  });

  it("lights Businesses — not Dashboard — on a business detail page", async () => {
    const { container } = await renderAt("/super-admin/merchants/739b38ad-f75f-4c5e-a69c-cfa6d4f8aa26");
    expect(current(container)).toEqual(["Businesses"]);
  });

  it("does not let Businesses light Business Users, or the reverse", async () => {
    const { container } = await renderAt("/super-admin/merchant-users");
    expect(current(container)).toEqual(["Business Users"]);
  });

  it("keeps Notifications lit on its tabs, and marks the tab too", async () => {
    const { container } = await renderAt("/super-admin/notifications/email");
    expect(current(container)).toEqual(["Notifications", "Email"]);
  });

  it("marks nothing when the route is not in the nav", async () => {
    // /super-admin/disputes is a real page, deliberately unlinked.
    const { container } = await renderAt("/super-admin/disputes");
    expect(current(container)).toEqual([]);
  });
});
