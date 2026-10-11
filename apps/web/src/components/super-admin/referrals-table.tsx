"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { tdClass, thClass } from "@/components/portal/card";
import { StatusBadge, type BadgeTone } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import {
  approveReferralCommission,
  clearReferralFraudHold,
  markReferralCommissionPaid,
  rejectReferralCommission,
  setReferralFraudHold,
} from "@/lib/admin/live-api";
import type { AdminReferralRow } from "@/lib/admin/types";

const TONE: Record<string, BadgeTone> = {
  pending_signup: "pending",
  pending_approval: "pending",
  active: "info",
  qualified: "positive",
  commission_pending: "pending",
  commission_approved: "positive-solid",
  commission_paid: "positive-solid",
  commission_rejected: "negative",
  fraud_hold: "negative",
  ineligible: "negative",
  expired: "neutral",
};

/** The states that still need a decision, so the queue opens on the work
 * rather than on a wall of settled history. */
const NEEDS_ACTION = new Set(["commission_pending", "fraud_hold"]);

function label(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function ReferralsTable({ rows }: { rows: AdminReferralRow[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const actionable = useMemo(() => rows.filter((r) => NEEDS_ACTION.has(r.status)), [rows]);
  const [filter, setFilter] = useState<"needs_action" | "all">(
    actionable.length > 0 ? "needs_action" : "all",
  );

  const visible = filter === "needs_action" ? actionable : rows;

  async function run(key: string, action: () => Promise<void>) {
    setBusy(key);
    setError(null);
    try {
      await action();
      // Server component above holds the data; refresh re-fetches it.
      router.refresh();
    } catch (err) {
      // The backend's own message — "Only a commission pending review can
      // be approved", say — tells the reviewer what to do next.
      setError(err instanceof Error ? err.message : "That action failed. Try again.");
    } finally {
      setBusy(null);
    }
  }

  if (rows.length === 0) {
    return <p className="p-6 text-sm text-on-surface-variant">No referrals yet.</p>;
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 p-5 pb-3">
        {(
          [
            ["needs_action", `Needs action (${actionable.length})`],
            ["all", `All (${rows.length})`],
          ] as const
        ).map(([key, text]) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            aria-pressed={filter === key}
            className={`rounded-full px-3.5 py-1.5 text-xs font-semibold transition-colors ${
              filter === key
                ? "bg-primary-container text-on-primary"
                : "bg-surface-container-highest text-on-surface-variant hover:text-on-background"
            }`}
          >
            {text}
          </button>
        ))}
      </div>

      {error && (
        <p role="alert" className="mx-5 mb-3 rounded-lg bg-error-container/10 px-3.5 py-2.5 text-sm text-error">
          {error}
        </p>
      )}

      {visible.length === 0 ? (
        <p className="px-6 pb-6 text-sm text-on-surface-variant">Nothing is waiting on a decision.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1180px] text-left">
            <thead>
              <tr className="border-t border-surface-container-highest text-xs font-semibold text-on-surface-variant">
                <th className={thClass}>Referrer</th>
                <th className={thClass}>Referred Business</th>
                <th className={thClass}>Referral Period</th>
                <th className={thClass}>Successful Volume</th>
                <th className={thClass}>InfinityPay Net Revenue</th>
                <th className={thClass}>Commission</th>
                <th className={thClass}>Status</th>
                <th className={`${thClass} text-right`}>Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {visible.map((row) => (
                <tr key={row.id} className="border-t border-surface-container-highest align-top">
                  <td className={tdClass}>
                    <div className="font-medium text-on-background">{row.referrer_name ?? "—"}</div>
                    <div className="font-mono text-xs text-on-surface-variant">{row.referral_code_used}</div>
                  </td>
                  <td className={tdClass}>
                    <div className="font-medium text-on-background">{row.referred_name ?? "—"}</div>
                    <div className="font-mono text-xs text-on-surface-variant">{row.referred_code ?? "—"}</div>
                  </td>
                  <td className={`${tdClass} text-on-surface-variant`}>
                    {row.referral_period_start_at ? (
                      <>
                        {formatDateTime(row.referral_period_start_at)}
                        <div className="text-xs">to {formatDateTime(row.referral_period_end_at ?? "")}</div>
                      </>
                    ) : (
                      <span className="italic">Not approved yet</span>
                    )}
                  </td>
                  <td className={tdClass}>
                    {row.successful_volume ? formatCurrency(row.successful_volume, row.currency) : "—"}
                    <div className="text-xs text-on-surface-variant">
                      needs {formatCurrency(row.qualification_volume_threshold, row.currency)}
                    </div>
                  </td>
                  <td className={tdClass}>
                    {row.infinitypay_net_revenue
                      ? formatCurrency(row.infinitypay_net_revenue, row.currency)
                      : "—"}
                  </td>
                  <td className={tdClass}>
                    <span className="font-semibold text-on-background">
                      {row.commission_amount ? formatCurrency(row.commission_amount, row.currency) : "—"}
                    </span>
                    <div className="text-xs text-on-surface-variant">
                      {(row.commission_rate_bps / 100).toFixed(0)}% of net revenue
                    </div>
                  </td>
                  <td className={tdClass}>
                    <StatusBadge label={label(row.status)} tone={TONE[row.status] ?? "neutral"} />
                    {row.fraud_flag_reason && (
                      <p className="mt-1 text-xs text-error">{row.fraud_flag_reason}</p>
                    )}
                  </td>
                  <td className={`${tdClass} text-right`}>
                    <div className="flex flex-col items-end gap-1.5">
                      {row.payout_eligible && row.commission_id && (
                        <button
                          type="button"
                          disabled={busy !== null}
                          onClick={() =>
                            run(row.id, () => approveReferralCommission(row.commission_id as string))
                          }
                          className="text-xs font-semibold text-primary-container hover:underline disabled:opacity-60"
                        >
                          Approve
                        </button>
                      )}
                      {row.commission_id && row.commission_status === "approved" && (
                        <button
                          type="button"
                          disabled={busy !== null}
                          onClick={() =>
                            run(row.id, () => markReferralCommissionPaid(row.commission_id as string))
                          }
                          className="text-xs font-semibold text-primary-container hover:underline disabled:opacity-60"
                        >
                          Mark paid
                        </button>
                      )}
                      {row.commission_id &&
                        ["pending_review", "approved"].includes(row.commission_status ?? "") && (
                          <button
                            type="button"
                            disabled={busy !== null}
                            onClick={() => {
                              const reason = window.prompt("Why is this commission being rejected?");
                              if (reason?.trim())
                                void run(row.id, () =>
                                  rejectReferralCommission(row.commission_id as string, reason.trim()),
                                );
                            }}
                            className="text-xs font-semibold text-error hover:underline disabled:opacity-60"
                          >
                            Reject
                          </button>
                        )}
                      {row.status === "fraud_hold" ? (
                        <button
                          type="button"
                          disabled={busy !== null}
                          onClick={() => run(row.id, () => clearReferralFraudHold(row.id))}
                          className="text-xs font-semibold text-on-surface-variant hover:underline disabled:opacity-60"
                        >
                          Clear hold
                        </button>
                      ) : (
                        <button
                          type="button"
                          disabled={busy !== null}
                          onClick={() => {
                            const reason = window.prompt("Why is this referral being held?");
                            if (reason?.trim())
                              void run(row.id, () => setReferralFraudHold(row.id, reason.trim()));
                          }}
                          className="text-xs font-semibold text-on-surface-variant hover:underline disabled:opacity-60"
                        >
                          Hold
                        </button>
                      )}
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
