import Link from "next/link";

import { Card } from "@/components/portal/card";
import { KpiCard } from "@/components/portal/kpi-card";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency } from "@/lib/format";
import type { MerchantOverview } from "@/lib/portal/api";

const KYC_TONE: Record<string, "positive-solid" | "pending" | "negative" | "neutral"> = {
  verified: "positive-solid",
  pending: "pending",
  rejected: "negative",
  unverified: "neutral",
};

const KYC_LABEL: Record<string, string> = {
  verified: "Verified",
  pending: "Verification Pending",
  rejected: "Verification Rejected",
  unverified: "Not Verified",
};

/** Real-data merchant dashboard, shown once GET /v1/merchant/overview
 * succeeds — see app/dashboard/overview/page.tsx for the fallback to
 * OverviewWelcome when it doesn't (no real merchant row for this user
 * yet). */
export function OverviewDashboard({ overview }: { overview: MerchantOverview }) {
  const currency = overview.merchant.currency;
  const kycStatus = overview.merchant.kyc_status;

  return (
    <div className="space-y-8">
      <PageHeader
        title={`Welcome back, ${overview.merchant.business_name}`}
        description="Here's what's happening with your InfinityPay account."
        action={
          <div className="flex flex-col items-start md:items-end gap-1.5">
            <StatusBadge label={KYC_LABEL[kycStatus] ?? kycStatus} tone={KYC_TONE[kycStatus] ?? "neutral"} dot />
            {overview.merchant.merchant_code && (
              <p className="text-xs text-on-surface-variant">
                ID: <span className="font-mono font-semibold text-on-background">{overview.merchant.merchant_code}</span>
              </p>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <KpiCard icon="account_balance_wallet" label="Available Balance" value={formatCurrency(overview.available_balance, currency)} />
        <KpiCard icon="payments" label="Total Collections" value={formatCurrency(overview.total_collections, currency)} />
        <KpiCard icon="request_quote" label="Total Fees Charged" value={formatCurrency(overview.total_fees_charged, currency)} />
        <KpiCard icon="hourglass_top" label="Pending Transactions" value={String(overview.pending_transactions)} />
        <KpiCard icon="link" label="Active Payment Links" value={String(overview.active_payment_links)} />
        <KpiCard icon="description" label="Unpaid Invoices" value={String(overview.unpaid_invoices)} />
        <KpiCard icon="account_balance" label="Successful Withdrawals" value={String(overview.successful_withdrawals)} />
      </div>

      <Card>
        <h3 className="text-lg font-semibold text-on-surface mb-4">Quick Actions</h3>
        <div className="grid sm:grid-cols-3 gap-3">
          <Link
            href="/dashboard/pay-by-link"
            className="flex items-center gap-2 rounded-lg border border-outline-variant px-4 py-3 text-sm text-on-surface hover:bg-surface-container transition-colors"
          >
            Create Pay by Link
          </Link>
          <Link
            href="/dashboard/invoices"
            className="flex items-center gap-2 rounded-lg border border-outline-variant px-4 py-3 text-sm text-on-surface hover:bg-surface-container transition-colors"
          >
            Create Invoice
          </Link>
          <Link
            href="/dashboard/withdrawals"
            className="flex items-center gap-2 rounded-lg border border-outline-variant px-4 py-3 text-sm text-on-surface hover:bg-surface-container transition-colors"
          >
            Request Withdrawal
          </Link>
        </div>
      </Card>
    </div>
  );
}
