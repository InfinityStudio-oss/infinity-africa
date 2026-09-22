import type { BadgeProps } from "@/lib/portal/status-tones";
import type {
  AdminCollectionRow,
  AdminInvoiceRow,
  AdminPaymentLinkRow,
  AdminWebhookEventRow,
  AdminWithdrawalRow,
  ComplianceFlagRow,
  IncidentRow,
  Merchant,
  MerchantUserRow,
  PlatformApiKeyRow,
  ProviderCallbackLogRow,
  SettlementAccountRow,
  SupportTicketRow,
} from "./types";

export function merchantStatusBadge(status: Merchant["account_status"]): BadgeProps {
  switch (status) {
    case "active":
      return { label: "Active", tone: "positive", dot: true };
    case "pending":
      return { label: "Pending Verification", tone: "pending" };
    case "suspended":
      return { label: "Suspended", tone: "negative" };
    case "closed":
      return { label: "Closed", tone: "neutral" };
  }
}

export function merchantUserStatusBadge(status: MerchantUserRow["status"]): BadgeProps {
  switch (status) {
    case "active":
      return { label: "Active", tone: "positive", dot: true };
    case "invited":
      return { label: "Invited", tone: "pending" };
    case "suspended":
      return { label: "Suspended", tone: "negative" };
  }
}

export function adminCollectionBadge(status: AdminCollectionRow["status"]): BadgeProps {
  switch (status) {
    case "successful":
      return { label: "Successful", tone: "positive-solid", icon: "check" };
    case "pending":
    case "processing":
      return { label: "Pending", tone: "pending" };
    case "failed":
      return { label: "Failed", tone: "negative" };
    case "reversed":
      return { label: "Reversed", tone: "negative", icon: "warning" };
    case "pending_review":
      return { label: "Pending review", tone: "pending", icon: "warning" };
  }
}

export function adminPaymentLinkBadge(status: AdminPaymentLinkRow["status"]): BadgeProps {
  switch (status) {
    case "ACTIVE":
      return { label: "Active", tone: "positive", dot: true };
    case "PAID":
      return { label: "Paid", tone: "positive-solid", icon: "check" };
    case "EXPIRED":
      return { label: "Expired", tone: "neutral" };
    case "CANCELLED":
      return { label: "Cancelled", tone: "negative" };
  }
}

export function adminInvoiceBadge(status: AdminInvoiceRow["status"]): BadgeProps {
  switch (status) {
    case "DRAFT":
      return { label: "Draft", tone: "neutral" };
    case "SENT":
      return { label: "Sent", tone: "info" };
    case "PAID":
      return { label: "Paid", tone: "positive-solid", icon: "check" };
    case "PARTIALLY_PAID":
      return { label: "Partially Paid", tone: "pending" };
    case "OVERDUE":
      return { label: "Overdue", tone: "negative" };
    case "CANCELLED":
      return { label: "Cancelled", tone: "neutral", strikethrough: true };
  }
}

/** autoApproved distinguishes an auto-processed withdrawal (skipped Super
 * Admin approval via the automated eligibility check) from an ordinary
 * manually-approved one — same underlying "PROCESSING" status either way,
 * just a different badge label so it's visible at a glance which path a
 * withdrawal took. See AdminWithdrawalRow.auto_approved. */
export function adminWithdrawalBadge(status: AdminWithdrawalRow["status"], autoApproved?: boolean): BadgeProps {
  switch (status) {
    case "PENDING_ADMIN_APPROVAL":
      return { label: "Pending Approval", tone: "pending" };
    case "INFO_REQUESTED":
      return { label: "Information Requested", tone: "pending", icon: "info" };
    case "PROCESSING":
      return autoApproved
        ? { label: "Auto-Processing", tone: "pending", icon: "bolt" }
        : { label: "Processing", tone: "pending" };
    case "SUCCESS":
      return { label: "Successful", tone: "positive-solid", icon: "check" };
    case "FAILED":
      return { label: "Failed", tone: "negative" };
    case "REJECTED":
      return { label: "Rejected", tone: "negative" };
    case "NEEDS_ADMIN_ATTENTION":
      return { label: "Needs Admin Attention", tone: "negative", icon: "warning" };
    case "NEEDS_RECONCILIATION":
      return { label: "Needs Reconciliation", tone: "negative", icon: "warning" };
    case "BLOCKED_IP_WHITELIST":
      return { label: "Blocked (IP Whitelist)", tone: "negative", icon: "warning" };
    case "REVERSED":
      return { label: "Reversed", tone: "neutral" };
  }
}

export function apiKeyEnvironmentBadge(environment: PlatformApiKeyRow["environment"]): BadgeProps {
  return environment === "Live"
    ? { label: "Live", tone: "positive", dot: true }
    : { label: "Sandbox", tone: "pending" };
}

export function apiKeyStatusBadge(status: PlatformApiKeyRow["status"]): BadgeProps {
  return status === "Active" ? { label: "Active", tone: "positive", dot: true } : { label: "Revoked", tone: "negative" };
}

export function adminWebhookEventBadge(status: AdminWebhookEventRow["status"]): BadgeProps {
  switch (status) {
    case "processed":
      return { label: "Processed", tone: "positive-solid", icon: "check" };
    case "received":
      return { label: "Received", tone: "pending" };
    case "failed":
      return { label: "Failed", tone: "negative" };
  }
}

export function callbackMatchStatusBadge(status: ProviderCallbackLogRow["match_status"]): BadgeProps {
  switch (status) {
    case "Matched":
      return { label: "Matched", tone: "positive" };
    case "Failed":
      return { label: "Failed", tone: "negative" };
    case "Unmatched":
    case "Duplicate":
      return { label: status, tone: "pending" };
  }
}

export function settlementStatusBadge(status: SettlementAccountRow["status"]): BadgeProps {
  return status === "Active" ? { label: "Active", tone: "positive", dot: true } : { label: "Under Review", tone: "pending" };
}

export function riskLevelBadge(level: ComplianceFlagRow["risk_level"]): BadgeProps {
  switch (level) {
    case "High":
      return { label: "High", tone: "negative" };
    case "Medium":
      return { label: "Medium", tone: "pending" };
    case "Low":
      return { label: "Low", tone: "neutral" };
  }
}

export function incidentStatusBadge(status: IncidentRow["status"]): BadgeProps {
  return status === "Ongoing" ? { label: "Ongoing", tone: "negative" } : { label: "Resolved", tone: "positive-solid", icon: "check" };
}

export function ticketPriorityBadge(priority: SupportTicketRow["priority"]): BadgeProps {
  switch (priority) {
    case "Urgent":
      return { label: "Urgent", tone: "negative" };
    case "High":
      return { label: "High", tone: "pending" };
    case "Medium":
      return { label: "Medium", tone: "info" };
    case "Low":
      return { label: "Low", tone: "neutral" };
  }
}

export function ticketStatusBadge(status: SupportTicketRow["status"]): BadgeProps {
  switch (status) {
    case "Open":
      return { label: "Open", tone: "positive", dot: true };
    case "Awaiting Merchant":
      return { label: "Awaiting Merchant", tone: "pending" };
    case "Resolved":
      return { label: "Resolved", tone: "positive-solid", icon: "check" };
    case "Closed":
      return { label: "Closed", tone: "neutral" };
  }
}

export function kycReviewBadge(): BadgeProps {
  return { label: "Pending Review", tone: "pending" };
}
