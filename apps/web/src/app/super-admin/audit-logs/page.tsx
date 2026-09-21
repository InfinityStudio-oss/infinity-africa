import { Card, tdClass, thClass } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { formatDateTime } from "@/lib/format";
import { listAdminAuditLogs } from "@/lib/admin/live-api";

export const metadata = {
  title: "Audit Logs | InfinityPay Super Admin",
};

export default async function SuperAdminAuditLogsPage() {
  const logs = await listAdminAuditLogs();

  return (
    <div className="space-y-8">
      <PageHeader title="Audit Logs" description="Every administrative action taken on the InfinityPay platform, in order." />

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">Activity Log</h3>
        </div>
        {logs.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">No administrative actions have been recorded yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[900px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Timestamp</th>
                  <th className={thClass}>Actor</th>
                  <th className={thClass}>Action</th>
                  <th className={thClass}>Entity</th>
                  <th className={thClass}>IP Address</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {logs.map((log) => (
                  <tr key={log.audit_id} className="border-t border-surface-container-highest">
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(log.created_at)}</td>
                    <td className={`${tdClass} text-on-background`}>{log.actor ?? "System"}</td>
                    <td className={`${tdClass} font-semibold text-on-background`}>{log.action}</td>
                    <td className={`${tdClass} text-on-surface-variant`}>
                      {log.entity_type}
                      {log.entity_id ? ` (${log.entity_id.slice(0, 8)})` : ""}
                    </td>
                    <td className={`${tdClass} font-mono text-xs text-on-surface-variant`}>{log.ip_address ?? "—"}</td>
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
