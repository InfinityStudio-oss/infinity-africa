import Link from "next/link";

import { AdminKpiCard } from "@/components/admin/kpi-card";
import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { getAdminOverview, listAdminAuditLogs } from "@/lib/admin/live-api";

export const metadata = {
  title: "Dashboard | InfinityPay Super Admin",
};

const MODULES = [
  { href: "/super-admin/merchants", icon: "storefront", title: "Business Management", description: "Onboard, verify & manage businesses" },
  { href: "/super-admin/payment-links", icon: "link", title: "Payment Links Monitoring", description: "Platform-wide link activity" },
  { href: "/super-admin/invoices", icon: "receipt", title: "Invoice Management", description: "Track invoices across businesses" },
  { href: "/super-admin/withdrawals", icon: "receipt_long", title: "Withdrawal Monitoring", description: "Approve & track payouts" },
  { href: "/admin/reconciliation-center", icon: "account_balance", title: "Reconciliation Center", description: "Callback logs & unmatched txns" },
  { href: "/admin/provider-status", icon: "dns", title: "Provider Status", description: "Selcom, M-Pesa, bank uptime" },
];

export default async function SuperAdminCommandCenterPage() {
  const [overview, recentActivity] = await Promise.all([getAdminOverview(), listAdminAuditLogs()]);

  return (
    <div className="space-y-8">
      <div className="flex flex-col md:flex-row justify-between md:items-end gap-4">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-on-surface mb-1">Dashboard</h2>
          <p className="text-base text-on-surface-variant">Overview of platform operations and health.</p>
        </div>
      </div>

      {!overview ? (
        <Card>
          <p className="text-sm text-on-surface-variant">
            Couldn&apos;t reach InfinityPay to load platform metrics. Check that apps/api is running and reachable.
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <AdminKpiCard variant="brand" icon="store" label="Total Businesses" value={overview.total_merchants.toLocaleString()} />
          <AdminKpiCard variant="brand" icon="account_balance_wallet" label="Collections Today" value={formatCurrency(overview.collections_today, "TZS")} />
          <AdminKpiCard variant="brand" icon="send_money" label="Withdrawals Today" value={formatCurrency(overview.withdrawals_today, "TZS")} />
          <AdminKpiCard variant="brand" icon="link" label="Active Payment Links" value={overview.active_payment_links.toLocaleString()} />
          <AdminKpiCard variant="brand" icon="receipt" label="Paid Invoices Today" value={overview.paid_invoices_today.toLocaleString()} />
          <AdminKpiCard variant="brand" icon="payments" label="Value Outstanding" value={formatCurrency(overview.outstanding_invoice_value, "TZS")} />
          <AdminKpiCard variant="brand" icon="warning" label="Failed Transactions" value={overview.failed_transactions.toLocaleString()} />
          <AdminKpiCard variant="brand" icon="monetization_on" label="Platform Revenue" value={formatCurrency(overview.platform_revenue, "TZS")} caption="Month to date" />
          <AdminKpiCard variant="brand" icon="assignment_ind" label="Pending Onboarding" value={overview.pending_onboarding_requests.toLocaleString()} />
          <AdminKpiCard variant="brand" icon="hourglass_empty" label="Pending Withdrawals" value={overview.pending_withdrawals.toLocaleString()} />
        </div>
      )}

      <div>
        <h3 className="text-2xl font-semibold text-on-background mb-4">Operational Modules</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {MODULES.map((module) => (
            <Link
              key={module.href}
              href={module.href}
              className="bg-surface rounded-xl border border-surface-container-highest shadow-ambient p-5 flex items-center gap-4 hover:border-primary/40 transition-colors"
            >
              <div className="w-11 h-11 rounded-lg bg-primary-container/10 flex items-center justify-center text-primary shrink-0">
                <Icon name={module.icon} />
              </div>
              <div>
                <p className="font-semibold text-sm text-on-background">{module.title}</p>
                <p className="text-xs text-on-surface-variant mt-0.5">{module.description}</p>
              </div>
            </Link>
          ))}
        </div>
      </div>

      <Card padded={false}>
        <div className="flex items-center justify-between p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">Recent Platform Activity</h3>
          <Link href="/super-admin/audit-logs" className="text-primary text-sm font-semibold hover:underline">
            View all
          </Link>
        </div>
        {recentActivity.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">No platform activity recorded yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[760px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Actor</th>
                  <th className={thClass}>Action</th>
                  <th className={thClass}>Entity</th>
                  <th className={thClass}>When</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {recentActivity.slice(0, 5).map((log) => (
                  <tr key={log.audit_id} className="border-t border-surface-container-highest">
                    <td className={`${tdClass} text-on-background font-medium`}>{log.actor ?? "System"}</td>
                    <td className={`${tdClass} text-on-surface-variant`}>{log.action}</td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{log.entity_type}</td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(log.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
