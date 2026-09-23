"use client";

import { Icon } from "@/components/portal/icon";
import { formatDateTime } from "@/lib/format";
import type { AdminTransactionRow } from "@/lib/admin/types";

const CSV_HEADER = [
  "Date",
  "Merchant",
  "ID",
  "Type",
  "Transaction ID",
  "Reference",
  "Provider Reference",
  "Method",
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
  return `"${value.replace(/"/g, '""')}"`;
}

function transactionsToCsv(transactions: AdminTransactionRow[]): string {
  const rows = transactions.map((transaction) => {
    const positive = transaction.type === "collection";
    const amount = `${positive ? "+" : "-"}${transaction.gross_amount}`;
    return [
      formatDateTime(transaction.created_at),
      transaction.merchant_name,
      transaction.merchant_code ?? "",
      transaction.type,
      transaction.transaction_id,
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

export function ExportTransactionsCsvButton({ transactions }: { transactions: AdminTransactionRow[] }) {
  function handleExportCsv() {
    const blob = new Blob([transactionsToCsv(transactions)], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `infinitypay-platform-transactions-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  return (
    <button
      type="button"
      onClick={handleExportCsv}
      disabled={transactions.length === 0}
      className="flex items-center gap-2 bg-surface border border-outline-variant text-on-surface px-4 py-2.5 rounded-lg text-sm font-medium hover:bg-surface-container-low transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <Icon name="download" className="text-[18px]" />
      Export CSV
    </button>
  );
}
