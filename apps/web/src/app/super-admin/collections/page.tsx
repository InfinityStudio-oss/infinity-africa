import { AdminKpiCard } from "@/components/admin/kpi-card";
import { PageHeader } from "@/components/portal/page-header";
import { CollectionsFilters } from "@/components/super-admin/collections-filters";
import { CollectionsTable } from "@/components/super-admin/collections-table";
import { formatCurrency } from "@/lib/format";
import { getAdminOverview, listAdminCollections, listAdminMerchants } from "@/lib/admin/live-api";

export const metadata = {
  title: "Collections | InfinityPay Super Admin",
};

interface SuperAdminCollectionsPageProps {
  searchParams: Promise<{
    merchant_id?: string;
    source?: string;
    method?: string;
    status?: string;
    date_from?: string;
    date_to?: string;
  }>;
}

export default async function SuperAdminCollectionsPage({ searchParams }: SuperAdminCollectionsPageProps) {
  const filters = await searchParams;

  const [collections, overview, merchants] = await Promise.all([
    listAdminCollections({
      merchantId: filters.merchant_id,
      source: filters.source,
      method: filters.method,
      status: filters.status,
      dateFrom: filters.date_from,
      dateTo: filters.date_to,
    }),
    getAdminOverview(),
    listAdminMerchants(),
  ]);
  const successful = collections.filter((c) => c.status === "successful").length;
  const pending = collections.filter((c) => c.status === "pending" || c.status === "processing").length;
  const failed = collections.filter((c) => c.status === "failed").length;

  return (
    <div className="space-y-8">
      <PageHeader title="Collections" description="Platform-wide mobile money collections across every business." />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
        <AdminKpiCard variant="brand" icon="payments" label="Collections Today" value={overview ? formatCurrency(overview.collections_today, "TZS") : "—"} />
        <AdminKpiCard variant="brand" icon="check_circle" label="Successful" value={successful.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="hourglass_empty" label="Pending" value={pending.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="error" label="Failed" value={failed.toLocaleString()} />
      </div>

      <CollectionsFilters
        merchants={merchants}
        initial={{
          merchantId: filters.merchant_id,
          source: filters.source,
          method: filters.method,
          status: filters.status,
          dateFrom: filters.date_from,
          dateTo: filters.date_to,
        }}
      />

      <CollectionsTable collections={collections} />
    </div>
  );
}
