"use client";

import { useEffect, useState } from "react";
import { COLLECTION_METHOD_LABELS } from "@infinity/shared";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { RefreshStatusButton } from "@/components/portal/refresh-status-button";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { createCollectionRequest, listCollections, refreshCollectionStatus } from "@/lib/portal/api";
import { collectionBadge } from "@/lib/portal/status-tones";
import type { Collection, PaymentLink } from "@/lib/portal/types";

/** What to tell a merchant when the payment worked but their own system
 * was never told about it.
 *
 * A collection can be entirely successful here — customer charged, wallet
 * credited — while the merchant's endpoint returned an error and the
 * notification never landed. Their screen then said "Success" and their
 * system showed nothing, so the customer was never activated and nobody
 * knew until the customer complained. On 2026-10-23 that was nine
 * customers in one day for a single partner.
 *
 * Shown only when there is something wrong: a delivered notification
 * needs no comment, and a payment that genuinely failed already explains
 * itself through failure_reason. */
function webhookNote(collection: Collection): string | null {
  const state = collection.webhook_delivery_status;
  if (state !== "failed" && state !== "retrying") return null;

  const code = collection.webhook_response_code;
  const reason = code ? `HTTP ${code}` : "no response";
  if (state === "retrying") {
    return `Your system has not accepted this yet (${reason}) — still retrying.`;
  }
  const tries = collection.webhook_attempts ?? 0;
  return `Your system did not receive this (${reason}${tries ? ` after ${tries} tries` : ""}).`;
}

export default function CollectionsPage() {
  const [collections, setCollections] = useState<Collection[]>([]);
  // Once a collection has been manually refreshed, keep showing the
  // button + its result message even after the status flips away from
  // "processing" — otherwise the row re-renders as resolved and the
  // outcome message (e.g. "Payment completed") never gets seen.
  const [refreshedIds, setRefreshedIds] = useState<Set<string>>(new Set());
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [customerEmail, setCustomerEmail] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [merchantReference, setMerchantReference] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [lastRequest, setLastRequest] = useState<PaymentLink | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    listCollections().then(setCollections);
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!amount) return;

    setSubmitting(true);
    try {
      // No channel chosen here — the customer picks Mobile Money Push,
      // Selcom Pesa, or Scan QR / TanQR themselves on the payment page
      // this creates (see PaymentForm).
      const paymentLink = await createCollectionRequest({
        customer_name: customerName || null,
        customer_phone: customerPhone || null,
        customer_email: customerEmail || null,
        amount,
        description: description || null,
        merchant_reference: merchantReference || null,
      });
      setLastRequest(paymentLink);
      setCopied(false);
      setCustomerName("");
      setCustomerPhone("");
      setCustomerEmail("");
      setAmount("");
      setDescription("");
      setMerchantReference("");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCopyLink() {
    if (!lastRequest) return;
    try {
      await navigator.clipboard.writeText(lastRequest.public_url);
      setCopied(true);
    } catch {
      // Clipboard access denied/unavailable — the link is still visible
      // and selectable in the panel below, so this isn't fatal.
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader title="Collections" description="Request one-off payments from customers — they choose how to pay." />

      <Card id="create-collection" className="scroll-mt-24">
        <h3 className="text-2xl font-semibold text-on-background mb-1">Request Collection</h3>
        <p className="text-sm text-on-surface-variant mb-5">
          Creates a payment page to share with your customer. They choose how to pay — Mobile Money Push, Selcom
          Pesa, or Scan QR / TanQR.
        </p>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5" htmlFor="cust-name">
                Customer Name <span className="text-on-surface-variant/70 font-normal">(optional)</span>
              </label>
              <input
                id="cust-name"
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                placeholder="e.g. Grace Mwakalinga"
                type="text"
                value={customerName}
                onChange={(event) => setCustomerName(event.target.value)}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5" htmlFor="cust-phone">
                Phone Number <span className="text-on-surface-variant/70 font-normal">(optional)</span>
              </label>
              <input
                id="cust-phone"
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                placeholder="+255 7XX XXX XXX"
                type="tel"
                value={customerPhone}
                onChange={(event) => setCustomerPhone(event.target.value)}
              />
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5" htmlFor="cust-email">
                Customer Email <span className="text-on-surface-variant/70 font-normal">(optional)</span>
              </label>
              <input
                id="cust-email"
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                placeholder="grace@example.com"
                type="email"
                value={customerEmail}
                onChange={(event) => setCustomerEmail(event.target.value)}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5" htmlFor="cust-amount">
                Amount in TZS
              </label>
              <div className="relative">
                <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-on-surface-variant text-sm font-semibold">
                  TZS
                </span>
                <input
                  id="cust-amount"
                  className="w-full pl-12 pr-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                  placeholder="50,000"
                  type="number"
                  min="1"
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                />
              </div>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5" htmlFor="cust-desc">
                Description
              </label>
              <input
                id="cust-desc"
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                placeholder="e.g. Payment for 2 bags of maize flour"
                type="text"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5" htmlFor="cust-ref">
                Internal Reference <span className="text-on-surface-variant/70 font-normal">(if available)</span>
              </label>
              <input
                id="cust-ref"
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                placeholder="e.g. ORDER-4821"
                type="text"
                value={merchantReference}
                onChange={(event) => setMerchantReference(event.target.value)}
              />
            </div>
          </div>
          <button
            className="w-full sm:w-auto bg-primary-container text-on-primary text-sm font-medium py-3 px-6 rounded-lg hover:opacity-90 transition-opacity flex items-center justify-center gap-2 disabled:opacity-60"
            type="submit"
            disabled={submitting}
          >
            <Icon name="payments" className="text-[20px]" />
            {submitting ? "Requesting…" : "Request Collection"}
          </button>
        </form>

        {lastRequest && (
          <div className="mt-6 pt-5 border-t border-surface-container-highest">
            <h4 className="text-sm font-semibold text-on-background mb-1">Payment page ready</h4>
            <p className="text-sm text-on-surface-variant mb-3">
              Share this link with your customer. They&apos;ll choose how to pay when they open it.
            </p>
            <div className="flex items-center gap-2">
              <input
                readOnly
                value={lastRequest.public_url}
                className="flex-1 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm text-on-surface-variant"
                onFocus={(event) => event.target.select()}
              />
              <button
                type="button"
                onClick={handleCopyLink}
                className="shrink-0 bg-primary-container text-on-primary text-sm font-medium py-2.5 px-4 rounded-lg hover:opacity-90 transition-opacity flex items-center gap-1.5"
                title="Copy link"
              >
                <Icon name={copied ? "check" : "content_copy"} className="text-[18px]" />
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          </div>
        )}
      </Card>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">Recent Collections</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[760px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Date</th>
                <th className={thClass}>Customer Phone</th>
                <th className={thClass}>Channel</th>
                <th className={thClass}>Amount</th>
                <th className={thClass}>Status</th>
                <th className={`${thClass} text-right`}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {collections.map((collection) => {
                const badge = collectionBadge(collection.status);
                const needsRefresh = collection.status === "processing" || refreshedIds.has(collection.id);
                return (
                  <tr key={collection.id} className="border-t border-surface-container-highest">
                    <td className={tdClass}>{formatDateTime(collection.initiated_at)}</td>
                    <td className={tdClass}>{collection.customer_phone}</td>
                    <td className={tdClass}>{collection.channel ?? COLLECTION_METHOD_LABELS[collection.method]}</td>
                    <td className={tdClass}>{formatCurrency(collection.amount, collection.currency)}</td>
                    <td className={tdClass}>
                      <StatusBadge {...badge} />
                      {(collection.status === "failed" || collection.status === "reversed") &&
                        collection.failure_reason && (
                          <p className="text-xs text-on-surface-variant mt-1">{collection.failure_reason}</p>
                        )}
                      {webhookNote(collection) && (
                        <p className="text-xs text-amber-700 mt-1">{webhookNote(collection)}</p>
                      )}
                    </td>
                    <td className={`${tdClass} text-right`}>
                      {needsRefresh && (
                        <RefreshStatusButton
                          onRefresh={() => refreshCollectionStatus(collection.id)}
                          onResult={(result) => {
                            setRefreshedIds((prev) => new Set(prev).add(collection.id));
                            setCollections((prev) =>
                              prev.map((c) => (c.id === collection.id ? { ...c, ...result } : c)),
                            );
                          }}
                        />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
