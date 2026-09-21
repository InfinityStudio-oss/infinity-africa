"use client";

import { useEffect, useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { TransactionDetailDrawer } from "@/components/merchant/transaction-detail-drawer";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { listMyRiskAlerts, listTransactions } from "@/lib/portal/api";
import { transactionStatusBadge, transactionTypeBadge } from "@/lib/portal/status-tones";
import type { Transaction } from "@/lib/portal/types";

const OPEN_ALERT_STATUSES = new Set(["OPEN", "UNDER_REVIEW", "DOCUMENTS_REQUESTED", "ESCALATED"]);

const CSV_HEADER = [
  "Date",
  "Type",
  "Transaction ID",
  "Reference",
  "Provider Reference",
  "Channel",
  "Opening Balance",
  "Amount",
  "Charge",
  "Net",
  "Closing Balance",
  "Currency",
  "Direction",
  "Status",
];

function csvCell(value: string): string {
  // Quote every cell and escape embedded quotes — simplest way to stay
  // correct for references/channels that might contain a comma.
  return `"${value.replace(/"/g, '""')}"`;
}

function transactionsToCsv(transactions: Transaction[]): string {
  const rows = transactions.map((transaction) => {
    const positive = transaction.type === "collection";
    const amount = `${positive ? "+" : "-"}${transaction.gross_amount}`;
    return [
      formatDateTime(transaction.created_at),
      transaction.type,
      transaction.id,
      transaction.reference,
      transaction.provider_reference ?? "",
      transaction.method,
      transaction.balance_before ?? "",
      amount,
      transaction.fee_amount,
      transaction.net_amount,
      transaction.balance_after ?? "",
      transaction.currency,
      transaction.direction ?? "",
      transaction.status,
    ]
      .map(csvCell)
      .join(",");
  });
  return [CSV_HEADER.map(csvCell).join(","), ...rows].join("\r\n");
}

function money(value: string | null, currency: string): string {
  return value === null ? "Not available" : formatCurrency(value, currency);
}

export default function TransactionsPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [flaggedTransactionIds, setFlaggedTransactionIds] = useState<Set<string>>(new Set());
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);

  useEffect(() => {
    listTransactions().then(setTransactions);
    listMyRiskAlerts().then((alerts) => {
      setFlaggedTransactionIds(
        new Set(alerts.filter((a) => a.transaction_id && OPEN_ALERT_STATUSES.has(a.status)).map((a) => a.transaction_id as string)),
      );
    });
  }, []);

  function handleExportCsv() {
    const blob = new Blob([transactionsToCsv(transactions)], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `infinity-africa-transactions-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Transactions"
        description="A unified ledger of every collection, withdrawal, and fee."
        action={
          <button
            type="button"
            onClick={handleExportCsv}
            disabled={transactions.length === 0}
            className="flex items-center gap-2 bg-surface border border-outline-variant text-on-surface px-4 py-2.5 rounded-lg text-sm font-medium hover:bg-surface-container-low transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Icon name="download" className="text-[18px]" />
            Export CSV
          </button>
        }
      />

      {flaggedTransactionIds.size > 0 && (
        <Card className="border-error/40">
          <div className="flex items-start gap-3">
            <Icon name="gpp_maybe" className="text-error text-[22px] shrink-0" />
            <div>
              <h3 className="font-semibold text-on-background mb-1">Transaction under review</h3>
              <p className="text-sm text-on-surface-variant">
                Please submit supporting documents requested by InfinityPay for the flagged transaction(s) below. See{" "}
                <a href="/merchant/risk-monitoring" className="text-primary font-semibold hover:underline">
                  Risk Monitoring
                </a>{" "}
                for details.
              </p>
            </div>
          </div>
        </Card>
      )}

      <Card>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Type</label>
            <select className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm">
              <option>All Types</option>
              <option>Collection</option>
              <option>Withdrawal</option>
              <option>Fee</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Status</label>
            <select className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm">
              <option>All Statuses</option>
              <option>Success</option>
              <option>Pending</option>
              <option>Failed</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5">From</label>
            <input className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm" type="date" defaultValue="2026-08-01" />
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5">To</label>
            <input className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm" type="date" defaultValue="2026-08-13" />
          </div>
        </div>
      </Card>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">All Transactions</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[1440px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Date</th>
                <th className={thClass}>Type</th>
                <th className={thClass}>Transaction ID</th>
                <th className={thClass}>Reference</th>
                <th className={thClass}>Provider Reference</th>
                <th className={thClass}>Method</th>
                <th className={thClass}>Opening Balance</th>
                <th className={thClass}>Amount</th>
                <th className={thClass}>Charge</th>
                <th className={thClass}>Net</th>
                <th className={thClass}>Closing Balance</th>
                <th className={thClass}>Status</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {transactions.map((transaction) => {
                const typeBadge = transactionTypeBadge(transaction.type);
                const statusBadge = transactionStatusBadge(transaction.status);
                const positive = transaction.type === "collection";
                return (
                  <tr
                    key={transaction.id}
                    onClick={() => setSelectedTransaction(transaction)}
                    className="border-t border-surface-container-highest cursor-pointer hover:bg-surface-container-low transition-colors"
                  >
                    <td className={`${tdClass} text-on-surface-variant text-xs whitespace-nowrap`}>{formatDateTime(transaction.created_at)}</td>
                    <td className={tdClass}>
                      <StatusBadge {...typeBadge} />
                    </td>
                    <td className={`${tdClass} font-mono text-xs text-on-surface-variant`}>{transaction.id.slice(0, 8)}</td>
                    <td className={`${tdClass} font-mono text-sm text-on-background`}>
                      {transaction.reference}
                      {flaggedTransactionIds.has(transaction.id) && (
                        <Icon name="gpp_maybe" className="text-error text-[16px] ml-1.5 align-text-bottom" />
                      )}
                    </td>
                    <td className={`${tdClass} font-mono text-xs text-on-surface-variant`}>{transaction.provider_reference ?? "—"}</td>
                    <td className={`${tdClass} text-on-surface-variant whitespace-nowrap`}>{transaction.method}</td>
                    <td className={`${tdClass} text-on-surface-variant whitespace-nowrap`}>
                      {money(transaction.balance_before, transaction.currency)}
                    </td>
                    <td className={`${tdClass} font-semibold ${positive ? "text-primary" : "text-on-background"} whitespace-nowrap`}>
                      {positive ? "+" : "-"}
                      {formatCurrency(transaction.gross_amount, transaction.currency)}
                    </td>
                    <td className={`${tdClass} text-on-surface-variant whitespace-nowrap`}>
                      {formatCurrency(transaction.fee_amount, transaction.currency)}
                    </td>
                    <td className={`${tdClass} whitespace-nowrap`}>{formatCurrency(transaction.net_amount, transaction.currency)}</td>
                    <td className={`${tdClass} font-semibold text-on-background whitespace-nowrap`}>
                      {money(transaction.balance_after, transaction.currency)}
                    </td>
                    <td className={tdClass}>
                      <StatusBadge {...statusBadge} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <TransactionDetailDrawer transaction={selectedTransaction} onClose={() => setSelectedTransaction(null)} />
    </div>
  );
}
