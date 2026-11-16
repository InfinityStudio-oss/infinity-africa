"use client";

import Link from "next/link";

import { Icon } from "@/components/portal/icon";
import { StatusBadge } from "@/components/portal/status-badge";
import type { BadgeTone } from "@/components/portal/status-badge";

export type DateRangeKey = "7d" | "30d" | "custom";

/**
 * The greeting line.
 *
 * Africa/Dar_es_Salaam, not the browser's zone: a merchant checking their
 * takings from abroad is still running a Tanzanian business, and "Good
 * evening" at 9am local would be the portal telling them it does not know
 * where they are. Computed from the Intl API rather than an offset
 * constant so it cannot drift if the zone ever gains a rule.
 */
export function greetingFor(now: Date = new Date()): string {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Africa/Dar_es_Salaam",
      hour: "numeric",
      hour12: false,
    }).format(now),
  );
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

/**
 * The name shown is the MERCHANT's, never the signed-in person's.
 *
 * Staff share a merchant account; greeting a cashier by their own name on
 * a page showing the business's money reads as a personal balance. It
 * also has to change when someone switches merchants, which it does here
 * by being a prop rather than anything cached.
 */
export function displayNameFor(businessName: string | null | undefined): string | null {
  const trimmed = businessName?.trim();
  return trimmed ? trimmed : null;
}

const STATUS_TONE: Record<string, BadgeTone> = {
  VERIFIED: "positive",
  ACTIVE: "positive",
  PENDING_VERIFICATION: "pending",
  UNVERIFIED: "pending",
  SUSPENDED: "negative",
  REJECTED: "negative",
};

const STATUS_LABEL: Record<string, string> = {
  VERIFIED: "Verified",
  ACTIVE: "Verified",
  PENDING_VERIFICATION: "Under review",
  UNVERIFIED: "Not verified",
  SUSPENDED: "Suspended",
  REJECTED: "Action needed",
};

const NEEDS_ATTENTION = new Set(["PENDING_VERIFICATION", "UNVERIFIED", "REJECTED", "SUSPENDED"]);

const RANGES: { key: DateRangeKey; label: string }[] = [
  { key: "7d", label: "Last 7 days" },
  { key: "30d", label: "Last 30 days" },
  { key: "custom", label: "Custom" },
];

export function OverviewHeader({
  businessName,
  accountStatus,
  range,
  onRangeChange,
  customStart,
  customEnd,
  onCustomChange,
  canCreatePaymentLink,
  now,
}: {
  businessName: string | null | undefined;
  accountStatus: string | null | undefined;
  range: DateRangeKey;
  onRangeChange: (range: DateRangeKey) => void;
  customStart: string;
  customEnd: string;
  onCustomChange: (start: string, end: string) => void;
  canCreatePaymentLink: boolean;
  /** Injectable so the greeting can be tested at a fixed hour. */
  now?: Date;
}) {
  const name = displayNameFor(businessName);
  const status = accountStatus ?? undefined;
  const needsAttention = status ? NEEDS_ATTENTION.has(status) : false;

  return (
    <header className="space-y-4">
      <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-2xl font-bold text-on-surface truncate">
              {name ? `${greetingFor(now)}, ${name}` : "Welcome to InfinityPay"}
            </h1>
            {status && (
              <StatusBadge
                label={STATUS_LABEL[status] ?? status.replace(/_/g, " ").toLowerCase()}
                tone={STATUS_TONE[status] ?? "neutral"}
                dot
              />
            )}
          </div>
          {needsAttention && (
            <Link
              href="/onboarding"
              className="mt-1.5 inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              {status === "SUSPENDED"
                ? "Contact support to restore your account"
                : "Finish setting up your account"}
              <Icon name="arrow_forward" className="text-[16px]" />
            </Link>
          )}
        </div>

        {canCreatePaymentLink && (
          <Link
            href="/dashboard/pay-by-link"
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary text-on-primary px-4 py-2.5 text-sm font-semibold shrink-0 hover:opacity-90 transition-opacity"
          >
            <Icon name="add_link" className="text-[18px]" />
            Create Payment Link
          </Link>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div
          role="group"
          aria-label="Reporting period"
          className="inline-flex rounded-lg border border-outline-variant bg-surface p-0.5"
        >
          {RANGES.map((option) => (
            <button
              key={option.key}
              type="button"
              aria-pressed={range === option.key}
              onClick={() => onRangeChange(option.key)}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                range === option.key
                  ? "bg-primary text-on-primary"
                  : "text-on-surface-variant hover:text-on-surface"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>

        {range === "custom" && (
          <div className="flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor="overview-start">
              Start date
            </label>
            <input
              id="overview-start"
              type="date"
              value={customStart}
              max={customEnd}
              onChange={(event) => onCustomChange(event.target.value, customEnd)}
              className="px-2.5 py-1.5 rounded-lg border border-outline-variant bg-surface text-sm text-on-surface"
            />
            <span className="text-sm text-on-surface-variant">to</span>
            <label className="sr-only" htmlFor="overview-end">
              End date
            </label>
            <input
              id="overview-end"
              type="date"
              value={customEnd}
              min={customStart}
              onChange={(event) => onCustomChange(customStart, event.target.value)}
              className="px-2.5 py-1.5 rounded-lg border border-outline-variant bg-surface text-sm text-on-surface"
            />
          </div>
        )}
      </div>
    </header>
  );
}
