"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { COLLECTION_METHOD_LABELS, COLLECTION_SOURCE_LABELS, CollectionMethod, CollectionSource } from "@infinity/shared";

import { Card } from "@/components/portal/card";
import type { MerchantOption } from "@/lib/admin/types";

const selectClass = "px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm";

export interface CollectionsFilterValues {
  merchantId?: string;
  source?: string;
  method?: string;
  status?: string;
  dateFrom?: string;
  dateTo?: string;
}

export function CollectionsFilters({ merchants, initial }: { merchants: MerchantOption[]; initial: CollectionsFilterValues }) {
  const router = useRouter();
  const [values, setValues] = useState<CollectionsFilterValues>(initial);

  function apply(next: CollectionsFilterValues) {
    setValues(next);
    const params = new URLSearchParams();
    if (next.merchantId) params.set("merchant_id", next.merchantId);
    if (next.source) params.set("source", next.source);
    if (next.method) params.set("method", next.method);
    if (next.status) params.set("status", next.status);
    if (next.dateFrom) params.set("date_from", next.dateFrom);
    if (next.dateTo) params.set("date_to", next.dateTo);
    const query = params.toString();
    router.push(query ? `/super-admin/collections?${query}` : "/super-admin/collections");
  }

  return (
    <Card>
      <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-6 gap-4">
        <select
          className={selectClass}
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
          className={selectClass}
          value={values.source ?? ""}
          onChange={(event) => apply({ ...values, source: event.target.value || undefined })}
        >
          <option value="">All Sources</option>
          {Object.values(CollectionSource).map((source) => (
            <option key={source} value={source}>
              {COLLECTION_SOURCE_LABELS[source]}
            </option>
          ))}
        </select>
        <select
          className={selectClass}
          value={values.method ?? ""}
          onChange={(event) => apply({ ...values, method: event.target.value || undefined })}
        >
          <option value="">All Methods</option>
          {Object.values(CollectionMethod).map((method) => (
            <option key={method} value={method}>
              {COLLECTION_METHOD_LABELS[method]}
            </option>
          ))}
        </select>
        <select
          className={selectClass}
          value={values.status ?? ""}
          onChange={(event) => apply({ ...values, status: event.target.value || undefined })}
        >
          <option value="">All Statuses</option>
          <option value="successful">Successful</option>
          <option value="pending">Pending</option>
          <option value="processing">Processing</option>
          <option value="failed">Failed</option>
          <option value="reversed">Reversed</option>
          <option value="pending_review">Pending Review</option>
        </select>
        <input
          className={selectClass}
          type="date"
          value={values.dateFrom ?? ""}
          onChange={(event) => apply({ ...values, dateFrom: event.target.value || undefined })}
          aria-label="From date"
        />
        <input
          className={selectClass}
          type="date"
          value={values.dateTo ?? ""}
          onChange={(event) => apply({ ...values, dateTo: event.target.value || undefined })}
          aria-label="To date"
        />
      </div>
    </Card>
  );
}
