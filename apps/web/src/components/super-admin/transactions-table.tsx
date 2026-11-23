"use client";

import { useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import type { BadgeProps } from "@/lib/portal/status-tones";
import { transactionStatusBadge } from "@/lib/portal/status-tones";
import type { AdminTransactionRow } from "@/lib/admin/types";

import { TransactionTrackingDrawer } from "./transaction-tracking-drawer";

function typeBadge(type: AdminTransactionRow["type"]): BadgeProps {
  switch (type) {
    case "collection":
      return { label: "Collection", tone: "positive", dot: true };
    case "disbursement":
      return { label: "Withdrawal", tone: "info" };
    case "payout":
      return { label: "Payout", tone: "info" };
    case "refund":
      return { label: "Refund", tone: "negative" };
    case "reversal":
      return { label: "Reversal", tone: "negative" };
    case "adjustment":
      return { label: "Adjustment", tone: "neutral" };
    case "fee":
      return { label: "Fee", tone: "neutral" };
  }
}

function money(value: string | null, currency: string): string {
  return value === null ? "Not available" : formatCurrency(value, currency);
}

export function TransactionsTable({
  transactions,
  filtered = false,
}: {
  transactions: AdminTransactionRow[];
  /** Whether a filter is narrowing this list. Wording only, but a
   * correctly filtered page headed "All Transactions" reads as one
   * that ignored the filter - which was reported as a broken filter
   * on the Collections screen. */
  filtered?: boolean;
}) {
  const [tracked, setTracked] = useState<AdminTransactionRow | null>(null);
  return (
    <>
    <Card padded={false}>
      <div className="p-5 pb-3">
        <h3 className="text-2xl font-semibold text-on-background">
          {filtered
            ? `Matching Transactions (${transactions.length.toLocaleString()})`
            : "All Transactions"}
        </h3>
      </div>
      {transactions.length === 0 ? (
        <p className="p-6 text-sm text-on-surface-variant">No transactions match these filters.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[1600px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Date</th>
                <th className={thClass}>Merchant</th>
                <th className={thClass}>Type</th>
                <th className={thClass}>Transaction ID</th>
                <th className={thClass}>Payment ID</th>
                <th className={thClass}>Reference</th>
                <th className={thClass}>Provider Reference</th>
                <th className={thClass}>Method</th>
                <th className={thClass}>Customer Phone</th>
                <th className={thClass}>Opening Balance</th>
                <th className={thClass}>Amount</th>
                <th className={thClass}>Charge</th>
                <th className={thClass}>Net</th>
                <th className={thClass}>Closing Balance</th>
                <th className={thClass}>Direction</th>
                <th className={thClass}>Status</th>
                <th className={thClass}>
                  <span className="sr-only">Tracking</span>
                </th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {transactions.map((transaction) => (
                <tr key={transaction.transaction_id} className="border-t border-surface-container-highest">
                  <td className={`${tdClass} text-on-surface-variant text-xs whitespace-nowrap`}>
                    {formatDateTime(transaction.created_at)}
                  </td>
                  <td className={tdClass}>
                    <div className="font-medium text-on-background">{transaction.merchant_name}</div>
                    {transaction.merchant_code && (
                      <div className="font-mono text-xs text-on-surface-variant">{transaction.merchant_code}</div>
                    )}
                  </td>
                  <td className={tdClass}>
                    <StatusBadge {...typeBadge(transaction.type)} />
                  </td>
                  <td className={`${tdClass} font-mono text-xs text-on-surface-variant`}>
                    {transaction.transaction_id.slice(0, 8)}
                  </td>
                  {/* The full id, not a prefix: this is the value a merchant
                    * reads out of their billing system, and an operator has
                    * to be able to match all of it. */}
                  <td className={`${tdClass} font-mono text-xs text-on-surface-variant whitespace-nowrap`}>
                    {transaction.collection_id ?? "—"}
                  </td>
                  <td className={`${tdClass} font-mono text-sm text-on-background`}>{transaction.reference}</td>
                  <td className={`${tdClass} font-mono text-xs text-on-surface-variant`}>
                    {transaction.provider_reference ?? "—"}
                  </td>
                  <td className={`${tdClass} text-on-surface-variant whitespace-nowrap`}>{transaction.method}</td>
                  {/* Shown so a phone search can be CHECKED against the
                    * number the operator was given. An em dash where
                    * there is no number, never a blank cell that could
                    * be mistaken for a match. */}
                  <td className={`${tdClass} font-mono text-xs text-on-surface-variant whitespace-nowrap`}>
                    {transaction.customer_phone ?? "—"}
                  </td>
                  <td className={`${tdClass} text-on-surface-variant whitespace-nowrap`}>
                    {money(transaction.balance_before, transaction.currency)}
                  </td>
                  <td className={`${tdClass} font-semibold text-on-background whitespace-nowrap`}>
                    {formatCurrency(transaction.gross_amount, transaction.currency)}
                  </td>
                  <td className={`${tdClass} text-on-surface-variant whitespace-nowrap`}>
                    {formatCurrency(transaction.fee_amount, transaction.currency)}
                  </td>
                  <td className={`${tdClass} whitespace-nowrap`}>
                    {formatCurrency(transaction.net_amount, transaction.currency)}
                  </td>
                  <td className={`${tdClass} font-semibold text-on-background whitespace-nowrap`}>
                    {money(transaction.balance_after, transaction.currency)}
                  </td>
                  <td className={tdClass}>
                    {transaction.direction ? (
                      <StatusBadge
                        label={transaction.direction === "credit" ? "Credit" : "Debit"}
                        tone={transaction.direction === "credit" ? "positive" : "neutral"}
                      />
                    ) : (
                      <span className="text-on-surface-variant text-xs">—</span>
                    )}
                  </td>
                  <td className={tdClass}>
                    <StatusBadge {...transactionStatusBadge(transaction.status)} />
                  </td>
                  <td className={tdClass}>
                    <button
                      type="button"
                      onClick={() => setTracked(transaction)}
                      className="text-sm font-medium text-primary hover:underline whitespace-nowrap"
                      aria-label={`Track payment ${transaction.reference}`}
                    >
                      Track
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
    {/* Outside the Card on purpose: .app-panel has backdrop-filter, which
      * makes it the containing block for position:fixed descendants, so a
      * drawer rendered inside it is clipped to the card instead of
      * covering the screen. */}
    <TransactionTrackingDrawer transaction={tracked} onClose={() => setTracked(null)} />
    </>
  );
}
