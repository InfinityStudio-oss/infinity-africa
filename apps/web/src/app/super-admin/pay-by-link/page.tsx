import { AdminKpiCard } from "@/components/admin/kpi-card";
import { Card, tdClass, thClass } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import { PayByLinkFilters } from "@/components/super-admin/pay-by-link-filters";
import { listAdminPayByLinks } from "@/lib/admin/live-api";

export const metadata = {
  title: "Pay by Link | InfinityPay Super Admin",
};

interface SuperAdminPayByLinkPageProps {
  searchParams: Promise<{ search?: string; state?: string }>;
}

export default async function SuperAdminPayByLinkPage({ searchParams }: SuperAdminPayByLinkPageProps) {
  const filters = await searchParams;
  const anyFilter = Boolean(filters.search || filters.state);
  // "" and "active"/"disabled" are three different things. Undefined
  // means no filter; sending false for "All" would hide every working
  // page on the platform.
  const isActive =
    filters.state === "active" ? true : filters.state === "disabled" ? false : undefined;
  const pages = await listAdminPayByLinks({ search: filters.search, isActive });
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

      <PayByLinkFilters initial={{ search: filters.search, state: filters.state }} />

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">
            {anyFilter ? "Matching Pay by Link Pages" : "All Pay by Link Pages"}
          </h3>
        </div>
        {pages.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">
            {/* Distinguished on purpose: "nobody has created one" is a
              * statement about the platform, and saying it while a
              * filter is hiding 27 pages would be false. */}
            {anyFilter
              ? "No Pay by Link pages match these filters."
              : "No merchant has created a Pay by Link page yet."}
          </p>
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
