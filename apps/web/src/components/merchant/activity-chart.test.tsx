import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActivityChart } from "./activity-chart";
import type { MerchantActivityPoint } from "@/lib/portal/types";

function series(points: Partial<MerchantActivityPoint>[]): MerchantActivityPoint[] {
  return points.map((point, index) => ({
    date: point.date ?? `2026-11-${String(index + 1).padStart(2, "0")}`,
    collected: point.collected ?? "0",
    paid_out: point.paid_out ?? "0",
    count: point.count ?? 0,
  }));
}

describe("ActivityChart", () => {
  it("names both series in a legend, so identity is never colour alone", () => {
    render(<ActivityChart series={series([{ collected: "1000", paid_out: "400" }])} />);

    // Scoped to the legend entries, which carry the running total - the
    // bare phrase also appears in the chart title ("Money in and out").
    expect(screen.getByText(/Money in\s*TZS/)).toBeInTheDocument();
    expect(screen.getByText(/Money out\s*TZS/)).toBeInTheDocument();
  });

  it("offers a table view of the same numbers", () => {
    render(
      <ActivityChart series={series([{ date: "2026-11-01", collected: "1500", paid_out: "250", count: 3 }])} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /View as table/i }));

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Money in/i })).toBeInTheDocument();
  });

  it("scales bars against a shared ceiling, so the two series stay comparable", () => {
    // One axis for both measures. If each were scaled to its own max, a
    // day with 100 in and 10 out would draw two equal bars.
    const { container } = render(
      <ActivityChart series={series([{ collected: "1000", paid_out: "100" }])} />,
    );

    const heights = Array.from(container.querySelectorAll<HTMLElement>("[style*='height']"))
      .map((element) => element.style.height)
      .filter((height) => height.endsWith("%"));

    expect(heights.length).toBeGreaterThanOrEqual(2);
    expect(heights[0]).not.toEqual(heights[1]);
  });

  it("draws nothing for a zero day rather than a floor-height bar", () => {
    // A zero day that renders as a visible stub reads as "a little bit
    // happened", which is a different claim from "nothing happened".
    const { container } = render(
      <ActivityChart series={series([{ collected: "0", paid_out: "0" }])} />,
    );

    expect(container.textContent).toMatch(/Nothing moved in or out/i);
  });

  it("keeps a zero day in the series rather than closing the gap", () => {
    const { container } = render(
      <ActivityChart
        series={series([
          { date: "2026-11-01", collected: "1000" },
          { date: "2026-11-02", collected: "0" },
          { date: "2026-11-03", collected: "2000" },
        ])}
      />,
    );

    // Three day columns, not two. A sparse series would let the chart
    // close the quiet day and hide the dip.
    const columns = container.querySelectorAll("[tabindex='0']");
    expect(columns.length).toBe(3);
  });

  it("says so plainly when there is no data at all", () => {
    render(<ActivityChart series={[]} />);

    expect(screen.getByText(/No activity in this period yet/i)).toBeInTheDocument();
  });

  it("labels the first and last day without labelling all fourteen", () => {
    const fourteen = series(
      Array.from({ length: 14 }, (_, index) => ({
        date: `2026-11-${String(index + 1).padStart(2, "0")}`,
        collected: String((index + 1) * 100),
      })),
    );
    const { container } = render(<ActivityChart series={fourteen} />);

    expect(container.textContent).toContain("1 Nov");
    expect(container.textContent).toContain("14 Nov");
    // A label on every column collides at phone width.
    expect(container.textContent).not.toContain("13 Nov");
  });
});
