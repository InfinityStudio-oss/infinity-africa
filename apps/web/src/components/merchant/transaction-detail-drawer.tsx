"use client";

import { Icon } from "@/components/portal/icon";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { transactionStatusBadge, transactionTypeBadge } from "@/lib/portal/status-tones";
import type { Transaction } from "@/lib/portal/types";

function Row({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-surface-container-highest last:border-0">
      <span className="text-sm text-on-surface-variant">{label}</span>
      <span className={`text-sm text-on-background text-right ${mono ? "font-mono" : "font-medium"}`}>{value}</span>
    </div>
  );
}

function money(value: string | null, currency: string): string {
  return value === null ? "Not available" : formatCurrency(value, currency);
}

export function TransactionDetailDrawer({
  transaction,
  onClose,
}: {
  transaction: Transaction | null;
  onClose: () => void;
}) {
  if (!transaction) return null;

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-label="Transaction detail"
        className="fixed inset-y-0 right-0 z-50 w-full sm:w-[420px] bg-surface shadow-ambient-lg overflow-y-auto"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-surface-container-highest sticky top-0 bg-surface">
          <h3 className="text-lg font-semibold text-on-background">Transaction Detail</h3>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 text-on-surface-variant hover:text-on-background rounded-lg"
            aria-label="Close"
          >
            <Icon name="close" className="text-[20px]" />
          </button>
        </div>

        <div className="p-5 space-y-6">
          <div className="flex items-center gap-2.5">
            <StatusBadge {...transactionTypeBadge(transaction.type)} />
            <StatusBadge {...transactionStatusBadge(transaction.status)} />
          </div>

          <div>
            <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2">
              Identifiers
            </p>
            <Row label="Transaction ID" value={transaction.id} mono />
            <Row label="Merchant Reference" value={transaction.reference} mono />
            <Row label="Provider Reference" value={transaction.provider_reference ?? "Not available"} mono />
          </div>

          <div>
            <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2">
              Charge Breakdown
            </p>
            <Row label="Amount" value={formatCurrency(transaction.gross_amount, transaction.currency)} />
            <Row label="Charge / Fee" value={formatCurrency(transaction.fee_amount, transaction.currency)} />
            <Row label="Net Amount" value={formatCurrency(transaction.net_amount, transaction.currency)} />
          </div>

          <div>
            <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2">
              Wallet Balance
            </p>
            <Row label="Opening Balance" value={money(transaction.balance_before, transaction.currency)} />
            <Row label="Closing Balance" value={money(transaction.balance_after, transaction.currency)} />
            <Row
              label="Direction"
              value={
                transaction.direction ? (
                  <StatusBadge
                    label={transaction.direction === "credit" ? "Credit" : "Debit"}
                    tone={transaction.direction === "credit" ? "positive" : "neutral"}
                  />
                ) : (
                  "Not available"
                )
              }
            />
          </div>

          <div>
            <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2">Other</p>
            <Row label="Payment Method" value={transaction.method} />
            <Row label="Customer Phone" value={transaction.customer_phone ?? "Not available"} mono />
            <Row label="Created" value={formatDateTime(transaction.created_at)} />
          </div>

          {(transaction.balance_before === null || transaction.balance_after === null) && (
            <p className="text-xs text-on-surface-variant">
              This transaction predates opening/closing balance tracking, so those two fields show as not
              available rather than an estimated number.
            </p>
          )}
        </div>
      </div>
    </>
  );
}
