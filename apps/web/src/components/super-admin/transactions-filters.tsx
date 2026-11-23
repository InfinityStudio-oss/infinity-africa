"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Card } from "@/components/portal/card";
import type { MerchantOption } from "@/lib/admin/types";

const inputClass = "px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm";

export interface TransactionsFilterValues {
  merchantId?: string;
  type?: string;
  status?: string;
  providerReference?: string;
  transactionId?: string;
  collectionId?: string;
  customerPhone?: string;
  dateFrom?: string;
  dateTo?: string;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function TransactionsFilters({ merchants, initial }: { merchants: MerchantOption[]; initial: TransactionsFilterValues }) {
  const router = useRouter();
  const [values, setValues] = useState<TransactionsFilterValues>(initial);

  // The phone field keeps its own draft and only searches when the
  // operator is finished - Enter, or leaving the field.
  //
  // Every other control here navigates on change, which is right for a
  // dropdown and wrong for a phone number: a 12-digit number typed into
  // an onChange field is 12 server round trips, each one a trigram scan
  // across every collection on the platform, and the operator watches
  // the page reload under them as they type.
  const [phoneDraft, setPhoneDraft] = useState(initial.customerPhone ?? "");

  // Keep the draft honest when the URL changes under us - back/forward,
  // or a cleared filter - so the box never shows a number that is not
  // the one being searched.
  useEffect(() => {
    setPhoneDraft(initial.customerPhone ?? "");
  }, [initial.customerPhone]);

  // The payment id a merchant quotes from their billing system. Checked
  // here before it is sent: the API takes a UUID, and a mistyped one
  // would come back as an error that this page renders as "no matches" -
  // telling the operator the payment does not exist when it was a typo.
  const [paymentIdDraft, setPaymentIdDraft] = useState(initial.collectionId ?? "");
  const [paymentIdError, setPaymentIdError] = useState<string | null>(null);
  // Follow the URL (back/forward, cleared filters) by adjusting state
  // during render, React's recommended alternative to an effect here.
  const [paymentIdFromUrl, setPaymentIdFromUrl] = useState(initial.collectionId);
  if (paymentIdFromUrl !== initial.collectionId) {
    setPaymentIdFromUrl(initial.collectionId);
    setPaymentIdDraft(initial.collectionId ?? "");
  }

  function applyPaymentId() {
    const trimmed = paymentIdDraft.trim();
    if (trimmed && !UUID_PATTERN.test(trimmed)) {
      setPaymentIdError("An InfinityPay Payment ID looks like 6f1c2b9e-1a2b-4c3d-8e9f-0123456789ab.");
      return;
    }
    setPaymentIdError(null);
    if (trimmed === (values.collectionId ?? "")) return;
    apply({ ...values, collectionId: trimmed || undefined });
  }

  function apply(next: TransactionsFilterValues) {
    setValues(next);
    const params = new URLSearchParams();
    if (next.merchantId) params.set("merchant_id", next.merchantId);
    if (next.type) params.set("type", next.type);
    if (next.status) params.set("status", next.status);
    if (next.providerReference) params.set("provider_reference", next.providerReference);
    if (next.transactionId) params.set("transaction_id", next.transactionId);
    if (next.collectionId) params.set("collection_id", next.collectionId);
    if (next.customerPhone) params.set("customer_phone", next.customerPhone);
    if (next.dateFrom) params.set("date_from", next.dateFrom);
    if (next.dateTo) params.set("date_to", next.dateTo);
    const query = params.toString();
    router.push(query ? `/super-admin/transactions?${query}` : "/super-admin/transactions");
  }

  function applyPhone() {
    const trimmed = phoneDraft.trim();
    // Nothing to do if it has not actually changed - a blur on an
    // untouched field should not reload the page.
    if (trimmed === (values.customerPhone ?? "")) return;
    apply({ ...values, customerPhone: trimmed || undefined });
  }

  return (
    <Card>
      {Object.values(values).some(Boolean) && (
        <div className="flex justify-end mb-3">
          <button
            type="button"
            onClick={() => {
              setValues({});
              setPhoneDraft("");
              setPaymentIdDraft("");
              setPaymentIdError(null);
              router.push("/super-admin/transactions");
            }}
            className="text-sm font-medium text-primary hover:underline"
          >
            Clear filters
          </button>
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        <select
          className={inputClass}
          value={values.merchantId ?? ""}
          onChange={(event) => apply({ ...values, merchantId: event.target.value || undefined })}
        >
          <option value="">All Merchants</option>
          {merchants.map((merchant) => (
            <option key={merchant.merchant_id} value={merchant.merchant_id}>
              {merchant.business_name}
            </option>
          ))}
        </select>
        <select
          className={inputClass}
          value={values.type ?? ""}
          onChange={(event) => apply({ ...values, type: event.target.value || undefined })}
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
        <select
          className={inputClass}
          value={values.status ?? ""}
          onChange={(event) => apply({ ...values, status: event.target.value || undefined })}
        >
          <option value="">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="processing">Processing</option>
          <option value="successful">Successful</option>
          <option value="failed">Failed</option>
          <option value="reversed">Reversed</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <input
          className={inputClass}
          placeholder="Provider reference"
          value={values.providerReference ?? ""}
          onChange={(event) => apply({ ...values, providerReference: event.target.value || undefined })}
        />
        <input
          className={inputClass}
          placeholder="Transaction ID"
          value={values.transactionId ?? ""}
          onChange={(event) => apply({ ...values, transactionId: event.target.value || undefined })}
        />
        <div>
          <input
            className={`${inputClass} w-full`}
            placeholder="InfinityPay Payment ID"
            aria-label="InfinityPay Payment ID (collection_id)"
            aria-invalid={paymentIdError ? true : undefined}
            aria-describedby={paymentIdError ? "payment-id-error" : undefined}
            value={paymentIdDraft}
            onChange={(event) => setPaymentIdDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                applyPaymentId();
              }
            }}
            onBlur={applyPaymentId}
          />
          {paymentIdError && (
            <p id="payment-id-error" role="alert" className="mt-1 text-xs text-error">
              {paymentIdError}
            </p>
          )}
        </div>
        <input
          className={inputClass}
          type="tel"
          inputMode="tel"
          placeholder="Customer phone — or last 6 digits"
          aria-label="Customer phone number"
          value={phoneDraft}
          onChange={(event) => setPhoneDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              applyPhone();
            }
          }}
          onBlur={applyPhone}
        />
        <input
          className={inputClass}
          type="date"
          value={values.dateFrom ?? ""}
          onChange={(event) => apply({ ...values, dateFrom: event.target.value || undefined })}
          aria-label="From date"
        />
        <input
          className={inputClass}
          type="date"
          value={values.dateTo ?? ""}
          onChange={(event) => apply({ ...values, dateTo: event.target.value || undefined })}
          aria-label="To date"
        />
      </div>
    </Card>
  );
}
