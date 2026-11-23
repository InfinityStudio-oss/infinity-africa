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
import {
  fetchAllTransactionsForExport,
  listMyRiskAlerts,
  readTransactionsPage,
  type TransactionFilters,
  type TransactionPage,
} from "@/lib/portal/api";
import { transactionStatusBadge, transactionTypeBadge } from "@/lib/portal/status-tones";
import type { Transaction } from "@/lib/portal/types";

/** Shared by the four filter controls so they stay visually identical. */
const FILTER_CLASS =
  "w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary";

const OPEN_ALERT_STATUSES = new Set(["OPEN", "UNDER_REVIEW", "DOCUMENTS_REQUESTED", "ESCALATED"]);

/** Rows per page. The API allows up to 100; 50 keeps the table readable
 * on a phone while still being a real slice of the filtered set. */
const PAGE_SIZE = 50;

/** The values the API accepts, so a stale or hand-edited link with
 * `status=Success` is explained on screen instead of being sent, failing,
 * and looking like "nothing was successful". */
const TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "collection", label: "Collection" },
  { value: "disbursement", label: "Withdrawal" },
  { value: "payout", label: "Payout (Disbursement API)" },
  { value: "fee", label: "Fee" },
  { value: "refund", label: "Refund" },
  { value: "reversal", label: "Reversal" },
  { value: "adjustment", label: "Adjustment" },
];
const STATUS_VALUES = Object.values(TransactionStatus) as string[];

const METHOD_LABELS: Record<string, string> = {
  MOBILE_MONEY: "Mobile money",
  CARD: "Card",
  BANK_TRANSFER: "Bank transfer",
  BANK_ACCOUNT: "Bank transfer",
  SELCOM_PESA: "Selcom Pesa",
  WALLET: "Wallet",
};

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
  // Appended last so existing spreadsheets that read columns by position
  // keep working. The value a billing system already holds, so an export
  // can be reconciled against it directly.
  "InfinityPay Payment ID",
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
      transaction.collection_id ?? "",
    ]
      .map(csvCell)
      .join(",");
  });
  return [CSV_HEADER.map(csvCell).join(","), ...rows].join("\r\n");
}

function downloadCsv(transactions: Transaction[]) {
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

function money(value: string | null, currency: string): string {
  return value === null ? "Not available" : formatCurrency(value, currency);
}

function invalidFilterMessage(type: string, status: string): string | null {
  if (status && !STATUS_VALUES.includes(status)) {
    return `“${status}” isn't a status InfinityPay records. Choose a status from the list, or clear filters.`;
  }
  if (type && !TYPE_OPTIONS.some((option) => option.value === type)) {
    return `“${type}” isn't a transaction type InfinityPay records. Choose a type from the list, or clear filters.`;
  }
  return null;
}

export default function TransactionsPage() {
  // Tagged with the request it answers, so "is this still loading?" is
  // derived (the answer on hand is for a different request) rather than
  // a flag set inside the effect.
  const [result, setResult] = useState<(TransactionPage & { key: string }) | null>(null);
  const [flaggedTransactionIds, setFlaggedTransactionIds] = useState<Set<string>>(new Set());
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportNote, setExportNote] = useState<{ tone: "error" | "info"; text: string } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // The URL is the single source of truth for every filter AND the page,
  // so a filtered view survives a refresh, can be linked to, and the
  // topbar box and this one cannot disagree about what is searched.
  const params = useSearchParams();
  const search = params.get("search") ?? "";
  const type = params.get("type") ?? "";
  const status = params.get("status") ?? "";
  // start_date / end_date are what the Overview chart links with; they
  // used to be ignored, so those links opened an unfiltered ledger.
  const dateFrom = params.get("date_from") ?? params.get("start_date") ?? "";
  const dateTo = params.get("date_to") ?? params.get("end_date") ?? "";
  const method = params.get("method") ?? "";
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const router = useRouter();
  const [searchDraft, setSearchDraft] = useState(search);

  const anyFilter = Boolean(search || type || status || dateFrom || dateTo || method);
  const invalidFilter = invalidFilterMessage(type, status);
  const filters: TransactionFilters = { search, type, status, dateFrom, dateTo, method };
  const requestKey = JSON.stringify([search, type, status, dateFrom, dateTo, method, page, reloadKey]);
  const loading = !invalidFilter && result?.key !== requestKey;

  /** Change one filter, keeping the rest - and go back to page 1, since
   * page 4 of the old filter means nothing under the new one. */
  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    // Normalise the Overview's aliases the moment anything is changed,
    // so the URL never carries two spellings of one date.
    for (const [alias, canonical] of [
      ["start_date", "date_from"],
      ["end_date", "date_to"],
    ] as const) {
      const aliased = next.get(alias);
      next.delete(alias);
      if (aliased && !next.get(canonical)) next.set(canonical, aliased);
    }
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("page");
    const query = next.toString();
    router.push(query ? `/portal/transactions?${query}` : "/portal/transactions");
  }

  function goToPage(target: number) {
    const next = new URLSearchParams(params.toString());
    if (target <= 1) next.delete("page");
    else next.set("page", String(target));
    const query = next.toString();
    router.push(query ? `/portal/transactions?${query}` : "/portal/transactions");
  }

  useEffect(() => {
    setSearchDraft(search);
  }, [search]);

  useEffect(() => {
    // An unknown status/type is explained on screen and never sent.
    if (invalidFilter) return;
    // A slow answer to an old filter must not overwrite the answer to
    // the filter the merchant is looking at now.
    let current = true;
    readTransactionsPage({ search, type, status, dateFrom, dateTo, method }, { page, pageSize: PAGE_SIZE }).then(
      (next) => {
        if (current) setResult({ ...next, key: requestKey });
      },
    );
    return () => {
      current = false;
    };
  }, [search, type, status, dateFrom, dateTo, method, page, invalidFilter, requestKey]);

  // Which transactions are under review does not depend on any filter,
  // so it is fetched once.
  useEffect(() => {
    listMyRiskAlerts().then((alerts) => {
      setFlaggedTransactionIds(
        new Set(alerts.filter((a) => a.transaction_id && OPEN_ALERT_STATUSES.has(a.status)).map((a) => a.transaction_id as string)),
      );
    });
  }, []);

  // Nothing from a previous request is shown under a new filter: rows
  // that belong to "All" sitting under "Failed" are exactly the
  // confusion this page is fixing.
  const settled = invalidFilter || loading ? null : result;
  const transactions = settled?.rows ?? [];
  const total = settled?.total ?? 0;
  const totalPages = settled?.totalPages ?? 0;
  const loadError = settled?.error ?? null;
  const firstShown = (page - 1) * PAGE_SIZE + 1;
  const lastShown = firstShown + transactions.length - 1;

  async function handleExportCsv() {
    // Every page the filters match, not the 50 rows on screen - the
    // export used to be whatever page 1 happened to hold.
    setExporting(true);
    setExportNote(null);
    try {
      const exported = await fetchAllTransactionsForExport(filters);
      if (exported.error) {
        setExportNote({ tone: "error", text: `Export failed: ${exported.error}` });
        return;
      }
      downloadCsv(exported.rows);
      if (exported.truncated) {
        setExportNote({
          tone: "info",
          text: `Exported the newest ${exported.rows.length.toLocaleString()} of ${exported.total.toLocaleString()} matching transactions. Narrow the dates to export the rest.`,
        });
      }
    } finally {
      setExporting(false);
    }
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
            disabled={exporting || loading || Boolean(loadError) || total === 0}
            className="flex items-center gap-2 bg-surface border border-outline-variant text-on-surface px-4 py-2.5 rounded-lg text-sm font-medium hover:bg-surface-container-low transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Icon name="download" className="text-[18px]" />
            {exporting ? "Exporting…" : "Export CSV"}
          </button>
        }
      />

      {exportNote && (
        <p
          role={exportNote.tone === "error" ? "alert" : "status"}
          className={`text-sm ${exportNote.tone === "error" ? "text-error" : "text-on-surface-variant"}`}
        >
          {exportNote.text}
        </p>
      )}

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
            // Kept alongside the other filters, not instead of them: a
            // merchant who has chosen Failed and then searches a phone
            // number wants that number's failed payments.
            setFilter("search", searchDraft.trim());
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
              placeholder="Customer phone, a reference, or an InfinityPay Payment ID"
              aria-label="Search transactions by customer phone, reference or InfinityPay Payment ID"
              value={searchDraft}
              onChange={(event) => {
                setSearchDraft(event.target.value);
                // Emptying the box drops the search without needing
                // Enter; anything else waits, because a phone search per
                // keystroke is a dozen needless lookups.
                if (event.target.value.trim() === "" && search !== "") setFilter("search", "");
              }}
            />
          </div>
        </form>
        {anyFilter && (
          <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
            <div className="flex flex-wrap gap-2">
              {/* The Overview chart filters by method, which has no
                * dropdown here. Shown as a chip so a filter is never in
                * force without being on screen. */}
              {method && (
                <button
                  type="button"
                  onClick={() => setFilter("method", "")}
                  className="inline-flex items-center gap-1 rounded-full bg-surface-container px-3 py-1 text-xs font-medium text-on-surface"
                  aria-label={`Remove method filter ${METHOD_LABELS[method] ?? method}`}
                >
                  Method: {METHOD_LABELS[method] ?? method}
                  <Icon name="close" className="text-[14px]" />
                </button>
              )}
            </div>
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
            {/* Withdrawal and Payout are deliberately separate — one is the
              * merchant moving their own balance, the other is the
              * Disbursement API. */}
            <select
              id="filter-type"
              className={FILTER_CLASS}
              value={TYPE_OPTIONS.some((o) => o.value === type) ? type : ""}
              onChange={(event) => setFilter("type", event.target.value)}
            >
              <option value="">All Types</option>
              {TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5" htmlFor="filter-status">
              Status
            </label>
            {/* Option values are the backend's own lowercase status values
              * (packages/shared TransactionStatus), labelled for people.
              * "Successful" sends `successful`, never "Success". */}
            <select
              id="filter-status"
              className={FILTER_CLASS}
              value={STATUS_VALUES.includes(status) ? status : ""}
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
        <div className="p-5 pb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-2xl font-semibold text-on-background">
            {anyFilter ? "Filtered Transactions" : "All Transactions"}
          </h3>
          {/* The count is the API's total over the whole filtered set,
            * from the same query as the rows - not this page's length. */}
          {!loading && !loadError && !invalidFilter && total > 0 && (
            <p className="text-sm text-on-surface-variant" aria-live="polite">
              {transactions.length > 0
                ? `Showing ${firstShown.toLocaleString()}–${lastShown.toLocaleString()} of ${total.toLocaleString()} ${total === 1 ? "transaction" : "transactions"}`
                : `${total.toLocaleString()} matching ${total === 1 ? "transaction" : "transactions"}`}
            </p>
          )}
        </div>

        {(invalidFilter || loadError) && (
          <div role="alert" className="mx-5 mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-error/40 bg-error/5 px-4 py-3">
            <Icon name="error" className="text-error text-[20px]" />
            <p className="text-sm text-on-background flex-1 min-w-[12rem]">
              {invalidFilter ?? `Transactions could not be loaded. ${loadError}`}
            </p>
            {loadError && !invalidFilter && (
              <button
                type="button"
                onClick={() => setReloadKey((key) => key + 1)}
                className="text-sm font-medium text-primary hover:underline"
              >
                Try again
              </button>
            )}
          </div>
        )}

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
                * has to say WHICH answer it is - including "we could not
                * find out", which used to render as "no matches". */}
              {transactions.length === 0 && !invalidFilter && !loadError && (
                <tr className="border-t border-surface-container-highest">
                  <td className={`${tdClass} text-center text-on-surface-variant`} colSpan={13}>
                    {loading ? (
                      "Loading…"
                    ) : total > 0 ? (
                      <>
                        This page is past the end of the results.{" "}
                        <button type="button" className="text-primary font-medium hover:underline" onClick={() => goToPage(1)}>
                          Go to the first page
                        </button>
                      </>
                    ) : search ? (
                      `Nothing found for “${search}”. Check the number, or try just the last 6 digits.`
                    ) : anyFilter ? (
                      "No transactions match these filters."
                    ) : (
                      "No transactions yet."
                    )}
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

        {totalPages > 1 && !loadError && !invalidFilter && (
          <nav
            aria-label="Transaction pages"
            className="flex items-center justify-between gap-3 border-t border-surface-container-highest px-5 py-3"
          >
            <button
              type="button"
              onClick={() => goToPage(page - 1)}
              disabled={page <= 1 || loading}
              className="flex items-center gap-1 rounded-lg border border-outline-variant px-3 py-2 text-sm font-medium text-on-surface disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Icon name="chevron_left" className="text-[18px]" />
              Previous
            </button>
            <span className="text-sm text-on-surface-variant">
              Page {page.toLocaleString()} of {totalPages.toLocaleString()}
            </span>
            <button
              type="button"
              onClick={() => goToPage(page + 1)}
              disabled={page >= totalPages || loading}
              className="flex items-center gap-1 rounded-lg border border-outline-variant px-3 py-2 text-sm font-medium text-on-surface disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Next
              <Icon name="chevron_right" className="text-[18px]" />
            </button>
          </nav>
        )}
      </Card>

      <TransactionDetailDrawer transaction={selectedTransaction} onClose={() => setSelectedTransaction(null)} />
    </div>
  );
}
