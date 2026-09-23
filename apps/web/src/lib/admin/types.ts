/**
 * Row shapes for the super admin dashboard's platform-wide monitoring
 * tables. Each mirrors what a real "list across all merchants" apps/api
 * endpoint would return (the merchant-scoped equivalents already exist —
 * see lib/portal/types.ts — these add merchant_name for the admin view and
 * flatten to just what each table displays). Swapping to FastAPI happens
 * in lib/admin/api.ts only — no component here talks to mock data directly.
 */

import type { UserRole } from "@infinity/shared";

export interface AdminOverview {
  total_merchants: number;
  collections_today: string;
  withdrawals_today: string;
  active_payment_links: number;
  paid_invoices_today: number;
  outstanding_invoice_value: string;
  failed_transactions: number;
  platform_revenue: string;
  pending_onboarding_requests: number;
  pending_withdrawals: number;
}

/** Straight passthrough of merchants.status — see supabase/migrations'
 * merchants table CHECK constraint. Distinct from AccountStatus
 * (onboarding_submissions.review_status, @infinity/shared) — this is the
 * merchant record's own lifecycle, not the onboarding review lifecycle. */
export type MerchantAccountStatus = "pending" | "active" | "suspended" | "closed";

export interface Merchant {
  merchant_id: string;
  /** Human-friendly account ID (27 + 6 digits) — identification only,
   * never an auth secret. Null only for defensive typing; a real merchant
   * always has one after supabase/migrations/20260829010000. */
  merchant_code: string | null;
  business_name: string;
  owner_name: string | null;
  email: string;
  contact_phone: string | null;
  nature_of_business: string | null;
  physical_address: string | null;
  account_status: MerchantAccountStatus;
  kyc_status: string;
  api_access_suspended: boolean;
  /** Read-only: computed self-service eligibility (approved + verified +
   * a pricing rule resolves + not suspended) — there's no per-merchant
   * "enable production" switch anymore; production keys are self-service. */
  production_api_eligible: boolean;
  available_balance: string;
  created_at: string;
}

export interface MerchantUserRow {
  user_id: string;
  merchant_id: string;
  merchant_name: string;
  merchant_code: string | null;
  full_name: string | null;
  email: string | null;
  role: UserRole;
  status: "invited" | "active" | "suspended";
  created_at: string;
}

export interface AdminCollectionRow {
  collection_id: string;
  merchant_id: string;
  merchant_name: string;
  merchant_code: string | null;
  source: string | null;
  method: string;
  amount: string;
  currency: string;
  fee_amount: string | null;
  net_amount: string | null;
  phone: string | null;
  merchant_reference: string | null;
  provider_reference: string | null;
  api_key_id: string | null;
  payment_link_id: string | null;
  invoice_id: string | null;
  status: "successful" | "pending" | "processing" | "failed" | "reversed" | "pending_review";
  created_at: string;
  // Selcom Checkout reconciliation detail — see
  // docs/selcom-checkout-collections.md.
  order_id: string | null;
  provider_transid: string | null;
  channel: string | null;
  provider_payment_status: string | null;
  failure_reason: string | null;
}

export interface AdminPaymentLinkRow {
  link_id: string;
  merchant_id: string;
  merchant_name: string;
  merchant_code: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  amount: string;
  currency: string;
  /** Mirrors PaymentLinkStatus (@infinity/shared) — the Stitch mockup's
   * "Deactivated" label maps to CANCELLED, the real enum's terminal-cancel
   * state. */
  status: "ACTIVE" | "PAID" | "EXPIRED" | "CANCELLED";
  expires_at: string | null;
  created_at: string;
  /** Which Merchant Portal surface (or external API) created this link —
   * "pay_by_link" for a customer submission through a merchant's
   * permanent Pay by Link page, "payment_link" for the ordinary
   * merchant-generated one, "request_collection" for the Request
   * Collection form (same underlying row/endpoint), "api" for
   * POST /v1/collections (external developer API). */
  created_via: "payment_link" | "request_collection" | "api" | "pay_by_link";
}

export interface AdminInvoiceRow {
  invoice_id: string;
  invoice_number: string;
  merchant_id: string;
  merchant_name: string;
  merchant_code: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  customer_email: string | null;
  total_amount: string;
  due_date: string;
  status: "DRAFT" | "SENT" | "PAID" | "PARTIALLY_PAID" | "OVERDUE" | "CANCELLED";
  created_at: string;
  /** Set only once the payment-request email actually goes out. */
  sent_at: string | null;
  /** Most recent email_deliveries row for this invoice, if any. */
  email_status: "sent" | "failed" | null;
  email_provider_message_id: string | null;
  email_failed_reason: string | null;
}

export interface AdminCustomerRow {
  id: string;
  name: string;
  phone: string;
  merchants: string[];
  total_spent: string;
  last_transaction_at: string;
  status: "active" | "inactive";
}

export interface AdminWithdrawalRow {
  withdrawal_id: string;
  merchant_id: string;
  merchant_name: string;
  merchant_code: string | null;
  method: "SELCOM_PESA" | "MOBILE_MONEY" | "BANK_ACCOUNT";
  amount: string;
  currency: string;
  destination: string;
  destination_code: string | null;
  destination_identifier: string;
  status:
    | "PENDING_ADMIN_APPROVAL"
    | "INFO_REQUESTED"
    | "PROCESSING"
    | "SUCCESS"
    | "FAILED"
    | "REJECTED"
    | "NEEDS_ADMIN_ATTENTION"
    | "NEEDS_RECONCILIATION"
    | "BLOCKED_IP_WHITELIST"
    | "REVERSED";
  requires_approval: boolean;
  /** True if this withdrawal skipped Super Admin approval via the
   * automated eligibility check. auto_decision_reason explains why,
   * whichever way the check went. */
  auto_approved: boolean;
  auto_decision_reason: string | null;
  provider_reference: string | null;
  total_charges: string;
  total_reserved_amount: string | null;
  recipient_net_amount: string | null;
  /** The merchant's current wallet balance (not a request-time snapshot) — see
   * apps/api/app/schemas/admin.py::AdminWithdrawalResponse.available_balance. */
  available_balance: string;
  pricing_rule_id: string | null;
  rejection_reason: string | null;
  admin_status_reason: string | null;
  created_at: string;
  // Delivery status of the two emails a withdrawal can trigger — see
  // app/services/email.py::send_withdrawal_request_notification_email /
  // send_withdrawal_success_email. null means that email hasn't been
  // attempted yet.
  request_email_status: "sent" | "failed" | null;
  success_email_status: "sent" | "failed" | null;
}

export interface PricingRuleRow {
  id: string;
  merchant_id: string | null;
  channel: "SELCOM_PESA" | "MOBILE_MONEY" | "BANK_ACCOUNT" | null;
  destination_code: string | null;
  percentage_fee: string;
  flat_fee: string;
  minimum_fee: string | null;
  maximum_fee: string | null;
  processor_fee_flat: string;
  processor_fee_pass_through: boolean;
  effective_from: string;
  effective_to: string | null;
  is_active: boolean;
  label: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

/** merchant_collection_pricing_rules — the collection-side sibling of
 * PricingRuleRow above (which, per the 2026-08-31 "fees apply to
 * collections only" policy, no longer charges anything — see
 * docs/collection-and-withdrawal-pricing.md). `channel` mirrors
 * CollectionMethod (how the customer paid), not DisbursementMethod. */
export interface CollectionPricingRuleRow {
  id: string;
  merchant_id: string | null;
  channel: "USSD_PUSH" | "STK_PUSH" | "SELCOM_PESA_PUSH" | "DYNAMIC_QR" | "HOSTED_CHECKOUT" | null;
  percentage_fee: string;
  flat_fee: string;
  minimum_fee: string | null;
  maximum_fee: string | null;
  effective_from: string;
  effective_to: string | null;
  is_active: boolean;
  label: string | null;
  notes: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

/** GET /v1/admin/customers — derived from real collections (grouped by
 * merchant + customer phone), not read from a table; see the backend's
 * own admin_customers.py docstring for why. Distinct from the older,
 * still-mock AdminCustomerRow below (lib/admin/api.ts / /admin/customers). */
export interface AdminCustomerPlatformRow {
  id: string;
  merchant_id: string;
  merchant_name: string;
  merchant_code: string | null;
  full_name: string | null;
  phone: string;
  currency: string;
  total_spent: string;
  transaction_count: number;
  first_seen_at: string | null;
  last_transaction_at: string | null;
}

export interface AdminApiKeyRow {
  id: string;
  name: string;
  environment: string;
  key_prefix: string;
  key_last4: string | null;
  scopes: string[];
  status: string;
  ip_whitelist_enabled: boolean;
  last_used_at: string | null;
  last_used_ip: string | null;
  revoked_at: string | null;
  created_at: string;
  updated_at: string;
}

/** A merchant's permanent public "Pay by Link" page, as seen by Super
 * Admin — same shape as apps/web's own PayByLink (lib/portal/types.ts),
 * duplicated here rather than shared since lib/admin and lib/portal are
 * deliberately independent data-access boundaries (see this file's own
 * module docstring). */
export interface AdminPayByLinkRow {
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

/** One email_deliveries row, narrowed to email_type =
 * 'merchant_collection_notification' — Super Admin's per-recipient
 * delivery history on the Notification Details card. */
export interface NotificationDeliveryLogRow {
  id: string;
  recipient_email: string;
  status: "sent" | "failed" | "skipped";
  provider_message_id: string | null;
  error_message: string | null;
  related_resource_id: string | null;
  created_at: string;
}

/** GET/PATCH /v1/admin/merchants/{id}/notification-settings — Super
 * Admin's Notification Details view for one merchant: the same settings
 * shape as apps/web's own NotificationSettings (lib/portal/types.ts),
 * plus the delivery summary a Super Admin needs to spot a merchant whose
 * notification email is silently failing. */
export interface AdminNotificationSettingsRow {
  id: string;
  merchant_id: string;
  merchant_name: string;
  merchant_code: string | null;
  primary_notification_email: string | null;
  secondary_notification_email: string | null;
  collection_notifications_enabled: boolean;
  last_notification_sent_at: string | null;
  last_notification_status: "sent" | "failed" | "skipped" | null;
  failed_notification_count: number;
  recent_deliveries: NotificationDeliveryLogRow[];
  created_at: string;
  updated_at: string;
  updated_by: string | null;
}

/** One row of GET /v1/admin/pay-by-link — the platform-wide Pay by Link
 * Monitoring list. Distinct from AdminPayByLinkRow above (a single
 * merchant's own page, shown on their detail page, no merchant_name/code
 * since the caller already has that context). */
export interface AdminPayByLinkListRow {
  pay_by_link_id: string;
  merchant_id: string;
  merchant_name: string;
  merchant_code: string | null;
  slug: string;
  display_name: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface AdminIpAllowlistRow {
  id: string;
  merchant_id: string;
  merchant_name: string;
  merchant_code: string | null;
  api_key_id: string | null;
  key_prefix: string | null;
  environment: "sandbox" | "live";
  label: string;
  ip_address_or_cidr: string;
  status: "pending" | "active" | "rejected";
  notes: string | null;
  created_by: string | null;
  approved_by: string | null;
  created_at: string;
  updated_at: string;
}

/** Platform-wide view (GET /v1/admin/api-keys) — same shape as
 * AdminApiKeyRow plus which merchant owns the key; no updated_at
 * (the endpoint doesn't return it). */
export interface AdminApiKeyPlatformRow {
  id: string;
  merchant_id: string;
  merchant_name: string;
  merchant_code: string | null;
  name: string;
  environment: string;
  key_prefix: string;
  key_last4: string | null;
  scopes: string[];
  status: string;
  ip_whitelist_enabled: boolean;
  last_used_at: string | null;
  last_used_ip: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface AdminTransactionRow {
  transaction_id: string;
  merchant_id: string;
  merchant_name: string;
  merchant_code: string | null;
  type: "collection" | "disbursement" | "fee" | "refund" | "reversal" | "adjustment";
  reference: string;
  provider_reference: string | null;
  method: string;
  gross_amount: string;
  fee_amount: string;
  net_amount: string;
  currency: string;
  status: "successful" | "pending" | "processing" | "failed" | "reversed" | "cancelled";
  /** Merchant-wallet balance snapshot around this transaction's most recent
   * ledger posting. Null for rows created before this was captured, or with
   * no wallet-affecting leg — render as "Not available", never computed. */
  balance_before: string | null;
  balance_after: string | null;
  direction: "debit" | "credit" | null;
  created_at: string;
}

export interface PlatformApiKeyRow {
  id: string;
  merchant_name: string;
  key_masked: string;
  environment: "Live" | "Sandbox";
  last_used_at: string;
  status: "Active" | "Revoked";
}

/** Inbound provider callback log (selcom_webhook_events) — not the outbound
 * merchant webhook deliveries table, which already has its own
 * merchant-scoped view (see lib/portal/types.ts's WebhookDelivery). */
export interface AdminWebhookEventRow {
  webhook_event_id: string;
  provider: string;
  event_type: string;
  reference: string;
  status: "received" | "processed" | "failed";
  processed_at: string | null;
  created_at: string;
  processing_error: string | null;
}

export interface FailedCallbackRow {
  id: string;
  provider: string;
  event_type: string;
  reference: string;
  received_at: string;
  error: string;
}

export interface UnmatchedTransactionRow {
  id: string;
  reference: string;
  provider: string;
  amount: string;
  received_at: string;
}

export interface DuplicateReferenceRow {
  id: string;
  reference: string;
  occurrences: number;
  first_seen: string;
  last_seen: string;
}

export interface ProviderCallbackLogRow {
  id: string;
  timestamp: string;
  provider: string;
  event: string;
  reference: string;
  http_status: number;
  match_status: "Matched" | "Failed" | "Unmatched" | "Duplicate";
}

export interface SettlementAccountRow {
  id: string;
  provider: string;
  account_reference: string;
  balance: string;
  last_settled_at: string;
  status: "Active" | "Under Review";
}

export interface KycReviewRow {
  id: string;
  merchant_name: string;
  document_type: string;
  submitted_at: string;
}

export interface ComplianceFlagRow {
  id: string;
  merchant_name: string;
  reason: string;
  flagged_at: string;
  risk_level: "High" | "Medium" | "Low";
}

export interface ProviderHealth {
  id: string;
  name: string;
  status: "operational" | "degraded" | "down";
  uptime_month: string;
  avg_response_ms: number | null;
}

export interface IncidentRow {
  id: string;
  provider: string;
  incident: string;
  start_time: string;
  duration: string;
  status: "Ongoing" | "Resolved";
}

export interface AuditLogRow {
  audit_id: string;
  actor: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  metadata: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}

/** A "contact us" submission from the public marketing site (POST
 * /v1/public/inquiries) — read-only here, the CEO is notified by email
 * as each one arrives (see docs/email-delivery.md). */
export interface AdminInquiryRow {
  id: string;
  full_name: string;
  business_name: string | null;
  email: string;
  phone: string | null;
  message: string;
  source: string;
  created_at: string;
}

export interface SupportTicketRow {
  id: string;
  ticket_number: string;
  merchant_name: string;
  subject: string;
  priority: "Urgent" | "High" | "Medium" | "Low";
  status: "Open" | "Awaiting Merchant" | "Resolved" | "Closed";
  updated_at: string;
}

// --- Risk monitoring / document requests / disputes -------------------------

export type FraudRiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type FraudAlertStatus = "OPEN" | "UNDER_REVIEW" | "DOCUMENTS_REQUESTED" | "CLEARED" | "ESCALATED" | "CLOSED";

export interface AdminFraudAlertRow {
  alert_id: string;
  merchant_id: string;
  merchant_name: string | null;
  merchant_code: string | null;
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

export interface AdminDocumentRequestFile {
  id: string;
  document_label: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  signed_url: string | null;
  created_at: string;
}

export interface AdminDocumentRequestRow {
  request_id: string;
  merchant_id: string;
  merchant_name: string | null;
  merchant_code: string | null;
  transaction_id: string | null;
  alert_id: string | null;
  requested_documents: string[];
  reason: string;
  status: DocumentRequestStatus;
  due_date: string | null;
  created_at: string;
  updated_at: string;
  files: AdminDocumentRequestFile[];
}

export type DisputeStatus =
  | "SUBMITTED"
  | "MERCHANT_NOTIFIED"
  | "UNDER_REVIEW"
  | "REFUND_REQUESTED"
  | "REFUNDED"
  | "REJECTED"
  | "CLOSED";

export interface AdminDisputeRow {
  dispute_id: string;
  merchant_id: string | null;
  merchant_name: string | null;
  merchant_code: string | null;
  transaction_id: string | null;
  customer_name: string;
  customer_phone: string;
  customer_email: string | null;
  transaction_reference: string | null;
  amount: string | null;
  reason_category: string;
  description: string;
  status: DisputeStatus;
  evidence_files: Array<{ file_path: string; original_filename: string }>;
  created_at: string;
  updated_at: string;
}

export type RefundStatus = "REQUESTED" | "APPROVED" | "PROCESSING" | "SUCCESS" | "FAILED" | "CANCELLED";

export interface AdminRefundRow {
  id: string;
  dispute_id: string;
  transaction_id: string;
  merchant_id: string;
  amount: string;
  currency: string;
  status: RefundStatus;
  requested_by: "merchant" | "admin";
  provider_reference: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminNotificationRow {
  id: string;
  notification_type: string;
  title: string;
  body: string;
  related_resource_type: string | null;
  related_resource_id: string | null;
  is_read: boolean;
  created_at: string;
}

export interface AdminTeamMember {
  id: string;
  name: string;
  email: string;
  role: "Super Admin" | "Operations Admin" | "Support Admin";
  status: "active";
}
