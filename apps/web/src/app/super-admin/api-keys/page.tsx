import { AdminKpiCard } from "@/components/admin/kpi-card";
import { PageHeader } from "@/components/portal/page-header";
import { ApiKeysTable } from "@/components/super-admin/api-keys-table";
import { listAdminApiKeys } from "@/lib/admin/live-api";

export const metadata = {
  title: "API Keys | InfinityPay Super Admin",
};

export default async function SuperAdminApiKeysPage() {
  const keys = await listAdminApiKeys();

  const active = keys.filter((k) => k.status === "active").length;
  const live = keys.filter((k) => k.environment === "live" && k.status === "active").length;
  const revoked = keys.filter((k) => k.status === "revoked").length;

  return (
    <div className="space-y-8">
      <PageHeader
        title="API Keys"
        description="Oversee sandbox and live API keys issued to every merchant on the platform."
      />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        <AdminKpiCard variant="brand" icon="vpn_key" label="Total Active Keys" value={active.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="bolt" label="Live Keys" value={live.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="block" label="Revoked" value={revoked.toLocaleString()} />
      </div>

      <ApiKeysTable rows={keys} />
    </div>
  );
}
