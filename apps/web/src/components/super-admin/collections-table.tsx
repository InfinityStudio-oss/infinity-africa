"use client";

import Link from "next/link";
import { useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { RefreshStatusButton } from "@/components/portal/refresh-status-button";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { refreshAdminCollectionStatusClient } from "@/lib/admin/refresh-collection-status-client";
import { adminCollectionBadge } from "@/lib/admin/status-tones";
import type { AdminCollectionRow } from "@/lib/admin/types";

/** Whether the merchant's own system was told about this payment.
 *
 * Super Admin is who gets asked "my customer paid and was never
 * connected", and this was the one screen that could not answer it — the
 * merchant could see the failure on their own page, the person fielding
 * the complaint could not. Success and error only: a delivery still
 * inside its ten-minute retry window is not yet news. */
function deliveryCell(row: AdminCollectionRow) {
  const state = row.webhook_delivery_status;
  if (!state) return <span className="text-xs text-on-surface-variant">—</span>;
  if (state === "delivered") {
    return <span className="text-xs text-on-surface-variant">Delivered</span>;
  }
  if (state === "failed") {
    const code = row.webhook_response_code;
    return (
      <span className="text-xs font-medium text-error">
        Not received{code ? ` · HTTP ${code}` : ""}
      </span>
    );
  }
  return <span className="text-xs text-on-surface-variant">Sending…</span>;
}

export function CollectionsTable({ collections: initialCollections }: { collections: AdminCollectionRow[] }) {
  const [collections, setCollections] = useState(initialCollections);
  // Once a collection has been manually refreshed, keep showing the
  // button + its result message even after the status flips away from
  // pending/processing — otherwise the row re-renders as resolved and
  // the outcome message (e.g. "Payment completed") never gets seen.
  const [refreshedIds, setRefreshedIds] = useState<Set<string>>(new Set());

  return (
    <Card padded={false}>
      <div className="p-5 pb-3">
        <h3 className="text-2xl font-semibold text-on-background">All Collections</h3>
      </div>
      {collections.length === 0 ? (
        <p className="p-6 text-sm text-on-surface-variant">No collections have been recorded yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[1500px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Merchant</th>
                <th className={thClass}>Source</th>
                <th className={thClass}>Phone</th>
                <th className={thClass}>Method / Channel</th>
                <th className={thClass}>Amount</th>
                <th className={thClass}>Fee</th>
                <th className={thClass}>Net</th>
                <th className={thClass}>Reference</th>
                <th className={thClass}>Order / Provider Ref</th>
                <th className={thClass}>Status</th>
                <th className={thClass}>Merchant notified</th>
                <th className={thClass}>Date</th>
                <th className={`${thClass} text-right`}>Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {collections.map((row) => {
                const needsRefresh =
                  row.status === "pending" || row.status === "processing" || refreshedIds.has(row.collection_id);
                return (
                  <tr key={row.collection_id} className="border-t border-surface-container-highest">
                    <td className={tdClass}>
                      <Link href={`/super-admin/merchants/${row.merchant_id}`} className="hover:underline">
                        <div className="text-on-background font-medium">{row.merchant_name}</div>
                        {row.merchant_code && (
                          <div className="font-mono text-xs text-on-surface-variant">{row.merchant_code}</div>
                        )}
                      </Link>
                    </td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{row.source ?? "—"}</td>
                    <td className={tdClass}>{row.phone ?? "—"}</td>
                    <td className={`${tdClass} text-on-surface-variant`}>
                      <div>{row.method}</div>
                      {row.channel && <div className="text-xs">{row.channel}</div>}
                    </td>
                    <td className={`${tdClass} font-semibold text-on-background`}>{formatCurrency(row.amount, row.currency)}</td>
                    <td className={`${tdClass} text-on-surface-variant`}>
                      {row.fee_amount ? formatCurrency(row.fee_amount, row.currency) : "—"}
                    </td>
                    <td className={`${tdClass} text-on-surface-variant`}>
                      {row.net_amount ? formatCurrency(row.net_amount, row.currency) : "—"}
                    </td>
                    <td className={`${tdClass} text-on-surface-variant text-xs font-mono`}>{row.merchant_reference ?? "—"}</td>
                    <td className={`${tdClass} text-on-surface-variant text-xs font-mono`}>
                      {row.order_id && <div>{row.order_id}</div>}
                      {row.provider_transid && <div>{row.provider_transid}</div>}
                      {row.provider_reference && <div>{row.provider_reference}</div>}
                      {!row.order_id && !row.provider_transid && !row.provider_reference && "—"}
                    </td>
                    <td className={tdClass}>
                      <StatusBadge {...adminCollectionBadge(row.status)} />
                      {(row.status === "failed" || row.status === "reversed") &&
                        (row.failure_reason || row.provider_payment_status) && (
                          <p className="text-xs text-on-surface-variant mt-1">
                            {row.failure_reason ?? row.provider_payment_status}
                          </p>
                        )}
                    </td>
                    <td className={tdClass}>{deliveryCell(row)}</td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(row.created_at)}</td>
                    <td className={`${tdClass} text-right`}>
                      {needsRefresh && (
                        <RefreshStatusButton
                          onRefresh={() => refreshAdminCollectionStatusClient(row.collection_id)}
                          onResult={(result) => {
                            setRefreshedIds((prev) => new Set(prev).add(row.collection_id));
                            setCollections((prev) =>
                              prev.map((c) => (c.collection_id === row.collection_id ? result : c)),
                            );
                          }}
                        />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
