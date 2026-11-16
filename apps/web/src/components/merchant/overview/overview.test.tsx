import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CollectionsBarChart } from "./collections-bar-chart";
import { CollectionsDonut } from "./collections-donut";
import { OverviewHeader, displayNameFor, greetingFor } from "./overview-header";
import type { CollectionsByMethod, CollectionsSeriesPoint } from "@/lib/portal/types";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard/overview",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

function series(points: Partial<CollectionsSeriesPoint>[]): CollectionsSeriesPoint[] {
  return points.map((point, index) => ({
    date: point.date ?? `2026-11-${String(index + 1).padStart(2, "0")}`,
    amount: point.amount ?? "0",
    count: point.count ?? 0,
  }));
}

function methods(entries: Partial<CollectionsByMethod>[]): CollectionsByMethod[] {
  return entries.map((entry) => ({
    method: entry.method ?? "MOBILE_MONEY",
    amount: entry.amount ?? "0",
    count: entry.count ?? 0,
  }));
}

/** 09:00 UTC is 12:00 in Dar es Salaam — afternoon. */
function atUtc(hour: number): Date {
  return new Date(Date.UTC(2026, 10, 16, hour, 0, 0));
}

// --- the greeting ------------------------------------------------------------

describe("greetingFor", () => {
  it("uses Dar es Salaam, not the machine's timezone", () => {
    // 22:00 UTC is 01:00 the next day in Tanzania. A browser in London
    // would say "Good evening"; the business is asleep, and the correct
    // answer for the merchant is morning.
    expect(greetingFor(atUtc(22))).toBe("Good morning");
  });

  it("says good morning before noon local", () => {
    expect(greetingFor(atUtc(5))).toBe("Good morning"); // 08:00 EAT
  });

  it("says good afternoon from noon local", () => {
    expect(greetingFor(atUtc(10))).toBe("Good afternoon"); // 13:00 EAT
  });

  it("says good evening from 17:00 local", () => {
    expect(greetingFor(atUtc(15))).toBe("Good evening"); // 18:00 EAT
  });
});

describe("displayNameFor", () => {
  it("returns the business name", () => {
    expect(displayNameFor("Kariakoo Traders")).toBe("Kariakoo Traders");
  });

  it("treats blank and missing names the same", () => {
    expect(displayNameFor("   ")).toBeNull();
    expect(displayNameFor(null)).toBeNull();
    expect(displayNameFor(undefined)).toBeNull();
  });
});

// --- the header --------------------------------------------------------------

function renderHeader(props: Partial<React.ComponentProps<typeof OverviewHeader>> = {}) {
  return render(
    <OverviewHeader
      businessName="Kariakoo Traders"
      accountStatus="VERIFIED"
      range="7d"
      onRangeChange={() => {}}
      customStart="2026-11-01"
      customEnd="2026-11-07"
      onCustomChange={() => {}}
      canCreatePaymentLink
      now={atUtc(10)}
      {...props}
    />,
  );
}

describe("OverviewHeader", () => {
  it("greets the merchant by their business name", () => {
    renderHeader();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Good afternoon, Kariakoo Traders",
    );
  });

  it("falls back to a welcome when the business name is missing", () => {
    renderHeader({ businessName: null });

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Welcome to InfinityPay");
  });

  it("shows the name it is given, so switching merchants changes it", () => {
    // The name is a prop, not read from the session or cached anywhere,
    // which is what makes a merchant switch show up here.
    const { rerender } = renderHeader();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Kariakoo Traders");

    rerender(
      <OverviewHeader
        businessName="Mbezi Supplies"
        accountStatus="VERIFIED"
        range="7d"
        onRangeChange={() => {}}
        customStart="2026-11-01"
        customEnd="2026-11-07"
        onCustomChange={() => {}}
        canCreatePaymentLink
        now={atUtc(10)}
      />,
    );

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Mbezi Supplies");
  });

  it("puts the account status in a badge beside the greeting", () => {
    renderHeader({ accountStatus: "PENDING_VERIFICATION" });

    expect(screen.getByText("Under review")).toBeInTheDocument();
  });

  it("offers an onboarding action when the account needs attention", () => {
    renderHeader({ accountStatus: "PENDING_VERIFICATION" });

    expect(screen.getByRole("link", { name: /Finish setting up/i })).toHaveAttribute(
      "href",
      "/onboarding",
    );
  });

  it("offers no onboarding nag once verified", () => {
    renderHeader({ accountStatus: "VERIFIED" });

    expect(screen.queryByRole("link", { name: /Finish setting up/i })).not.toBeInTheDocument();
  });

  it("has exactly one Create Payment Link button", () => {
    renderHeader();

    expect(screen.getAllByRole("link", { name: /Create Payment Link/i })).toHaveLength(1);
  });

  it("hides Create Payment Link from a role that may not", () => {
    renderHeader({ canCreatePaymentLink: false });

    expect(screen.queryByRole("link", { name: /Create Payment Link/i })).not.toBeInTheDocument();
  });

  it("offers the three reporting ranges and marks the active one", () => {
    renderHeader({ range: "30d" });

    const group = screen.getByRole("group", { name: /Reporting period/i });
    expect(within(group).getByRole("button", { name: "Last 7 days" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(within(group).getByRole("button", { name: "Last 30 days" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("only shows the date inputs on the custom range", () => {
    const { rerender } = renderHeader({ range: "7d" });
    expect(screen.queryByLabelText(/Start date/i)).not.toBeInTheDocument();

    rerender(
      <OverviewHeader
        businessName="Kariakoo Traders"
        accountStatus="VERIFIED"
        range="custom"
        onRangeChange={() => {}}
        customStart="2026-11-01"
        customEnd="2026-11-07"
        onCustomChange={() => {}}
        canCreatePaymentLink
        now={atUtc(10)}
      />,
    );
    expect(screen.getByLabelText(/Start date/i)).toBeInTheDocument();
  });

  it("reports a range change", () => {
    const onRangeChange = vi.fn();
    renderHeader({ onRangeChange });

    fireEvent.click(screen.getByRole("button", { name: "Last 30 days" }));

    expect(onRangeChange).toHaveBeenCalledWith("30d");
  });
});

// --- the bar chart -----------------------------------------------------------

describe("CollectionsBarChart", () => {
  it("summarises itself in text, so the chart is not the only way in", () => {
    render(
      <CollectionsBarChart
        series={series([{ amount: "1000", count: 2 }, { amount: "500", count: 1 }])}
      />,
    );

    expect(screen.getByText(/across 3 payments/i)).toBeInTheDocument();
  });

  it("gives every day a keyboard-reachable description", () => {
    const { container } = render(
      <CollectionsBarChart series={series([{ date: "2026-11-01", amount: "1500", count: 3 }])} />,
    );

    const day = container.querySelector("[tabindex='0']");
    expect(day).toHaveAttribute("aria-label", expect.stringContaining("3 payments"));
  });

  it("shows date, amount and count on hover", () => {
    // Three days, so the hovered day's label is not also the axis's
    // first-and-last label - with one point those collide and the
    // assertion cannot tell the tooltip from the axis.
    const { container } = render(
      <CollectionsBarChart
        series={series([
          { date: "2026-11-01", amount: "1000", count: 1 },
          { date: "2026-11-02", amount: "1500", count: 3 },
          { date: "2026-11-03", amount: "900", count: 2 },
        ])}
      />,
    );

    fireEvent.mouseEnter(container.querySelectorAll("[tabindex='0']")[1]!);

    expect(screen.getByText("3 payments")).toBeInTheDocument();
    // Matched loosely: the exact currency rendering is Intl's business,
    // and pinning it here would make this a test of the locale.
    expect(screen.getByText(/1,500/)).toBeInTheDocument();
  });

  it("keeps a zero day in the series rather than closing the gap", () => {
    const { container } = render(
      <CollectionsBarChart
        series={series([
          { date: "2026-11-01", amount: "1000" },
          { date: "2026-11-02", amount: "0" },
          { date: "2026-11-03", amount: "2000" },
        ])}
      />,
    );

    expect(container.querySelectorAll("[tabindex='0']")).toHaveLength(3);
  });

  it("draws no bar at all for a zero day", () => {
    // A floor-height stub would read as "a little came in", which is a
    // different claim from "nothing came in".
    const { container } = render(
      <CollectionsBarChart series={series([{ date: "2026-11-01", amount: "0" }])} />,
    );

    const bars = Array.from(container.querySelectorAll<HTMLElement>("[style*='height']"));
    expect(bars.every((bar) => bar.style.height === "0%")).toBe(true);
  });

  it("offers the same numbers as a table", () => {
    render(<CollectionsBarChart series={series([{ amount: "1500", count: 2 }])} />);

    fireEvent.click(screen.getByRole("button", { name: /View as table/i }));

    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("says plainly when there were no collections", () => {
    render(<CollectionsBarChart series={series([{ amount: "0" }])} />);

    expect(screen.getByText(/No collections in this period/i)).toBeInTheDocument();
  });
});

// --- the donut ---------------------------------------------------------------

describe("CollectionsDonut", () => {
  it("puts the period total in the centre", () => {
    render(
      <CollectionsDonut
        byMethod={methods([
          { method: "MOBILE_MONEY", amount: "6000", count: 3 },
          { method: "CARD", amount: "4000", count: 1 },
        ])}
      />,
    );

    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("10k TZS")).toBeInTheDocument();
  });

  it("names every method, so identity is never colour alone", () => {
    render(
      <CollectionsDonut
        byMethod={methods([
          { method: "MOBILE_MONEY", amount: "6000" },
          { method: "CARD", amount: "4000" },
        ])}
      />,
    );

    expect(screen.getByText("Mobile money")).toBeInTheDocument();
    expect(screen.getByText("Card")).toBeInTheDocument();
  });

  it("links a method to its filtered transactions for the same period", () => {
    render(
      <CollectionsDonut
        byMethod={methods([{ method: "MOBILE_MONEY", amount: "6000" }])}
        startDate="2026-11-01"
        endDate="2026-11-07"
      />,
    );

    const link = screen.getByRole("link", { name: /Mobile money transactions/i });
    expect(link).toHaveAttribute("href", expect.stringContaining("method=MOBILE_MONEY"));
    expect(link).toHaveAttribute("href", expect.stringContaining("start_date=2026-11-01"));
  });

  it("lists only the methods actually used", () => {
    render(<CollectionsDonut byMethod={methods([{ method: "MOBILE_MONEY", amount: "500" }])} />);

    expect(screen.queryByText("Card")).not.toBeInTheDocument();
  });

  it("folds a long tail into one Other slice rather than inventing hues", () => {
    render(
      <CollectionsDonut
        byMethod={methods([
          { method: "MOBILE_MONEY", amount: "500" },
          { method: "CARD", amount: "400" },
          { method: "BANK_TRANSFER", amount: "300" },
          { method: "WALLET", amount: "200" },
          { method: "SELCOM_PESA", amount: "100" },
        ])}
      />,
    );

    expect(screen.getByText("Other methods")).toBeInTheDocument();
  });

  it("does not link Other anywhere, because it is several methods", () => {
    render(
      <CollectionsDonut
        byMethod={methods([
          { method: "MOBILE_MONEY", amount: "500" },
          { method: "CARD", amount: "400" },
          { method: "BANK_TRANSFER", amount: "300" },
          { method: "WALLET", amount: "200" },
          { method: "SELCOM_PESA", amount: "100" },
        ])}
      />,
    );

    expect(screen.queryByRole("link", { name: /Other methods/i })).not.toBeInTheDocument();
  });

  it("says so when there is nothing to split", () => {
    render(<CollectionsDonut byMethod={[]} />);

    expect(screen.getByText(/No collections in this period/i)).toBeInTheDocument();
  });
});

