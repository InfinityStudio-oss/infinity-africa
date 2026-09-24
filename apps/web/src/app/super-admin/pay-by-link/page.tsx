import { AdminKpiCard } from "@/components/admin/kpi-card";
import { Card, tdClass, thClass } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import { listAdminPayByLinks } from "@/lib/admin/live-api";

export const metadata = {
  title: "Pay by Link | InfinityPay Super Admin",
};

export default async function SuperAdminPayByLinkPage() {
  const pages = await listAdminPayByLinks();
  const active = pages.filter((p) => p.is_active).length;
  const disabled = pages.length - active;
  const everUsed = pages.filter((p) => p.last_used_at).length;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Pay by Link Monitoring"
        description="Platform-wide view of every permanent Pay by Link page created by businesses — separate from generated Payment Links."
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
        <AdminKpiCard variant="brand" icon="storefront" label="Total Pages" value={pages.length.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="bolt" label="Active" value={active.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="block" label="Disabled" value={disabled.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="check_circle" label="Ever Used" value={everUsed.toLocaleString()} />
      </div>

      <Card>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <input
            className="sm:col-span-2 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
            placeholder="Slug or business"
          />
          <select className="px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm">
            <option>All Statuses</option>
            <option>Active</option>
            <option>Disabled</option>
          </select>
        </div>
      </Card>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">All Pay by Link Pages</h3>
        </div>
        {pages.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">No merchant has created a Pay by Link page yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[860px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Slug</th>
                  <th className={thClass}>Merchant</th>
                  <th className={thClass}>Display Name</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass}>Created</th>
                  <th className={thClass}>Last Used</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {pages.map((page) => (
                  <tr
                    key={page.pay_by_link_id}
                    className={`border-t border-surface-container-highest ${page.is_active ? "" : "opacity-60"}`}
                  >
                    <td className={`${tdClass} font-mono text-on-background`}>/{page.slug}</td>
                    <td className={tdClass}>
                      <div>{page.merchant_name}</div>
                      {page.merchant_code && (
                        <div className="font-mono text-xs text-on-surface-variant">{page.merchant_code}</div>
                      )}
                    </td>
                    <td className={tdClass}>{page.display_name}</td>
                    <td className={tdClass}>
                      <StatusBadge
                        label={page.is_active ? "Active" : "Disabled"}
                        tone={page.is_active ? "positive" : "neutral"}
                      />
                    </td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(page.created_at)}</td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>
                      {page.last_used_at ? formatDateTime(page.last_used_at) : "Never"}
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
