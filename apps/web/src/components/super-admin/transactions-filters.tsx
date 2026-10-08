"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Card } from "@/components/portal/card";
import type { MerchantOption } from "@/lib/admin/types";

const inputClass = "px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm";

export interface TransactionsFilterValues {
  merchantId?: string;
  type?: string;
  status?: string;
  providerReference?: string;
  transactionId?: string;
  dateFrom?: string;
  dateTo?: string;
}

export function TransactionsFilters({ merchants, initial }: { merchants: MerchantOption[]; initial: TransactionsFilterValues }) {
  const router = useRouter();
  const [values, setValues] = useState<TransactionsFilterValues>(initial);

  function apply(next: TransactionsFilterValues) {
    setValues(next);
    const params = new URLSearchParams();
    if (next.merchantId) params.set("merchant_id", next.merchantId);
    if (next.type) params.set("type", next.type);
    if (next.status) params.set("status", next.status);
    if (next.providerReference) params.set("provider_reference", next.providerReference);
    if (next.transactionId) params.set("transaction_id", next.transactionId);
    if (next.dateFrom) params.set("date_from", next.dateFrom);
    if (next.dateTo) params.set("date_to", next.dateTo);
    const query = params.toString();
    router.push(query ? `/super-admin/transactions?${query}` : "/super-admin/transactions");
  }

  return (
    <Card>
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
