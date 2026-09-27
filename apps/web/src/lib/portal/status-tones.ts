import {
  DISBURSEMENT_STATUS_LABELS,
  DisbursementStatus,
  INVOICE_STATUS_LABELS,
  InvoiceStatus,
  PAYMENT_LINK_STATUS_LABELS,
  PaymentLinkStatus,
} from "@infinity/shared";

import type { BadgeTone } from "@/components/portal/status-badge";
import type { CollectionStatus, TransactionStatus, WebhookEvent } from "./types";

export interface BadgeProps {
  label: string;
  tone: BadgeTone;
  dot?: boolean;
  icon?: string;
  strikethrough?: boolean;
}

export function paymentLinkBadge(status: PaymentLinkStatus): BadgeProps {
  const label = PAYMENT_LINK_STATUS_LABELS[status];
  switch (status) {
    case PaymentLinkStatus.ACTIVE:
      return { label, tone: "positive", dot: true };
    case PaymentLinkStatus.PAID:
      return { label, tone: "positive-solid", icon: "check" };
    case PaymentLinkStatus.EXPIRED:
      return { label, tone: "neutral" };
    case PaymentLinkStatus.CANCELLED:
      return { label, tone: "neutral", strikethrough: true };
  }
}

export function invoiceBadge(status: InvoiceStatus): BadgeProps {
  const label = INVOICE_STATUS_LABELS[status];
  switch (status) {
    case InvoiceStatus.DRAFT:
      return { label, tone: "neutral" };
    case InvoiceStatus.SENT:
      return { label, tone: "info" };
    case InvoiceStatus.PAID:
      return { label, tone: "positive-solid", icon: "check" };
    case InvoiceStatus.PARTIALLY_PAID:
      return { label, tone: "pending" };
    case InvoiceStatus.OVERDUE:
      return { label, tone: "negative" };
    case InvoiceStatus.CANCELLED:
      return { label, tone: "neutral", strikethrough: true };
  }
}

/** Merchant-facing names for the withdrawal statuses whose shared label
 * describes an internal step rather than anything the merchant can act on.
 *
 * The backend statuses are unchanged and DISBURSEMENT_STATUS_LABELS is
 * untouched — Super Admin still reads "Pending Approval", because that is
 * exactly what it is waiting for and who is waiting on it. A merchant has
 * no approval to give and no admin to chase, so for them the honest
 * description is that the request is being processed.
 *
 * Only statuses that leak an internal actor are remapped. "Failed",
 * "Rejected" and "Reversed" are the merchant's business and stay as they
 * are. */
const MERCHANT_DISBURSEMENT_STATUS_LABELS: Partial<Record<DisbursementStatus, string>> = {
  [DisbursementStatus.PENDING_ADMIN_APPROVAL]: "Processing",
  [DisbursementStatus.NEEDS_ADMIN_ATTENTION]: "Processing",
  [DisbursementStatus.NEEDS_RECONCILIATION]: "Processing",
  [DisbursementStatus.BLOCKED_IP_WHITELIST]: "Processing",
};

export function disbursementBadge(status: DisbursementStatus): BadgeProps {
  const label = MERCHANT_DISBURSEMENT_STATUS_LABELS[status] ?? DISBURSEMENT_STATUS_LABELS[status];
  switch (status) {
    case DisbursementStatus.PENDING_ADMIN_APPROVAL:
      return { label, tone: "pending" };
    case DisbursementStatus.INFO_REQUESTED:
      return { label, tone: "pending", icon: "info" };
    case DisbursementStatus.PROCESSING:
      return { label, tone: "pending" };
    case DisbursementStatus.SUCCESS:
      return { label: "Completed", tone: "positive", dot: true };
    case DisbursementStatus.FAILED:
      return { label, tone: "negative" };
    case DisbursementStatus.REJECTED:
      return { label, tone: "negative" };
    case DisbursementStatus.NEEDS_ADMIN_ATTENTION:
      return { label, tone: "negative", icon: "warning" };
    case DisbursementStatus.NEEDS_RECONCILIATION:
      return { label, tone: "negative", icon: "warning" };
    case DisbursementStatus.BLOCKED_IP_WHITELIST:
      return { label, tone: "negative", icon: "warning" };
    case DisbursementStatus.REVERSED:
      return { label, tone: "neutral" };
  }
}

export function collectionBadge(status: CollectionStatus): BadgeProps {
  switch (status) {
    case "processing":
      return { label: "Awaiting confirmation", tone: "pending" };
    case "successful":
      return { label: "Success", tone: "positive", dot: true };
    case "failed":
      return { label: "Failed", tone: "negative" };
    case "reversed":
      return { label: "Reversed", tone: "negative", icon: "warning" };
    case "pending_review":
      return { label: "Pending review", tone: "pending", icon: "info" };
  }
}

export function transactionStatusBadge(status: TransactionStatus): BadgeProps {
  switch (status) {
    case "successful":
      return { label: "Success", tone: "positive-solid", icon: "check" };
    case "pending":
    case "processing":
      return { label: "Pending", tone: "pending" };
    case "failed":
      return { label: "Failed", tone: "negative" };
    case "reversed":
      return { label: "Reversed", tone: "neutral" };
    case "cancelled":
      return { label: "Cancelled", tone: "neutral", strikethrough: true };
  }
}

export function webhookDeliveryBadge(status: WebhookEvent["status"]): BadgeProps {
  switch (status) {
    case "delivered":
      return { label: "Delivered", tone: "positive-solid", icon: "check" };
    case "failed":
      return { label: "Failed", tone: "negative" };
    case "retrying":
      return { label: "Retrying", tone: "pending" };
    case "pending":
      return { label: "Pending", tone: "pending" };
  }
}

export function transactionTypeBadge(type: string): BadgeProps {
  switch (type) {
    case "collection":
      return { label: "Collection", tone: "positive", dot: true };
    case "disbursement":
      return { label: "Withdrawal", tone: "info" };
    default:
      return { label: type.charAt(0).toUpperCase() + type.slice(1), tone: "neutral" };
  }
}
