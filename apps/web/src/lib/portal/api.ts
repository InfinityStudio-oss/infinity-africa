/**
 * Data-access boundary for the merchant portal.
 *
 * Payment links, invoices, collections, withdrawals (disbursements),
 * transactions, API keys, webhooks, and the wallet ledger call the real
 * apps/api /v1/merchant/* endpoints — see docs/api.md. Everything else
 * (customers, team, support) still resolves against the in-memory
 * mock-data.ts arrays, since no corresponding self-service endpoint exists
 * yet; each section below is labeled LIVE or MOCK accordingly.
 *
 * No component should import mock-data.ts directly — only this file does.
 */

import { getAccessTokenClient } from "@/lib/supabase/client-session";

import { mockSupportTickets, MOCK_MERCHANT_ID } from "./mock-data";
import type {
  AllowedIpDraft,
  ApiEnvelope,
  ApiKey,
  ApiRequestLog,
  AppNotification,
  Collection,
  Customer,
  Disbursement,
  Dispute,
  DisputeWithMessages,
  DocumentRequest,
  FeeBreakdown,
  FraudAlert,
  HostedCheckoutCollection,
  Invoice,
  InvoiceItem,
  IpAllowlistEntry,
  MerchantProfile,
  MerchantUser,
  NotificationSettings,
  PayByLink,
  PaymentLink,
  Refund,
  SupportTicket,
  Transaction,
  WalletLedgerEntry,
  WebhookConfig,
  WebhookConfigWithSecret,
  WebhookEvent,
  WebhookTestResult,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL;

/**
 * Attaches the signed-in merchant's Supabase access token as
 * `Authorization: Bearer <token>`. Every page that calls into this file is
 * a Client Component (including transactions/page.tsx, converted from a
 * Server Component specifically so this file could stay single and
 * client-only) — so the client-safe getAccessTokenClient() is the only
 * token getter this module ever needs. A "server-only"-marked getter
 * must never be imported here, even dynamically: Turbopack's production
 * build still traces a dynamic import() into the module graph for the
 * server-only check, so it fails the build the same as a static import
 * would — this file, and everything it imports, must stay client-safe.
 */
async function getAuthHeader(): Promise<Record<string, string>> {
  const token = await getAccessTokenClient();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function idempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `idem-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Reads never throw on a network failure (backend unreachable, DNS,
 * timeout) — same "return null, let the caller decide what to show"
 * convention as lib/payment-links.ts's fetchPublicPaymentLink. */
async function apiGet<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE}${path}`, { headers: await getAuthHeader(), cache: "no-store" });
    if (!res.ok) return null;
    const body: ApiEnvelope<T> = await res.json();
    return body.success ? (body.data ?? null) : null;
  } catch {
    return null;
  }
}

async function apiWrite<T>(
  path: string,
  method: "POST" | "PATCH" | "DELETE",
  input: unknown,
  { idempotent = false }: { idempotent?: boolean } = {},
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(idempotent ? { "Idempotency-Key": idempotencyKey() } : {}),
        ...(await getAuthHeader()),
      },
      body: JSON.stringify(input),
    });
  } catch {
    // Network failure (backend unreachable, DNS, timeout) — not a response
    // the backend sent, so there's no error.code to preserve.
    throw new Error("Couldn't reach InfinityPay. Check your connection and try again.");
  }

  const body: ApiEnvelope<T> = await res.json();
  if (!res.ok || !body.success || body.data === undefined) {
    const error = new Error(body.error?.message ?? "Request failed") as Error & { code?: string };
    error.code = body.error?.code;
    throw error;
  }
  return body.data;
}

// --- Payment Links (LIVE) ---------------------------------------------------

export async function listPaymentLinks(): Promise<PaymentLink[]> {
  return (await apiGet<PaymentLink[]>("/v1/merchant/payment-links")) ?? [];
}

export async function getPaymentLink(id: string): Promise<PaymentLink | null> {
  return apiGet<PaymentLink>(`/v1/merchant/payment-links/${id}`);
}

export interface CreatePaymentLinkInput {
  amount: string;
  currency: string;
  customer_name: string | null;
  customer_phone: string | null;
  customer_email: string | null;
  description: string | null;
  // No longer collected from the merchant (2026-08-23) — every payment
  // link now always offers the single "Pay securely" hosted-checkout
  // flow. Backend defaults this when omitted; kept optional only for
  // backward compatibility.
  allowed_payment_methods?: PaymentLink["allowed_payment_methods"];
  expires_at: string | null;
  merchant_reference: string | null;
  success_redirect_url: string | null;
  failure_redirect_url: string | null;
  // "request_collection" for the Request Collection form; omitted (backend
  // defaults to "payment_link") for the Payment Links page — a label only,
  // for Super Admin's source filter, never security-relevant.
  origin?: "payment_link" | "request_collection";
}

export async function createPaymentLink(input: CreatePaymentLinkInput): Promise<PaymentLink> {
  return apiWrite<PaymentLink>("/v1/merchant/payment-links", "POST", input, { idempotent: true });
}

export type UpdatePaymentLinkInput = Partial<CreatePaymentLinkInput>;

export async function updatePaymentLink(id: string, input: UpdatePaymentLinkInput): Promise<PaymentLink> {
  return apiWrite<PaymentLink>(`/v1/merchant/payment-links/${id}`, "PATCH", input);
}

export async function cancelPaymentLink(id: string): Promise<PaymentLink> {
  return apiWrite<PaymentLink>(`/v1/merchant/payment-links/${id}/cancel`, "PATCH", {});
}

// --- Pay by Link (LIVE) -------------------------------------------------------
// The merchant's one permanent public checkout page — see
// docs/PAY_BY_LINK.md. Additive to Payment Links above, never a
// replacement for it.

export async function getMyPayByLink(): Promise<PayByLink | null> {
  return apiGet<PayByLink>("/v1/merchant/pay-by-link/me");
}

export interface CreatePayByLinkInput {
  display_name?: string | null;
  slug?: string | null;
  description?: string | null;
}

export async function createPayByLink(input: CreatePayByLinkInput): Promise<PayByLink> {
  return apiWrite<PayByLink>("/v1/merchant/pay-by-link", "POST", input);
}

export interface UpdatePayByLinkInput {
  display_name?: string;
  slug?: string;
  description?: string;
  is_active?: boolean;
}

export async function updatePayByLink(input: UpdatePayByLinkInput): Promise<PayByLink> {
  return apiWrite<PayByLink>("/v1/merchant/pay-by-link/me", "PATCH", input);
}

export async function checkPayByLinkSlugAvailability(
  slug: string,
): Promise<{ available: boolean; reason?: string }> {
  const result = await apiGet<{ available: boolean; reason?: string }>(
    `/v1/merchant/pay-by-link/slug-availability?slug=${encodeURIComponent(slug)}`,
  );
  return result ?? { available: false, reason: "Couldn't check availability. Try again." };
}

// --- Invoices (LIVE) ---------------------------------------------------------

export async function listInvoices(): Promise<Invoice[]> {
  return (await apiGet<Invoice[]>("/v1/merchant/invoices")) ?? [];
}

export interface CreateInvoiceInput {
  customer_name: string;
  customer_phone: string | null;
  customer_email: string | null;
  due_date: string;
  notes: string | null;
  items: Array<Pick<InvoiceItem, "description" | "quantity" | "unit_price">>;
  send_now: boolean;
}

export async function createInvoice(input: CreateInvoiceInput): Promise<Invoice> {
  const invoice = await apiWrite<Invoice>("/v1/merchant/invoices", "POST", {
    customer_name: input.customer_name,
    customer_phone: input.customer_phone,
    customer_email: input.customer_email,
    due_date: input.due_date,
    notes: input.notes,
    items: input.items.map((item) => ({ description: item.description, quantity: item.quantity, unit_price: item.unit_price })),
  });

  if (input.send_now) {
    return apiWrite<Invoice>(`/v1/merchant/invoices/${invoice.id}/send`, "POST", {});
  }
  return invoice;
}

/** Generates (or returns the existing) Pay Now payment link for a sent
 * invoice — backs the invoices table's "Copy Pay Now link" action. */
export async function generateInvoicePaymentLink(invoiceId: string): Promise<PaymentLink> {
  return apiWrite<PaymentLink>(`/v1/merchant/invoices/${invoiceId}/payment-link`, "POST", {});
}

// --- Collections (LIVE) ----------------------------------------------------

const COLLECTION_METHOD_PATHS: Record<Collection["method"], string> = {
  USSD_PUSH: "ussd-push",
  STK_PUSH: "stk-push",
  SELCOM_PESA_PUSH: "selcom-pesa-push",
  DYNAMIC_QR: "dynamic-qr",
  // Never actually used by createCollection() below — HOSTED_CHECKOUT
  // collections go through createHostedCheckoutCollection() instead.
  // Listed only so this Record stays exhaustive over CollectionMethod.
  HOSTED_CHECKOUT: "hosted-checkout",
};

export async function listCollections(): Promise<Collection[]> {
  return (await apiGet<Collection[]>("/v1/merchant/collections")) ?? [];
}

/** Manual Selcom Checkout order-status reconciliation for a collection
 * stuck "processing" — same completion logic a webhook would apply, safe
 * to call repeatedly (backend enforces it never double-credits). */
export async function refreshCollectionStatus(collectionId: string): Promise<Collection> {
  return apiWrite<Collection>(`/v1/merchant/collections/${collectionId}/refresh-status`, "POST", undefined);
}

export interface CreateCollectionInput {
  customer_name: string;
  customer_phone: string;
  customer_email?: string | null;
  amount: string;
  method: Collection["method"];
  description: string | null;
  callback_url?: string | null;
  invoice_id?: string | null;
}

export async function createCollection(input: CreateCollectionInput): Promise<Collection> {
  const path = `/v1/merchant/collections/${COLLECTION_METHOD_PATHS[input.method]}`;
  return apiWrite<Collection>(
    path,
    "POST",
    {
      amount: input.amount,
      currency: "TZS",
      customer_phone: input.customer_phone,
      customer_name: input.customer_name,
      customer_email: input.customer_email ?? null,
      description: input.description,
      callback_url: input.callback_url ?? null,
      invoice_id: input.invoice_id ?? null,
    },
    { idempotent: true },
  );
}

export interface CreateHostedCheckoutCollectionInput {
  customer_name?: string | null;
  customer_phone?: string | null;
  customer_email?: string | null;
  amount: string;
  description?: string | null;
  merchant_reference?: string | null;
}

/** "Request Collection" (2026-08-23) — no channel to pick; Selcom's own
 * hosted checkout page shows whichever methods are enabled on the
 * account. Returns the collection plus its decoded payment_gateway_url. */
export async function createHostedCheckoutCollection(
  input: CreateHostedCheckoutCollectionInput,
): Promise<HostedCheckoutCollection> {
  return apiWrite<HostedCheckoutCollection>(
    "/v1/merchant/collections/hosted-checkout",
    "POST",
    {
      amount: input.amount,
      currency: "TZS",
      customer_name: input.customer_name ?? null,
      customer_phone: input.customer_phone ?? null,
      customer_email: input.customer_email ?? null,
      description: input.description ?? null,
      merchant_reference: input.merchant_reference ?? null,
    },
    { idempotent: true },
  );
}

export interface CreateCollectionRequestInput {
  customer_name?: string | null;
  customer_phone?: string | null;
  customer_email?: string | null;
  amount: string;
  description?: string | null;
  merchant_reference?: string | null;
}

/** "Request Collection" (2026-08-24) — the merchant picks no channel;
 * this creates a payment link under the hood (no expiry, no redirect
 * URLs) and hands back its public_url for the merchant to share. The
 * customer opens that page and chooses Mobile Money Push / Selcom Pesa /
 * Scan QR themselves — see PaymentForm. Same underlying resource as
 * createPaymentLink() above, just a lighter-weight call shape for this
 * quicker form. */
export async function createCollectionRequest(input: CreateCollectionRequestInput): Promise<PaymentLink> {
  return createPaymentLink({
    amount: input.amount,
    currency: "TZS",
    customer_name: input.customer_name ?? null,
    customer_phone: input.customer_phone ?? null,
    customer_email: input.customer_email ?? null,
    description: input.description ?? null,
    expires_at: null,
    merchant_reference: input.merchant_reference ?? null,
    success_redirect_url: null,
    failure_redirect_url: null,
    origin: "request_collection",
  });
}

// --- Withdrawals (LIVE — /v1/merchant/withdrawals; frontend keeps calling
// this "disbursement" internally, matching the existing Disbursement type
// and the established "Withdrawals" (UI) / "disbursement" (code) naming
// convention already used elsewhere in the portal). ------------------------

export async function listDisbursements(): Promise<Disbursement[]> {
  return (await apiGet<Disbursement[]>("/v1/merchant/withdrawals")) ?? [];
}

export async function getAvailableBalance(): Promise<string> {
  const overview = await apiGet<{ available_balance: string }>("/v1/merchant/overview");
  return overview?.available_balance ?? "0";
}

export interface CreateDisbursementInput {
  method: Disbursement["method"];
  destination_name: string;
  destination_identifier: string;
  destination_code: string;
  bank_name: string | null;
  amount: string;
  network?: string | null;
  description?: string | null;
}

export class InsufficientBalanceError extends Error {}

export async function createDisbursement(input: CreateDisbursementInput): Promise<Disbursement> {
  const isBank = input.method === "BANK_ACCOUNT";
  const isMobileMoney = input.method === "MOBILE_MONEY";
  const payload = {
    method: input.method,
    amount: input.amount,
    currency: "TZS",
    destination_name: input.destination_name,
    destination_code: input.destination_code,
    destination_phone: isBank ? null : input.destination_identifier,
    bank_name: isBank ? input.bank_name : null,
    bank_account_number: isBank ? input.destination_identifier : null,
    bank_account_name: isBank ? input.destination_name : null,
    network: isMobileMoney ? (input.network ?? null) : null,
    description: input.description ?? null,
  };

  try {
    return await apiWrite<Disbursement>("/v1/merchant/withdrawals", "POST", payload, { idempotent: true });
  } catch (err) {
    const error = err as Error & { code?: string };
    if (error.code === "insufficient_balance") {
      throw new InsufficientBalanceError(error.message);
    }
    throw err;
  }
}

export interface QuoteWithdrawalChargesInput {
  amount: string;
  method: Disbursement["method"];
  destination_code: string;
  destination_identifier: string;
  recipient_name?: string | null;
}

/** POST /v1/merchant/withdrawals/quote — read-only, no withdrawal created,
 * no funds reserved, Selcom never called. Shows the merchant the full fee
 * breakdown before they submit; the actual submission
 * (createDisbursement, above) recalculates and freezes the same breakdown
 * server-side rather than trusting this response. */
export async function calculateWithdrawalCharges(input: QuoteWithdrawalChargesInput): Promise<FeeBreakdown> {
  return apiWrite<FeeBreakdown>("/v1/merchant/withdrawals/quote", "POST", {
    amount: input.amount,
    method: input.method,
    destination_code: input.destination_code,
    destination_identifier: input.destination_identifier,
    recipient_name: input.recipient_name ?? null,
  });
}

// --- Transactions (LIVE) ----------------------------------------------------

export async function listTransactions(): Promise<Transaction[]> {
  return (await apiGet<Transaction[]>("/v1/merchant/transactions")) ?? [];
}

// --- API Keys (LIVE) ---------------------------------------------------------

export async function listApiKeys(): Promise<ApiKey[]> {
  return (await apiGet<ApiKey[]>("/v1/merchant/api-keys")) ?? [];
}

export async function createApiKey(input: {
  name: string;
  environment: ApiKey["environment"];
  scopes: string[];
  // Part 6's per-key choice: enable IP whitelisting (with the allowed IPs
  // added inline, right here), or explicitly continue without it. Exactly
  // one is true — the backend reconciles this if both/neither are sent.
  ip_whitelist_enabled?: boolean;
  continue_without_ip_whitelist?: boolean;
  // Required (min 1), enforced server-side, when ip_whitelist_enabled is
  // true — the inline "Allowed server IPs" list on the same form.
  allowed_ips?: AllowedIpDraft[];
}): Promise<{ key: ApiKey; plaintext_key: string }> {
  const created = await apiWrite<ApiKey & { plaintext_key: string }>("/v1/merchant/api-keys", "POST", input);
  const { plaintext_key, ...key } = created;
  return { key: key as ApiKey, plaintext_key };
}

export async function renameApiKey(apiKeyId: string, name: string): Promise<ApiKey> {
  return apiWrite<ApiKey>(`/v1/merchant/api-keys/${apiKeyId}`, "PATCH", { name });
}

/** Switch an existing key between "Enable"/"Continue without" IP
 * whitelisting — the backend rejects enabling if the key has no linked,
 * non-rejected allowlist entry yet (add one first via createIpAllowlistEntry
 * with this key's id). */
export async function updateApiKeyIpWhitelist(apiKeyId: string, ipWhitelistEnabled: boolean): Promise<ApiKey> {
  return apiWrite<ApiKey>(`/v1/merchant/api-keys/${apiKeyId}/ip-whitelist`, "PATCH", {
    ip_whitelist_enabled: ipWhitelistEnabled,
  });
}

export async function revokeApiKey(apiKeyId: string): Promise<ApiKey> {
  return apiWrite<ApiKey>(`/v1/merchant/api-keys/${apiKeyId}/revoke`, "PATCH", {});
}

/** Revokes the given key and creates a fresh one with the same name/
 * environment/scopes in one action — the new plaintext key is shown
 * exactly once, same rule as createApiKey. */
export async function rotateApiKey(apiKeyId: string): Promise<{ key: ApiKey; plaintext_key: string }> {
  const created = await apiWrite<ApiKey & { plaintext_key: string }>(
    `/v1/merchant/api-keys/${apiKeyId}/rotate`,
    "POST",
    {},
  );
  const { plaintext_key, ...key } = created;
  return { key: key as ApiKey, plaintext_key };
}

// --- IP Allowlist (LIVE) -------------------------------------------------------

export async function listIpAllowlist(filters?: { apiKeyId?: string }): Promise<IpAllowlistEntry[]> {
  const params = filters?.apiKeyId ? `?api_key_id=${encodeURIComponent(filters.apiKeyId)}` : "";
  return (await apiGet<IpAllowlistEntry[]>(`/v1/merchant/ip-allowlist${params}`)) ?? [];
}

export async function createIpAllowlistEntry(input: {
  environment: IpAllowlistEntry["environment"];
  label: string;
  ip_address_or_cidr: string;
  notes?: string | null;
  api_key_id?: string | null;
}): Promise<IpAllowlistEntry> {
  return apiWrite<IpAllowlistEntry>("/v1/merchant/ip-allowlist", "POST", input);
}

export async function deleteIpAllowlistEntry(entryId: string): Promise<void> {
  await apiWrite(`/v1/merchant/ip-allowlist/${entryId}`, "DELETE", {});
}

// --- API Logs (LIVE) -----------------------------------------------------------

export async function listApiLogs(): Promise<ApiRequestLog[]> {
  return (await apiGet<ApiRequestLog[]>("/v1/merchant/api-logs")) ?? [];
}

// --- Overview (LIVE) ---------------------------------------------------------

export interface MerchantOverview {
  merchant: {
    id: string;
    merchant_code: string | null;
    business_name: string;
    currency: string;
    status: string;
    kyc_status: string;
  };
  total_collections: string;
  available_balance: string;
  pending_transactions: number;
  successful_withdrawals: number;
  active_payment_links: number;
  unpaid_invoices: number;
  total_fees_charged: string;
}

/** Returns null on any non-2xx (no real merchant yet for this user, token
 * expired, network error) — the merchant overview page falls back to the
 * onboarding-status view in that case rather than erroring. */
export async function getMerchantOverview(): Promise<MerchantOverview | null> {
  return apiGet<MerchantOverview>("/v1/merchant/overview");
}

// --- Business profile (LIVE) -------------------------------------------------

export async function getMyMerchant(): Promise<MerchantProfile | null> {
  return apiGet<MerchantProfile>("/v1/merchant/me");
}

export interface UpdateMerchantProfileInput {
  business_name?: string;
  legal_name?: string;
  contact_phone?: string;
}

export async function updateMyMerchantProfile(
  merchantId: string,
  input: UpdateMerchantProfileInput,
): Promise<MerchantProfile> {
  return apiWrite<MerchantProfile>(`/v1/merchants/${merchantId}`, "PATCH", input);
}

// --- Notification settings (LIVE) ----------------------------------------------
// Where THIS merchant wants collection transaction notifications emailed —
// separate from the customer's own payment receipt, which is never
// configurable.

export async function getMyNotificationSettings(): Promise<NotificationSettings | null> {
  return apiGet<NotificationSettings>("/v1/merchant/notification-settings");
}

export interface UpdateNotificationSettingsInput {
  primary_notification_email: string | null;
  secondary_notification_email: string | null;
  collection_notifications_enabled: boolean;
}

export async function updateMyNotificationSettings(
  input: UpdateNotificationSettingsInput,
): Promise<NotificationSettings> {
  return apiWrite<NotificationSettings>("/v1/merchant/notification-settings", "PATCH", input);
}

// --- Team / Users (LIVE) ------------------------------------------------------

/** The signed-in user's own membership (name/email/role) — what the
 * portal topbar's account menu reads from. Available to every merchant
 * role, not admin-only. */
export async function getMyMembership(): Promise<MerchantUser | null> {
  return apiGet<MerchantUser>("/v1/merchant/users/me");
}

/** Admin-only — every other function in this section is too. */
export async function listMerchantUsers(): Promise<MerchantUser[]> {
  return (await apiGet<MerchantUser[]>("/v1/merchant/users")) ?? [];
}

export interface CreateMerchantUserInput {
  full_name: string;
  email: string;
  role: MerchantUser["role"];
}

export async function createMerchantUser(input: CreateMerchantUserInput): Promise<MerchantUser> {
  return apiWrite<MerchantUser>("/v1/merchant/users", "POST", input);
}

export interface UpdateMerchantUserInput {
  role?: MerchantUser["role"];
  status?: MerchantUser["status"];
}

export async function updateMerchantUser(userRowId: string, input: UpdateMerchantUserInput): Promise<MerchantUser> {
  return apiWrite<MerchantUser>(`/v1/merchant/users/${userRowId}`, "PATCH", input);
}

export async function deactivateMerchantUser(userRowId: string): Promise<MerchantUser> {
  return apiWrite<MerchantUser>(`/v1/merchant/users/${userRowId}/deactivate`, "POST", {});
}

/** Only valid while the invited teammate is still status "invited" — for
 * when the original invite email failed to send, or just got lost. */
export async function resendMerchantUserInvite(userRowId: string): Promise<MerchantUser> {
  return apiWrite<MerchantUser>(`/v1/merchant/users/${userRowId}/resend-invite`, "POST", {});
}

/** Called once by a newly-invited staff member right after they set their
 * password on /merchant/invite/accept — flips their own merchant_users row
 * from 'invited' to 'active'. Not admin-only, unlike everything else in
 * this section: the caller isn't a team member yet, they're the person
 * accepting the invite. merchant_id is resolved backend-side from the
 * caller's own JWT + their existing merchant_users row — never sent here. */
export async function acceptMyInvite(): Promise<MerchantUser> {
  return apiWrite<MerchantUser>("/v1/merchant/users/me/accept-invite", "POST", {});
}

// ============================================================================
// Everything below is still MOCK — no /v1/merchant/* endpoint exists yet for
// customers or support. (Wallet ledger is LIVE — see below; linked
// withdrawal accounts has no backend concept at all yet, not even mocked.)
// ============================================================================

const mockStore = {
  // Starts empty, not seeded with mockCustomers()'s demo rows (Grace
  // Mwakalinga, Juma Traders, ...) — those were fabricated data with no
  // backend behind them. A merchant can still add real entries via the
  // "Add Customer" form below; they just won't persist past this
  // session/reload until a real /v1/merchant/customers endpoint exists.
  customers: [] as Customer[],
  supportTickets: mockSupportTickets(),
};

let sequence = 1;
function generateId(prefix: string): string {
  sequence += 1;
  return `${prefix}-${Date.now().toString(36)}${sequence}`;
}

function nowIso(): string {
  return new Date().toISOString();
}

// --- Customers (MOCK) --------------------------------------------------------

export async function listCustomers(): Promise<Customer[]> {
  return mockStore.customers;
}

export interface CreateCustomerInput {
  name: string;
  phone: string | null;
  email: string | null;
}

export async function createCustomer(input: CreateCustomerInput): Promise<Customer> {
  const customer: Customer = {
    id: generateId("cus"),
    merchant_id: MOCK_MERCHANT_ID,
    name: input.name,
    phone: input.phone,
    email: input.email,
    total_spent: "0.00",
    last_transaction_at: null,
    status: "active",
    created_at: nowIso(),
  };
  mockStore.customers = [customer, ...mockStore.customers];
  return customer;
}

// --- Wallet ---------------------------------------------------------------

export interface WalletLedgerDateRange {
  start_date?: string;
  end_date?: string;
}

export async function listWalletLedger(filters?: WalletLedgerDateRange): Promise<WalletLedgerEntry[]> {
  const params = new URLSearchParams({ page_size: "100" });
  if (filters?.start_date) params.set("start_date", filters.start_date);
  if (filters?.end_date) params.set("end_date", filters.end_date);
  return (await apiGet<WalletLedgerEntry[]>(`/v1/merchant/wallet/ledger?${params.toString()}`)) ?? [];
}

/** Downloads the Wallet Ledger Excel export for the given date range as a
 * Blob — the caller turns it into a browser download (see
 * apps/web/src/app/portal/wallet/page.tsx). A plain <a href> can't be used
 * here: the export endpoint requires the merchant's own bearer token,
 * which only a fetch() with an Authorization header can attach. Throws
 * with a user-facing message on any failure — same convention as
 * apiWrite — so the caller can show it as an error banner. */
export async function exportWalletLedger({ start_date, end_date }: Required<WalletLedgerDateRange>): Promise<Blob> {
  const params = new URLSearchParams({ start_date, end_date, format: "xlsx" });
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/v1/merchant/wallet/ledger/export?${params.toString()}`, {
      headers: await getAuthHeader(),
    });
  } catch {
    throw new Error("Couldn't reach InfinityPay. Check your connection and try again.");
  }

  if (!res.ok) {
    let message = "Couldn't export the wallet ledger. Please try again.";
    try {
      const body: ApiEnvelope<never> = await res.json();
      message = body.error?.message ?? message;
    } catch {
      // Non-JSON error body — fall back to the generic message above.
    }
    throw new Error(message);
  }
  return res.blob();
}

// --- Support (MOCK) ------------------------------------------------------------

export async function listSupportTickets(): Promise<SupportTicket[]> {
  return mockStore.supportTickets;
}

export async function createSupportTicket(input: { subject: string; category: string }): Promise<SupportTicket> {
  const ticket: SupportTicket = {
    id: generateId("tkt"),
    subject: input.subject,
    category: input.category,
    status: "open",
    created_at: nowIso(),
  };
  mockStore.supportTickets = [ticket, ...mockStore.supportTickets];
  return ticket;
}

// --- Webhooks (LIVE) ---------------------------------------------------------

export async function getWebhookConfig(): Promise<WebhookConfig | null> {
  return apiGet<WebhookConfig>("/v1/merchant/webhook-config");
}

export interface UpdateWebhookConfigInput {
  webhook_url?: string;
  subscribed_events?: string[];
  regenerate_secret?: boolean;
}

export async function updateWebhookConfig(input: UpdateWebhookConfigInput): Promise<WebhookConfigWithSecret> {
  return apiWrite<WebhookConfigWithSecret>("/v1/merchant/webhook-config", "PATCH", input);
}

export async function sendTestWebhook(): Promise<WebhookTestResult> {
  return apiWrite<WebhookTestResult>("/v1/merchant/webhook-config/test", "POST", {});
}

export async function listWebhookEvents(): Promise<WebhookEvent[]> {
  return (await apiGet<WebhookEvent[]>("/v1/merchant/webhook-events")) ?? [];
}

// --- Risk monitoring (LIVE) --------------------------------------------------

export async function listMyRiskAlerts(): Promise<FraudAlert[]> {
  return (await apiGet<FraudAlert[]>("/v1/merchant/risk-alerts")) ?? [];
}

// --- Document requests (LIVE) ------------------------------------------------

export async function listMyDocumentRequests(): Promise<DocumentRequest[]> {
  return (await apiGet<DocumentRequest[]>("/v1/merchant/document-requests")) ?? [];
}

export async function submitDocumentRequestFile(
  requestId: string,
  documentLabel: string,
  file: File,
): Promise<DocumentRequest> {
  const formData = new FormData();
  formData.append("document_label", documentLabel);
  formData.append("file", file);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/v1/merchant/document-requests/${requestId}/submit`, {
      method: "POST",
      headers: await getAuthHeader(),
      body: formData,
    });
  } catch {
    throw new Error("Couldn't reach InfinityPay. Check your connection and try again.");
  }
  const body: ApiEnvelope<DocumentRequest> = await res.json();
  if (!res.ok || !body.success || body.data === undefined) {
    const error = new Error(body.error?.message ?? "Request failed") as Error & { code?: string };
    error.code = body.error?.code;
    throw error;
  }
  return body.data;
}

// --- Disputes (LIVE) -----------------------------------------------------------

export async function listMyDisputes(): Promise<Dispute[]> {
  return (await apiGet<Dispute[]>("/v1/merchant/disputes")) ?? [];
}

export async function getMyDispute(disputeId: string): Promise<DisputeWithMessages | null> {
  return apiGet<DisputeWithMessages>(`/v1/merchant/disputes/${disputeId}`);
}

export async function respondToDispute(disputeId: string, body: string): Promise<DisputeWithMessages> {
  return apiWrite<DisputeWithMessages>(`/v1/merchant/disputes/${disputeId}/respond`, "POST", { body });
}

export async function acceptRefund(disputeId: string, amount: string): Promise<Refund> {
  return apiWrite<Refund>(`/v1/merchant/disputes/${disputeId}/accept-refund`, "POST", { amount });
}

// --- Notifications (LIVE) ----------------------------------------------------

export async function listMyNotifications(): Promise<AppNotification[]> {
  return (await apiGet<AppNotification[]>("/v1/merchant/notifications")) ?? [];
}
