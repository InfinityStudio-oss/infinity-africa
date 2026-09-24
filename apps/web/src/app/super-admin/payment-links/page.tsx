import { AdminKpiCard } from "@/components/admin/kpi-card";
import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { listAdminPaymentLinks } from "@/lib/admin/live-api";
import { adminPaymentLinkBadge } from "@/lib/admin/status-tones";

export const metadata = {
  title: "Payment Links | InfinityPay Super Admin",
};

const SOURCE_LABELS: Record<string, string> = {
  payment_link: "Payment Link",
  request_collection: "Request Collection",
  api: "API",
  pay_by_link: "Pay by Link",
};

export default async function SuperAdminPaymentLinksPage() {
  const links = await listAdminPaymentLinks();
  const active = links.filter((l) => l.status === "ACTIVE").length;
  const paid = links.filter((l) => l.status === "PAID").length;
  const expired = links.filter((l) => l.status === "EXPIRED").length;

  return (
    <div className="space-y-8">
      <PageHeader title="Payment Links Monitoring" description="Platform-wide view of every payment link created by businesses." />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
        <AdminKpiCard variant="brand" icon="link" label="Total Links" value={links.length.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="bolt" label="Active" value={active.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="check_circle" label="Paid" value={paid.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="event_busy" label="Expired" value={expired.toLocaleString()} />
      </div>

      <Card>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
          <input className="sm:col-span-2 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm" placeholder="Link ID, business, or customer" />
          <select className="px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm">
            <option>All Statuses</option>
            <option>Active</option>
            <option>Paid</option>
            <option>Expired</option>
            <option>Cancelled</option>
          </select>
          <input className="px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm" type="date" />
        </div>
      </Card>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">All Payment Links</h3>
        </div>
        {links.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">No payment links have been created yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[980px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Link ID</th>
                  <th className={thClass}>Merchant</th>
                  <th className={thClass}>Source</th>
                  <th className={thClass}>Customer</th>
                  <th className={thClass}>Amount</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass}>Expiry</th>
                  <th className={thClass}>Created Date</th>
                  <th className={`${thClass} text-right`}>Actions</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {links.map((link) => (
                  <tr key={link.link_id} className={`border-t border-surface-container-highest ${link.status === "EXPIRED" ? "opacity-60" : ""}`}>
                    <td className={`${tdClass} font-mono text-on-background`}>{link.link_id}</td>
                    <td className={tdClass}>
                      <div>{link.merchant_name}</div>
                      {link.merchant_code && (
                        <div className="font-mono text-xs text-on-surface-variant">{link.merchant_code}</div>
                      )}
                    </td>
                    <td className={`${tdClass} text-xs text-on-surface-variant`}>
                      {SOURCE_LABELS[link.created_via] ?? link.created_via}
                    </td>
                    <td className={tdClass}>{link.customer_name ?? link.customer_phone ?? "—"}</td>
                    <td className={`${tdClass} font-semibold text-on-background`}>{formatCurrency(link.amount, link.currency)}</td>
                    <td className={tdClass}>
                      <StatusBadge {...adminPaymentLinkBadge(link.status)} />
                    </td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{link.expires_at ? formatDateTime(link.expires_at) : "—"}</td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(link.created_at)}</td>
                    <td className={`${tdClass} text-right`}>
                      <button className="p-1.5 text-on-surface-variant hover:text-primary" title="View">
                        <Icon name="visibility" className="text-[18px]" />
                      </button>
                    </td>
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
