"use client";

import { useState } from "react";

import { USER_ROLE_LABELS, UserRole } from "@infinity/shared";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import { merchantUserStatusBadge } from "@/lib/admin/status-tones";
import type { MerchantUserRow } from "@/lib/admin/types";

const ROLE_FILTERS = ["All Roles", UserRole.MERCHANT_ADMIN, UserRole.MERCHANT_STAFF, UserRole.DEVELOPER] as const;

function initials(name: string): string {
  return name
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function MerchantUsersTable({ rows }: { rows: MerchantUserRow[] }) {
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<(typeof ROLE_FILTERS)[number]>("All Roles");

  const filtered = rows.filter((user) => {
    if (roleFilter !== "All Roles" && user.role !== roleFilter) return false;
    const name = user.full_name ?? "";
    const email = user.email ?? "";
    if (
      search &&
      !name.toLowerCase().includes(search.toLowerCase()) &&
      !user.merchant_name.toLowerCase().includes(search.toLowerCase()) &&
      !email.toLowerCase().includes(search.toLowerCase())
    ) {
      return false;
    }
    return true;
  });

  return (
    <>
      <Card>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
          <input
            className="sm:col-span-3 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
            placeholder="Search by user name, business, or email"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            className="px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
            value={roleFilter}
            onChange={(event) => setRoleFilter(event.target.value as (typeof ROLE_FILTERS)[number])}
          >
            {ROLE_FILTERS.map((role) => (
              <option key={role} value={role}>
                {role === "All Roles" ? role : USER_ROLE_LABELS[role]}
              </option>
            ))}
          </select>
        </div>
      </Card>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">All Business Users</h3>
        </div>
        {filtered.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">No merchant users match your filters.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[900px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>User</th>
                  <th className={thClass}>Merchant</th>
                  <th className={thClass}>Role</th>
                  <th className={thClass}>Created</th>
                  <th className={thClass}>Status</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {filtered.map((user) => (
                  <tr
                    key={user.user_id}
                    className={`border-t border-surface-container-highest ${user.status === "suspended" ? "opacity-60" : ""}`}
                  >
                    <td className={tdClass}>
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-full bg-primary-container/15 text-primary flex items-center justify-center font-bold text-xs shrink-0">
                          {initials(user.full_name ?? user.email ?? "?")}
                        </div>
                        <div>
                          <div className="font-medium text-on-background">{user.full_name ?? "—"}</div>
                          <div className="text-xs text-on-surface-variant">{user.email ?? "—"}</div>
                        </div>
                      </div>
                    </td>
                    <td className={tdClass}>
                      <div className="text-on-surface-variant">{user.merchant_name}</div>
                      {user.merchant_code && (
                        <div className="font-mono text-xs text-on-surface-variant">{user.merchant_code}</div>
                      )}
                    </td>
                    <td className={tdClass}>
                      <StatusBadge label={USER_ROLE_LABELS[user.role]} tone="info" />
                    </td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(user.created_at)}</td>
                    <td className={tdClass}>
                      <StatusBadge {...merchantUserStatusBadge(user.status)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
