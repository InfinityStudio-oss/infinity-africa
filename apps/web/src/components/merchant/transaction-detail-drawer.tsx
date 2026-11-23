"use client";

import { useEffect, useState } from "react";

import { Reference, TrackingTimeline } from "@/components/payment-tracking/tracking-timeline";
import { Icon } from "@/components/portal/icon";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { getTransactionTracking } from "@/lib/portal/api";
import { transactionStatusBadge, transactionTypeBadge } from "@/lib/portal/status-tones";
import type { PaymentTracking, Transaction } from "@/lib/portal/types";

function Row({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2.5 border-b border-surface-container-highest last:border-0">
      <span className="text-sm text-on-surface-variant shrink-0">{label}</span>
      <span className={`text-sm text-on-background text-right break-all ${mono ? "font-mono" : "font-medium"}`}>{value}</span>
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
  // Tagged with the transaction it belongs to, so opening another row
  // can never show the previous one's timeline, and loading is derived.
  const [loaded, setLoaded] = useState<{ id: string; data: PaymentTracking | null; error: string | null } | null>(null);
  const transactionId = transaction?.id ?? null;

  useEffect(() => {
    if (!transactionId) return;
    let current = true;
    getTransactionTracking(transactionId)
      .then((result) => {
        if (!current) return;
        setLoaded({
          id: transactionId,
          data: result.data,
          error: result.data ? null : (result.error ?? "Tracking is not available for this transaction."),
        });
      })
      .catch(() => {
        if (current) setLoaded({ id: transactionId, data: null, error: "Tracking could not be loaded." });
      });
    return () => {
      current = false;
    };
  }, [transactionId]);

  const mine = loaded && loaded.id === transactionId ? loaded : null;
  const tracking = mine?.data ?? null;
  const trackingError = mine?.error ?? null;
  const trackingLoading = Boolean(transactionId) && !mine;

  if (!transaction) return null;
  const ids = tracking?.identifiers;

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-label="Transaction detail"
        className="fixed inset-y-0 right-0 z-50 w-full sm:w-[440px] bg-surface shadow-ambient-lg overflow-y-auto"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-surface-container-highest sticky top-0 bg-surface z-10">
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

          {transaction.collection_id && (
            <div>
              <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2">
                References for your billing system
              </p>
              <Reference
                label="InfinityPay Payment ID"
                value={ids?.payment_id ?? transaction.collection_id}
                hint="Share this one with your billing system and with support. It is the collection_id in API responses and webhooks."
                copy
              />
              <Reference
                label="Your order reference"
                value={ids ? ids.merchant_reference : null}
                hint="The reference your own system sent when it created the payment."
              />
            </div>
          )}

          <div>
            <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2">
              Identifiers
            </p>
            <Row label="Transaction ID" value={transaction.id} mono />
            {/* NOT "Merchant Reference": that name belongs to the API and
                webhook field carrying the INTEGRATOR's own reference
                (collections.merchant_reference). This is InfinityPay's
                own TXN-... handle. */}
            <Row label="Transaction Reference" value={transaction.reference} mono />
            <Row label="Provider Reference" value={transaction.provider_reference ?? "Not available"} mono />
          </div>

          <div>
            <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2">
              Payment tracking
            </p>
            {trackingLoading && <p className="text-sm text-on-surface-variant">Loading payment tracking…</p>}
            {!trackingLoading && trackingError && (
              <p role="alert" className="text-sm text-error">
                {trackingError}
              </p>
            )}
            {tracking && <TrackingTimeline tracking={tracking} />}
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
