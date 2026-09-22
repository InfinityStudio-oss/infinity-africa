/**
 * Mirrors apps/api's Pydantic response schemas field-for-field (snake_case,
 * amounts as strings, ISO timestamps as strings) so the mock data layer and
 * the real FastAPI responses are interchangeable without a translation
 * layer — see lib/portal/api.ts.
 */

import type {
  CollectionMethod,
  DisbursementMethod,
  DisbursementStatus,
  InvoiceStatus,
  PaymentLinkStatus,
  UserRole,
} from "@infinity/shared";

/** Mirrors apps/api's {success, data} / {success, error} envelope. */
export interface ApiEnvelope<T> {
  success: boolean;
  data?: T;
  error?: { code: string; message: string };
  meta?: { page: number; page_size: number; total: number; total_pages: number } | null;
}

export interface PaymentLink {
  id: string;
  merchant_id: string;
  customer_id: string | null;
  amount: string;
  currency: string;
  customer_name: string | null;
  customer_phone: string | null;
  customer_email: string | null;
  description: string | null;
  allowed_payment_methods: CollectionMethod[];
  expires_at: string | null;
  status: PaymentLinkStatus;
  public_slug: string;
  public_url: string;
  merchant_reference: string | null;
  success_redirect_url: string | null;
  failure_redirect_url: string | null;
  paid_at: string | null;
  attempt_count: number;
  created_at: string;
  updated_at: string;
  // Only ever set by the create-link response — true/false for "an email
  // was attempted and it succeeded/failed", null for "no customer_email,
  // nothing was attempted". Every other endpoint (list/get/cancel) leaves
  // this null; they don't re-attempt a send.
  customer_email_sent: boolean | null;
}

/** A merchant's permanent public "Pay by Link" checkout page
 * (/pay/{slug}) — distinct from PaymentLink above, which is a one-off
 * generated/shareable link with a fixed amount. See docs/PAY_BY_LINK.md. */
export interface PayByLink {
  id: string;
  merchant_id: string;
  slug: string;
  public_url: string;
  display_name: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
}

/** Up to 2 email addresses this merchant wants notified when a collection
 * transaction is successfully confirmed — distinct from a customer's own
 * payment receipt email, which is never configurable. See
 * docs/merchant-collection-notifications.md. */
export interface NotificationSettings {
  id: string;
  merchant_id: string;
  primary_notification_email: string | null;
  secondary_notification_email: string | null;
  collection_notifications_enabled: boolean;
  created_at: string;
  updated_at: string;
  updated_by: string | null;
}

export interface InvoiceItem {
  id: string;
  description: string;
  quantity: string;
  unit_price: string;
  line_total: string;
  sort_order: number;
}

export interface Invoice {
  id: string;
  merchant_id: string;
  customer_id: string | null;
  invoice_number: string;
  customer_name: string | null;
  customer_email: string | null;
  customer_phone: string | null;
  due_date: string;
  currency: string;
  subtotal: string;
  tax_amount: string;
  discount_amount: string;
  total_amount: string;
  amount_paid: string;
  status: InvoiceStatus;
  payment_link_id: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  /** Set only once the payment-request email actually goes out — null
   * means never successfully sent, even if a send was attempted. */
  sent_at: string | null;
  items: InvoiceItem[];
}

/** collections.status — a 3-state in-flight/resolved lifecycle, distinct
 * from the uppercase DisbursementStatus / TS-shared TransactionStatus. */
export type CollectionStatus = "processing" | "successful" | "failed" | "reversed" | "pending_review";

export interface Collection {
  id: string;
  merchant_id: string;
  customer_id: string | null;
  payment_link_id: string | null;
  invoice_id: string | null;
  merchant_reference: string | null;
  method: CollectionMethod;
  amount: string;
  currency: string;
  customer_phone: string | null;
  status: CollectionStatus;
  provider: string | null;
  provider_reference: string | null;
  transaction_reference: string | null;
  message: string | null;
  expires_at: string | null;
  initiated_at: string;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  // Selcom Checkout reconciliation detail — populated once a
  // create-order-minimal/wallet-push collection resolves via webhook or
  // manual refresh (see docs/selcom-checkout-collections.md).
  failure_reason: string | null;
  checkout_order_id: string | null;
  provider_transid: string | null;
  provider_resultcode: string | null;
  provider_result: string | null;
  provider_payment_status: string | null;
  channel: string | null;
}

/** "Request Collection" response (2026-08-23) — no channel to pick;
 * payment_gateway_url is Selcom's own hosted checkout page, already
 * decoded, for the merchant to open or copy. */
export interface HostedCheckoutCollection extends Collection {
  payment_gateway_url: string | null;
}

export interface Disbursement {
  id: string;
  merchant_id: string;
  settlement_account_id: string | null;
  method: DisbursementMethod;
  amount: string;
  currency: string;
  destination_name: string;
  destination_identifier: string;
  destination_code: string | null;
  bank_name: string | null;
  status: DisbursementStatus;
  requires_approval: boolean;
  // True if this withdrawal skipped Super Admin approval via the
  // automated eligibility check — approved_by/approved_at stay null in
  // that case, since no human approved it.
  auto_approved: boolean;
  auto_decision_reason: string | null;
  approved_by: string | null;
  approved_at: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  admin_status_reason: string | null;
  provider_reference: string | null;
  // Fee snapshot — calculated once at submission time and frozen; see
  // lib/portal/api.ts's calculateWithdrawalCharges for the pre-submit quote.
  processor_charge: string;
  infinity_fee: string;
  percentage_fee_component: string;
  flat_fee_component: string;
  total_charges: string;
  total_reserved_amount: string | null;
  recipient_net_amount: string | null;
  pricing_rule_id: string | null;
  transaction_reference: string | null;
  fee_amount: string | null;
  net_amount: string | null;
  initiated_at: string;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

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
  pricing_rule_id: string | null;
  pricing_rule_label: string | null;
  processor_fee_pass_through: boolean;
  /** True when the applied rule is a platform fallback (no merchant-specific
   * rule matched) rather than one scoped to this merchant. */
  is_platform_fallback: boolean;
}

export type TransactionType = "collection" | "disbursement" | "fee" | "refund" | "reversal" | "adjustment";
export type TransactionStatus = "pending" | "processing" | "successful" | "failed" | "reversed" | "cancelled";

export interface Transaction {
  id: string;
  merchant_id: string;
  reference: string;
  provider_reference: string | null;
  type: TransactionType;
  method: string;
  collection_id: string | null;
  disbursement_id: string | null;
  gross_amount: string;
  fee_amount: string;
  net_amount: string;
  currency: string;
  status: TransactionStatus;
  /** Wallet balance snapshot around this transaction's most recent ledger
   * posting. Null for transactions from before this was captured, or with
   * no wallet-affecting leg — render as "Not available", never computed. */
  balance_before: string | null;
  balance_after: string | null;
  direction: "debit" | "credit" | null;
  created_at: string;
}

export interface Customer {
  id: string;
  merchant_id: string;
  name: string;
  phone: string | null;
  email: string | null;
  total_spent: string;
  last_transaction_at: string | null;
  status: "active" | "inactive";
  created_at: string;
}

export interface ApiKey {
  id: string;
  merchant_id: string;
  name: string;
  environment: "sandbox" | "live";
  key_prefix: string;
  key_last4: string | null;
  scopes: string[];
  status: "active" | "revoked";
  ip_whitelist_enabled: boolean;
  continue_without_ip_whitelist: boolean;
  last_used_at: string | null;
  last_used_ip: string | null;
  revoked_at: string | null;
  created_at: string;
  updated_at: string;
}

/** One row of the inline "Allowed server IPs" list on the API key creation
 * form — submitted as ApiKeyCreate.allowed_ips, not a separate call. */
export interface AllowedIpDraft {
  ip_address_or_cidr: string;
  label: string | null;
}

export interface IpAllowlistEntry {
  id: string;
  merchant_id: string;
  api_key_id: string | null;
  environment: "sandbox" | "live";
  label: string;
  ip_address_or_cidr: string;
  status: "pending" | "active" | "rejected";
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApiRequestLog {
  id: string;
  api_key_id: string | null;
  environment: "sandbox" | "live";
  method: string;
  path: string;
  status_code: number;
  ip_address: string | null;
  duration_ms: number | null;
  created_at: string;
}

/** The 8 scopes a merchant can grant an API key — mirrors
 * app.schemas.api_keys.API_KEY_SCOPES. */
export const API_KEY_SCOPES = [
  "collections:write",
  "collections:read",
  "payment_links:write",
  "payment_links:read",
  "invoices:write",
  "invoices:read",
  "transactions:read",
  "webhooks:manage",
] as const;

export type ApiKeyScope = (typeof API_KEY_SCOPES)[number];

export interface WalletLedgerEntry {
  id: string;
  transaction_id: string | null;
  date: string;
  description: string;
  direction: "credit" | "debit";
  amount: string;
  balance_before: string;
  balance_after: string;
  /** Joined from the entry's transaction — null when there isn't one
   * linked (older/edge-case rows), never guessed. */
  type: string | null;
  reference: string | null;
  provider_reference: string | null;
  method: string | null;
  fee_amount: string | null;
  net_amount: string | null;
  status: string | null;
}

/** apps/api's MerchantUserResponse (merchant_users row + the invited
 * person's full_name/email, joined from Supabase Auth — see
 * app.services.admin_directory.best_effort_user_profile). */
export interface MerchantUser {
  id: string;
  user_id: string;
  merchant_id: string;
  full_name: string | null;
  email: string | null;
  role: UserRole;
  status: "invited" | "active" | "suspended";
  created_at: string;
  updated_at: string;
}

/** apps/api's MerchantResponse — the merchant's own business profile
 * (GET/PATCH /v1/merchant/me, /v1/merchants/{id}). */
export interface MerchantProfile {
  id: string;
  /** Human-friendly Merchant ID (27 + 6 digits) — identification only, not
   * a secret. Nullable purely for defensive typing (older API deploys
   * before this field existed); a real merchant always has one. */
  merchant_code: string | null;
  business_name: string;
  legal_name: string | null;
  country: string;
  currency: string;
  contact_email: string;
  contact_phone: string | null;
  status: string;
  kyc_status: string;
  api_access_suspended: boolean;
  webhook_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface SupportTicket {
  id: string;
  subject: string;
  category: string;
  status: "open" | "resolved";
  created_at: string;
}

/** The events services/webhooks.py can enqueue — mirrors the
 * webhook_events.event_name CHECK constraint. */
export const WEBHOOK_EVENT_NAMES = [
  "collection.pending",
  "collection.success",
  "collection.failed",
  "disbursement.success",
  "disbursement.failed",
  "invoice.paid",
  "invoice.overdue",
  "payment_link.created",
  "payment_link.paid",
  "payment_link.expired",
  "refund.succeeded",
  "refund.failed",
  "chargeback.opened",
  "chargeback.resolved",
] as const;

export interface WebhookLastDelivery {
  event_name: string;
  status: string;
  created_at: string;
}

export interface WebhookConfig {
  webhook_url: string | null;
  subscribed_events: string[] | null;
  has_secret: boolean;
  last_delivery: WebhookLastDelivery | null;
}

/** Only present once, immediately after regenerate_secret: true. */
export interface WebhookConfigWithSecret extends WebhookConfig {
  secret: string | null;
}

export interface WebhookTestResult {
  delivered: boolean;
  http_status: number | null;
  latency_ms: number;
}

/** Mirrors app.schemas.webhook_config.WebhookEventResponse — a row from the
 * outbound delivery queue (webhook_events), not yet auto-delivered by a
 * worker (see docs/api.md's Webhooks page for the current state of that). */
export interface WebhookEvent {
  id: string;
  event_name: string;
  payload: Record<string, unknown>;
  target_url: string;
  status: "pending" | "delivered" | "failed" | "retrying";
  attempts: number;
  last_attempted_at: string | null;
  delivered_at: string | null;
  response_status_code: number | null;
  created_at: string;
}

// --- Risk monitoring / disputes / refunds -----------------------------------

export type FraudRiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type FraudAlertStatus = "OPEN" | "UNDER_REVIEW" | "DOCUMENTS_REQUESTED" | "CLEARED" | "ESCALATED" | "CLOSED";

export interface FraudAlert {
  id: string;
  merchant_id: string;
  transaction_id: string | null;
  customer_phone: string | null;
  rule_code: string;
  risk_level: FraudRiskLevel;
  reason: string;
  status: FraudAlertStatus;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type DocumentRequestStatus = "PENDING" | "SUBMITTED" | "APPROVED" | "REJECTED";

export interface DocumentRequestFile {
  id: string;
  request_id: string;
  document_label: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  created_at: string;
}

export interface DocumentRequest {
  id: string;
  merchant_id: string;
  transaction_id: string | null;
  alert_id: string | null;
  requested_documents: string[];
  reason: string;
  status: DocumentRequestStatus;
  due_date: string | null;
  created_at: string;
  updated_at: string;
  files: DocumentRequestFile[];
}

export const DISPUTE_REASON_CATEGORIES = [
  "PRODUCT_NOT_RECEIVED",
  "SERVICE_NOT_DELIVERED",
  "WRONG_PRODUCT_OR_SERVICE",
  "DUPLICATE_PAYMENT",
  "UNAUTHORIZED_PAYMENT",
  "REFUND_REQUESTED",
  "OTHER",
] as const;
export type DisputeReasonCategory = (typeof DISPUTE_REASON_CATEGORIES)[number];

export type DisputeStatus =
  | "SUBMITTED"
  | "MERCHANT_NOTIFIED"
  | "UNDER_REVIEW"
  | "REFUND_REQUESTED"
  | "REFUNDED"
  | "REJECTED"
  | "CLOSED";

export interface DisputeMessage {
  id: string;
  dispute_id: string;
  sender_type: "merchant" | "admin" | "system";
  sender_id: string | null;
  body: string;
  attachment_files: Array<{ file_path: string; original_filename: string }>;
  created_at: string;
}

export interface Dispute {
  id: string;
  merchant_id: string | null;
  transaction_id: string | null;
  customer_name: string;
  customer_phone: string;
  customer_email: string | null;
  transaction_reference: string | null;
  amount: string | null;
  reason_category: DisputeReasonCategory;
  description: string;
  status: DisputeStatus;
  evidence_files: Array<{ file_path: string; original_filename: string }>;
  created_at: string;
  updated_at: string;
}

export interface DisputeWithMessages extends Dispute {
  messages: DisputeMessage[];
}

export type RefundStatus = "REQUESTED" | "APPROVED" | "PROCESSING" | "SUCCESS" | "FAILED" | "CANCELLED";

export interface Refund {
  id: string;
  dispute_id: string;
  transaction_id: string;
  merchant_id: string;
  amount: string;
  currency: string;
  status: RefundStatus;
  requested_by: "merchant" | "admin";
  evidence_files: Array<{ file_path: string; original_filename: string }>;
  provider_reference: string | null;
  created_at: string;
  updated_at: string;
}

export interface AppNotification {
  id: string;
  recipient_type: "merchant" | "admin";
  merchant_id: string | null;
  notification_type: "fraud_alert" | "document_request" | "dispute_received" | "refund_requested" | "dispute_status_updated";
  title: string;
  body: string;
  related_resource_type: string | null;
  related_resource_id: string | null;
  is_read: boolean;
  created_at: string;
}
