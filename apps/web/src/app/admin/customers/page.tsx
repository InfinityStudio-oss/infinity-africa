import { AdminKpiCard } from "@/components/admin/kpi-card";
import { Card, tdClass, thClass } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { listAdminCustomers } from "@/lib/admin/api";

export const metadata = {
  title: "Customers | InfinityPay Super Admin",
};

export default async function AdminCustomersPage() {
  const customers = await listAdminCustomers();

  return (
    <div className="space-y-8">
      <PageHeader title="Customers" description="Everyone who has paid an InfinityPay merchant, across the whole platform." />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        <AdminKpiCard icon="group" label="Total Customers" value="18,204" />
        <AdminKpiCard icon="person_add" label="New This Month" value="612" />
        <AdminKpiCard icon="repeat" label="Repeat Customers" value="41%" />
      </div>

      <Card>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
          <input className="sm:col-span-2 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm" placeholder="Search by name or phone..." />
          <select className="sm:col-span-2 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm">
            <option>All Merchants</option>
            <option>Juma Traders Ltd</option>
            <option>Amani Store</option>
            <option>Neema Salon</option>
            <option>Baraka Textiles</option>
            <option>Kilimanjaro Cafe</option>
            <option>Grace Mwakalinga Designs</option>
          </select>
        </div>
      </Card>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">All Customers</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[820px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Customer</th>
                <th className={thClass}>Phone</th>
                <th className={thClass}>Merchant(s) Transacted With</th>
                <th className={thClass}>Total Spent</th>
                <th className={thClass}>Last Transaction</th>
                <th className={thClass}>Status</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {customers.map((customer) => (
                <tr key={customer.id} className="border-t border-surface-container-highest">
                  <td className={tdClass}>
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-primary-container/15 text-primary flex items-center justify-center font-bold text-xs shrink-0">
                        {customer.name.charAt(0)}
                      </div>
                      <span className="font-medium text-on-background">{customer.name}</span>
                    </div>
                  </td>
                  <td className={`${tdClass} text-on-surface-variant`}>{customer.phone}</td>
                  <td className={`${tdClass} text-on-surface-variant text-xs`}>{customer.merchants.join(", ")}</td>
                  <td className={`${tdClass} font-semibold text-on-background`}>{formatCurrency(customer.total_spent, "TZS")}</td>
                  <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(customer.last_transaction_at)}</td>
                  <td className={tdClass}>
                    {customer.status === "active" ? (
                      <StatusBadge label="Active" tone="positive" dot />
                    ) : (
                      <StatusBadge label="Inactive" tone="neutral" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
