/** The mobile app's one way of talking to InfinityPay.
 *
 * This is a client of the same API the web portal uses — the same
 * `/v1/merchant/*` routes, the same Supabase JWT, the same ownership and
 * role checks on the server. There is no mobile-specific backend, no
 * second wallet, no second ledger. A withdrawal requested on a phone is
 * the same row a Super Admin approves on the web.
 *
 * Two rules this file exists to enforce:
 *
 * 1. **The backend is the only authority.** Nothing here computes a
 *    balance, a fee, a limit or a permission. Every number the app shows
 *    came from a response. If the app ever disagrees with the portal, it
 *    is a display bug, never a difference of opinion about money.
 *
 * 2. **Amounts stay strings.** The API sends decimals as strings
 *    deliberately; parsing them into JavaScript numbers loses precision
 *    on large shilling amounts. They are formatted for display and
 *    otherwise passed back untouched.
 *
 * Super Admin routes (`/v1/admin/*`) are deliberately absent. Platform
 * operations stay on the web portal, and the API would refuse them for a
 * merchant session anyway.
 */

import { getAccessToken, signOut } from "../auth/session";

const API_BASE = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Raised when the merchant is signed in but not allowed to do this yet
 * — pending approval, suspended, or restricted by a Super Admin. The UI
 * explains it rather than pretending the feature is broken. */
export class MerchantNotApprovedError extends ApiError {}

interface ApiEnvelope<T> {
  success: boolean;
  data: T;
  error?: { code: string; message: string };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getAccessToken();

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      // Only ever set from the keychain, and never logged — a bearer
      // token is as good as the password that produced it.
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });

  if (response.status === 401) {
    // The token is gone or expired. Clear it so the app returns to the
    // login screen rather than retrying with a credential that will
    // never work again.
    await signOut();
    throw new ApiError("Your session has expired. Please sign in again.", 401, "unauthorized");
  }

  let body: ApiEnvelope<T> | null = null;
  try {
    body = (await response.json()) as ApiEnvelope<T>;
  } catch {
    // A non-JSON body (a gateway error page, say) is still a failure —
    // it just cannot explain itself.
  }

  if (!response.ok || !body?.success) {
    const code = body?.error?.code ?? null;
    const message =
      body?.error?.message ?? "Couldn't reach InfinityPay. Check your connection and try again.";
    if (response.status === 403 && code === "merchant_not_approved") {
      throw new MerchantNotApprovedError(message, response.status, code);
    }
    throw new ApiError(message, response.status, code);
  }

  return body.data;
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

// --- Types -------------------------------------------------------------
// Each one is a subset of the API's own response model, with the field
// names taken from it verbatim (apps/api/app/schemas/*.py). Amounts are
// strings for the reason in this file's header.

export interface Merchant {
  id: string;
  business_name: string;
  merchant_code: string | null;
  /** "pending" | "active" | "suspended" | "rejected" today, but typed as
   * a string: the API returns a plain status column, and a union here
   * would turn a new status into a type error instead of a label. */
  status: string;
  kyc_status: string;
  contact_email: string;
  contact_phone: string | null;
  api_access_suspended: boolean;
}

export interface Overview {
  merchant: Merchant;
  available_balance: string;
  collections_today: string;
  withdrawals_today: string;
  total_collections: string;
  pending_transactions: number;
  successful_withdrawals: number;
  active_payment_links: number;
  unpaid_invoices: number;
  total_fees_charged: string;
}

export interface Transaction {
  id: string;
  reference: string;
  type: string;
  method: string;
  status: string;
  gross_amount: string;
  fee_amount: string;
  net_amount: string;
  currency: string;
  balance_after: string | null;
  direction: string | null;
  customer_phone: string | null;
  created_at: string;
}

export interface LedgerEntry {
  id: string;
  /** The posting date. Named `date` by the API, not `created_at`. */
  date: string;
  description: string | null;
  direction: "credit" | "debit";
  amount: string;
  balance_before: string;
  balance_after: string;
  type: string | null;
  reference: string | null;
  method: string | null;
  fee_amount: string | null;
  net_amount: string | null;
  status: string | null;
  customer_phone: string | null;
}

export interface Withdrawal {
  id: string;
  method: string;
  amount: string;
  currency: string;
  destination_name: string;
  destination_identifier: string;
  destination_code: string | null;
  bank_name: string | null;
  status: string;
  requires_approval: boolean;
  created_at: string;
}

/** The server's fee calculation. Every field is quoted by
 * /v1/merchant/withdrawals/quote; none is computed here. */
export interface FeeBreakdown {
  withdrawal_amount: string;
  processor_charge: string;
  infinity_fee: string;
  percentage_fee: string;
  flat_fee: string;
  total_charges: string;
  total_reserved_amount: string;
  recipient_net_amount: string;
  channel: string;
  destination_code: string;
}

export interface ApiKey {
  id: string;
  name: string;
  environment: string;
  public_key: string | null;
  key_prefix: string;
  key_last4: string | null;
  status: string;
  ip_whitelist_enabled: boolean;
  last_used_at: string | null;
  created_at: string;
}

export interface WebhookConfig {
  webhook_url: string | null;
  subscribed_events: string[] | null;
  /** Whether a signing secret exists. The secret itself is returned once,
   * at the moment it is generated in the portal, and never again. */
  has_secret: boolean;
  last_delivery: { event_name: string; status: string; created_at: string } | null;
}

export interface WebhookEvent {
  id: string;
  event_name: string;
  target_url: string;
  status: string;
  attempts: number;
  last_attempted_at: string | null;
  response_status_code: number | null;
  created_at: string;
}

export interface IpAllowlistEntry {
  id: string;
  /** A single address or a CIDR range — the API's own field name. */
  ip_address_or_cidr: string;
  label: string;
  environment: string;
  status: string;
  notes: string | null;
  created_at: string;
}

export interface NotificationSettings {
  primary_notification_email: string | null;
  secondary_notification_email: string | null;
  collection_notifications_enabled: boolean;
}

/** Withdrawal destinations, mirroring DESTINATION_CODE_LABELS and
 * DisbursementMethod in apps/api/app/schemas/enums.py. The method is
 * implied by the destination, exactly as it is server-side — the app
 * never asks a merchant for both.
 *
 * Kept in step by hand. The server validates the code regardless, so a
 * drift here produces a rejected request, not a wrong payout. */
export const DESTINATION_OPTIONS = [
  { code: "SELCOM", label: "Selcom Pesa", method: "SELCOM_PESA" },
  { code: "MPESA", label: "M-Pesa", method: "MOBILE_MONEY" },
  { code: "AIRTELMONEY", label: "Airtel Money", method: "MOBILE_MONEY" },
  { code: "HALOPESA", label: "HaloPesa", method: "MOBILE_MONEY" },
  { code: "MIXXBYYAS", label: "Mixx by Yas (Tigo Pesa)", method: "MOBILE_MONEY" },
  { code: "TTCLPESA", label: "TTCL Pesa", method: "MOBILE_MONEY" },
] as const;

// --- Merchant APIs -----------------------------------------------------
// One function per screen's needs. Each maps to a route the web portal
// already uses, so the two interfaces cannot drift apart.

export const api = {
  /** Home. */
  overview: () => request<Overview>("/v1/merchant/overview"),

  me: () => request<Merchant>("/v1/merchant/me"),

  /** Transactions, newest first. `search` matches the reference and is
   * applied server-side; there is deliberately no status filter, because
   * the endpoint is paginated and filtering the page already on the
   * device would hide matches sitting on page two. */
  transactions: (opts: { search?: string; page?: number; pageSize?: number } = {}) =>
    request<Transaction[]>(
      `/v1/merchant/transactions${query({
        search: opts.search,
        page: opts.page ?? 1,
        page_size: opts.pageSize ?? 25,
      })}`,
    ),

  /** Wallet ledger. balance_before/balance_after come from the server, so
   * a running total is never recomputed on the device. */
  walletLedger: (opts: { page?: number; pageSize?: number } = {}) =>
    request<LedgerEntry[]>(
      `/v1/merchant/wallet/ledger${query({ page: opts.page ?? 1, page_size: opts.pageSize ?? 25 })}`,
    ),

  withdrawals: (opts: { page?: number; pageSize?: number } = {}) =>
    request<Withdrawal[]>(
      `/v1/merchant/withdrawals${query({ page: opts.page ?? 1, page_size: opts.pageSize ?? 25 })}`,
    ),

  /** What a withdrawal would cost. Read-only: creates nothing, reserves
   * nothing, and never calls the provider. */
  withdrawalQuote: (input: {
    amount: string;
    method: string;
    destination_code: string;
    destination_identifier: string;
  }) =>
    request<FeeBreakdown>("/v1/merchant/withdrawals/quote", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  apiKeys: () => request<ApiKey[]>("/v1/merchant/api-keys"),

  webhookConfig: () => request<WebhookConfig>("/v1/merchant/webhook-config"),

  webhookEvents: (opts: { page?: number; pageSize?: number } = {}) =>
    request<WebhookEvent[]>(
      `/v1/merchant/webhook-events${query({ page: opts.page ?? 1, page_size: opts.pageSize ?? 25 })}`,
    ),

  ipAllowlist: () => request<IpAllowlistEntry[]>("/v1/merchant/ip-allowlist"),

  notificationSettings: () =>
    request<NotificationSettings>("/v1/merchant/notification-settings"),
};

export { API_BASE };
