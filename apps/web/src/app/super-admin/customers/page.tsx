import { AdminKpiCard } from "@/components/admin/kpi-card";
import { PageHeader } from "@/components/portal/page-header";
import { CustomersFilters } from "@/components/super-admin/customers-filters";
import { CustomersTable } from "@/components/super-admin/customers-table";
import { getAdminCustomerSummary, listAdminCustomers, listAdminMerchantOptions } from "@/lib/admin/live-api";

export const metadata = {
  title: "Customers | InfinityPay Super Admin",
};

interface SuperAdminCustomersPageProps {
  searchParams: Promise<{ merchant_id?: string }>;
}

export default async function SuperAdminCustomersPage({ searchParams }: SuperAdminCustomersPageProps) {
  const { merchant_id: merchantId } = await searchParams;

  // The summary is its own request because the list is paginated. Counting
  // the rows this page received is what made the cards read "100" when
  // there were 940 customers, 840 of them never sent to the browser.
  const [customers, merchants, summary] = await Promise.all([
    listAdminCustomers({ merchantId }),
    listAdminMerchantOptions(),
    getAdminCustomerSummary({ merchantId }),
  ]);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Customers"
        description="Everyone who has paid an InfinityPay business, across the whole platform."
      />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        <AdminKpiCard variant="brand" icon="group" label="Total Customers" value={summary ? summary.total_customers.toLocaleString() : "—"} />
        <AdminKpiCard variant="brand" icon="person_add" label="New This Month" value={summary ? summary.new_this_month.toLocaleString() : "—"} />
        <AdminKpiCard variant="brand" icon="repeat" label="Repeat Customers" value={summary ? summary.repeat_customers.toLocaleString() : "—"} />
      </div>

      <CustomersFilters merchants={merchants} selectedMerchantId={merchantId} />

      <CustomersTable rows={customers} />

      {/* The list is one page of 100. Saying so beats a table that looks
          complete and is not - there is no pagination control yet. */}
      {summary && summary.total_customers > customers.length ? (
        <p className="text-sm text-on-surface-variant">
          Showing the {customers.length.toLocaleString()} most recently active of{" "}
          {summary.total_customers.toLocaleString()} customers. Filter by business to narrow the list.
        </p>
      ) : null}
    </div>
  );
}
