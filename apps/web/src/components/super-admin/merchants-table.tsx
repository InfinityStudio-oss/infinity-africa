"use client";

import Link from "next/link";
import { useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { approveMerchantAction, setMerchantStatusAction } from "@/lib/admin/live-actions";
import { merchantStatusBadge } from "@/lib/admin/status-tones";
import type { Merchant } from "@/lib/admin/types";

function initials(name: string): string {
  return name
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function MerchantsTable({ rows }: { rows: Merchant[] }) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("All Statuses");

  const filtered = rows.filter((merchant) => {
    if (statusFilter !== "All Statuses") {
      const labels: Record<string, Merchant["account_status"]> = {
        Active: "active",
        "Pending Verification": "pending",
        Suspended: "suspended",
        Closed: "closed",
      };
      if (merchant.account_status !== labels[statusFilter]) return false;
    }
    if (search) {
      const needle = search.toLowerCase();
      const haystack = [
        merchant.business_name,
        merchant.merchant_code ?? "",
        merchant.email,
        merchant.contact_phone ?? "",
      ]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });

  return (
    <>
      <Card>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <input
            className="sm:col-span-2 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
            placeholder="Search by ID, business name, email, or phone"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            className="px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option>All Statuses</option>
            <option>Active</option>
            <option>Pending Verification</option>
            <option>Suspended</option>
            <option>Closed</option>
          </select>
        </div>
      </Card>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">All Merchants</h3>
        </div>
        {filtered.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">No merchants match your filters.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[900px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Merchant</th>
                  <th className={thClass}>Owner</th>
                  <th className={thClass}>Available Balance</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass}>Created</th>
                  <th className={`${thClass} text-right`}>Actions</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {filtered.map((merchant) => {
                  const badge = merchantStatusBadge(merchant.account_status);
                  return (
                    <tr
                      key={merchant.merchant_id}
                      className={`border-t border-surface-container-highest ${merchant.account_status === "suspended" ? "opacity-60" : ""}`}
                    >
                      <td className={tdClass}>
                        <Link
                          href={`/super-admin/merchants/${merchant.merchant_id}`}
                          className="flex items-center gap-3 hover:opacity-80"
                        >
                          <div className="w-9 h-9 rounded-full bg-primary-container/15 text-primary flex items-center justify-center font-bold text-xs shrink-0">
                            {initials(merchant.business_name)}
                          </div>
                          <div>
                            <div className="font-medium text-on-background">{merchant.business_name}</div>
                            <div className="text-xs text-on-surface-variant">
                              {merchant.email}
                              {merchant.merchant_code && (
                                <>
                                  {" "}
                                  · <span className="font-mono">{merchant.merchant_code}</span>
                                </>
                              )}
                            </div>
                          </div>
                        </Link>
                      </td>
                      <td className={`${tdClass} text-on-surface-variant`}>{merchant.owner_name ?? "—"}</td>
                      <td className={`${tdClass} font-semibold text-on-background`}>
                        {formatCurrency(merchant.available_balance, "TZS")}
                      </td>
                      <td className={tdClass}>
                        <StatusBadge {...badge} />
                      </td>
                      <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(merchant.created_at)}</td>
                      <td className={`${tdClass} text-right whitespace-nowrap`}>
                        {merchant.account_status === "pending" && (
                          <form action={approveMerchantAction.bind(null, merchant.merchant_id)} className="inline">
                            <button className="p-1.5 text-on-surface-variant hover:text-primary" title="Approve">
                              <Icon name="check_circle" className="text-[18px]" />
                            </button>
                          </form>
                        )}
                        {merchant.account_status === "active" && (
                          <form
                            action={setMerchantStatusAction.bind(null, merchant.merchant_id, "suspended")}
                            className="inline"
                          >
                            <button className="p-1.5 text-on-surface-variant hover:text-error" title="Suspend">
                              <Icon name="block" className="text-[18px]" />
                            </button>
                          </form>
                        )}
                        {merchant.account_status === "suspended" && (
                          <form
                            action={setMerchantStatusAction.bind(null, merchant.merchant_id, "active")}
                            className="inline"
                          >
                            <button className="p-1.5 text-on-surface-variant hover:text-primary" title="Reactivate">
                              <Icon name="restart_alt" className="text-[18px]" />
                            </button>
                          </form>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
