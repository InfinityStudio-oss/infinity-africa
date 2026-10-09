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

import * as Crypto from "expo-crypto";

import { getAccessToken, signOut } from "../auth/session";

const API_BASE = process.env.EXPO_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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

/** Ask for a password-reset email.
 *
 * Deliberately the backend's own endpoint rather than
 * supabase.auth.resetPasswordForEmail: the backend generates the recovery
 * link, points it at the web portal's reset form, and sends InfinityPay's
 * branded email through Resend. Calling Supabase straight from here would
 * send Supabase's default template to the project's Site URL — the
 * marketing homepage — where a merchant would arrive holding a recovery
 * token and nothing to type a new password into.
 *
 * Unauthenticated, and never throws. The endpoint returns one identical
 * response whether or not the address has an account, so that nobody can
 * use it to discover who banks with InfinityPay. Surfacing a network
 * error here would reintroduce exactly that signal, so the caller shows
 * the same message either way.
 */
export async function requestPasswordReset(email: string): Promise<void> {
  try {
    await fetch(`${API_BASE}/v1/auth/forgot-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // redirect_path is a closed set of two values server-side, so this
      // cannot be pointed at a host someone else controls.
      body: JSON.stringify({ email: email.trim(), redirect_path: "/dashboard/reset-password" }),
    });
  } catch {
    // Swallowed on purpose — see above.
  }
}

/** A fresh key per submission attempt, so a retry the merchant did not
 * intend cannot become a second withdrawal request.
 *
 * expo-crypto rather than Math.random: this guards a money operation, and
 * Hermes ships no global crypto.randomUUID to fall back on. */
function idempotencyKey(): string {
  return Crypto.randomUUID();
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
  balance_before: string | null;
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

/** The four reports a merchant can generate, mirroring ReportType in
 * apps/api/app/schemas/enums.py. Titles come from the server in the
 * response; these labels are only for the picker. */
export const REPORT_TYPES = [
  { type: "TRANSACTIONS_SUMMARY", label: "Transactions summary" },
  { type: "WITHDRAWALS_SUMMARY", label: "Withdrawals summary" },
  { type: "FEES_SUMMARY", label: "Fees summary" },
  { type: "CUSTOMER_STATEMENT", label: "Customer statement" },
] as const;

export type ReportType = (typeof REPORT_TYPES)[number]["type"];

export interface GeneratedReport {
  report_type: string;
  title: string;
  start_date: string;
  end_date: string;
  filename: string;
  row_count: number;
  totals: Record<string, string>;
  /** Echoed back by the server so the merchant sees exactly where it went
   * rather than trusting that "sent" meant the right addresses. */
  emailed_to: string[];
}

export interface Membership {
  id: string;
  full_name: string | null;
  email: string | null;
  /** MERCHANT_ADMIN | MERCHANT_STAFF | DEVELOPER. Only MERCHANT_ADMIN may
   * raise a withdrawal, matching the backend gate. */
  role: string;
  status: string;
}

/** What POST /withdrawals returns: no withdrawal yet, only a challenge.
 * Carries no code and no hash, and the email only masked, so it is safe
 * to render. */
export interface WithdrawalOtpChallenge {
  otp_required: boolean;
  challenge_id: string;
  masked_email: string;
  expires_at: string;
  resend_cooldown_seconds: number;
  max_attempts: number;
}

/** Payout methods and their destinations, mirroring
 * DISBURSEMENT_METHOD_LABELS and DESTINATION_CODES_BY_METHOD in
 * packages/shared, which in turn mirror DisbursementMethod and
 * DestinationCode in apps/api/app/schemas/enums.py.
 *
 * Picking a destination is all the app asks for: the bank name and the
 * mobile-money network are both implied by it and are derived
 * server-side, so neither is sent.
 *
 * Kept in step by hand. The server validates every code it is given, so
 * a drift here produces a rejected request, never a wrong payout.
 */
export const DISBURSEMENT_METHODS = [
  { method: "SELCOM_PESA", label: "Selcom Pesa", recommended: true },
  { method: "MOBILE_MONEY", label: "Mobile Money", recommended: false },
  { method: "BANK_ACCOUNT", label: "Bank Account", recommended: false },
] as const;

export type DisbursementMethod = (typeof DISBURSEMENT_METHODS)[number]["method"];

export const DESTINATIONS_BY_METHOD: Record<DisbursementMethod, { code: string; label: string }[]> = {
  SELCOM_PESA: [{ code: "SELCOM", label: "Selcom Pesa" }],
  MOBILE_MONEY: [
    { code: "MPESA", label: "M-Pesa" },
    { code: "AIRTELMONEY", label: "Airtel Money" },
    { code: "HALOPESA", label: "HaloPesa" },
    { code: "MIXXBYYAS", label: "Mixx by Yas (Tigo Pesa)" },
    { code: "TTCLPESA", label: "TTCL Pesa" },
  ],
  BANK_ACCOUNT: [
    { code: "CRDB", label: "CRDB Bank" },
    { code: "NMB", label: "NMB Bank" },
    { code: "NBC", label: "NBC Bank" },
    { code: "ABSA", label: "Absa Bank" },
    { code: "BOA", label: "Bank of Africa" },
    { code: "DTB", label: "Diamond Trust Bank" },
    { code: "EQUITY", label: "Equity Bank" },
    { code: "EXIM", label: "Exim Bank" },
    { code: "KCB", label: "KCB Bank" },
    { code: "STANBIC", label: "Stanbic Bank" },
    { code: "SCB", label: "Standard Chartered Bank" },
    { code: "TCB", label: "Tanzania Commercial Bank" },
  ],
};

export function destinationLabel(code: string | null | undefined): string {
  if (!code) return "—";
  for (const list of Object.values(DESTINATIONS_BY_METHOD)) {
    const hit = list.find((option) => option.code === code);
    if (hit) return hit.label;
  }
  return code;
}

export function methodLabel(method: string | null | undefined): string {
  return DISBURSEMENT_METHODS.find((m) => m.method === method)?.label ?? method ?? "—";
}

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

  apiKeys: () => request<ApiKey[]>("/v1/merchant/api-keys"),

  webhookConfig: () => request<WebhookConfig>("/v1/merchant/webhook-config"),

  webhookEvents: (opts: { page?: number; pageSize?: number } = {}) =>
    request<WebhookEvent[]>(
      `/v1/merchant/webhook-events${query({ page: opts.page ?? 1, page_size: opts.pageSize ?? 25 })}`,
    ),

  ipAllowlist: () => request<IpAllowlistEntry[]>("/v1/merchant/ip-allowlist"),

  notificationSettings: () =>
    request<NotificationSettings>("/v1/merchant/notification-settings"),

  /** The signed-in user's own membership, including their role. Read so
   * the withdrawal form can say up front that only an account admin may
   * raise one, instead of letting a staff user fill it in and meet a 403.
   * The server still enforces it; this only avoids wasted typing. */
  membership: () => request<Membership>("/v1/merchant/users/me"),

  /** Validates an intended withdrawal server-side and reports what it
   * would reserve from the wallet.
   *
   * Merchant withdrawals are not charged, so this is not used to show a
   * fee: it is the server's own check that the amount and destination are
   * acceptable, and total_reserved_amount is what the balance must cover.
   * The portal shows "You receive the full amount" from the same call,
   * and a "TZS 0.00 fee" line is deliberately absent in both.
   */
  withdrawalQuote: (input: {
    amount: string;
    method: string;
    destination_code: string;
    destination_identifier: string;
  }) =>
    request<FeeBreakdown>("/v1/merchant/withdrawals/quote", {
      method: "POST",
      body: JSON.stringify({ ...input, recipient_name: null }),
    }),

  /** Who owns a withdrawal destination, for the review step.
   *
   * Never throws and never blocks: a withdrawal must not fail because a
   * courtesy lookup did. Null means the name could not be established —
   * an unsupported channel, an account that does not exist, or a provider
   * that did not answer — and the review shows "Name not available",
   * which is the honest thing to show in all three cases. */
  resolveWithdrawalRecipient: async (input: {
    method: string;
    destination_code: string;
    destination_identifier: string;
  }): Promise<string | null> => {
    try {
      const result = await request<{ recipient_name: string | null }>(
        "/v1/merchant/withdrawals/resolve-recipient",
        { method: "POST", body: JSON.stringify(input) },
      );
      return result.recipient_name ?? null;
    } catch {
      return null;
    }
  },

  /** Step 1 of raising a withdrawal. **Creates nothing.**
   *
   * The backend validates the request, emails a 6-digit code to the
   * merchant's own registered address, and returns a challenge. Nothing is
   * written to disbursements and no funds are reserved until
   * verifyWithdrawal() succeeds, so an abandoned challenge is inert.
   *
   * The Idempotency-Key makes a retried submission — a flaky mobile
   * connection is the normal case here — reuse the same challenge instead
   * of emailing a second code for the same request. */
  createWithdrawal: (input: {
    method: DisbursementMethod;
    amount: string;
    destination_code: string;
    destination_identifier: string;
    description?: string | null;
  }) => {
    const isBank = input.method === "BANK_ACCOUNT";
    return request<WithdrawalOtpChallenge>("/v1/merchant/withdrawals", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey() },
      body: JSON.stringify({
        method: input.method,
        amount: input.amount,
        currency: "TZS",
        destination_code: input.destination_code,
        // One identifier field or the other, never both — the backend's
        // own validator requires the bank field for BANK_ACCOUNT and the
        // phone field for everything else.
        destination_phone: isBank ? null : input.destination_identifier,
        bank_account_number: isBank ? input.destination_identifier : null,
        // No destination_name: nothing here resolves a real one, and
        // sending a typed value would be inventing it. The backend derives
        // its own display label.
        description: input.description ?? null,
      }),
    });
  },

  /** Step 2. Verifies the emailed code and only then creates the
   * withdrawal, as PENDING_ADMIN_APPROVAL.
   *
   * The withdrawal is built from the payload stored on the challenge, not
   * from anything re-sent now, so the amount and destination created are
   * exactly the ones that were validated and emailed. No provider is
   * called here — that still happens only from a Super Admin's approval. */
  verifyWithdrawal: (challengeId: string, code: string) =>
    request<Withdrawal>(`/v1/merchant/withdrawals/${challengeId}/verify`, {
      method: "POST",
      body: JSON.stringify({ code }),
    }),

  /** A fresh code on the same challenge. The stored payload is untouched,
   * so a resend cannot change the amount or destination the code is bound
   * to. */
  resendWithdrawalOtp: (challengeId: string) =>
    request<WithdrawalOtpChallenge>(`/v1/merchant/withdrawals/${challengeId}/resend`, {
      method: "POST",
      body: JSON.stringify({}),
    }),

  /** Builds a report server-side and emails it, with the file attached,
   * to the merchant's account email. That address is always included by
   * the backend and cannot be removed, so a report about an account's
   * money always reaches the person who owns it. The attachment is a PDF
   * statement — for raw rows, the Transactions and Wallet screens export
   * CSV on the device. */
  generateReport: (input: { report_type: ReportType; start_date: string; end_date: string }) =>
    request<GeneratedReport>("/v1/merchant/reports", {
      method: "POST",
      body: JSON.stringify({ ...input, recipients: [] }),
    }),
};

export { API_BASE };
