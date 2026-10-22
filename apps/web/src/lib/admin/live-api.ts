import "server-only";

import { getAccessToken } from "@/lib/supabase/session";

import type {
  EffectiveSettingsReport,
  AdminApiKeyPlatformRow,
  AdminApiKeyRow,
  AdminCustomerPlatformRow,
  AdminCustomerSummary,
  AdminReferralRow,
  AdminReferralSummary,
  AdminCollectionRow,
  AdminDisputeRow,
  AdminDocumentRequestRow,
  AdminFraudAlertRow,
  AdminInquiryRow,
  AdminInvoiceRow,
  AdminIpAllowlistRow,
  AdminNotificationRow,
  AdminTeamMember,
  AdminNotificationSettingsRow,
  AdminOverview,
  AdminPayByLinkListRow,
  AdminPayByLinkRow,
  AdminPaymentLinkRow,
  AdminRefundRow,
  AdminTransactionRow,
  AdminWebhookEventRow,
  AdminWithdrawalRow,
  DisbursementFloatBalance,
  MerchantOption,
  AuditLogRow,
  CollectionPricingRuleRow,
  Merchant,
  MerchantAccountStatus,
  MerchantUserRow,
  PricingRuleRow,
  AdminSmsCampaignRow,
  AdminSmsDryRun,
  AdminSmsMessageRow,
  AdminSmsOverview,
  AdminSmsPreview,
  AdminSmsSettings,
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

async function apiWrite<T>(
  path: string,
  method: "POST" | "PATCH" | "DELETE",
  input?: unknown,
): Promise<T> {
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

/** Just enough to fill a "filter by business" dropdown.
 *
 * listAdminMerchants() below is for the Businesses page, which shows an
 * owner's name — and paying for that costs one Supabase Auth call per
 * merchant owner on the backend. Four pages were calling it only to list
 * names in a select, so each one waited on owner lookups it never
 * rendered, and the wait grew with the merchant count. */
export async function listAdminMerchantOptions(): Promise<MerchantOption[]> {
  return apiList<MerchantOption>(`/v1/admin/merchants/directory`);
}

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
  /** Omitted means "leave unchanged" on the backend, never "off". */
  collection_sms_enabled?: boolean;
  announcement_sms_enabled?: boolean;
  sms_notification_phone?: string;
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

// --- Super Admin SMS ---------------------------------------------------
// Every one of these is Super Admin only on the backend, including the
// reads: an SMS list carries merchant phone numbers and message bodies.

export async function getAdminSmsOverview(): Promise<AdminSmsOverview | null> {
  return apiGet<AdminSmsOverview>("/v1/admin/sms/overview");
}

export async function getAdminSmsSettings(): Promise<AdminSmsSettings | null> {
  return apiGet<AdminSmsSettings>("/v1/admin/sms/settings");
}

export async function listAdminSmsMessages(filters?: {
  status?: string;
  purpose?: string;
  campaignId?: string;
}): Promise<AdminSmsMessageRow[]> {
  const params = new URLSearchParams();
  if (filters?.status) params.set("status_filter", filters.status);
  if (filters?.purpose) params.set("purpose", filters.purpose);
  if (filters?.campaignId) params.set("campaign_id", filters.campaignId);
  const query = params.toString();
  return apiList<AdminSmsMessageRow>(`/v1/admin/sms/messages${query ? `?${query}` : ""}`);
}

export async function listAdminSmsCampaigns(): Promise<AdminSmsCampaignRow[]> {
  return apiList<AdminSmsCampaignRow>("/v1/admin/sms/campaigns");
}

export async function previewAdminSms(input: {
  body: string;
  merchant_ids?: string[] | null;
}): Promise<AdminSmsPreview> {
  return apiWrite<AdminSmsPreview>("/v1/admin/sms/preview", "POST", input);
}

/** Asks the provider to price the message. Sends nothing, charges
 * nothing and consumes no idempotency key. */
export async function dryRunAdminSms(input: {
  body: string;
  merchant_ids?: string[] | null;
}): Promise<AdminSmsDryRun> {
  return apiWrite<AdminSmsDryRun>("/v1/admin/sms/dry-run", "POST", input);
}

export async function createAdminSmsCampaign(input: {
  title: string;
  body: string;
  merchant_ids?: string[] | null;
}): Promise<AdminSmsCampaignRow> {
  return apiWrite<AdminSmsCampaignRow>("/v1/admin/sms/campaigns", "POST", input);
}

export async function updateAdminSmsCampaign(
  campaignId: string,
  input: { title: string; body: string; merchant_ids?: string[] | null },
): Promise<AdminSmsCampaignRow> {
  return apiWrite<AdminSmsCampaignRow>(`/v1/admin/sms/campaigns/${campaignId}`, "PATCH", input);
}

export async function duplicateAdminSmsCampaign(campaignId: string): Promise<AdminSmsCampaignRow> {
  return apiWrite<AdminSmsCampaignRow>(`/v1/admin/sms/campaigns/${campaignId}/duplicate`, "POST");
}

export async function deleteAdminSmsCampaign(campaignId: string): Promise<void> {
  await apiWrite(`/v1/admin/sms/campaigns/${campaignId}`, "DELETE");
}

/** The only call here that can cause an SMS to be sent. */
export async function sendAdminSmsCampaign(campaignId: string): Promise<AdminSmsCampaignRow> {
  return apiWrite<AdminSmsCampaignRow>(`/v1/admin/sms/campaigns/${campaignId}/send`, "POST");
}

export async function retryAdminSmsMessage(messageId: string): Promise<void> {
  await apiWrite(`/v1/admin/sms/messages/${messageId}/retry`, "POST");
}

export async function correctMerchantContactEmail(merchantId: string, email: string): Promise<void> {
  await apiWrite(`/v1/admin/merchants/${merchantId}/correct-contact-email`, "POST", { email });
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

export async function getAdminCustomerSummary(
  filters?: { merchantId?: string },
): Promise<AdminCustomerSummary | null> {
  const params = new URLSearchParams();
  if (filters?.merchantId) params.set("merchant_id", filters.merchantId);
  const query = params.toString();
  return apiGet<AdminCustomerSummary>(`/v1/admin/customers/summary${query ? `?${query}` : ""}`);
}

export async function listAdminReferrals(filters?: { status?: string }): Promise<AdminReferralRow[]> {
  const params = new URLSearchParams(LIST_ALL_PARAMS);
  if (filters?.status) params.set("status", filters.status);
  return apiList<AdminReferralRow>(`/v1/admin/referrals?${params.toString()}`);
}

/** Counted server-side across every referral, so the cards cannot report
 * a page size as a total. */
export async function getAdminReferralSummary(): Promise<AdminReferralSummary | null> {
  return apiGet<AdminReferralSummary>("/v1/admin/referrals/summary");
}

export async function approveReferralCommission(commissionId: string): Promise<void> {
  await apiWrite(`/v1/admin/referrals/commissions/${commissionId}/approve`, "POST", {});
}

export async function rejectReferralCommission(commissionId: string, reason: string): Promise<void> {
  await apiWrite(`/v1/admin/referrals/commissions/${commissionId}/reject`, "POST", { reason });
}

/** Records a payout made elsewhere. This does not pay anything. */
export async function markReferralCommissionPaid(commissionId: string, note?: string): Promise<void> {
  await apiWrite(`/v1/admin/referrals/commissions/${commissionId}/paid`, "POST", { note: note ?? null });
}

export async function setReferralFraudHold(referralId: string, reason: string): Promise<void> {
  await apiWrite(`/v1/admin/referrals/${referralId}/fraud-hold`, "POST", { reason });
}

export async function clearReferralFraudHold(referralId: string): Promise<void> {
  await apiWrite(`/v1/admin/referrals/${referralId}/fraud-hold`, "DELETE");
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

export async function retryWithdrawalPayout(disbursementId: string): Promise<void> {
  await apiWrite(`/v1/admin/withdrawals/${disbursementId}/retry`, "POST");
}

/** The platform's own Selcom disbursement float. Never throws for a
 * caller: the endpoint reports `available: null` with a reason rather
 * than failing, so a provider outage cannot take the withdrawals page
 * down with it. */
export async function getDisbursementFloatBalance(): Promise<DisbursementFloatBalance> {
  return (
    (await apiGet<DisbursementFloatBalance>(`/v1/admin/withdrawals/float-balance`)) ?? {
      available: null,
      currency: "TZS",
      reason: "provider_unavailable",
    }
  );
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

/**
 * Returns null when the roster could not be READ, as distinct from an
 * empty array meaning there are genuinely no admins.
 *
 * apiList collapses both into []: apiGet swallows a 404, a 500, an
 * expired token and a dropped connection alike and returns null. For
 * most lists that is a reasonable trade. For this one it is not -- "no
 * platform admins found" shown to a signed-in super admin is impossible
 * by definition, so rendering it means the page is lying about something
 * it could simply have said it did not know.
 */
export async function listAdminTeam(): Promise<AdminTeamMember[] | null> {
  return apiGet<AdminTeamMember[]>("/v1/admin/team");
}

/**
 * The operational switches as the running API actually resolved them.
 *
 * Added after an evening spent unable to answer "is this variable
 * actually set?" from outside the process. A variable that is absent,
 * misspelled or unreadable all produce the same outcome - the field's
 * default - and two of those three are completely silent. Selcom
 * callbacks kept being rejected after the flag enabling them had
 * reportedly been set; 177 went unprocessed after a confirmed deploy
 * before the cause turned out to be that the process had never seen it.
 *
 * `source` is the field that answers it: "env" means something supplied
 * the value, "default" means nothing did.
 */
export async function getEffectiveSettings(): Promise<EffectiveSettingsReport | null> {
  return apiGet<EffectiveSettingsReport>("/v1/admin/diagnostics/settings");
}
