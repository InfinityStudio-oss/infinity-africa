"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { tdClass, thClass } from "@/components/portal/card";
import { OnboardingReviewActions } from "@/components/super-admin/onboarding-review-actions";
import { StatusBadge, type BadgeTone } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import type { OnboardingSubmission } from "@/lib/onboarding/types";
import { ACCOUNT_STATUS_LABELS, AccountStatus, DOCUMENT_UPLOAD_STATUS_LABELS, SERVICE_NEEDED_LABELS } from "@infinity/shared";

const ACCOUNT_TONE: Record<AccountStatus, BadgeTone> = {
  [AccountStatus.PENDING_VERIFICATION]: "pending",
  [AccountStatus.VERIFIED]: "positive-solid",
  [AccountStatus.REJECTED]: "negative",
  [AccountStatus.INFO_REQUESTED]: "info",
};

const DOCUMENT_TONE: Record<string, BadgeTone> = {
  UPLOADED: "pending",
  VERIFIED: "positive",
  REJECTED: "negative",
};

/** The two states that are waiting on a Super Admin to do something. */
const ACTIONABLE: AccountStatus[] = [AccountStatus.PENDING_VERIFICATION, AccountStatus.INFO_REQUESTED];

type Filter = "NEEDS_REVIEW" | "ALL" | AccountStatus;

export function OnboardingTable({ rows }: { rows: OnboardingSubmission[] }) {
  const needsReview = useMemo(() => rows.filter((r) => ACTIONABLE.includes(r.review_status)), [rows]);

  /** Opens on the businesses waiting for a decision, when there are any.
   *
   * Every submission ever made lives in this one table, so after a few
   * dozen signups the one business awaiting approval sits below a screen
   * of already-verified ones, with nothing to scroll to and no badge to
   * search for. The KPI card above says how many are pending but cannot
   * take you to them. Landing on that subset is the whole job of this
   * page; "All" is one click away and keeps its full count. */
  const [filter, setFilter] = useState<Filter>(needsReview.length > 0 ? "NEEDS_REVIEW" : "ALL");

  const counts = useMemo(() => {
    const byStatus = (status: AccountStatus) => rows.filter((r) => r.review_status === status).length;
    return {
      NEEDS_REVIEW: needsReview.length,
      ALL: rows.length,
      [AccountStatus.VERIFIED]: byStatus(AccountStatus.VERIFIED),
      [AccountStatus.REJECTED]: byStatus(AccountStatus.REJECTED),
    };
  }, [rows, needsReview]);

  const visible = useMemo(() => {
    const matching =
      filter === "ALL"
        ? rows
        : filter === "NEEDS_REVIEW"
          ? needsReview
          : rows.filter((r) => r.review_status === filter);

    // Anything awaiting a decision floats to the top even under "All", so
    // the work is never below the fold. Newest first within each group,
    // matching the order the API already returns.
    return [...matching].sort((a, b) => {
      const aActionable = ACTIONABLE.includes(a.review_status) ? 0 : 1;
      const bActionable = ACTIONABLE.includes(b.review_status) ? 0 : 1;
      if (aActionable !== bActionable) return aActionable - bActionable;
      return b.submitted_at.localeCompare(a.submitted_at);
    });
  }, [rows, needsReview, filter]);

  if (rows.length === 0) {
    return <p className="p-6 text-sm text-on-surface-variant">No onboarding submissions yet.</p>;
  }

  const chips: { key: Filter; label: string; count: number }[] = [
    { key: "NEEDS_REVIEW", label: "Needs review", count: counts.NEEDS_REVIEW },
    { key: AccountStatus.VERIFIED, label: "Verified", count: counts[AccountStatus.VERIFIED] },
    { key: AccountStatus.REJECTED, label: "Rejected", count: counts[AccountStatus.REJECTED] },
    { key: "ALL", label: "All", count: counts.ALL },
  ];

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 p-5 pb-3">
        {chips.map((chip) => {
          const active = filter === chip.key;
          return (
            <button
              key={chip.key}
              type="button"
              onClick={() => setFilter(chip.key)}
              aria-pressed={active}
              className={`rounded-full px-3.5 py-1.5 text-xs font-semibold transition-colors ${
                active
                  ? "bg-primary-container text-on-primary"
                  : "bg-surface-container-highest text-on-surface-variant hover:text-on-background"
              }`}
            >
              {chip.label} ({chip.count})
            </button>
          );
        })}
      </div>

      {visible.length === 0 ? (
        <p className="px-6 pb-6 text-sm text-on-surface-variant">
          {filter === "NEEDS_REVIEW"
            ? "Nothing is waiting for a decision right now."
            : "No submissions with this status."}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[1100px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Business Name</th>
                <th className={thClass}>Owner Email</th>
                <th className={thClass}>Contact Phone</th>
                <th className={thClass}>Nature of Business</th>
                <th className={thClass}>Physical Address</th>
                <th className={thClass}>Services Needed</th>
                <th className={thClass}>Document Status</th>
                <th className={thClass}>Account Status</th>
                <th className={`${thClass} text-right`}>Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {visible.map((row) => (
                <tr key={row.id} className="border-t border-surface-container-highest align-top">
                  <td className={tdClass}>
                    <div className="font-medium text-on-background">{row.business_name}</div>
                    {row.merchant_code && (
                      <div className="font-mono text-xs text-on-surface-variant">{row.merchant_code}</div>
                    )}
                  </td>
                  <td className={`${tdClass} text-on-surface-variant`}>{row.owner_email}</td>
                  <td className={`${tdClass} text-on-surface-variant`}>{row.contact_phone ?? "—"}</td>
                  <td className={`${tdClass} text-on-surface-variant`}>{row.nature_of_business}</td>
                  <td className={`${tdClass} text-on-surface-variant`}>
                    {/* Both halves are optional in practice, and ", " on its
                        own reads as a rendering fault rather than a blank. */}
                    {[row.physical_address, row.region_city].filter(Boolean).join(", ") || "—"}
                  </td>
                  <td className={tdClass}>
                    <div className="flex flex-wrap gap-1 max-w-[220px]">
                      {row.services_needed.map((service) => (
                        <span
                          key={service}
                          className="inline-flex items-center rounded-full bg-surface-container-highest px-2 py-0.5 text-[11px] font-medium text-on-surface-variant"
                        >
                          {SERVICE_NEEDED_LABELS[service]}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className={tdClass}>
                    <StatusBadge label={DOCUMENT_UPLOAD_STATUS_LABELS[row.document_status]} tone={DOCUMENT_TONE[row.document_status]} />
                  </td>
                  <td className={tdClass}>
                    <StatusBadge label={ACCOUNT_STATUS_LABELS[row.review_status]} tone={ACCOUNT_TONE[row.review_status]} />
                    <p className="mt-1 text-[11px] text-outline">{formatDateTime(row.submitted_at)}</p>
                  </td>
                  <td className={`${tdClass} text-right`}>
                    <div className="flex flex-col items-end gap-2">
                      <Link
                        href={`/super-admin/onboarding/${row.id}`}
                        className="text-xs font-semibold text-primary-container hover:underline"
                      >
                        View
                      </Link>
                      <OnboardingReviewActions submissionId={row.id} variant="compact" />
                    </div>
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
