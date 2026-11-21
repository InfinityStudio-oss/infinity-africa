"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, useTransition } from "react";

import { tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { formatDateTime } from "@/lib/format";
import { setCollectionEmailsEnabledAction } from "@/lib/admin/live-actions";
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
/**
 * One row, switchable in place.
 *
 * The whole row is a component rather than the switch alone because two
 * cells describe the same fact: the pill says Enabled/Disabled and
 * "Receives" says either an address or "Nobody — switched off". Keeping
 * one optimistic `enabled` for both means they can never contradict each
 * other while the save is in flight, which is exactly the moment an
 * operator is looking to see whether the click took.
 *
 * Optimistic, then reverted on failure. The alternative — wait for the
 * round trip — leaves the pill reading "Enabled" after a deliberate
 * click to disable, which reads as a dead control and invites a second
 * click.
 */
function NotificationRow({ row }: { row: AdminNotificationSettingsListRow }) {
  const [enabled, setEnabled] = useState(row.collection_notifications_enabled);
  const [error, setError] = useState<string | null>(null);
  // The value currently being written, or null when nothing is in
  // flight. Kept separately from `enabled` on purpose: deriving the
  // in-progress label from `enabled` means that the instant a failed
  // save reverts it, the pill reads "Enabling…" — announcing the exact
  // thing that just did not happen.
  const [saving, setSaving] = useState<boolean | null>(null);
  const [pending, startTransition] = useTransition();

  function toggle() {
    const next = !enabled;
    setError(null);
    setEnabled(next);
    setSaving(next);
    startTransition(async () => {
      const result = await setCollectionEmailsEnabledAction(row.merchant_id, next);
      if (result.error) {
        // Nothing was saved, so the pill must go back to what the server
        // still holds rather than leaving a lie on screen.
        setEnabled(!next);
        setError(result.error);
      }
      setSaving(null);
    });
  }

  return (
    <tr className="border-t border-surface-container-highest align-top">
      <td className={tdClass}>
        <div className="font-medium text-on-background">{row.merchant_name}</div>
        {row.merchant_code && (
          <div className="font-mono text-xs text-on-surface-variant">{row.merchant_code}</div>
        )}
      </td>
      <td className={tdClass}>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label={`Collection emails for ${row.merchant_name}`}
          title={
            enabled
              ? "Click to stop sending collection emails to this business"
              : "Click to start sending collection emails to this business"
          }
          disabled={pending || saving !== null}
          onClick={toggle}
          // Measured against the composited panel (#cfdade), not against
          // the token: these backgrounds are translucent tints, so the
          // real background has to be mixed before it can be judged.
          // Enabled 7.07:1 at rest, 5.68:1 on hover; disabled 5.30:1 and
          // 5.74:1. The darker ink on hover is not decoration — red-700
          // on red-200 measures 4.47:1 and misses the 4.5 floor.
          //
          // Nothing is dimmed while saving. The usual disabled:opacity-60
          // took the in-flight label to 2.86:1, i.e. the one moment the
          // operator most wants to read it. The pulsing dot and the
          // "Disabling…" label carry that state instead.
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold transition-colors cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1 disabled:cursor-wait ${
            enabled
              ? "bg-primary-container/10 text-primary hover:bg-primary-container/25"
              : "bg-red-100 text-red-700 hover:bg-red-200 hover:text-red-800"
          }`}
        >
          <span className={`h-1.5 w-1.5 rounded-full bg-current ${saving !== null ? "animate-pulse" : ""}`} />
          {saving !== null
            ? saving
              ? "Enabling…"
              : "Disabling…"
            : enabled
              ? "Enabled"
              : "Disabled"}
        </button>
        {/* Never configured is not the same as off, and reads like it
            unless the table says so. Once the operator has switched the
            row themselves it is no longer a default, whatever the
            server-rendered prop still says. */}
        {!row.configured && enabled === row.collection_notifications_enabled && (
          <p className="text-[11px] text-outline mt-1">Default — never changed</p>
        )}
        {error && (
          <p role="alert" className="text-[11px] text-red-700 mt-1 max-w-[14rem]">
            {error}
          </p>
        )}
      </td>
      <td className={`${tdClass} text-on-surface-variant`}>
        {enabled ? (
          // effective_recipient is null whenever the server rendered this
          // row as OFF, so straight after switching one back on there is
          // no address to name yet — it arrives with the revalidated row
          // a moment later. Printing the usual "—" in that gap would say
          // "nobody is told", which is the opposite of what just
          // happened.
          row.effective_recipient ?? row.primary_notification_email ? (
            <>
              <span className="break-all">{row.effective_recipient ?? row.primary_notification_email}</span>
              {row.uses_account_email_fallback && (
                <p className="text-[11px] text-outline mt-0.5 flex items-center gap-1">
                  <Icon name="info" className="text-[12px]" />
                  Account email — no notification address set
                </p>
              )}
            </>
          ) : (
            <span className="text-outline">Their account email</span>
          )
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
  );
}

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
                <NotificationRow key={row.merchant_id} row={row} />
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
