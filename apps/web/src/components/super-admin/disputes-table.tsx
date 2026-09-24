"use client";

import { Fragment, useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import {
  requestRefundForDisputeAction,
  updateDisputeStatusAction,
  updateRefundStatusAction,
} from "@/lib/admin/live-actions";
import type { AdminDisputeRow, DisputeStatus } from "@/lib/admin/types";

const STATUS_OPTIONS: DisputeStatus[] = [
  "SUBMITTED",
  "MERCHANT_NOTIFIED",
  "UNDER_REVIEW",
  "REFUND_REQUESTED",
  "REFUNDED",
  "REJECTED",
  "CLOSED",
];

const REFUND_STATUS_OPTIONS = ["APPROVED", "PROCESSING", "SUCCESS", "FAILED", "CANCELLED"];

export function DisputesTable({ rows }: { rows: AdminDisputeRow[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <Card padded={false}>
      <div className="p-5 pb-3">
        <h3 className="text-2xl font-semibold text-on-background">All Disputes</h3>
      </div>
      {rows.length === 0 ? (
        <p className="p-6 text-sm text-on-surface-variant">No disputes have been reported.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[1000px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Merchant</th>
                <th className={thClass}>Customer</th>
                <th className={thClass}>Transaction Ref</th>
                <th className={thClass}>Amount</th>
                <th className={thClass}>Reason</th>
                <th className={thClass}>Status</th>
                <th className={thClass}>Created</th>
                <th className={`${thClass} text-right`}>Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {rows.map((dispute) => (
                <Fragment key={dispute.dispute_id}>
                  <tr className="border-t border-surface-container-highest">
                    <td className={tdClass}>
                      <div className="font-medium text-on-background">{dispute.merchant_name ?? "Unmatched"}</div>
                      {dispute.merchant_code && (
                        <div className="font-mono text-xs text-on-surface-variant">{dispute.merchant_code}</div>
                      )}
                    </td>
                    <td className={tdClass}>
                      {dispute.customer_name}
                      <div className="text-xs text-on-surface-variant">{dispute.customer_phone}</div>
                    </td>
                    <td className={`${tdClass} font-mono text-xs`}>{dispute.transaction_reference ?? "—"}</td>
                    <td className={tdClass}>{dispute.amount ? formatCurrency(dispute.amount, "TZS") : "—"}</td>
                    <td className={tdClass}>{dispute.reason_category.replace(/_/g, " ")}</td>
                    <td className={tdClass}>
                      <StatusBadge label={dispute.status.replace(/_/g, " ")} tone="neutral" />
                    </td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(dispute.created_at)}</td>
                    <td className={`${tdClass} text-right`}>
                      <button
                        onClick={() => setExpanded(expanded === dispute.dispute_id ? null : dispute.dispute_id)}
                        className="inline-flex items-center gap-1 text-primary text-xs font-semibold hover:underline"
                      >
                        {expanded === dispute.dispute_id ? "Hide" : "Manage"}
                        <Icon name={expanded === dispute.dispute_id ? "expand_less" : "expand_more"} className="text-[16px]" />
                      </button>
                    </td>
                  </tr>
                  {expanded === dispute.dispute_id && (
                    <tr className="border-t border-surface-container-highest">
                      <td colSpan={8} className="p-0">
                        <div className="p-5 bg-surface-container-low space-y-4">
                          <p className="text-sm text-on-surface">{dispute.description}</p>

                          <form action={updateDisputeStatusAction.bind(null, dispute.dispute_id)} className="flex flex-wrap items-center gap-2">
                            <select name="status" defaultValue={dispute.status} className="px-3 py-2 bg-surface border border-surface-container-highest rounded-lg text-xs">
                              {STATUS_OPTIONS.map((option) => (
                                <option key={option} value={option}>
                                  {option.replace(/_/g, " ")}
                                </option>
                              ))}
                            </select>
                            <input
                              name="note"
                              placeholder="Note to business (optional)"
                              className="px-3 py-2 bg-surface border border-surface-container-highest rounded-lg text-xs w-64"
                            />
                            <button type="submit" className="bg-primary-container text-on-primary text-xs font-semibold py-2 px-4 rounded-lg hover:opacity-90">
                              Update &amp; Notify Merchant
                            </button>
                          </form>

                          {dispute.transaction_id && (
                            <form action={requestRefundForDisputeAction.bind(null, dispute.dispute_id)} className="flex flex-wrap items-center gap-2">
                              <input
                                name="amount"
                                placeholder="Refund amount"
                                className="px-3 py-2 bg-surface border border-surface-container-highest rounded-lg text-xs w-40"
                              />
                              <button type="submit" className="bg-white border border-primary text-primary text-xs font-semibold py-2 px-4 rounded-lg hover:bg-primary-container/10">
                                Request Refund
                              </button>
                            </form>
                          )}

                          {dispute.status === "REFUND_REQUESTED" && (
                            <form action={updateRefundStatusAction.bind(null, dispute.dispute_id)} className="flex flex-wrap items-center gap-2">
                              <select name="status" defaultValue="SUCCESS" className="px-3 py-2 bg-surface border border-surface-container-highest rounded-lg text-xs">
                                {REFUND_STATUS_OPTIONS.map((option) => (
                                  <option key={option} value={option}>
                                    {option}
                                  </option>
                                ))}
                              </select>
                              <button type="submit" className="border border-outline-variant text-on-surface-variant text-xs font-semibold py-2 px-4 rounded-lg hover:bg-surface-container-highest">
                                Mark Refund Status
                              </button>
                            </form>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
