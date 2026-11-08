import { AdminKpiCard } from "@/components/admin/kpi-card";
import { PageHeader } from "@/components/portal/page-header";
import { CollectionsFilters } from "@/components/super-admin/collections-filters";
import { CollectionsTable } from "@/components/super-admin/collections-table";
import { formatCurrency } from "@/lib/format";
import { getAdminOverview, listAdminCollectionsResult, listAdminMerchantOptions } from "@/lib/admin/live-api";

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

  const [collectionsResult, overview, merchants] = await Promise.all([
    listAdminCollectionsResult({
      merchantId: filters.merchant_id,
      source: filters.source,
      method: filters.method,
      status: filters.status,
      dateFrom: filters.date_from,
      dateTo: filters.date_to,
    }),
    getAdminOverview(),
    listAdminMerchantOptions(),
  ]);
  const { rows: collections, failure: loadFailure } = collectionsResult;
  const loadFailed = loadFailure !== null;
  const successful = collections.filter((c) => c.status === "successful").length;
  const pending = collections.filter((c) => c.status === "pending" || c.status === "processing").length;
  const failed = collections.filter((c) => c.status === "failed").length;
  // A failed load is not a page of zeroes. Showing "0" next to a
  // populated Collections Today figure is how this page spent two days
  // insisting nothing had been collected while 80,000 rows sat in the
  // table.
  const tile = (n: number) => (loadFailed ? "—" : n.toLocaleString());

  return (
    <div className="space-y-8">
      <PageHeader title="Collections" description="Platform-wide mobile money collections across every business." />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
        <AdminKpiCard variant="brand" icon="payments" label="Collections Today" value={overview ? formatCurrency(overview.collections_today, "TZS") : "—"} />
        <AdminKpiCard variant="brand" icon="check_circle" label="Successful" value={tile(successful)} />
        <AdminKpiCard variant="brand" icon="hourglass_empty" label="Pending" value={tile(pending)} />
        <AdminKpiCard variant="brand" icon="error" label="Failed" value={tile(failed)} />
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

      <CollectionsTable collections={collections} loadFailure={loadFailure} />
    </div>
  );
}
