"use client";

import { useId, useMemo, useState } from "react";

import { formatCurrency } from "@/lib/format";
import type { MerchantActivityPoint } from "@/lib/portal/types";

/**
 * Daily money in against money out, as grouped bars.
 *
 * Why grouped bars and not a line: the series is 14 discrete daily
 * totals with real zeros in it. A line drawn through a zero day implies
 * the account was mid-transaction at 3am and the value passed through
 * nothing on its way somewhere - bars say "that day, nothing happened",
 * which is what the data means. The two measures are the same unit on
 * the same scale, so they share one axis; that is also why this is not
 * two charts.
 *
 * Colors are categorical slots 1 and 2 in fixed order - money in is
 * always blue, money out always orange, whatever the period shows, so a
 * filter can never repaint the survivors. Validated rather than eyeballed:
 * worst adjacent CVD Delta E 24.7 light / 26.8 dark, normal-vision
 * 33.6 / 31.8, both >= 3:1 against their surface.
 *
 * Identity is never carried by color alone: there is a legend, and the
 * table view below is the accessible path to the same numbers.
 */

const MONEY_IN = "var(--viz-series-1)";
const MONEY_OUT = "var(--viz-series-2)";

function shortDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** A round-ish tick above the tallest bar, so the axis reads in human
 * numbers rather than "1,473,219". */
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

export function ActivityChart({
  series,
  currency = "TZS",
}: {
  series: MerchantActivityPoint[];
  currency?: string;
}) {
  const titleId = useId();
  const [hovered, setHovered] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  const points = useMemo(
    () =>
      series.map((point) => ({
        date: point.date,
        inAmount: Number(point.collected),
        outAmount: Number(point.paid_out),
        count: point.count,
      })),
    [series],
  );

  const ceiling = useMemo(
    () => niceCeiling(Math.max(...points.map((p) => Math.max(p.inAmount, p.outAmount)), 0)),
    [points],
  );

  const totalIn = points.reduce((sum, p) => sum + p.inAmount, 0);
  const totalOut = points.reduce((sum, p) => sum + p.outAmount, 0);

  if (points.length === 0) {
    return (
      <p className="text-sm text-on-surface-variant">No activity in this period yet.</p>
    );
  }

  const everythingIsZero = ceiling <= 1 && totalIn === 0 && totalOut === 0;

  return (
    <div
      className="viz-root"
      style={
        {
          // Categorical slots 1 and 2, light values.
          //
          // Light only, because the portal is light only - there is no
          // dark theme in globals.css, and a chart that answered
          // prefers-color-scheme on its own would go dark inside a page
          // that stayed light. The validated dark steps for these two
          // slots are #3987e5 and #d95926 (worst adjacent CVD Delta E
          // 26.8, normal-vision 31.8, both >= 3:1 on the dark surface);
          // use those when the portal gains a dark theme rather than
          // flipping these.
          "--viz-series-1": "#2a78d6",
          "--viz-series-2": "#eb6834",
        } as React.CSSProperties
      }
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3 mb-1">
        <h3 id={titleId} className="text-base font-semibold">
          Money in and out
        </h3>
        <button
          type="button"
          onClick={() => setShowTable((open) => !open)}
          className="text-xs font-medium text-on-surface-variant hover:text-on-surface underline"
        >
          {showTable ? "Hide table" : "View as table"}
        </button>
      </div>

      {/* Legend. Always present for two series, and the swatch carries the
          identity while the text stays in ink tokens. */}
      <div className="flex items-center gap-4 mb-3 text-xs text-on-surface-variant">
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block w-2.5 h-2.5 rounded-sm"
            style={{ background: MONEY_IN }}
            aria-hidden
          />
          Money in {formatCurrency(String(totalIn), currency)}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block w-2.5 h-2.5 rounded-sm"
            style={{ background: MONEY_OUT }}
            aria-hidden
          />
          Money out {formatCurrency(String(totalOut), currency)}
        </span>
      </div>

      {everythingIsZero ? (
        <p className="text-sm text-on-surface-variant py-6">
          Nothing moved in or out over this period.
        </p>
      ) : (
        <div className="relative">
          {/* The y axis, recessive on purpose: three labels, no grid
              lines competing with the bars. */}
          <div className="flex gap-2">
            <div className="flex flex-col justify-between text-[10px] text-on-surface-variant tabular-nums h-40 shrink-0 text-right w-10">
              <span>{compact(ceiling)}</span>
              <span>{compact(ceiling / 2)}</span>
              <span>0</span>
            </div>

            <div
              className="flex-1 flex items-end gap-1 h-40 border-b border-surface-container-highest"
              role="img"
              aria-labelledby={titleId}
            >
              {points.map((point, index) => {
                const isHovered = hovered === index;
                return (
                  <div
                    key={point.date}
                    // A hit target the width of the day, not the width of
                    // a 5px bar.
                    className="flex-1 h-full flex items-end justify-center gap-[2px] relative cursor-default"
                    onMouseEnter={() => setHovered(index)}
                    onMouseLeave={() => setHovered(null)}
                    onFocus={() => setHovered(index)}
                    onBlur={() => setHovered(null)}
                    tabIndex={0}
                  >
                    {isHovered && (
                      <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 z-10 whitespace-nowrap rounded-lg bg-surface border border-surface-container-highest shadow-ambient px-2.5 py-2 text-[11px] pointer-events-none">
                        <p className="font-semibold mb-0.5">{shortDate(point.date)}</p>
                        <p className="flex items-center gap-1.5">
                          <span
                            className="inline-block w-2 h-2 rounded-sm"
                            style={{ background: MONEY_IN }}
                            aria-hidden
                          />
                          In {formatCurrency(String(point.inAmount), currency)}
                        </p>
                        <p className="flex items-center gap-1.5">
                          <span
                            className="inline-block w-2 h-2 rounded-sm"
                            style={{ background: MONEY_OUT }}
                            aria-hidden
                          />
                          Out {formatCurrency(String(point.outAmount), currency)}
                        </p>
                        <p className="text-on-surface-variant mt-0.5">
                          {point.count} payment{point.count === 1 ? "" : "s"}
                        </p>
                      </div>
                    )}
                    {/* 4px rounded data-ends anchored to the baseline, and
                        a 2px surface gap between the pair. */}
                    <div
                      className="w-1/2 max-w-[14px] rounded-t transition-opacity"
                      style={{
                        height: `${Math.max((point.inAmount / ceiling) * 100, point.inAmount > 0 ? 1.5 : 0)}%`,
                        background: MONEY_IN,
                        opacity: hovered === null || isHovered ? 1 : 0.45,
                      }}
                    />
                    <div
                      className="w-1/2 max-w-[14px] rounded-t transition-opacity"
                      style={{
                        height: `${Math.max((point.outAmount / ceiling) * 100, point.outAmount > 0 ? 1.5 : 0)}%`,
                        background: MONEY_OUT,
                        opacity: hovered === null || isHovered ? 1 : 0.45,
                      }}
                    />
                  </div>
                );
              })}
            </div>
          </div>

          {/* Date labels: first, last and roughly the middle. Labelling
              all fourteen collides at phone width. */}
          <div className="flex gap-2 mt-1.5">
            <div className="w-10 shrink-0" />
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
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-xs">
            <caption className="sr-only">Daily money in and money out</caption>
            <thead>
              <tr className="text-left text-on-surface-variant">
                <th scope="col" className="py-1.5 pr-3 font-semibold">
                  Date
                </th>
                <th scope="col" className="py-1.5 pr-3 font-semibold">
                  Money in
                </th>
                <th scope="col" className="py-1.5 pr-3 font-semibold">
                  Money out
                </th>
                <th scope="col" className="py-1.5 font-semibold">
                  Payments
                </th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {points.map((point) => (
                <tr key={point.date} className="border-t border-surface-container-highest/60">
                  <th scope="row" className="py-1.5 pr-3 font-normal text-left">
                    {shortDate(point.date)}
                  </th>
                  <td className="py-1.5 pr-3">{formatCurrency(String(point.inAmount), currency)}</td>
                  <td className="py-1.5 pr-3">
                    {formatCurrency(String(point.outAmount), currency)}
                  </td>
                  <td className="py-1.5">{point.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
