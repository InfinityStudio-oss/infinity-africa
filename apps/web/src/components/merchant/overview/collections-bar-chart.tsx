"use client";

import { useId, useMemo, useState } from "react";

import { formatCurrency } from "@/lib/format";
import type { CollectionsSeriesPoint } from "@/lib/portal/types";

/**
 * Successful collections per day.
 *
 * Bars, not a line: these are discrete daily totals with real zeros in
 * them, and a line drawn through a zero day claims the value passed
 * through nothing on its way somewhere. Bars say "that day, nothing came
 * in", which is what the data means.
 *
 * One series, so no legend - the title names it. The brand blue is the
 * only hue, and it carries no identity, only "this is the measure".
 */

const BAR = "#1d4ed8";

function shortDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
  });
}

/** A round tick above the tallest bar, so the axis reads in human numbers
 * rather than "1,473,219". */
function niceCeiling(max: number): number {
  if (max <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  for (const step of [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10]) {
    if (magnitude * step >= max) return magnitude * step;
  }
  return magnitude * 10;
}

function compact(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}k`;
  return String(Math.round(value));
}

export function CollectionsBarChart({
  series,
  currency = "TZS",
}: {
  series: CollectionsSeriesPoint[];
  currency?: string;
}) {
  const titleId = useId();
  const summaryId = useId();
  const [hovered, setHovered] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  const points = useMemo(
    () =>
      series.map((point) => ({
        date: point.date,
        amount: Number(point.amount),
        count: point.count,
      })),
    [series],
  );

  const ceiling = useMemo(
    () => niceCeiling(Math.max(...points.map((p) => p.amount), 0)),
    [points],
  );

  const total = points.reduce((sum, p) => sum + p.amount, 0);
  const totalCount = points.reduce((sum, p) => sum + p.count, 0);
  const best = points.reduce<typeof points[number] | null>(
    (top, p) => (top === null || p.amount > top.amount ? p : top),
    null,
  );

  // The text alternative, and a plain-language summary for everyone else.
  // A chart nobody can read is a chart that is only decoration.
  const summary =
    total === 0
      ? "No collections in this period."
      : `${formatCurrency(String(total), currency)} across ${totalCount} payment${
          totalCount === 1 ? "" : "s"
        }${best && best.amount > 0 ? `, busiest on ${shortDate(best.date)}` : ""}.`;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 id={titleId} className="text-base font-semibold text-on-surface">
            Collections over time
          </h2>
          <p id={summaryId} className="mt-0.5 text-sm text-on-surface-variant">
            {summary}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowTable((open) => !open)}
          className="text-xs font-medium text-on-surface-variant hover:text-on-surface underline"
        >
          {showTable ? "Hide table" : "View as table"}
        </button>
      </div>

      {points.length === 0 ? (
        <p className="mt-6 text-sm text-on-surface-variant">Nothing to chart yet.</p>
      ) : (
        <div className="mt-5">
          <div className="flex gap-2">
            <div className="flex flex-col justify-between text-[10px] text-on-surface-variant tabular-nums h-48 shrink-0 text-right w-11">
              <span>{compact(ceiling)}</span>
              <span>{compact(ceiling / 2)}</span>
              <span>0</span>
            </div>

            <div
              className="flex-1 flex items-end gap-1 h-48 border-b border-outline-variant"
              role="img"
              aria-labelledby={`${titleId} ${summaryId}`}
            >
              {points.map((point, index) => {
                const isHovered = hovered === index;
                return (
                  <div
                    key={point.date}
                    // The hit target is the width of the day, not the
                    // width of a thin bar.
                    className="flex-1 h-full flex items-end justify-center relative rounded-sm"
                    onMouseEnter={() => setHovered(index)}
                    onMouseLeave={() => setHovered(null)}
                    onFocus={() => setHovered(index)}
                    onBlur={() => setHovered(null)}
                    tabIndex={0}
                    aria-label={`${shortDate(point.date)}: ${formatCurrency(
                      String(point.amount),
                      currency,
                    )} from ${point.count} payment${point.count === 1 ? "" : "s"}`}
                  >
                    {isHovered && (
                      <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 z-10 whitespace-nowrap rounded-lg bg-surface border border-outline-variant shadow-ambient px-2.5 py-2 text-[11px] pointer-events-none">
                        <p className="font-semibold text-on-surface">{shortDate(point.date)}</p>
                        <p className="text-on-surface">
                          {formatCurrency(String(point.amount), currency)}
                        </p>
                        <p className="text-on-surface-variant">
                          {point.count} payment{point.count === 1 ? "" : "s"}
                        </p>
                      </div>
                    )}
                    <div
                      className="w-2/3 max-w-[22px] rounded-t transition-opacity"
                      style={{
                        // A zero day draws nothing. A floor-height stub
                        // would read as "a little came in", which is a
                        // different claim.
                        height: `${point.amount > 0 ? Math.max((point.amount / ceiling) * 100, 1.5) : 0}%`,
                        background: BAR,
                        opacity: hovered === null || isHovered ? 1 : 0.5,
                      }}
                    />
                  </div>
                );
              })}
            </div>
          </div>

          {/* First, middle and last only. Labelling every day collides at
              phone width, and the tooltip carries the exact date anyway. */}
          <div className="flex gap-2 mt-1.5">
            <div className="w-11 shrink-0" />
            <div className="flex-1 flex justify-between text-[10px] text-on-surface-variant">
              <span>{shortDate(points[0].date)}</span>
              {points.length > 2 && (
                <span>{shortDate(points[Math.floor(points.length / 2)].date)}</span>
              )}
              <span>{shortDate(points[points.length - 1].date)}</span>
            </div>
          </div>
        </div>
      )}

      {showTable && (
        <div className="mt-4 overflow-x-auto max-h-64">
          <table className="w-full text-xs">
            <caption className="sr-only">Successful collections by day</caption>
            <thead>
              <tr className="text-left text-on-surface-variant">
                <th scope="col" className="py-1.5 pr-3 font-semibold">
                  Date
                </th>
                <th scope="col" className="py-1.5 pr-3 font-semibold">
                  Collected
                </th>
                <th scope="col" className="py-1.5 font-semibold">
                  Payments
                </th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {points.map((point) => (
                <tr key={point.date} className="border-t border-outline-variant/60">
                  <th scope="row" className="py-1.5 pr-3 font-normal text-left text-on-surface">
                    {shortDate(point.date)}
                  </th>
                  <td className="py-1.5 pr-3 text-on-surface">
                    {formatCurrency(String(point.amount), currency)}
                  </td>
                  <td className="py-1.5 text-on-surface">{point.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
