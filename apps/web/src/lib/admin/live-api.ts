import "server-only";

import { getAccessToken } from "@/lib/supabase/session";

import type {
  AdminApiKeyPlatformRow,
  AdminApiKeyRow,
  AdminCustomerPlatformRow,
  AdminCollectionRow,
  AdminDisputeRow,
  AdminDocumentRequestRow,
  AdminFraudAlertRow,
  AdminInquiryRow,
  AdminInvoiceRow,
  AdminIpAllowlistRow,
  AdminNotificationRow,
  AdminNotificationSettingsRow,
  AdminOverview,
  AdminPayByLinkListRow,
  AdminPayByLinkRow,
  AdminPaymentLinkRow,
  AdminRefundRow,
  AdminTransactionRow,
  AdminWebhookEventRow,
  AdminWithdrawalRow,
  AuditLogRow,
  CollectionPricingRuleRow,
  Merchant,
  MerchantAccountStatus,
  MerchantUserRow,
  PricingRuleRow,
} from "./types";

/**
 * Live data-access boundary for the 11 in-scope Super Admin dashboard
 * resources (Command Center, Merchants, Merchant Users, Payment Links,
 * Invoices, Collections, Withdrawals, Transactions, Webhooks, Audit Logs,
 * Inquiries) — calls the real apps/api /v1/admin/* endpoints. Server-only, same shape as
 * lib/onboarding/api.ts: every caller is a Server Component or Server
 * Action under app/super-admin/*, so this can safely use the cookie-based
 * getAccessToken() with no Turbopack client/server bundling conflict.
 *
 * The remaining ~15 out-of-scope resources (customers, pricing, api-keys,
 * reconciliation, settlement, compliance-kyc, provider-status,
 * support-tickets, admin-team) stay in lib/admin/api.ts, still mock — that
 * file is still imported by 5 "use client" pages, so it deliberately has no
 * "server-only" marker and must not gain one.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL;
const LIST_ALL_PARAMS = "page=1&page_size=100";

interface ApiEnvelope<T> {
  success: boolean;
  data?: T;
  error?: { code: string; message: string };
}

export class AdminApiError extends Error {
  code?: string;
  constructor(message: string, code?: string) {
    super(message);
    this.code = code;
  }
}

async function authHeader(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Reads never throw — network failure, no session, or a non-2xx all
 * degrade to null/[]/error-state-in-the-UI, matching lib/onboarding/api.ts
 * and lib/portal/api.ts's established convention. */
async function apiGet<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE}${path}`, { headers: await authHeader(), cache: "no-store" });
    if (!res.ok) return null;
    const body: ApiEnvelope<T> = await res.json();
    return body.success ? (body.data ?? null) : null;
  } catch {
    return null;
  }
}

async function apiList<T>(path: string): Promise<T[]> {
  return (await apiGet<T[]>(path)) ?? [];
}

async function apiWrite<T>(path: string, method: "POST" | "PATCH", input?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: { "Content-Type": "application/json", ...(await authHeader()) },
      body: input !== undefined ? JSON.stringify(input) : undefined,
    });
  } catch {
    throw new AdminApiError("Couldn't reach InfinityPay. Check your connection and try again.");
  }

  const body: ApiEnvelope<T> = await res.json();
  if (!res.ok || !body.success || body.data === undefined) {
    const error = new AdminApiError(body.error?.message ?? "Request failed", body.error?.code);
    throw error;
  }
  return body.data;
}

// --- Command Center ----------------------------------------------------

export async function getAdminOverview(): Promise<AdminOverview | null> {
  return apiGet<AdminOverview>("/v1/admin/overview");
}

// --- Merchants -----------------------------------------------------------

export async function listAdminMerchants(): Promise<Merchant[]> {
  return apiList<Merchant>(`/v1/admin/merchants?${LIST_ALL_PARAMS}`);
}

export async function getAdminMerchant(merchantId: string): Promise<Merchant | null> {
  return apiGet<Merchant>(`/v1/admin/merchants/${merchantId}`);
}

export async function listAdminMerchantApiKeys(merchantId: string): Promise<AdminApiKeyRow[]> {
  return apiList<AdminApiKeyRow>(`/v1/admin/merchants/${merchantId}/api-keys`);
}

/** Null when the merchant hasn't created their permanent Pay by Link
 * page yet — see docs/PAY_BY_LINK.md. */
export async function getAdminMerchantPayByLink(merchantId: string): Promise<AdminPayByLinkRow | null> {
  return apiGet<AdminPayByLinkRow>(`/v1/admin/merchants/${merchantId}/pay-by-link`);
}

/** Super Admin's Notification Details for one merchant — settings plus
 * delivery summary. Null only on a network/auth failure (the backend
 * itself lazily creates a default settings row on first read, so a
 * merchant who's never configured anything still returns a real row). */
export async function getAdminMerchantNotificationSettings(
  merchantId: string,
): Promise<AdminNotificationSettingsRow | null> {
  return apiGet<AdminNotificationSettingsRow>(`/v1/admin/merchants/${merchantId}/notification-settings`);
}

export interface NotificationSettingsInput {
  primary_notification_email: string | null;
  secondary_notification_email: string | null;
  collection_notifications_enabled: boolean;
}

export async function updateAdminMerchantNotificationSettings(
  merchantId: string,
  input: NotificationSettingsInput,
): Promise<AdminNotificationSettingsRow> {
  return apiWrite<AdminNotificationSettingsRow>(
    `/v1/admin/merchants/${merchantId}/notification-settings`,
    "PATCH",
    input,
  );
}

export async function suspendMerchantApiAccess(merchantId: string): Promise<void> {
  await apiWrite(`/v1/admin/merchants/${merchantId}/api-access/suspend`, "POST");
}

export async function reinstateMerchantApiAccess(merchantId: string): Promise<void> {
  await apiWrite(`/v1/admin/merchants/${merchantId}/api-access/reinstate`, "POST");
}

export async function listAdminIpAllowlist(filters?: { merchantId?: string }): Promise<AdminIpAllowlistRow[]> {
  const params = new URLSearchParams(LIST_ALL_PARAMS);
  if (filters?.merchantId) params.set("merchant_id", filters.merchantId);
  return apiList<AdminIpAllowlistRow>(`/v1/admin/ip-allowlist?${params.toString()}`);
}

export async function approveIpAllowlistEntry(entryId: string): Promise<void> {
  await apiWrite(`/v1/admin/ip-allowlist/${entryId}/approve`, "POST");
}

export async function rejectIpAllowlistEntry(entryId: string): Promise<void> {
  await apiWrite(`/v1/admin/ip-allowlist/${entryId}/reject`, "POST");
}

export async function listAdminApiKeys(filters?: {
  merchantId?: string;
  status?: string;
  environment?: string;
}): Promise<AdminApiKeyPlatformRow[]> {
  const params = new URLSearchParams(LIST_ALL_PARAMS);
  if (filters?.merchantId) params.set("merchant_id", filters.merchantId);
  if (filters?.status) params.set("status", filters.status);
  if (filters?.environment) params.set("environment", filters.environment);
  return apiList<AdminApiKeyPlatformRow>(`/v1/admin/api-keys?${params.toString()}`);
}

export async function revokeAdminApiKey(apiKeyId: string): Promise<AdminApiKeyPlatformRow> {
  return apiWrite<AdminApiKeyPlatformRow>(`/v1/admin/api-keys/${apiKeyId}/revoke`, "PATCH");
}

export async function listAdminCustomers(filters?: { merchantId?: string }): Promise<AdminCustomerPlatformRow[]> {
  const params = new URLSearchParams(LIST_ALL_PARAMS);
  if (filters?.merchantId) params.set("merchant_id", filters.merchantId);
  return apiList<AdminCustomerPlatformRow>(`/v1/admin/customers?${params.toString()}`);
}

export async function updateMerchantStatus(merchantId: string, status: MerchantAccountStatus): Promise<void> {
  await apiWrite(`/v1/merchants/${merchantId}/status`, "PATCH", { status });
}

export async function approveMerchantOnboarding(merchantId: string): Promise<void> {
  await apiWrite(`/v1/admin/onboarding/${merchantId}/approve`, "PATCH");
}

// --- Merchant Users (read-only — no mutation endpoint requested) ---------

export async function listAdminMerchantUsers(): Promise<MerchantUserRow[]> {
  return apiList<MerchantUserRow>(`/v1/admin/merchant-users?${LIST_ALL_PARAMS}`);
}

// --- Payment Links / Invoices / Collections --------------------------------

export async function listAdminPaymentLinks(filters?: { merchantId?: string }): Promise<AdminPaymentLinkRow[]> {
  const params = new URLSearchParams(LIST_ALL_PARAMS);
  if (filters?.merchantId) params.set("merchant_id", filters.merchantId);
  return apiList<AdminPaymentLinkRow>(`/v1/admin/payment-links?${params.toString()}`);
}

/** Platform-wide Pay by Link Monitoring — every merchant's permanent
 * checkout page, separate from listAdminPaymentLinks above (which lists
 * payments, including ones created through a Pay by Link page). */
export async function listAdminPayByLinks(filters?: {
  merchantId?: string;
  isActive?: boolean;
}): Promise<AdminPayByLinkListRow[]> {
  const params = new URLSearchParams(LIST_ALL_PARAMS);
  if (filters?.merchantId) params.set("merchant_id", filters.merchantId);
  if (filters?.isActive !== undefined) params.set("is_active", String(filters.isActive));
  return apiList<AdminPayByLinkListRow>(`/v1/admin/pay-by-link?${params.toString()}`);
}

export async function listAdminInvoices(filters?: { merchantId?: string }): Promise<AdminInvoiceRow[]> {
  const params = new URLSearchParams(LIST_ALL_PARAMS);
  if (filters?.merchantId) params.set("merchant_id", filters.merchantId);
  return apiList<AdminInvoiceRow>(`/v1/admin/invoices?${params.toString()}`);
}

export async function listAdminCollections(filters?: {
  merchantId?: string;
  source?: string;
  method?: string;
  status?: string;
  dateFrom?: string;
  dateTo?: string;
  customerPhone?: string;
  merchantReference?: string;
  apiKeyId?: string;
  paymentLinkId?: string;
  invoiceId?: string;
}): Promise<AdminCollectionRow[]> {
  const params = new URLSearchParams(LIST_ALL_PARAMS);
  if (filters?.merchantId) params.set("merchant_id", filters.merchantId);
  if (filters?.source) params.set("source", filters.source);
  if (filters?.method) params.set("method", filters.method);
  if (filters?.status) params.set("status", filters.status);
  if (filters?.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters?.dateTo) params.set("date_to", filters.dateTo);
  if (filters?.customerPhone) params.set("customer_phone", filters.customerPhone);
  if (filters?.merchantReference) params.set("merchant_reference", filters.merchantReference);
  if (filters?.apiKeyId) params.set("api_key_id", filters.apiKeyId);
  if (filters?.paymentLinkId) params.set("payment_link_id", filters.paymentLinkId);
  if (filters?.invoiceId) params.set("invoice_id", filters.invoiceId);
  return apiList<AdminCollectionRow>(`/v1/admin/collections?${params.toString()}`);
}

// Manual Selcom Checkout order-status refresh is a client-side
// interactive action (loading state, inline result) — see
// lib/admin/refresh-collection-status-client.ts, which this
// "server-only" file cannot host.

// --- Withdrawals -----------------------------------------------------------

export async function listAdminWithdrawals(filters?: {
  status?: string;
  requiresApproval?: boolean;
  merchantId?: string;
}): Promise<AdminWithdrawalRow[]> {
  const params = new URLSearchParams(LIST_ALL_PARAMS);
  if (filters?.status) params.set("status", filters.status);
  if (filters?.requiresApproval !== undefined) params.set("requires_approval", String(filters.requiresApproval));
  if (filters?.merchantId) params.set("merchant_id", filters.merchantId);
  return apiList<AdminWithdrawalRow>(`/v1/admin/withdrawals?${params.toString()}`);
}

export async function approveWithdrawal(disbursementId: string): Promise<void> {
  await apiWrite(`/v1/admin/withdrawals/${disbursementId}/approve`, "POST");
}

export async function rejectWithdrawal(disbursementId: string, rejectionReason: string): Promise<void> {
  await apiWrite(`/v1/admin/withdrawals/${disbursementId}/reject`, "POST", { rejection_reason: rejectionReason });
}

export async function requestInfoWithdrawal(
  disbursementId: string,
  input: { message: string; requestedDocuments: string[] },
): Promise<void> {
  await apiWrite(`/v1/admin/withdrawals/${disbursementId}/request-info`, "POST", {
    message: input.message,
    requested_documents: input.requestedDocuments,
  });
}

export async function refreshWithdrawalStatus(disbursementId: string): Promise<void> {
  await apiWrite(`/v1/admin/withdrawals/${disbursementId}/refresh-status`, "POST");
}

export async function reconcilePendingWithdrawals(): Promise<{ checked: number; resolved: number; still_pending: number }> {
  return apiWrite(`/v1/admin/withdrawals/reconcile-pending`, "POST");
}

// --- Pricing rules -----------------------------------------------------------

export async function listPricingRulesForMerchant(merchantId: string): Promise<PricingRuleRow[]> {
  return apiList<PricingRuleRow>(`/v1/admin/merchants/${merchantId}/pricing-rules`);
}

export async function listPlatformFallbackPricingRules(): Promise<PricingRuleRow[]> {
  return apiList<PricingRuleRow>(`/v1/admin/pricing-rules`);
}

export interface PricingRuleInput {
  channel?: string | null;
  destination_code?: string | null;
  percentage_fee?: string;
  flat_fee?: string;
  minimum_fee?: string | null;
  maximum_fee?: string | null;
  processor_fee_flat?: string;
  processor_fee_pass_through?: boolean;
  effective_from?: string | null;
  effective_to?: string | null;
  label?: string | null;
}

export async function createMerchantPricingRule(merchantId: string, input: PricingRuleInput): Promise<PricingRuleRow> {
  return apiWrite<PricingRuleRow>(`/v1/admin/merchants/${merchantId}/pricing-rules`, "POST", input);
}

export async function createPlatformFallbackPricingRule(input: PricingRuleInput): Promise<PricingRuleRow> {
  return apiWrite<PricingRuleRow>(`/v1/admin/pricing-rules/platform-fallback`, "POST", input);
}

export async function updatePricingRule(ruleId: string, input: Partial<PricingRuleInput>): Promise<PricingRuleRow> {
  return apiWrite<PricingRuleRow>(`/v1/admin/pricing-rules/${ruleId}`, "PATCH", input);
}

export async function deactivatePricingRule(ruleId: string): Promise<PricingRuleRow> {
  return apiWrite<PricingRuleRow>(`/v1/admin/pricing-rules/${ruleId}/deactivate`, "POST");
}

// --- Collection pricing rules (LIVE) — the collection-side sibling of the
// (now inactive-for-fees) withdrawal pricing rules above. -------------------

export async function listCollectionPricingRulesForMerchant(merchantId: string): Promise<CollectionPricingRuleRow[]> {
  return apiList<CollectionPricingRuleRow>(`/v1/admin/merchants/${merchantId}/collection-pricing-rules`);
}

export async function listPlatformFallbackCollectionPricingRules(): Promise<CollectionPricingRuleRow[]> {
  return apiList<CollectionPricingRuleRow>(`/v1/admin/collection-pricing-rules`);
}

export interface CollectionPricingRuleInput {
  channel?: string | null;
  percentage_fee?: string;
  flat_fee?: string;
  minimum_fee?: string | null;
  maximum_fee?: string | null;
  effective_from?: string | null;
  effective_to?: string | null;
  is_active?: boolean;
  label?: string | null;
  notes?: string | null;
}

export async function createMerchantCollectionPricingRule(
  merchantId: string,
  input: CollectionPricingRuleInput,
): Promise<CollectionPricingRuleRow> {
  return apiWrite<CollectionPricingRuleRow>(`/v1/admin/merchants/${merchantId}/collection-pricing-rules`, "POST", input);
}

export async function createPlatformFallbackCollectionPricingRule(
  input: CollectionPricingRuleInput,
): Promise<CollectionPricingRuleRow> {
  return apiWrite<CollectionPricingRuleRow>(`/v1/admin/collection-pricing-rules/platform-fallback`, "POST", input);
}

export async function updateCollectionPricingRule(
  ruleId: string,
  input: Partial<CollectionPricingRuleInput>,
): Promise<CollectionPricingRuleRow> {
  return apiWrite<CollectionPricingRuleRow>(`/v1/admin/collection-pricing-rules/${ruleId}`, "PATCH", input);
}

export async function deactivateCollectionPricingRule(ruleId: string): Promise<CollectionPricingRuleRow> {
  return apiWrite<CollectionPricingRuleRow>(`/v1/admin/collection-pricing-rules/${ruleId}/deactivate`, "POST");
}

export async function activateCollectionPricingRule(ruleId: string): Promise<CollectionPricingRuleRow> {
  return apiWrite<CollectionPricingRuleRow>(`/v1/admin/collection-pricing-rules/${ruleId}/activate`, "POST");
}

// --- Transactions / Webhooks / Audit Logs (read-only) ----------------------

export async function listAdminTransactions(filters?: {
  merchantId?: string;
  type?: string;
  status?: string;
  providerReference?: string;
  transactionId?: string;
  dateFrom?: string;
  dateTo?: string;
}): Promise<AdminTransactionRow[]> {
  const params = new URLSearchParams(LIST_ALL_PARAMS);
  if (filters?.merchantId) params.set("merchant_id", filters.merchantId);
  if (filters?.type) params.set("type", filters.type);
  if (filters?.status) params.set("status", filters.status);
  if (filters?.providerReference) params.set("provider_reference", filters.providerReference);
  if (filters?.transactionId) params.set("transaction_id", filters.transactionId);
  if (filters?.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters?.dateTo) params.set("date_to", filters.dateTo);
  return apiList<AdminTransactionRow>(`/v1/admin/transactions?${params.toString()}`);
}

export async function listAdminWebhookEvents(): Promise<AdminWebhookEventRow[]> {
  return apiList<AdminWebhookEventRow>(`/v1/admin/webhooks?${LIST_ALL_PARAMS}`);
}

export async function listAdminAuditLogs(): Promise<AuditLogRow[]> {
  return apiList<AuditLogRow>(`/v1/admin/audit-logs?${LIST_ALL_PARAMS}`);
}

export async function listAdminInquiries(): Promise<AdminInquiryRow[]> {
  return apiList<AdminInquiryRow>(`/v1/admin/inquiries?${LIST_ALL_PARAMS}`);
}

// --- Risk monitoring -------------------------------------------------------

export async function listAdminRiskAlerts(filters?: { merchantId?: string }): Promise<AdminFraudAlertRow[]> {
  const params = new URLSearchParams(LIST_ALL_PARAMS);
  if (filters?.merchantId) params.set("merchant_id", filters.merchantId);
  return apiList<AdminFraudAlertRow>(`/v1/admin/risk-alerts?${params.toString()}`);
}

export async function updateRiskAlertStatus(alertId: string, status: string, note?: string): Promise<void> {
  await apiWrite(`/v1/admin/risk-alerts/${alertId}/status`, "PATCH", { status, note });
}

export async function addRiskAlertNote(alertId: string, note: string): Promise<void> {
  await apiWrite(`/v1/admin/risk-alerts/${alertId}/notes`, "POST", { note });
}

export async function requestDocumentsForAlert(
  alertId: string,
  input: { requested_documents: string[]; reason: string; due_date?: string },
): Promise<void> {
  await apiWrite(`/v1/admin/risk-alerts/${alertId}/request-documents`, "POST", input);
}

// --- Document requests -----------------------------------------------------

export async function listAdminDocumentRequests(): Promise<AdminDocumentRequestRow[]> {
  return apiList<AdminDocumentRequestRow>("/v1/admin/document-requests");
}

export async function approveDocumentRequest(requestId: string): Promise<void> {
  await apiWrite(`/v1/admin/document-requests/${requestId}/approve`, "PATCH");
}

export async function rejectDocumentRequest(requestId: string): Promise<void> {
  await apiWrite(`/v1/admin/document-requests/${requestId}/reject`, "PATCH");
}

// --- Disputes ----------------------------------------------------------------

export async function listAdminDisputes(): Promise<AdminDisputeRow[]> {
  return apiList<AdminDisputeRow>("/v1/admin/disputes");
}

export async function updateDisputeStatus(disputeId: string, status: string, note?: string): Promise<void> {
  await apiWrite(`/v1/admin/disputes/${disputeId}/status`, "PATCH", { status, note });
}

export async function requestRefundForDispute(disputeId: string, amount: string): Promise<AdminRefundRow> {
  return apiWrite<AdminRefundRow>(`/v1/admin/disputes/${disputeId}/request-refund`, "POST", { amount });
}

export async function updateRefundStatus(
  disputeId: string,
  status: string,
  providerReference?: string,
): Promise<AdminRefundRow> {
  return apiWrite<AdminRefundRow>(`/v1/admin/disputes/${disputeId}/refund-status`, "PATCH", {
    status,
    provider_reference: providerReference,
  });
}

// --- Notifications -----------------------------------------------------------

export async function listAdminNotifications(): Promise<AdminNotificationRow[]> {
  return apiList<AdminNotificationRow>("/v1/admin/notifications");
}
