"use client";

import { useEffect, useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { KpiCard } from "@/components/portal/kpi-card";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { exportWalletLedger, getAvailableBalance, getMyMerchant, listWalletLedger } from "@/lib/portal/api";
import { transactionStatusBadge, transactionTypeBadge } from "@/lib/portal/status-tones";
import type { TransactionStatus, WalletLedgerEntry } from "@/lib/portal/types";

type QuickFilterKey = "today" | "yesterday" | "7d" | "30d" | "thisMonth" | "lastMonth";

const QUICK_FILTERS: { key: QuickFilterKey; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "7d", label: "Last 7 Days" },
  { key: "30d", label: "Last 30 Days" },
  { key: "thisMonth", label: "This Month" },
  { key: "lastMonth", label: "Last Month" },
];

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** Local calendar date as YYYY-MM-DD — deliberately not toISOString(),
 * which is UTC and can land on the wrong day depending on the merchant's
 * own timezone offset. */
function toDateInputValue(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function addDays(d: Date, days: number): Date {
  const copy = new Date(d);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function quickFilterRange(filter: QuickFilterKey): { start: string; end: string } {
  const today = new Date();
  switch (filter) {
    case "today":
      return { start: toDateInputValue(today), end: toDateInputValue(today) };
    case "yesterday": {
      const y = addDays(today, -1);
      return { start: toDateInputValue(y), end: toDateInputValue(y) };
    }
    case "7d":
      return { start: toDateInputValue(addDays(today, -6)), end: toDateInputValue(today) };
    case "30d":
      return { start: toDateInputValue(addDays(today, -29)), end: toDateInputValue(today) };
    case "thisMonth":
      return {
        start: toDateInputValue(new Date(today.getFullYear(), today.getMonth(), 1)),
        end: toDateInputValue(today),
      };
    case "lastMonth": {
      const firstOfThisMonth = new Date(today.getFullYear(), today.getMonth(), 1);
      const lastOfPrevMonth = addDays(firstOfThisMonth, -1);
      const firstOfPrevMonth = new Date(lastOfPrevMonth.getFullYear(), lastOfPrevMonth.getMonth(), 1);
      return { start: toDateInputValue(firstOfPrevMonth), end: toDateInputValue(lastOfPrevMonth) };
    }
  }
}

function money(value: string | null, currency: string): string {
  return value === null ? "Not available" : formatCurrency(value, currency);
}

const primaryButtonClass =
  "flex items-center justify-center gap-2 bg-primary-container text-on-primary px-4 py-2.5 rounded-lg text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed";
const secondaryButtonClass =
  "flex items-center justify-center gap-2 bg-surface border border-outline-variant text-on-surface px-4 py-2.5 rounded-lg text-sm font-medium hover:bg-surface-container-low transition-colors disabled:opacity-50 disabled:cursor-not-allowed";

export default function WalletPage() {
  const [availableBalance, setAvailableBalance] = useState<string | null>(null);
  const [ledger, setLedger] = useState<WalletLedgerEntry[]>([]);
  const [merchantCode, setMerchantCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [draftStart, setDraftStart] = useState("");
  const [draftEnd, setDraftEnd] = useState("");
  const [appliedStart, setAppliedStart] = useState("");
  const [appliedEnd, setAppliedEnd] = useState("");
  const [activeQuickFilter, setActiveQuickFilter] = useState<QuickFilterKey | null>(null);

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");

  function fetchLedger(start: string, end: string) {
    setLoading(true);
    listWalletLedger({ start_date: start || undefined, end_date: end || undefined })
      .then(setLedger)
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    getAvailableBalance().then(setAvailableBalance);
    getMyMerchant().then((merchant) => setMerchantCode(merchant?.merchant_code ?? null));
    // loading already starts true (useState(true) above) — only clear it
    // once this resolves, rather than calling setLoading synchronously
    // inside the effect body.
    listWalletLedger({}).then(setLedger).finally(() => setLoading(false));
  }, []);

  function handleQuickFilter(filter: QuickFilterKey) {
    const { start, end } = quickFilterRange(filter);
    setDraftStart(start);
    setDraftEnd(end);
    setAppliedStart(start);
    setAppliedEnd(end);
    setActiveQuickFilter(filter);
    fetchLedger(start, end);
  }

  function handleApply() {
    setActiveQuickFilter(null);
    setAppliedStart(draftStart);
    setAppliedEnd(draftEnd);
    fetchLedger(draftStart, draftEnd);
  }

  function handleReset() {
    setDraftStart("");
    setDraftEnd("");
    setAppliedStart("");
    setAppliedEnd("");
    setActiveQuickFilter(null);
    fetchLedger("", "");
  }

  async function handleExport() {
    setExportError("");
    setExporting(true);
    try {
      // If the merchant hasn't picked a range yet, export a sensible
      // default (Last 30 Days) rather than blocking on an error — an
      // already-applied filter always takes priority and is respected
      // exactly.
      const { start, end } =
        appliedStart && appliedEnd ? { start: appliedStart, end: appliedEnd } : quickFilterRange("30d");

      const blob = await exportWalletLedger({ start_date: start, end_date: end });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `infinity-africa-wallet-ledger-${start}-to-${end}.xlsx`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Couldn't export the wallet ledger. Please try again.");
    } finally {
      setExporting(false);
    }
  }

  const isFiltered = Boolean(appliedStart || appliedEnd);
  const emptyMessage = isFiltered ? "No wallet ledger entries found for this date range." : "No wallet activity yet.";

  return (
    <div className="space-y-8">
      <PageHeader
        title="Wallet"
        description="Your available balance and wallet activity."
        action={
          merchantCode ? (
            <p className="text-xs text-on-surface-variant">
              ID: <span className="font-mono font-semibold text-on-background">{merchantCode}</span>
            </p>
          ) : undefined
        }
      />

      <section className="grid grid-cols-1 sm:max-w-xs gap-4">
        <KpiCard
          variant="brand"
          icon="account_balance_wallet"
          label="Available Balance"
          value={availableBalance !== null ? formatCurrency(availableBalance, "TZS") : "—"}
        />
      </section>

      <Card>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label htmlFor="wallet-ledger-start-date" className="block text-sm font-medium text-on-surface-variant mb-1.5">
              Start Date
            </label>
            <input
              id="wallet-ledger-start-date"
              type="date"
              className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
              value={draftStart}
              max={draftEnd || undefined}
              onChange={(event) => {
                setDraftStart(event.target.value);
                setActiveQuickFilter(null);
              }}
            />
          </div>
          <div>
            <label htmlFor="wallet-ledger-end-date" className="block text-sm font-medium text-on-surface-variant mb-1.5">
              End Date
            </label>
            <input
              id="wallet-ledger-end-date"
              type="date"
              className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
              value={draftEnd}
              min={draftStart || undefined}
              onChange={(event) => {
                setDraftEnd(event.target.value);
                setActiveQuickFilter(null);
              }}
            />
          </div>
          <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-2">
            <button type="button" onClick={handleApply} className={`${primaryButtonClass} flex-1`}>
              Apply Filter
            </button>
            <button type="button" onClick={handleReset} className={`${secondaryButtonClass} flex-1`}>
              Reset
            </button>
            <button type="button" onClick={handleExport} disabled={exporting} className={`${secondaryButtonClass} flex-1`}>
              <Icon name={exporting ? "progress_activity" : "download"} className={`text-[18px] ${exporting ? "animate-spin" : ""}`} />
              {exporting ? "Exporting…" : "Export Excel"}
            </button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {QUICK_FILTERS.map((filter) => (
            <button
              key={filter.key}
              type="button"
              onClick={() => handleQuickFilter(filter.key)}
              className={
                activeQuickFilter === filter.key
                  ? "px-3.5 py-2 rounded-full bg-primary-container/10 text-primary text-sm font-semibold"
                  : "px-3.5 py-2 rounded-full bg-surface-container-low text-on-surface-variant text-sm font-semibold hover:bg-surface-container-highest"
              }
            >
              {filter.label}
            </button>
          ))}
          <span className="px-3.5 py-2 rounded-full text-on-surface-variant text-sm">Custom Range: use the date fields above</span>
        </div>

        {exportError && (
          <div className="mt-4 rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error" role="alert">
            {exportError}
          </div>
        )}
      </Card>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">Wallet Ledger</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[1500px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Date</th>
                <th className={thClass}>Transaction ID</th>
                <th className={thClass}>Type</th>
                <th className={thClass}>Reference</th>
                <th className={thClass}>Payment Method</th>
                <th className={thClass}>Opening Balance</th>
                <th className={thClass}>Amount</th>
                <th className={thClass}>Charge / Fee</th>
                <th className={thClass}>Net Amount</th>
                <th className={thClass}>Closing Balance</th>
                <th className={thClass}>Direction</th>
                <th className={thClass}>Status</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {loading ? (
                <tr>
                  <td className={`${tdClass} text-on-surface-variant`} colSpan={12}>
                    Loading wallet activity…
                  </td>
                </tr>
              ) : ledger.length === 0 ? (
                <tr>
                  <td className={`${tdClass} text-on-surface-variant`} colSpan={12}>
                    {emptyMessage}
                  </td>
                </tr>
              ) : (
                ledger.map((entry) => (
                  <tr key={entry.id} className="border-t border-surface-container-highest">
                    <td className={`${tdClass} text-on-surface-variant text-xs whitespace-nowrap`}>{formatDateTime(entry.date)}</td>
                    <td className={`${tdClass} font-mono text-xs text-on-surface-variant`}>
                      {entry.transaction_id ? entry.transaction_id.slice(0, 8) : "—"}
                    </td>
                    <td className={tdClass}>
                      {entry.type ? <StatusBadge {...transactionTypeBadge(entry.type)} /> : <span className="text-on-surface-variant text-xs">—</span>}
                    </td>
                    <td className={`${tdClass} font-mono text-sm text-on-background`}>{entry.reference ?? "—"}</td>
                    <td className={`${tdClass} text-on-surface-variant whitespace-nowrap`}>{entry.method ?? "—"}</td>
                    <td className={`${tdClass} text-on-surface-variant whitespace-nowrap`}>
                      {formatCurrency(entry.balance_before, "TZS")}
                    </td>
                    <td className={`${tdClass} font-semibold ${entry.direction === "credit" ? "text-primary" : "text-on-background"} whitespace-nowrap`}>
                      {entry.direction === "credit" ? "+" : "-"}
                      {formatCurrency(entry.amount, "TZS")}
                    </td>
                    <td className={`${tdClass} text-on-surface-variant whitespace-nowrap`}>{money(entry.fee_amount, "TZS")}</td>
                    <td className={`${tdClass} whitespace-nowrap`}>{money(entry.net_amount, "TZS")}</td>
                    <td className={`${tdClass} font-semibold whitespace-nowrap`}>{formatCurrency(entry.balance_after, "TZS")}</td>
                    <td className={tdClass}>
                      {entry.direction === "credit" ? (
                        <StatusBadge label="Credit" tone="positive" dot />
                      ) : (
                        <StatusBadge label="Debit" tone="neutral" />
                      )}
                    </td>
                    <td className={tdClass}>
                      {entry.status ? (
                        <StatusBadge {...transactionStatusBadge(entry.status as TransactionStatus)} />
                      ) : (
                        <span className="text-on-surface-variant text-xs">—</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
