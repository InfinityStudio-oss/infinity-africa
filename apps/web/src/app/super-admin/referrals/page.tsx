import { AdminKpiCard } from "@/components/admin/kpi-card";
import { Card } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { ReferralsTable } from "@/components/super-admin/referrals-table";
import { formatCurrency } from "@/lib/format";
import { getAdminReferralSummary, listAdminReferrals } from "@/lib/admin/live-api";

export const metadata = {
  title: "Referrals | InfinityPay Super Admin",
};

export default async function SuperAdminReferralsPage() {
  // The summary is its own request because the list is paginated.
  // Counting the rows this page received would report a page size as a
  // total, which is the mistake the Customers cards used to make.
  const [referrals, summary] = await Promise.all([listAdminReferrals(), getAdminReferralSummary()]);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Referrals"
        description="Merchants who invited other businesses, and what they have earned. Commission is paid only after a referred business is approved and trades — never for a signup."
      />

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <AdminKpiCard
          variant="brand"
          icon="group_add"
          label="Total Referrals"
          value={(summary?.total_referrals ?? 0).toLocaleString()}
        />
        <AdminKpiCard
          variant="brand"
          icon="hourglass_empty"
          label="Awaiting Review"
          value={(summary?.awaiting_review ?? 0).toLocaleString()}
          caption={formatCurrency(summary?.pending_review_amount ?? "0", "TZS")}
        />
        <AdminKpiCard
          variant="brand"
          icon="task_alt"
          label="Approved, Unpaid"
          value={formatCurrency(summary?.approved_unpaid_amount ?? "0", "TZS")}
        />
        <AdminKpiCard
          // Warning tone so a non-zero number reads as something to look
          // at rather than another statistic.
          tone={summary && summary.fraud_holds > 0 ? "warning" : "default"}
          variant="brand"
          icon="gpp_maybe"
          label="Fraud Holds"
          value={(summary?.fraud_holds ?? 0).toLocaleString()}
        />
      </div>

      <Card padded={false}>
        <ReferralsTable rows={referrals} />
      </Card>

      <p className="text-sm text-on-surface-variant">
        Approving a commission marks it payable; it does not pay it. Pay it through the normal
        withdrawal process, then mark it paid here so the record matches.
      </p>
    </div>
  );
}
