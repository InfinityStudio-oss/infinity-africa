import { AdminKpiCard } from "@/components/admin/kpi-card";
import { PageHeader } from "@/components/portal/page-header";
import { CustomersFilters } from "@/components/super-admin/customers-filters";
import { CustomersTable } from "@/components/super-admin/customers-table";
import { listAdminCustomers, listAdminMerchants } from "@/lib/admin/live-api";

export const metadata = {
  title: "Customers | InfinityPay Super Admin",
};

interface SuperAdminCustomersPageProps {
  searchParams: Promise<{ merchant_id?: string }>;
}

export default async function SuperAdminCustomersPage({ searchParams }: SuperAdminCustomersPageProps) {
  const { merchant_id: merchantId } = await searchParams;

  const [customers, merchants] = await Promise.all([
    listAdminCustomers({ merchantId }),
    listAdminMerchants(),
  ]);

  const now = new Date();
  const newThisMonth = customers.filter((c) => {
    if (!c.first_seen_at) return false;
    const seen = new Date(c.first_seen_at);
    return seen.getUTCFullYear() === now.getUTCFullYear() && seen.getUTCMonth() === now.getUTCMonth();
  }).length;
  const repeatCustomers = customers.filter((c) => c.transaction_count > 1).length;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Customers"
        description="Everyone who has paid an InfinityPay merchant, across the whole platform."
      />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        <AdminKpiCard variant="brand" icon="group" label="Total Customers" value={customers.length.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="person_add" label="New This Month" value={newThisMonth.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="repeat" label="Repeat Customers" value={repeatCustomers.toLocaleString()} />
      </div>

      <CustomersFilters merchants={merchants} selectedMerchantId={merchantId} />

      <CustomersTable rows={customers} />
    </div>
  );
}
