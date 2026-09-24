import { AdminKpiCard } from "@/components/admin/kpi-card";
import { PageHeader } from "@/components/portal/page-header";
import { DisputesTable } from "@/components/super-admin/disputes-table";
import { listAdminDisputes } from "@/lib/admin/live-api";

export const metadata = {
  title: "Disputes | InfinityPay Super Admin",
};

export default async function SuperAdminDisputesPage() {
  const disputes = await listAdminDisputes();

  const counts = {
    total: disputes.length,
    underReview: disputes.filter((d) => d.status === "UNDER_REVIEW").length,
    refundRequested: disputes.filter((d) => d.status === "REFUND_REQUESTED").length,
    refunded: disputes.filter((d) => d.status === "REFUNDED").length,
  };

  return (
    <div className="space-y-8">
      <PageHeader title="Disputes" description="Customer-reported chargebacks and product/service issues across all businesses." />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
        <AdminKpiCard variant="brand" icon="gavel" label="Total Disputes" value={counts.total.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="hourglass_empty" label="Under Review" value={counts.underReview.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="request_quote" label="Refund Requested" value={counts.refundRequested.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="check_circle" label="Refunded" value={counts.refunded.toLocaleString()} />
      </div>

      <DisputesTable rows={disputes} />
    </div>
  );
}
