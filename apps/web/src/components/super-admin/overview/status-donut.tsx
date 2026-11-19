"use client";

import { useId, useState } from "react";

import type { AdminCollectionStatus } from "@/lib/admin/live-api";

/**
 * How collections are split across their statuses, platform-wide.
 *
 * A doughnut rather than a pie because the centre earns its keep: it
 * holds the total the segments are parts of, which is the number a
 * Super Admin reads first.
 *
 * Every segment is a real `meta.total` for that status filter, so these
 * are the same figures the Collections page shows under the same filter
 * — not a sample, and not derived from a capped page.
 *
 * **Never colour alone.** Each segment is named in the legend with its
 * count and share, and a status that is zero is dropped rather than
 * drawn as an invisible sliver. These are status colours, so the label
 * carries the meaning and the colour only helps you find the label.
 */

// Validated with the dataviz palette checker against the frosted panel
// (composites to ~#cfdade): all four pass the lightness band, the chroma
// floor, CVD separation, the normal-vision floor, and 3:1 contrast.
//
// The ORDER is part of the result, not a preference. Amber beside
// crimson fails the normal-vision floor outright (ΔE 14.1), and green
// beside amber fails protanopia (ΔE 5.0). Putting blue between green and
// amber, and keeping crimson at the far end, is what makes the set pass.
// Reordering these without re-running the checker will quietly break it.
const STATUS_STYLE: Record<AdminCollectionStatus, { colour: string; label: string }> = {
  successful: { colour: "#15803d", label: "Successful" },
  processing: { colour: "#1d4ed8", label: "Processing" },
  pending: { colour: "#a16207", label: "Pending" },
  failed: { colour: "#9f1239", label: "Failed" },
  reversed: { colour: "#6b21a8", label: "Reversed" },
  pending_review: { colour: "#0f766e", label: "Pending review" },
};

const RING_ORDER: AdminCollectionStatus[] = [
  "successful",
  "processing",
  "pending",
  "failed",
  "reversed",
  "pending_review",
];

const RADIUS = 56;
const STROKE = 22;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function CollectionStatusDonut({
  counts,
}: {
  counts: { status: AdminCollectionStatus; count: number | null }[];
}) {
  const titleId = useId();
  const summaryId = useId();
  const [hovered, setHovered] = useState<AdminCollectionStatus | null>(null);

  const byStatus = new Map(counts.map((entry) => [entry.status, entry.count]));
  const unavailable = counts.filter((entry) => entry.count === null).length;

  // Zero-count statuses are dropped: a platform with no reversals should
  // not carry a permanently empty legend row explaining what a reversal
  // would have been.
  const segments = RING_ORDER.map((status) => ({
    status,
    count: byStatus.get(status) ?? null,
    ...STATUS_STYLE[status],
  })).filter((segment) => (segment.count ?? 0) > 0);

  const total = segments.reduce((sum, segment) => sum + (segment.count ?? 0), 0);

  const summary =
    total === 0
      ? "No collection status data available."
      : segments
          .map((segment) => `${segment.label} ${(((segment.count ?? 0) / total) * 100).toFixed(1)}%`)
          .join(", ");

  let offset = 0;

  return (
    <div className="flex h-full flex-col">
      <h2 id={titleId} className="text-base font-semibold text-on-surface">
        Transaction status
      </h2>
      <p id={summaryId} className="mt-0.5 text-sm text-on-surface-variant">
        {total === 0
          ? "Could not be loaded."
          : `${total.toLocaleString()} collection${total === 1 ? "" : "s"} all time.`}
        {unavailable > 0 && total > 0 ? ` ${unavailable} status unavailable.` : ""}
      </p>

      {total === 0 ? (
        <p className="mt-6 text-sm text-on-surface-variant">Data unavailable.</p>
      ) : (
        <>
          <div className="mt-4 flex justify-center">
            <svg
              viewBox="0 0 160 160"
              className="h-40 w-40"
              role="img"
              aria-labelledby={`${titleId} ${summaryId}`}
            >
              {/* The track, so the ring reads as a whole even when one
                  status dominates it. */}
              <circle
                cx="80"
                cy="80"
                r={RADIUS}
                fill="none"
                stroke="rgba(16, 42, 67, 0.10)"
                strokeWidth={STROKE}
              />
              {segments.map((segment) => {
                const share = (segment.count ?? 0) / total;
                const length = share * CIRCUMFERENCE;
                // A 2px surface-coloured gap between neighbouring fills,
                // so two segments never touch and blur into one shape.
                const dash = `${Math.max(length - 2, 0.5)} ${CIRCUMFERENCE - Math.max(length - 2, 0.5)}`;
                const rotation = (offset / CIRCUMFERENCE) * 360 - 90;
                offset += length;
                const dim = hovered !== null && hovered !== segment.status;
                return (
                  <circle
                    key={segment.status}
                    cx="80"
                    cy="80"
                    r={RADIUS}
                    fill="none"
                    stroke={segment.colour}
                    strokeWidth={hovered === segment.status ? STROKE + 4 : STROKE}
                    strokeDasharray={dash}
                    transform={`rotate(${rotation} 80 80)`}
                    opacity={dim ? 0.45 : 1}
                    style={{ transition: "opacity 150ms, stroke-width 150ms" }}
                  />
                );
              })}
              <text
                x="80"
                y="74"
                textAnchor="middle"
                className="fill-on-surface"
                style={{ fontSize: 22, fontWeight: 700 }}
              >
                {segments[0] ? `${(((segments[0].count ?? 0) / total) * 100).toFixed(0)}%` : "—"}
              </text>
              <text
                x="80"
                y="92"
                textAnchor="middle"
                className="fill-on-surface-variant"
                style={{ fontSize: 10 }}
              >
                {segments[0]?.label ?? ""}
              </text>
            </svg>
          </div>

          <ul className="mt-4 space-y-1.5">
            {segments.map((segment) => (
              <li
                key={segment.status}
                className="flex items-center justify-between gap-3 rounded-md px-1.5 py-1 text-sm"
                onMouseEnter={() => setHovered(segment.status)}
                onMouseLeave={() => setHovered(null)}
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden
                    className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
                    style={{ backgroundColor: segment.colour }}
                  />
                  <span className="truncate text-on-surface">{segment.label}</span>
                </span>
                <span className="shrink-0 tabular-nums text-on-surface-variant">
                  {(segment.count ?? 0).toLocaleString()}
                  <span className="ml-1.5 text-on-surface font-medium">
                    {(((segment.count ?? 0) / total) * 100).toFixed(1)}%
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
