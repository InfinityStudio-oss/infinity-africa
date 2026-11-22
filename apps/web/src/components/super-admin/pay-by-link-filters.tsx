"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Card } from "@/components/portal/card";

/**
 * The Super Admin Pay by Link filters.
 *
 * Like the invoice ones, these two controls existed with no handler
 * attached: a search box and a status dropdown that moved nothing.
 *
 * Status is active/disabled rather than a lifecycle, so it maps to the
 * endpoint's is_active boolean. "" means no filter, which is NOT the
 * same as is_active=false - sending `false` for "All" would hide every
 * working page on the platform.
 */

const FILTER_CLASS =
  "px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary";

export interface PayByLinkFilterValues {
  search?: string;
  /** "active" | "disabled", or undefined for all. */
  state?: string;
}

export function PayByLinkFilters({ initial }: { initial: PayByLinkFilterValues }) {
  const router = useRouter();

  // A draft, applied on Enter or blur - a slug typed character by
  // character would be one server round trip per keystroke.
  const [draft, setDraft] = useState(initial.search ?? "");

  useEffect(() => {
    setDraft(initial.search ?? "");
  }, [initial.search]);

  const anyFilter = Boolean(initial.search || initial.state);

  function push(next: PayByLinkFilterValues) {
    const params = new URLSearchParams();
    if (next.search) params.set("search", next.search);
    if (next.state) params.set("state", next.state);
    const query = params.toString();
    router.push(query ? `/super-admin/pay-by-link?${query}` : "/super-admin/pay-by-link");
  }

  function applySearch() {
    const trimmed = draft.trim();
    if (trimmed === (initial.search ?? "")) return;
    push({ ...initial, search: trimmed || undefined });
  }

  return (
    <Card>
      {anyFilter && (
        <div className="flex justify-end mb-3">
          <button
            type="button"
            onClick={() => router.push("/super-admin/pay-by-link")}
            className="text-sm font-medium text-primary hover:underline"
          >
            Clear filters
          </button>
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <input
          className={`sm:col-span-2 ${FILTER_CLASS}`}
          type="search"
          placeholder="Slug, display name, or business"
          aria-label="Search Pay by Link pages by slug, display name, or business"
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
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
          aria-label="Page status"
          value={initial.state ?? ""}
          onChange={(event) => push({ ...initial, state: event.target.value || undefined })}
        >
          <option value="">All Statuses</option>
          <option value="active">Active</option>
          <option value="disabled">Disabled</option>
        </select>
      </div>
    </Card>
  );
}
