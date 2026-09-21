"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { QrCode } from "@/components/payment-link/qr-code";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { cancelPaymentLink, createPaymentLink, listPaymentLinks } from "@/lib/portal/api";
import { paymentLinkBadge } from "@/lib/portal/status-tones";
import type { PaymentLink } from "@/lib/portal/types";

const FILTERS = ["All", "Active", "Paid", "Expired", "Cancelled"] as const;

function whatsappShareUrl(link: Pick<PaymentLink, "amount" | "currency" | "public_url">): string {
  return `https://wa.me/?text=${encodeURIComponent(
    `Please complete your payment of ${formatCurrency(link.amount, link.currency)} via this secure InfinityPay link: ${link.public_url}`,
  )}`;
}

/** Shared by the "just created" panel and a list row's expanded "View"
 * panel — same fields, same actions, so a merchant sees identical detail
 * either way. */
function PaymentLinkDetail({
  link,
  onCopy,
  copied,
}: {
  link: PaymentLink;
  onCopy: () => void;
  copied: boolean;
}) {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Generated Payment URL</label>
        <div className="flex items-center gap-2">
          <input
            className="flex-1 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm text-on-surface truncate"
            readOnly
            value={link.public_url}
          />
          <button
            type="button"
            onClick={onCopy}
            className="shrink-0 p-2.5 bg-primary-container/10 text-primary rounded-lg hover:bg-primary-container/20 transition-colors"
            title="Copy link"
          >
            <Icon name={copied ? "check" : "content_copy"} className="text-[20px]" />
          </button>
        </div>
        {copied && <p className="mt-1 text-xs font-medium text-primary">Copied!</p>}
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <span className="text-on-surface-variant">Status</span>
        <span className="text-right">
          <StatusBadge {...paymentLinkBadge(link.status)} />
        </span>
        <span className="text-on-surface-variant">Amount</span>
        <span className="text-right font-semibold text-on-background">{formatCurrency(link.amount, link.currency)}</span>
        <span className="text-on-surface-variant">Created</span>
        <span className="text-right text-on-background">{formatDateTime(link.created_at)}</span>
        <span className="text-on-surface-variant">Expires</span>
        <span className="text-right text-on-background">{link.expires_at ? formatDateTime(link.expires_at) : "Never"}</span>
        {link.paid_at && (
          <>
            <span className="text-on-surface-variant">Paid</span>
            <span className="text-right text-on-background">{formatDateTime(link.paid_at)}</span>
          </>
        )}
        <span className="text-on-surface-variant">Attempts</span>
        <span className="text-right text-on-background">{link.attempt_count}</span>
        {link.merchant_reference && (
          <>
            <span className="text-on-surface-variant">Reference</span>
            <span className="text-right text-on-background">{link.merchant_reference}</span>
          </>
        )}
      </div>

      <div className="flex flex-col sm:flex-row gap-2.5">
        <a
          href={whatsappShareUrl(link)}
          target="_blank"
          rel="noreferrer"
          className="flex-1 flex items-center justify-center gap-2 bg-primary-container text-on-primary text-sm font-medium py-2.5 rounded-lg hover:opacity-90 transition-opacity"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
            <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z" />
            <path d="M12.001 2C6.478 2 2 6.477 2 12c0 1.802.472 3.552 1.369 5.09L2 22l5.03-1.319A9.96 9.96 0 0 0 12.001 22C17.523 22 22 17.523 22 12S17.523 2 12.001 2zm0 18.09c-1.61 0-3.19-.433-4.567-1.253l-.328-.194-3.03.795.81-2.955-.213-.34A8.075 8.075 0 0 1 3.91 12c0-4.465 3.63-8.09 8.091-8.09 4.462 0 8.09 3.625 8.09 8.09 0 4.465-3.628 8.09-8.09 8.09z" />
          </svg>
          Share
        </a>
        <a
          href={link.public_url}
          target="_blank"
          rel="noreferrer"
          className="flex-1 flex items-center justify-center gap-2 border border-surface-container-highest text-on-surface text-sm font-medium py-2.5 rounded-lg hover:bg-surface-container-low transition-colors"
        >
          <Icon name="open_in_new" className="text-[18px]" />
          Preview Customer Page
        </a>
      </div>

      <div className="flex flex-col items-center gap-2 pt-2 border-t border-surface-container-highest">
        <QrCode payload={link.public_url} expiresAt={link.expires_at} />
      </div>
    </div>
  );
}

export function PaymentLinksView() {
  const [links, setLinks] = useState<PaymentLink[]>([]);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("All");
  const [lastCreated, setLastCreated] = useState<PaymentLink | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [copiedPanel, setCopiedPanel] = useState(false);
  const [copiedRowId, setCopiedRowId] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [customerEmail, setCustomerEmail] = useState("");
  const [amount, setAmount] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [description, setDescription] = useState("");
  const [merchantReference, setMerchantReference] = useState("");
  const [createMessage, setCreateMessage] = useState("");

  useEffect(() => {
    listPaymentLinks().then((data) => {
      setLinks(data);
      setLastCreated(data[0] ?? null);
    });
  }, []);

  const filtered = useMemo(() => {
    if (filter === "All") return links;
    return links.filter((link) => link.status === filter.toUpperCase());
  }, [links, filter]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!amount) return;

    setSubmitting(true);
    try {
      const link = await createPaymentLink({
        amount,
        currency: "TZS",
        customer_name: customerName || null,
        customer_phone: customerPhone || null,
        customer_email: customerEmail || null,
        description: description || null,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        merchant_reference: merchantReference || null,
        success_redirect_url: null,
        failure_redirect_url: null,
      });
      setLinks((prev) => [link, ...prev]);
      setLastCreated(link);
      setCopiedPanel(false);
      setCustomerName("");
      setCustomerPhone("");
      setCustomerEmail("");
      setAmount("");
      setExpiresAt("");
      setDescription("");
      setMerchantReference("");
      setCreateMessage(
        link.customer_email_sent === true
          ? "Payment link created and emailed to customer."
          : link.customer_email_sent === false
            ? "Payment link created, but email could not be sent. You can copy or share the link manually."
            : "Payment link created. Add a customer email to send it automatically, or copy/share it manually.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCopyPanel() {
    if (!lastCreated) return;
    try {
      await navigator.clipboard.writeText(lastCreated.public_url);
      setCopiedPanel(true);
      setTimeout(() => setCopiedPanel(false), 2000);
    } catch {
      // Clipboard API unavailable (e.g. insecure context) — no-op, the URL
      // is still visible and selectable in the input.
    }
  }

  async function handleCopyRow(link: PaymentLink) {
    try {
      await navigator.clipboard.writeText(link.public_url);
      setCopiedRowId(link.id);
      setTimeout(() => setCopiedRowId((current) => (current === link.id ? null : current)), 2000);
    } catch {
      // no-op
    }
  }

  async function handleCancel(link: PaymentLink) {
    if (!window.confirm("Cancel this payment link? Customers won't be able to pay it anymore.")) return;
    setCancellingId(link.id);
    try {
      const cancelled = await cancelPaymentLink(link.id);
      setLinks((prev) => prev.map((row) => (row.id === link.id ? cancelled : row)));
      if (lastCreated?.id === link.id) setLastCreated(cancelled);
    } finally {
      setCancellingId(null);
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Payment Links"
        description="Create secure links and share them with customers to get paid instantly."
        action={
          <a
            href="#create-link"
            className="flex items-center justify-center gap-2 bg-primary-container text-on-primary px-4 py-2.5 rounded-lg text-sm font-medium hover:opacity-90 transition-opacity w-fit"
          >
            <Icon name="add" className="text-[18px]" />
            New Payment Link
          </a>
        }
      />

      <section id="create-link" className="scroll-mt-24 grid grid-cols-1 lg:grid-cols-5 gap-6">
        <form onSubmit={handleSubmit} className="lg:col-span-3 bg-surface rounded-xl border border-surface-container-highest shadow-ambient p-6 space-y-5">
          <h3 className="text-2xl font-semibold text-on-background mb-1">Create Payment Link</h3>
          <p className="text-sm text-on-surface-variant -mt-3">
            Secure Selcom hosted checkout — the customer chooses their payment method on checkout.
          </p>
          <div className="grid sm:grid-cols-2 gap-5">
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Customer Name</label>
              <input
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                placeholder="e.g. Grace Mwakalinga"
                type="text"
                value={customerName}
                onChange={(event) => setCustomerName(event.target.value)}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Phone Number</label>
              <input
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                placeholder="+255 7XX XXX XXX"
                type="tel"
                value={customerPhone}
                onChange={(event) => setCustomerPhone(event.target.value)}
              />
            </div>
          </div>
          <div className="grid sm:grid-cols-2 gap-5">
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Customer Email</label>
              <input
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                placeholder="grace@example.com"
                type="email"
                value={customerEmail}
                onChange={(event) => setCustomerEmail(event.target.value)}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Internal Reference</label>
              <input
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                placeholder="e.g. ORDER-4821"
                type="text"
                value={merchantReference}
                onChange={(event) => setMerchantReference(event.target.value)}
              />
            </div>
          </div>
          <div className="grid sm:grid-cols-2 gap-5">
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Amount (TZS)</label>
              <div className="relative">
                <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-on-surface-variant text-sm font-semibold">
                  TZS
                </span>
                <input
                  className="w-full pl-12 pr-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                  placeholder="25,000"
                  type="number"
                  min="1"
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Expiry Date &amp; Time</label>
              <input
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                type="datetime-local"
                value={expiresAt}
                onChange={(event) => setExpiresAt(event.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Description</label>
            <input
              className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
              placeholder="e.g. Invoice for graphic design services"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <button
            className="w-full bg-primary-container text-on-primary text-sm font-medium py-3 rounded-lg hover:opacity-90 transition-opacity flex items-center justify-center gap-2 disabled:opacity-60"
            type="submit"
            disabled={submitting}
          >
            <Icon name="link" className="text-[20px]" />
            {submitting ? "Generating…" : "Generate Payment Link"}
          </button>
        </form>

        <div className="lg:col-span-2 bg-surface rounded-xl border border-surface-container-highest shadow-ambient p-6 flex flex-col gap-5 h-fit">
          <div>
            <h3 className="text-2xl font-semibold text-on-background mb-1">Your Payment Link</h3>
            <p className="text-sm text-on-surface-variant">Share it with your customer to collect payment instantly.</p>
          </div>
          {createMessage && (
            <div
              className={
                lastCreated?.customer_email_sent === false
                  ? "rounded-lg bg-[#FEFCE8] text-[#854D0E] px-4 py-3 text-sm font-medium"
                  : "rounded-lg bg-primary-container/10 text-primary px-4 py-3 text-sm font-medium"
              }
            >
              {createMessage}
            </div>
          )}
          {lastCreated ? (
            <PaymentLinkDetail link={lastCreated} onCopy={handleCopyPanel} copied={copiedPanel} />
          ) : (
            <p className="text-sm text-on-surface-variant">Generate a link to see it here.</p>
          )}
        </div>
      </section>

      <Card padded={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">Your Payment Links</h3>
          <div className="flex gap-2">
            {FILTERS.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setFilter(option)}
                className={
                  filter === option
                    ? "px-3 py-1.5 rounded-full bg-primary-container/10 text-primary text-xs font-semibold"
                    : "px-3 py-1.5 rounded-full text-on-surface-variant text-xs font-semibold hover:bg-surface-container-low"
                }
              >
                {option}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[980px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Customer</th>
                <th className={thClass}>Amount</th>
                <th className={thClass}>Status</th>
                <th className={thClass}>Created</th>
                <th className={thClass}>Expires</th>
                <th className={thClass}>Attempts</th>
                <th className={`${thClass} text-right`}>Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {filtered.map((link) => {
                const badge = paymentLinkBadge(link.status);
                return (
                  <Fragment key={link.id}>
                    <tr className={`border-t border-surface-container-highest ${link.status === "EXPIRED" ? "opacity-60" : ""}`}>
                      <td className={tdClass}>
                        <div className="font-medium text-on-background">{link.customer_name ?? "—"}</div>
                        <div className="text-xs text-on-surface-variant">{link.description}</div>
                      </td>
                      <td className={`${tdClass} font-semibold text-on-background`}>{formatCurrency(link.amount, link.currency)}</td>
                      <td className={tdClass}>
                        <StatusBadge {...badge} />
                      </td>
                      <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(link.created_at)}</td>
                      <td className={`${tdClass} text-on-surface-variant text-xs`}>
                        {link.expires_at ? formatDateTime(link.expires_at) : "—"}
                      </td>
                      <td className={`${tdClass} text-on-surface-variant text-xs`}>{link.attempt_count}</td>
                      <td className={`${tdClass} text-right whitespace-nowrap`}>
                        <button
                          type="button"
                          onClick={() => handleCopyRow(link)}
                          className="p-1.5 text-on-surface-variant hover:text-primary"
                          title="Copy link"
                        >
                          <Icon name={copiedRowId === link.id ? "check" : "content_copy"} className="text-[18px]" />
                        </button>
                        <a
                          href={whatsappShareUrl(link)}
                          target="_blank"
                          rel="noreferrer"
                          className="p-1.5 text-on-surface-variant hover:text-primary inline-flex"
                          title="Share via WhatsApp"
                        >
                          <Icon name="ios_share" className="text-[18px]" />
                        </a>
                        <button
                          type="button"
                          onClick={() => setExpandedId((current) => (current === link.id ? null : link.id))}
                          className="p-1.5 text-on-surface-variant hover:text-primary"
                          title="View details"
                        >
                          <Icon name={expandedId === link.id ? "expand_less" : "visibility"} className="text-[18px]" />
                        </button>
                        {link.status === "ACTIVE" && (
                          <button
                            type="button"
                            onClick={() => handleCancel(link)}
                            disabled={cancellingId === link.id}
                            className="p-1.5 text-error hover:opacity-80 disabled:opacity-50"
                            title="Cancel link"
                          >
                            <Icon name="cancel" className="text-[18px]" />
                          </button>
                        )}
                      </td>
                    </tr>
                    {expandedId === link.id && (
                      <tr className="border-t border-surface-container-highest bg-surface-container-lowest">
                        <td colSpan={7} className="px-5 py-5">
                          <div className="max-w-lg">
                            <PaymentLinkDetail
                              link={link}
                              onCopy={() => handleCopyRow(link)}
                              copied={copiedRowId === link.id}
                            />
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
