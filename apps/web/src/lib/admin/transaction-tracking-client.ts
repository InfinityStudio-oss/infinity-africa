"use client";

/**
 * Client-safe read of GET /v1/admin/transactions/{id}/tracking, for the
 * Super Admin transactions table's tracking drawer. Same reasoning as
 * refresh-collection-status-client.ts: lib/admin/live-api.ts is
 * server-only, and this is an interactive open-and-look read.
 *
 * Read-only. Nothing here resends a webhook or retries a payment.
 */
import { getAccessTokenClient } from "@/lib/supabase/client-session";
import type { PaymentTracking } from "@/lib/portal/types";

interface ApiEnvelope<T> {
  success: boolean;
  data?: T;
  error?: { code: string; message: string };
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL;

export async function getAdminTransactionTrackingClient(
  transactionId: string,
): Promise<{ data: PaymentTracking | null; error: string | null }> {
  const token = await getAccessTokenClient();
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/v1/admin/transactions/${encodeURIComponent(transactionId)}/tracking`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      cache: "no-store",
    });
  } catch {
    return { data: null, error: "Couldn't reach InfinityPay. Check your connection and try again." };
  }
  let body: ApiEnvelope<PaymentTracking> | null = null;
  try {
    body = (await res.json()) as ApiEnvelope<PaymentTracking>;
  } catch {
    body = null;
  }
  if (!res.ok || !body?.success || !body.data) {
    return { data: null, error: body?.error?.message ?? `Tracking could not be loaded (HTTP ${res.status}).` };
  }
  return { data: body.data, error: null };
}
