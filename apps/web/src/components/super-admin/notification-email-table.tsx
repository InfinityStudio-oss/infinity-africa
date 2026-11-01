"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import type { AdminNotificationSettingsListRow } from "@/lib/admin/types";

/**
 * Super Admin → Notifications → Email.
 *
 * The column that earns its place is **Receives**: not the stored
 * address, but the address an email would actually go to today. The
 * fallback rule (no address configured → the account's own contact
 * email) is real, and a table showing only the stored field would have an
 * operator reading a blank as "they get nothing" when in fact they do.
 *
 * Search and paging are server-side — the form submits to the same route
 * with ?q= and ?page=, so a filtered view is a real URL somebody can
 * send to a colleague, and the browser never holds more than one page.
 */
export function NotificationEmailTable({
  rows,
  search,
  page,
  totalPages,
}: {
  rows: AdminNotificationSettingsListRow[];
  search: string;
  page: number;
  totalPages: number;
}) {
  const router = useRouter();
  const params = useSearchParams();
  const [term, setTerm] = useState(search);

  function go(next: { q?: string; page?: number }) {
    const query = new URLSearchParams(params.toString());
    if (next.q !== undefined) {
      if (next.q) query.set("q", next.q);
      else query.delete("q");
      // A new search starts at the beginning; keeping the old page
      // number is how a search lands on an empty screen that looks like
      // "no results".
      query.delete("page");
    }
    if (next.page !== undefined) query.set("page", String(next.page));
    router.push(`/super-admin/notifications/email?${query.toString()}`);
  }

  return (
    <div className="space-y-4">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          go({ q: term.trim() });
        }}
        className="flex flex-wrap gap-2"
      >
        <input
          type="search"
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder="Search by business name or ID"
          aria-label="Search businesses"
          className="flex-1 min-w-[16rem] rounded-lg border border-outline-variant bg-transparent px-3 py-2 text-sm text-on-surface placeholder-outline focus:outline-none focus:border-primary-container"
        />
        <button
          type="submit"
          className="rounded-lg bg-primary-container px-4 py-2 text-sm font-semibold text-on-primary hover:opacity-90"
        >
          Search
        </button>
        {search && (
          <button
            type="button"
            onClick={() => {
              setTerm("");
              go({ q: "" });
            }}
            className="rounded-lg border border-outline-variant px-4 py-2 text-sm font-semibold text-on-surface-variant hover:bg-surface-container-low"
          >
            Clear
          </button>
        )}
      </form>

      {rows.length === 0 ? (
        <div className="rounded-xl border border-outline-variant bg-surface p-8 text-center">
          <p className="text-sm text-on-surface-variant">
            {search ? `No business matches “${search}”.` : "No businesses yet."}
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-outline-variant bg-surface overflow-x-auto">
          <table className="w-full text-left min-w-[900px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold">
                <th className={thClass}>Business</th>
                <th className={thClass}>Collection emails</th>
                <th className={thClass}>Receives</th>
                <th className={thClass}>Last changed</th>
                <th className={`${thClass} text-right`}>Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {rows.map((row) => (
                <tr key={row.merchant_id} className="border-t border-surface-container-highest align-top">
                  <td className={tdClass}>
                    <div className="font-medium text-on-background">{row.merchant_name}</div>
                    {row.merchant_code && (
                      <div className="font-mono text-xs text-on-surface-variant">{row.merchant_code}</div>
                    )}
                  </td>
                  <td className={tdClass}>
                    <StatusBadge
                      label={row.collection_notifications_enabled ? "Enabled" : "Disabled"}
                      tone={row.collection_notifications_enabled ? "positive" : "negative"}
                    />
                    {/* Never configured is not the same as off, and reads
                        like it unless the table says so. */}
                    {!row.configured && (
                      <p className="text-[11px] text-outline mt-1">Default — never changed</p>
                    )}
                  </td>
                  <td className={`${tdClass} text-on-surface-variant`}>
                    {row.collection_notifications_enabled ? (
                      <>
                        <span className="break-all">{row.effective_recipient ?? "—"}</span>
                        {row.uses_account_email_fallback && (
                          <p className="text-[11px] text-outline mt-0.5 flex items-center gap-1">
                            <Icon name="info" className="text-[12px]" />
                            Account email — no notification address set
                          </p>
                        )}
                      </>
                    ) : (
                      <span className="text-outline">Nobody — switched off</span>
                    )}
                  </td>
                  <td className={`${tdClass} text-on-surface-variant text-xs`}>
                    {row.updated_at ? formatDateTime(row.updated_at) : "—"}
                  </td>
                  <td className={`${tdClass} text-right`}>
                    <Link
                      href={`/super-admin/merchants/${row.merchant_id}`}
                      className="text-xs font-semibold text-primary-container hover:underline"
                    >
                      Edit
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-on-surface-variant">
            Page {page} of {totalPages}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => go({ page: page - 1 })}
              className="rounded-lg border border-outline-variant px-3 py-1.5 text-xs font-semibold text-on-surface-variant disabled:opacity-40 hover:bg-surface-container-low"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => go({ page: page + 1 })}
              className="rounded-lg border border-outline-variant px-3 py-1.5 text-xs font-semibold text-on-surface-variant disabled:opacity-40 hover:bg-surface-container-low"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
