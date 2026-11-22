"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { INVOICE_STATUS_LABELS, InvoiceStatus } from "@infinity/shared";

import { Card } from "@/components/portal/card";

/**
 * The Super Admin invoice filters.
 *
 * These three controls existed before this file and were wired to
 * nothing: a search box, a status dropdown and an unlabelled date
 * input, none with a handler. The screen looked filterable and was not,
 * which is worse than having no filters, because the list below them
 * appeared to be a result.
 *
 * Every value lives in the URL so a filtered view can be linked to and
 * reloaded, and so the server component below does the filtering - the
 * list is paginated, and narrowing the page the browser already holds
 * would report "no such invoice" for one on page two.
 */

const FILTER_CLASS =
  "px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary";

export interface InvoiceFilterValues {
  search?: string;
  status?: string;
  dueBefore?: string;
}

export function InvoicesFilters({ initial }: { initial: InvoiceFilterValues }) {
  const router = useRouter();

  // The search box keeps a draft and searches on Enter or on leaving
  // the field. The dropdown and the date box navigate on change, which
  // is right for them: one interaction produces one complete value. A
  // text box does not - typing an invoice number would be a server
  // round trip per character, with the page reloading underneath.
  const [draft, setDraft] = useState(initial.search ?? "");

  // Follow the URL when it changes under us - back/forward, or Clear -
  // so the box never shows a term the results are not for.
  useEffect(() => {
    setDraft(initial.search ?? "");
  }, [initial.search]);

  const anyFilter = Boolean(initial.search || initial.status || initial.dueBefore);

  function push(next: InvoiceFilterValues) {
    const params = new URLSearchParams();
    if (next.search) params.set("search", next.search);
    if (next.status) params.set("status", next.status);
    if (next.dueBefore) params.set("due_before", next.dueBefore);
    const query = params.toString();
    router.push(query ? `/super-admin/invoices?${query}` : "/super-admin/invoices");
  }

  function applySearch() {
    const trimmed = draft.trim();
    // A blur on an untouched box is not a search.
    if (trimmed === (initial.search ?? "")) return;
    push({ ...initial, search: trimmed || undefined });
  }

  return (
    <Card>
      {anyFilter && (
        <div className="flex justify-end mb-3">
          <button
            type="button"
            onClick={() => router.push("/super-admin/invoices")}
            className="text-sm font-medium text-primary hover:underline"
          >
            Clear filters
          </button>
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <input
          className={`sm:col-span-2 ${FILTER_CLASS}`}
          type="search"
          placeholder="Invoice number, business, or customer"
          aria-label="Search invoices by number, business, or customer"
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
            // Emptying the box restores the full list without needing
            // Enter; making someone press it to undo a search reads as
            // a broken page.
            if (event.target.value.trim() === "" && initial.search) {
              push({ ...initial, search: undefined });
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              applySearch();
            }
          }}
          onBlur={applySearch}
        />
        <select
          className={FILTER_CLASS}
          aria-label="Invoice status"
          value={initial.status ?? ""}
          onChange={(event) => push({ ...initial, status: event.target.value || undefined })}
        >
          <option value="">All Statuses</option>
          {/* Labelled from the shared enum, so these cannot drift from
            * the values the API accepts. */}
          {Object.values(InvoiceStatus).map((value) => (
            <option key={value} value={value}>
              {INVOICE_STATUS_LABELS[value]}
            </option>
          ))}
        </select>
        <div>
          {/* The old date box had no label at all, so there was no way
            * to tell which date it meant. It means the due date, which
            * is the column on this screen and the one that matters for
            * chasing an unpaid invoice. */}
          <label className="block text-xs font-medium text-on-surface-variant mb-1" htmlFor="due-before">
            Due on or before
          </label>
          <input
            id="due-before"
            className={`w-full ${FILTER_CLASS}`}
            type="date"
            value={initial.dueBefore ?? ""}
            onChange={(event) => push({ ...initial, dueBefore: event.target.value || undefined })}
          />
        </div>
      </div>
    </Card>
  );
}
