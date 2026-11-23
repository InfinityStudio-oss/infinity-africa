"use client";

import { useEffect, useState } from "react";

import { EnvironmentBadge, Reference, TrackingTimeline } from "@/components/payment-tracking/tracking-timeline";
import { Icon } from "@/components/portal/icon";
import { getAdminTransactionTrackingClient } from "@/lib/admin/transaction-tracking-client";
import type { AdminTransactionRow } from "@/lib/admin/types";
import type { PaymentTracking } from "@/lib/portal/types";

/** The Super Admin view of "my customer paid and was never connected":
 * the same recorded evidence the merchant sees, for any merchant. */
export function TransactionTrackingDrawer({
  transaction,
  onClose,
}: {
  transaction: AdminTransactionRow | null;
  onClose: () => void;
}) {
  const [loaded, setLoaded] = useState<{ id: string; data: PaymentTracking | null; error: string | null } | null>(null);
  const transactionId = transaction?.transaction_id ?? null;

  useEffect(() => {
    if (!transactionId) return;
    let current = true;
    getAdminTransactionTrackingClient(transactionId).then((result) => {
      if (current) setLoaded({ id: transactionId, ...result });
    });
    return () => {
      current = false;
    };
  }, [transactionId]);

  const mine = loaded && loaded.id === transactionId ? loaded : null;
  const tracking = mine?.data ?? null;
  const error = mine?.error ?? null;
  const loading = Boolean(transactionId) && !mine;

  if (!transaction) return null;
  const ids = tracking?.identifiers;

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-label="Payment tracking"
        className="fixed inset-y-0 right-0 z-50 w-full sm:w-[440px] app-drawer-surface shadow-ambient-lg overflow-y-auto"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-surface-container-highest sticky top-0 app-drawer-surface z-10">
          <div className="min-w-0">
            <h3 className="text-lg font-semibold text-on-background">Payment tracking</h3>
            <p className="text-xs text-on-surface-variant truncate">
              {transaction.merchant_name}
              {transaction.merchant_code ? ` · ${transaction.merchant_code}` : ""}
            </p>
          </div>
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
          {tracking?.environment && (
            <div className="flex items-center gap-2">
              <EnvironmentBadge environment={tracking.environment} />
              {tracking.environment === "sandbox" && (
                <span className="text-sm text-on-surface-variant">Simulated - no real money moved.</span>
              )}
            </div>
          )}
          <div>
            <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2">References</p>
            <Reference
              label="InfinityPay Payment ID"
              value={ids?.payment_id ?? transaction.collection_id ?? null}
              hint="collection_id in the merchant's API responses and webhooks - the value their billing system holds."
              copy
            />
            <Reference
              label="Merchant's order reference"
              value={ids ? ids.merchant_reference : null}
              hint="The merchant's own reference, as their system sent it."
            />
            <Reference label="Transaction Reference" value={transaction.reference} hint="InfinityPay's ledger reference." />
            <Reference
              label="Provider Reference"
              value={transaction.provider_reference}
              hint="The mobile-money provider's own reference."
            />
          </div>
          <div>
            <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2">Timeline</p>
            {loading && <p className="text-sm text-on-surface-variant">Loading payment tracking…</p>}
            {!loading && error && (
              <p role="alert" className="text-sm text-error">
                {error}
              </p>
            )}
            {tracking && <TrackingTimeline tracking={tracking} audience="admin" />}
          </div>
        </div>
      </div>
    </>
  );
}
