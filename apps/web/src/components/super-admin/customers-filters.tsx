"use client";

import { useRouter } from "next/navigation";

import { Card } from "@/components/portal/card";
import type { MerchantOption } from "@/lib/admin/types";

export function CustomersFilters({ merchants, selectedMerchantId }: { merchants: MerchantOption[]; selectedMerchantId?: string }) {
  const router = useRouter();

  return (
    <Card>
      <select
        className="px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm w-full sm:w-72"
        value={selectedMerchantId ?? ""}
        onChange={(event) => {
          const value = event.target.value;
          router.push(value ? `/super-admin/customers?merchant_id=${value}` : "/super-admin/customers");
        }}
      >
        <option value="">All Merchants</option>
        {merchants.map((merchant) => (
          <option key={merchant.merchant_id} value={merchant.merchant_id}>
            {merchant.business_name}
          </option>
        ))}
      </select>
    </Card>
  );
}
