"use client";

import { useId, useMemo, useState } from "react";

import type { AdminDailyCollectionPoint } from "@/lib/admin/live-api";

/**
 * Successful collections per day, platform-wide.
 *
 * **This charts a COUNT, not an amount, and says so on its face.** There
 * is no admin endpoint that sums collection value per day, and the list
 * endpoints are capped at 100 rows, so a per-day total could only be
 * produced by adding up a truncated page — which on a platform taking
 * thousands of collections a day would be wrong every busy day, and
 * wrong in the flattering direction. A count is a figure the API answers
 * exactly. Labelling it "collections" and letting it be read as money
 * would be the worst of both.
 *
 * Bars, not a line: these are discrete daily totals with real zeros in
 * them, and a line drawn through a zero day claims the value passed
 * through nothing on its way somewhere.
 *
 * One series, so no legend — the heading names it.
 */

// Measured against the frosted panel, which composites to about #cfdade
// over the page and #d0e8ec over the cyan glow: 3.35:1 and 3.73:1, both
// past the 3:1 minimum for a large mark.
const BAR = "#4474b4";
// Today, picked out so the eye lands on it first without needing a label.
const BAR_LATEST = "#2c5680";
const GRID = "rgba(16, 42, 67, 0.14)";

function shortDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** A round tick above the tallest bar, so the axis reads in human
 * numbers rather than "3,471". */
function niceCeiling(max: number): number {
  if (max <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  for (const step of [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10]) {
    if (magnitude * step >= max) return magnitude * step;
  }
  return magnitude * 10;
}

function compact(value: number): string {
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}k`;
  return String(Math.round(value));
}

export function CollectionsTrendChart({ points }: { points: AdminDailyCollectionPoint[] }) {
  const titleId = useId();
  const summaryId = useId();
  const [hovered, setHovered] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  // A day whose request failed is a gap, never a zero bar. A zero bar is
  // a claim that nothing came in that day.
  const known = useMemo(() => points.filter((p) => p.count !== null), [points]);
  const missing = points.length - known.length;

  const ceiling = useMemo(
    () => niceCeiling(Math.max(...known.map((p) => p.count ?? 0), 0)),
    [known],
  );

  const total = known.reduce((sum, p) => sum + (p.count ?? 0), 0);
  const best = known.reduce<AdminDailyCollectionPoint | null>(
    (top, p) => (top === null || (p.count ?? 0) > (top.count ?? 0) ? p : top),
    null,
  );

  const summary =
    known.length === 0
      ? "Daily collection counts could not be loaded."
      : `${total.toLocaleString()} successful collection${total === 1 ? "" : "s"} over ${known.length} day${
          known.length === 1 ? "" : "s"
        }${best && (best.count ?? 0) > 0 ? `, busiest on ${shortDate(best.date)}` : ""}.${
          missing > 0 ? ` ${missing} day${missing === 1 ? "" : "s"} unavailable.` : ""
        }`;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="min-w-0">
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
            <div className="flex flex-col justify-between text-[10px] text-on-surface-variant tabular-nums h-56 shrink-0 text-right w-11">
              <span>{compact(ceiling)}</span>
              <span>{compact(ceiling / 2)}</span>
              <span>0</span>
            </div>

            <div
              className="relative flex-1 flex items-end gap-1.5 h-56 border-b border-outline-variant"
              role="img"
              aria-labelledby={`${titleId} ${summaryId}`}
            >
              <div aria-hidden className="absolute inset-x-0 top-0" style={{ borderTop: `1px solid ${GRID}` }} />
              <div aria-hidden className="absolute inset-x-0 top-1/2" style={{ borderTop: `1px solid ${GRID}` }} />

              {points.map((point, index) => {
                const isLatest = index === points.length - 1;
                const unavailable = point.count === null;
                const height = unavailable ? 0 : ((point.count ?? 0) / ceiling) * 100;
                return (
                  <div
                    key={point.date}
                    className="relative flex-1 min-w-0 flex items-end justify-center h-full"
                    onMouseEnter={() => setHovered(index)}
                    onMouseLeave={() => setHovered(null)}
                    onFocus={() => setHovered(index)}
                    onBlur={() => setHovered(null)}
                    tabIndex={0}
                    // The hit target is the whole column, not the bar,
                    // so a short day is as easy to reach as a tall one.
                    aria-label={
                      unavailable
                        ? `${shortDate(point.date)}: unavailable`
                        : `${shortDate(point.date)}: ${(point.count ?? 0).toLocaleString()} collections`
                    }
                  >
                    {hovered === index && (
                      <div className="absolute bottom-full mb-2 z-10 whitespace-nowrap rounded-md bg-[#0b2738] px-2.5 py-1.5 text-[11px] font-medium text-white shadow-lg">
                        <span className="block opacity-80">{shortDate(point.date)}</span>
                        {unavailable ? "Unavailable" : `${(point.count ?? 0).toLocaleString()} collections`}
                      </div>
                    )}
                    {unavailable ? (
                      // A hatched stub, so a failed day is visibly not a
                      // quiet day.
                      <div
                        className="w-full rounded-t-[4px] h-1.5"
                        style={{
                          background:
                            "repeating-linear-gradient(45deg, rgba(16,42,67,0.28) 0 3px, transparent 3px 6px)",
                        }}
                      />
                    ) : (
                      <div
                        className="w-full rounded-t-[4px] transition-[height] duration-300"
                        style={{
                          height: `${Math.max(height, (point.count ?? 0) > 0 ? 2 : 0)}%`,
                          backgroundColor: isLatest ? BAR_LATEST : BAR,
                        }}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="flex gap-2 mt-2">
            <div className="w-11 shrink-0" />
            <div className="flex-1 flex gap-1.5">
              {points.map((point, index) => (
                <div
                  key={point.date}
                  className="flex-1 min-w-0 text-center text-[10px] text-on-surface-variant truncate"
                >
                  {/* Every other label on a 14-day window, so they do not
                      collide at narrow widths. */}
                  {index % 2 === 0 || index === points.length - 1 ? shortDate(point.date) : ""}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {showTable && (
        <div className="mt-4 max-h-56 overflow-auto rounded-lg border border-outline-variant">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Successful collections per day</caption>
            <thead className="sticky top-0 bg-surface-container-high">
              <tr className="text-xs font-semibold text-on-surface-variant">
                <th className="px-3 py-2">Day</th>
                <th className="px-3 py-2 text-right">Collections</th>
              </tr>
            </thead>
            <tbody>
              {points.map((point) => (
                <tr key={point.date} className="border-t border-outline-variant">
                  <td className="px-3 py-2">{shortDate(point.date)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {point.count === null ? "Unavailable" : point.count.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
