"use client";

/**
 * Client-safe counterpart to lib/admin/live-api.ts's read-only,
 * server-only collections access — that file is marked "server-only"
 * (Server Component/Server Action use only, cookie-based
 * getAccessToken()), so it cannot be imported from the "use client"
 * CollectionsTable (components/super-admin/collections-table.tsx), which
 * needs a real interactive click-and-see-the-result "Refresh status"
 * button rather than a full-page Server Action round trip. Mirrors
 * lib/portal/api.ts's client-side auth pattern instead
 * (getAccessTokenClient()), scoped to this one write call.
 */
import { getAccessTokenClient } from "@/lib/supabase/client-session";

import type { AdminCollectionRow } from "./types";

interface ApiEnvelope<T> {
  success: boolean;
  data?: T;
  error?: { code: string; message: string };
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL;

export async function refreshAdminCollectionStatusClient(collectionId: string): Promise<AdminCollectionRow> {
  const token = await getAccessTokenClient();

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/v1/admin/collections/${collectionId}/refresh-status`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch {
    throw new Error("Couldn't reach InfinityPay. Check your connection and try again.");
  }

  const body: ApiEnvelope<AdminCollectionRow> = await res.json();
  if (!res.ok || !body.success || body.data === undefined) {
    throw new Error(body.error?.message ?? "Request failed");
  }
  return body.data;
}
