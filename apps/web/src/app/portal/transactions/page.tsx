"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { TRANSACTION_STATUS_LABELS, TransactionStatus } from "@infinity/shared";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { TransactionDetailDrawer } from "@/components/merchant/transaction-detail-drawer";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { listMyRiskAlerts, listTransactions } from "@/lib/portal/api";
import { transactionStatusBadge, transactionTypeBadge } from "@/lib/portal/status-tones";
import type { Transaction } from "@/lib/portal/types";

/** Shared by the four filter controls so they stay visually identical. */
const FILTER_CLASS =
  "w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary";

const OPEN_ALERT_STATUSES = new Set(["OPEN", "UNDER_REVIEW", "DOCUMENTS_REQUESTED", "ESCALATED"]);

const CSV_HEADER = [
  "Date",
  "Type",
  "Transaction ID",
  "Reference",
  "Provider Reference",
  "Channel",
  "Customer Phone",
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
      transaction.customer_phone ?? "",
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

  // Set by the topbar search box, which navigates here with the term
  // rather than filtering rows this page already holds — the endpoint is
  // paginated, so that would miss anything past the first page.
  const params = useSearchParams();
  const search = params.get("search") ?? "";
  const type = params.get("type") ?? "";
  const status = params.get("status") ?? "";
  const dateFrom = params.get("date_from") ?? "";
  const dateTo = params.get("date_to") ?? "";
  const router = useRouter();
  // The URL stays the single source of truth for every filter, so this
  // box and the topbar box cannot disagree about what is being
  // searched, and a filtered view can be linked to or reloaded.
  const [searchDraft, setSearchDraft] = useState(search);
  const [loading, setLoading] = useState(true);

  const anyFilter = Boolean(search || type || status || dateFrom || dateTo);

  /** Change one filter, keeping the rest. */
  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    const query = next.toString();
    router.push(query ? `/portal/transactions?${query}` : "/portal/transactions");
  }

  useEffect(() => {
    setSearchDraft(search);
  }, [search]);

  useEffect(() => {
    setLoading(true);
    listTransactions({ search, type, status, dateFrom, dateTo })
      .then(setTransactions)
      .finally(() => setLoading(false));
  }, [search, type, status, dateFrom, dateTo]);

  // Which transactions are under review does not depend on any filter,
  // so it is fetched once. It used to sit in the effect above, where
  // every filter change would have re-requested it for no reason.
  useEffect(() => {
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
    link.download = `infinitypay-transactions-${new Date().toISOString().slice(0, 10)}.csv`;
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
                Please submit supporting documents requested by InfinityPay for the flagged transaction(s) below.
                Contact support if you need details.
              </p>
            </div>
          </div>
        </Card>
      )}

      <Card>
        <form
          role="search"
          className="mb-4"
          onSubmit={(event) => {
            event.preventDefault();
            const term = searchDraft.trim();
            // Pushed to the URL rather than held here, so a found
            // payment can be linked to or reloaded, and so the topbar
            // box shows the same thing.
            router.push(term ? `/portal/transactions?search=${encodeURIComponent(term)}` : "/portal/transactions");
          }}
        >
          <label className="block text-sm font-medium text-on-surface-variant mb-1.5" htmlFor="transaction-search">
            Find a payment
          </label>
          <div className="relative">
            <Icon
              name="search"
              className="absolute left-3 top-1/2 -translate-y-1/2 text-outline pointer-events-none"
            />
            <input
              id="transaction-search"
              className="w-full pl-10 pr-4 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm text-on-surface placeholder-outline"
              type="search"
              placeholder="Customer phone, or the last 6 digits — or a reference"
              aria-label="Search transactions by customer phone or reference"
              value={searchDraft}
              onChange={(event) => {
                setSearchDraft(event.target.value);
                // Emptying the box restores the full ledger without
                // needing Enter; anything else waits, because a phone
                // search per keystroke is a dozen needless lookups.
                if (event.target.value.trim() === "" && search !== "") router.push("/portal/transactions");
              }}
            />
          </div>
        </form>
        {anyFilter && (
          <div className="flex justify-end mb-3">
            <button
              type="button"
              onClick={() => router.push("/portal/transactions")}
              className="text-sm font-medium text-primary hover:underline"
            >
              Clear filters
            </button>
          </div>
        )}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5" htmlFor="filter-type">
              Type
            </label>
            {/* Every type the ledger can hold, not the three this
              * offered before. A missing option is a question the
              * merchant cannot ask: payouts and refunds exist and were
              * both unfindable. Withdrawal and Payout are deliberately
              * separate — one is the merchant moving their own balance,
              * the other is the Disbursement API. */}
            <select
              id="filter-type"
              className={FILTER_CLASS}
              value={type}
              onChange={(event) => setFilter("type", event.target.value)}
            >
              <option value="">All Types</option>
              <option value="collection">Collection</option>
              <option value="disbursement">Withdrawal</option>
              <option value="payout">Payout (Disbursement API)</option>
              <option value="fee">Fee</option>
              <option value="refund">Refund</option>
              <option value="reversal">Reversal</option>
              <option value="adjustment">Adjustment</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5" htmlFor="filter-status">
              Status
            </label>
            {/* Labelled from the shared enum so these cannot drift from
              * what the backend accepts — "Success" here was not a
              * value the API has ever known. */}
            <select
              id="filter-status"
              className={FILTER_CLASS}
              value={status}
              onChange={(event) => setFilter("status", event.target.value)}
            >
              <option value="">All Statuses</option>
              {Object.values(TransactionStatus).map((value) => (
                <option key={value} value={value}>
                  {TRANSACTION_STATUS_LABELS[value]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5" htmlFor="filter-from">
              From
            </label>
            {/* No default date. The two hardcoded August dates that used
              * to sit here made the page look filtered to a range
              * nobody had chosen, while in fact filtering nothing. */}
            <input
              id="filter-from"
              className={FILTER_CLASS}
              type="date"
              max={dateTo || undefined}
              value={dateFrom}
              onChange={(event) => setFilter("date_from", event.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5" htmlFor="filter-to">
              To
            </label>
            <input
              id="filter-to"
              className={FILTER_CLASS}
              type="date"
              min={dateFrom || undefined}
              value={dateTo}
              onChange={(event) => setFilter("date_to", event.target.value)}
            />
          </div>
        </div>
      </Card>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">
            {anyFilter ? "Filtered Transactions" : "All Transactions"}
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[1590px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Date</th>
                <th className={thClass}>Type</th>
                <th className={thClass}>Transaction ID</th>
                <th className={thClass}>Reference</th>
                <th className={thClass}>Provider Reference</th>
                <th className={thClass}>Method</th>
                <th className={thClass}>Customer Phone</th>
                <th className={thClass}>Opening Balance</th>
                <th className={thClass}>Amount</th>
                <th className={thClass}>Charge</th>
                <th className={thClass}>Net</th>
                <th className={thClass}>Closing Balance</th>
                <th className={thClass}>Status</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {/* No rows is the answer to "did my customer pay?", so it
                * has to say which answer it is. A silent gap reads as a
                * broken page, and a merchant who thinks the page is
                * broken has learned nothing about their money. */}
              {transactions.length === 0 && (
                <tr className="border-t border-surface-container-highest">
                  <td className={`${tdClass} text-center text-on-surface-variant`} colSpan={13}>
                    {loading
                      ? "Loading…"
                      : search
                        ? `Nothing found for “${search}”. Check the number, or try just the last 6 digits.`
                        : anyFilter
                          ? "No transactions match these filters."
                          : "No transactions yet."}
                  </td>
                </tr>
              )}
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
                    <td className={`${tdClass} font-mono text-xs text-on-background whitespace-nowrap`}>
                      {transaction.customer_phone ?? "—"}
                    </td>
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
