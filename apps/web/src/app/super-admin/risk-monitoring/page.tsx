import { AdminKpiCard } from "@/components/admin/kpi-card";
import { PageHeader } from "@/components/portal/page-header";
import { RiskMonitoringTable } from "@/components/super-admin/risk-monitoring-table";
import { listAdminRiskAlerts } from "@/lib/admin/live-api";

export const metadata = {
  title: "Risk Monitoring | InfinityPay Super Admin",
};

export default async function SuperAdminRiskMonitoringPage() {
  const alerts = await listAdminRiskAlerts();

  const counts = {
    open: alerts.filter((a) => a.status === "OPEN").length,
    underReview: alerts.filter((a) => ["UNDER_REVIEW", "DOCUMENTS_REQUESTED"].includes(a.status)).length,
    critical: alerts.filter((a) => a.risk_level === "CRITICAL" || a.risk_level === "HIGH").length,
    escalated: alerts.filter((a) => a.status === "ESCALATED").length,
  };

  return (
    <div className="space-y-8">
      <PageHeader title="Risk Monitoring" description="Suspicious activity detected across the platform, awaiting review." />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
        <AdminKpiCard variant="brand" icon="gpp_maybe" label="Open Alerts" value={counts.open.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="hourglass_empty" label="Under Review" value={counts.underReview.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="warning" label="High / Critical Risk" value={counts.critical.toLocaleString()} tone={counts.critical > 0 ? "warning" : "default"} />
        <AdminKpiCard variant="brand" icon="priority_high" label="Escalated" value={counts.escalated.toLocaleString()} />
      </div>

      <RiskMonitoringTable rows={alerts} />
    </div>
  );
}
