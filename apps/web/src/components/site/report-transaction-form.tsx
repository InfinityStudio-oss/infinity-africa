"use client";

import { useState } from "react";

import { Icon } from "@/components/portal/icon";
import { DisputeReportError, submitDisputeReport } from "@/lib/public/disputes";

const REASON_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "PRODUCT_NOT_RECEIVED", label: "Product not received" },
  { value: "SERVICE_NOT_DELIVERED", label: "Service not delivered" },
  { value: "WRONG_PRODUCT_OR_SERVICE", label: "Wrong product/service" },
  { value: "DUPLICATE_PAYMENT", label: "Duplicate payment" },
  { value: "UNAUTHORIZED_PAYMENT", label: "Unauthorized payment" },
  { value: "REFUND_REQUESTED", label: "Refund requested" },
  { value: "OTHER", label: "Other" },
];

const inputClass =
  "w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm";
const labelClass = "block text-sm font-medium text-on-surface-variant mb-1.5";

export function ReportTransactionForm() {
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [customerEmail, setCustomerEmail] = useState("");
  const [transactionReference, setTransactionReference] = useState("");
  const [merchantName, setMerchantName] = useState("");
  const [amount, setAmount] = useState("");
  const [paymentDate, setPaymentDate] = useState("");
  const [reasonCategory, setReasonCategory] = useState(REASON_OPTIONS[0].value);
  const [description, setDescription] = useState("");
  const [evidence, setEvidence] = useState<File[]>([]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await submitDisputeReport({
        customer_name: customerName,
        customer_phone: customerPhone,
        customer_email: customerEmail || undefined,
        transaction_reference: transactionReference || undefined,
        merchant_name: merchantName || undefined,
        amount: amount || undefined,
        payment_date: paymentDate || undefined,
        reason_category: reasonCategory,
        description,
        evidence,
      });
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof DisputeReportError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (submitted) {
    return (
      <div className="text-center py-10">
        <div className="w-14 h-14 rounded-full bg-primary-container/10 text-primary flex items-center justify-center mx-auto mb-4">
          <Icon name="check_circle" className="text-[28px]" />
        </div>
        <h3 className="text-xl font-semibold text-on-surface mb-2">Report received</h3>
        <p className="text-sm text-on-surface-variant max-w-md mx-auto">
          Your report has been received. InfinityPay will review the transaction and contact the business where
          necessary.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {error && <div className="rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error">{error}</div>}

      <div className="grid sm:grid-cols-2 gap-5">
        <div>
          <label className={labelClass}>Your Full Name</label>
          <input required value={customerName} onChange={(e) => setCustomerName(e.target.value)} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Phone Number</label>
          <input required value={customerPhone} onChange={(e) => setCustomerPhone(e.target.value)} placeholder="+255 7XX XXX XXX" className={inputClass} />
        </div>
      </div>

      <div>
        <label className={labelClass}>Email (optional)</label>
        <input type="email" value={customerEmail} onChange={(e) => setCustomerEmail(e.target.value)} className={inputClass} />
      </div>

      <div className="grid sm:grid-cols-2 gap-5">
        <div>
          <label className={labelClass}>Transaction Reference</label>
          <input value={transactionReference} onChange={(e) => setTransactionReference(e.target.value)} placeholder="TXN-..." className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Business Name (if known)</label>
          <input value={merchantName} onChange={(e) => setMerchantName(e.target.value)} className={inputClass} />
        </div>
      </div>

      <div className="grid sm:grid-cols-2 gap-5">
        <div>
          <label className={labelClass}>Amount Paid</label>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="25000.00" className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Payment Date</label>
          <input type="date" value={paymentDate} onChange={(e) => setPaymentDate(e.target.value)} className={inputClass} />
        </div>
      </div>

      <div>
        <label className={labelClass}>Reason</label>
        <select value={reasonCategory} onChange={(e) => setReasonCategory(e.target.value)} className={inputClass}>
          {REASON_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className={labelClass}>Description</label>
        <textarea
          required
          rows={4}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Tell us what happened…"
          className={inputClass}
        />
      </div>

      <div>
        <label className={labelClass}>Supporting Evidence (optional)</label>
        <input
          type="file"
          multiple
          accept=".pdf,.jpg,.jpeg,.png"
          onChange={(e) => setEvidence(e.target.files ? Array.from(e.target.files) : [])}
          className="text-sm"
        />
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="w-full bg-primary-container text-on-primary text-sm font-medium py-3 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
      >
        {submitting ? "Submitting…" : "Submit Report"}
      </button>
    </form>
  );
}
