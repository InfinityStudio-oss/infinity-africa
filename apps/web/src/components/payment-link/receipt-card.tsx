"use client";

import { formatCurrency, formatDateTime, maskAccountIdentifier } from "@/lib/format";
import type { PublicCollectionReceipt } from "@/lib/payment-links";

/**
 * A printable payment receipt — every value here came straight from
 * Selcom's own confirmed data (see the backend receipt endpoint's
 * docstring), nothing is generated. "Download Receipt" uses the
 * browser's native print dialog (Save as PDF works the same way on
 * desktop and mobile) rather than a client-side PDF library — no new
 * dependency, and it's the most reliable way to get a real, saved file
 * across every device this page might be opened on.
 *
 * print:hidden / print:* utilities (Tailwind's print variant) strip the
 * chrome (button, "Secured by" footer via the parent page) so only the
 * receipt itself ends up in the saved PDF.
 */
/** A short, friendly receipt number derived from the collection id — the
 * backend has no separate receipt-number field, so this is presentation
 * only. The raw collection/transaction ids are deliberately not shown on
 * the customer-facing receipt (internal record-keeping detail, not
 * something a customer needs). */
function receiptNumber(collectionId: string): string {
  return `RCPT-${collectionId.replace(/-/g, "").slice(-8).toUpperCase()}`;
}

export function ReceiptCard({ receipt, slug }: { receipt: PublicCollectionReceipt; slug: string }) {
  return (
    <div>
      <div
        id="receipt"
        className="rounded-lg border border-outline-variant bg-surface p-6 shadow-sm print:rounded-none print:border-0 print:shadow-none sm:p-8"
      >
        <div className="-mx-6 -mt-6 flex items-center justify-between rounded-t-lg border-b border-dashed border-primary/20 bg-accent px-6 py-5 sm:-mx-8 sm:-mt-8 sm:px-8 print:rounded-none">
          <div>
            <span className="flex items-center">
              <span className="text-lg font-bold tracking-tight text-primary">InfinityPay</span>
            </span>
            <p className="mt-0.5 text-xs text-primary/70">Payment Receipt</p>
          </div>
          <CheckBadge />
        </div>

        <div className="mt-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-on-surface-variant">Amount paid</p>
          <p className="mt-1 text-3xl font-bold text-on-surface">{formatCurrency(receipt.amount, receipt.currency)}</p>
        </div>

        <dl className="mt-6 space-y-3 text-sm">
          <Row label="Status" value="Successful" />
          <Row label="Receipt no." value={receiptNumber(receipt.collection_id)} mono />
          <Row label="Paid to" value={receipt.merchant_name} />
          {receipt.merchant_code && <Row label="Merchant ID" value={receipt.merchant_code} mono />}
          {receipt.description && <Row label="Description" value={receipt.description} />}
          {(receipt.customer_name || receipt.customer_phone) && (
            <Row
              label="Paid by"
              value={[receipt.customer_name, receipt.customer_phone ? maskAccountIdentifier(receipt.customer_phone) : null]
                .filter(Boolean)
                .join(" · ")}
            />
          )}
          <Row label="Payment method" value={receipt.method} />
          {receipt.channel && <Row label="Channel" value={receipt.channel} />}
          {receipt.provider_reference && <Row label="Selcom reference" value={receipt.provider_reference} mono />}
          {receipt.completed_at && <Row label="Date" value={formatDateTime(receipt.completed_at)} />}
        </dl>

        <p className="mt-6 border-t border-dashed border-outline-variant pt-4 text-center text-xs text-on-surface-variant">
          Powered by InfinityPay.
        </p>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-2.5 print:hidden sm:grid-cols-2">
        <button
          type="button"
          onClick={() => window.print()}
          className="rounded bg-primary-container px-4 py-3 text-sm font-semibold text-on-primary shadow-sm transition-colors hover:bg-primary"
        >
          Download Receipt PDF
        </button>
        <button
          type="button"
          onClick={() => window.print()}
          className="rounded border border-outline-variant px-4 py-3 text-sm font-semibold text-on-surface transition-colors hover:bg-surface-container-low"
        >
          Print Receipt
        </button>
      </div>
      <a
        href={`/pay/${slug}`}
        className="mt-2.5 block w-full rounded px-4 py-2 text-center text-xs font-medium text-on-surface-variant hover:underline print:hidden"
      >
        Back to payment status
      </a>
    </div>
  );
}

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <dt className="text-on-surface-variant">{label}</dt>
      <dd className={`text-right font-medium text-on-surface ${mono ? "font-mono text-xs" : ""}`}>{value}</dd>
    </div>
  );
}

function CheckBadge() {
  return (
    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary-fixed text-primary">
      <svg viewBox="0 0 24 24" fill="none" strokeWidth={2.5} stroke="currentColor" className="h-5 w-5">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
      </svg>
    </span>
  );
}
