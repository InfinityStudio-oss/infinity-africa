/**
 * Public, unauthenticated dispute/chargeback reporting — POST
 * /v1/public/disputes/report. No auth token involved at all (unlike
 * lib/portal/api.ts / lib/admin/live-api.ts), so this is a plain
 * client-safe module — used directly from the "use client" form on
 * /report-transaction.
 */

export interface DisputeReportInput {
  customer_name: string;
  customer_phone: string;
  customer_email?: string;
  transaction_reference?: string;
  merchant_name?: string;
  amount?: string;
  payment_date?: string;
  reason_category: string;
  description: string;
  evidence?: File[];
}

export interface DisputeReportResult {
  id: string;
  status: string;
}

interface ApiEnvelope<T> {
  success: boolean;
  data?: T;
  error?: { code: string; message: string };
}

export class DisputeReportError extends Error {
  code?: string;
  constructor(message: string, code?: string) {
    super(message);
    this.code = code;
  }
}

export async function submitDisputeReport(input: DisputeReportInput): Promise<DisputeReportResult> {
  const formData = new FormData();
  formData.append("customer_name", input.customer_name);
  formData.append("customer_phone", input.customer_phone);
  if (input.customer_email) formData.append("customer_email", input.customer_email);
  if (input.transaction_reference) formData.append("transaction_reference", input.transaction_reference);
  if (input.merchant_name) formData.append("merchant_name", input.merchant_name);
  if (input.amount) formData.append("amount", input.amount);
  if (input.payment_date) formData.append("payment_date", input.payment_date);
  formData.append("reason_category", input.reason_category);
  formData.append("description", input.description);
  for (const file of input.evidence ?? []) {
    formData.append("evidence", file);
  }

  let res: Response;
  try {
    res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/public/disputes/report`, {
      method: "POST",
      body: formData,
    });
  } catch {
    throw new DisputeReportError("Couldn't reach InfinityPay. Check your connection and try again.");
  }

  const body: ApiEnvelope<DisputeReportResult> = await res.json();
  if (!res.ok || !body.success || body.data === undefined) {
    throw new DisputeReportError(body.error?.message ?? "Couldn't submit your report. Please try again.", body.error?.code);
  }
  return body.data;
}
