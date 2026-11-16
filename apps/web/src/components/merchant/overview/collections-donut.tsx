"use client";

import Link from "next/link";
import { useId, useMemo, useState } from "react";

import { formatCurrency } from "@/lib/format";
import type { CollectionsByMethod } from "@/lib/portal/types";

/**
 * Collections split by payment method.
 *
 * The total sits in the centre because that is the number being broken
 * up - and because it is the same number the bar chart beside it totals
 * to. Both are built from one set of rows on the server for exactly that
 * reason; if these two ever disagree, the bug is upstream of this file.
 *
 * Colours are a fixed categorical order - blue, orange, teal, violet -
 * validated rather than chosen by eye: worst adjacent CVD Delta E 14.5
 * (target >= 8), normal-vision 25.4 (floor 15), all >= 3:1 against the
 * pale card. It opens with the two brand hues so the chart belongs to
 * the page. The teal was nudged from #0d8b80 to #0f9e90 because the
 * first measured 0.099 chroma - a hair under the floor, which is the
 * point where a slot starts reading as grey. The order is fixed, so
 * filtering or a slow month can never repaint the methods that remain.
 *
 * Identity is never colour alone: every slice is also named in the
 * legend with its share, and the table view carries the same numbers.
 */

const SLICE_COLORS = ["#2d4f91", "#d1600f", "#0f9e90", "#6b4fc4"];
// Past four, the rest fold into one slice rather than inventing a fifth
// hue. Neutral, because "Other" is not an identity - 4.76:1 on white.
const OTHER_COLOR = "#64748b";
const MAX_SLICES = 4;

const METHOD_LABELS: Record<string, string> = {
  MOBILE_MONEY: "Mobile money",
  CARD: "Card",
  BANK_TRANSFER: "Bank transfer",
  BANK_ACCOUNT: "Bank transfer",
  SELCOM_PESA: "Selcom Pesa",
  WALLET: "Wallet",
  UNKNOWN: "Unrecorded",
};

function label(method: string): string {
  return METHOD_LABELS[method] ?? method.replace(/_/g, " ").toLowerCase();
}

function compactTotal(value: number, currency: string): string {
  // Everything is abbreviated, including small amounts. The full
  // formatCurrency form ("TZS 1,000.00") is wider than the ring's hole
  // and collided with it; the exact figure is in the legend directly
  // below, so the centre only has to carry the magnitude.
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M ${currency}`;
  if (value >= 10_000) return `${Math.round(value / 1_000)}k ${currency}`;
  return `${Math.round(value).toLocaleString("en-US")} ${currency}`;
}

export function CollectionsDonut({
  byMethod,
  currency = "TZS",
  startDate,
  endDate,
}: {
  byMethod: CollectionsByMethod[];
  currency?: string;
  startDate?: string;
  endDate?: string;
}) {
  const titleId = useId();
  const summaryId = useId();
  const [hovered, setHovered] = useState<string | null>(null);

  const slices = useMemo(() => {
    const entries = byMethod.map((entry) => ({
      method: entry.method,
      amount: Number(entry.amount),
      count: entry.count,
    }));
    if (entries.length <= MAX_SLICES) return entries;
    const head = entries.slice(0, MAX_SLICES - 1);
    const tail = entries.slice(MAX_SLICES - 1);
    return [
      ...head,
      {
        method: "__other__",
        amount: tail.reduce((sum, e) => sum + e.amount, 0),
        count: tail.reduce((sum, e) => sum + e.count, 0),
      },
    ];
  }, [byMethod]);

  const total = slices.reduce((sum, slice) => sum + slice.amount, 0);

  const summary =
    total === 0
      ? "No collections in this period."
      : slices
          .map(
            (slice) =>
              `${slice.method === "__other__" ? "Other" : label(slice.method)} ${Math.round(
                (slice.amount / total) * 100,
              )}%`,
          )
          .join(", ") + ".";

  if (total === 0) {
    return (
      <div>
        <h2 className="text-base font-semibold text-on-surface">Collections by payment method</h2>
        <p className="mt-0.5 text-sm text-on-surface-variant">
          No collections in this period.
        </p>
        <div className="mt-8 flex items-center justify-center">
          <div
            className="w-36 h-36 rounded-full border-[11px] border-surface-container-highest"
            aria-hidden
          />
        </div>
      </div>
    );
  }

  // A conic gradient rather than SVG arcs: one element, no path maths,
  // and the 2px surface-coloured gaps between segments come free as hard
  // colour stops.
  let cursor = 0;
  const stops: string[] = [];
  const GAP_DEGREES = 2;
  slices.forEach((slice, index) => {
    const color = slice.method === "__other__" ? OTHER_COLOR : SLICE_COLORS[index % SLICE_COLORS.length];
    const sweep = (slice.amount / total) * 360;
    const start = cursor;
    const end = cursor + Math.max(sweep - GAP_DEGREES, 0.5);
    stops.push(`${color} ${start}deg ${end}deg`);
    stops.push(`transparent ${end}deg ${cursor + sweep}deg`);
    cursor += sweep;
  });

  return (
    <div>
      <h2 id={titleId} className="text-base font-semibold text-on-surface">
        Collections by payment method
      </h2>
      <p id={summaryId} className="mt-0.5 text-sm text-on-surface-variant">
        {summary}
      </p>

      <div className="mt-5 flex items-center justify-center">
        <div
          className="relative w-40 h-40"
          role="img"
          aria-labelledby={`${titleId} ${summaryId}`}
        >
          {/* The track. Without it a merchant who only uses one method
              sees a filled circle, which reads as a pie rather than a
              proportion of anything. */}
          <div className="absolute inset-0 rounded-full" style={{ background: "#e4edf8" }} aria-hidden />
          <div
            className="absolute inset-0 rounded-full"
            style={{ background: `conic-gradient(${stops.join(", ")})` }}
          />
          {/* The hole, in the card's own colour, with the total in it. */}
          <div className="absolute inset-[14%] rounded-full bg-surface flex flex-col items-center justify-center">
            <span className="text-[11px] text-on-surface-variant">Total</span>
            <span className="text-lg font-bold text-on-surface tabular-nums leading-tight text-center px-2">
              {compactTotal(total, currency)}
            </span>
          </div>
        </div>
      </div>

      <ul className="mt-5 space-y-1.5">
        {slices.map((slice, index) => {
          const color =
            slice.method === "__other__" ? OTHER_COLOR : SLICE_COLORS[index % SLICE_COLORS.length];
          const share = Math.round((slice.amount / total) * 100);
          const name = slice.method === "__other__" ? "Other methods" : label(slice.method);

          const row = (
            <>
              <span
                className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
                style={{ background: color }}
                aria-hidden
              />
              {/* The name takes the slack and the amount wraps beneath it
                  on a narrow screen. An earlier version pinned the amount
                  to a fixed width and then to shrink-0, which is what
                  pushed the whole page wider than a phone: a column that
                  cannot shrink does not truncate, it widens its parent. */}
              <span className="flex-1 min-w-0">
                <span className="block truncate text-on-surface">{name}</span>
                <span className="block sm:hidden tabular-nums text-xs text-on-surface-variant truncate">
                  {formatCurrency(String(slice.amount), currency)}
                </span>
              </span>
              <span className="tabular-nums text-on-surface-variant shrink-0">{share}%</span>
              <span className="hidden sm:block tabular-nums text-on-surface font-medium text-right shrink-0">
                {formatCurrency(String(slice.amount), currency)}
              </span>
            </>
          );

          // "Other" is several methods at once, so there is no single
          // filtered view to send anyone to. It stays plain text rather
          // than becoming a link that lies about where it goes.
          if (slice.method === "__other__") {
            return (
              <li key={slice.method} className="flex items-center gap-2 text-sm px-2 py-1.5">
                {row}
              </li>
            );
          }

          return (
            <li key={slice.method}>
              <Link
                href={{
                  pathname: "/portal/transactions",
                  query: {
                    method: slice.method,
                    ...(startDate ? { start_date: startDate } : {}),
                    ...(endDate ? { end_date: endDate } : {}),
                  },
                }}
                onMouseEnter={() => setHovered(slice.method)}
                onMouseLeave={() => setHovered(null)}
                className={`flex items-center gap-2 text-sm px-2 py-1.5 rounded-lg transition-colors ${
                  hovered === slice.method ? "bg-surface-container" : "hover:bg-surface-container"
                }`}
                aria-label={`View ${name} transactions for this period`}
              >
                {row}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
