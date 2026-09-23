import { UserRole } from "@infinity/shared";

import { AdminKpiCard } from "@/components/admin/kpi-card";
import { PageHeader } from "@/components/portal/page-header";
import { MerchantUsersTable } from "@/components/super-admin/merchant-users-table";
import { listAdminMerchantUsers } from "@/lib/admin/live-api";

export const metadata = {
  title: "Merchant Users | InfinityPay Super Admin",
};

export default async function SuperAdminMerchantUsersPage() {
  const users = await listAdminMerchantUsers();

  const counts = {
    total: users.length,
    admins: users.filter((u) => u.role === UserRole.MERCHANT_ADMIN).length,
    staff: users.filter((u) => u.role === UserRole.MERCHANT_STAFF).length,
    developers: users.filter((u) => u.role === UserRole.DEVELOPER).length,
  };

  return (
    <div className="space-y-8">
      <PageHeader title="Merchant Users" description="View user accounts across every merchant on the InfinityPay platform." />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
        <AdminKpiCard variant="brand" icon="group" label="Total Users" value={counts.total.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="admin_panel_settings" label="Admins" value={counts.admins.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="badge" label="Staff" value={counts.staff.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="terminal" label="Developers" value={counts.developers.toLocaleString()} />
      </div>

      <MerchantUsersTable rows={users} />
    </div>
  );
}
