import { PulsingDot } from "@/components/admin/pulsing-dot";
import { Card, tdClass, thClass } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import { listIncidents, listProviderHealth } from "@/lib/admin/api";
import { incidentStatusBadge } from "@/lib/admin/status-tones";
import type { ProviderHealth } from "@/lib/admin/types";

export const metadata = {
  title: "Provider Status | InfinityPay Super Admin",
};

const STATUS_META: Record<ProviderHealth["status"], { label: string; color: string; textClass: string; animate: boolean; extraBorder?: string }> = {
  operational: { label: "Operational", color: "bg-primary", textClass: "text-primary", animate: true },
  degraded: { label: "Degraded Performance", color: "bg-amber-500", textClass: "text-amber-600", animate: true },
  down: { label: "Down", color: "bg-error", textClass: "text-error", animate: false, extraBorder: "border-l-4 border-error" },
};

export default async function ProviderStatusPage() {
  const [providers, incidents] = await Promise.all([listProviderHealth(), listIncidents()]);

  return (
    <div className="space-y-8">
      <PageHeader title="Provider Status" description="Live uptime and health for every payment network InfinityPay connects to." />

      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
        {providers.map((provider) => {
          const meta = STATUS_META[provider.status];
          return (
            <div
              key={provider.id}
              className={`bg-surface rounded-xl border border-surface-container-highest shadow-ambient p-5 ${meta.extraBorder ?? ""}`}
            >
              <div className="flex items-center justify-between mb-4">
                <h4 className="text-lg font-semibold text-on-background">{provider.name}</h4>
                <div className="flex items-center gap-2">
                  <PulsingDot color={meta.color} animate={meta.animate} />
                  <span className={`text-xs font-semibold ${meta.textClass}`}>{meta.label}</span>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3 pt-3 border-t border-surface-container-highest">
                <div>
                  <p className="text-xs text-on-surface-variant">Uptime (month)</p>
                  <p className="text-sm font-semibold text-on-background">{provider.uptime_month}</p>
                </div>
                <div>
                  <p className="text-xs text-on-surface-variant">Avg response</p>
                  <p className="text-sm font-semibold text-on-background">
                    {provider.avg_response_ms !== null ? `${provider.avg_response_ms}ms` : "—"}
                  </p>
                </div>
              </div>
            </div>
          );
        })}
      </section>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">Incident History</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[760px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Provider</th>
                <th className={thClass}>Incident</th>
                <th className={thClass}>Start Time</th>
                <th className={thClass}>Duration</th>
                <th className={thClass}>Status</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {incidents.map((incident) => (
                <tr key={incident.id} className="border-t border-surface-container-highest">
                  <td className={`${tdClass} font-medium text-on-background`}>{incident.provider}</td>
                  <td className={`${tdClass} text-on-surface-variant`}>{incident.incident}</td>
                  <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(incident.start_time)}</td>
                  <td className={`${tdClass} text-on-surface-variant text-xs`}>{incident.duration}</td>
                  <td className={tdClass}>
                    <StatusBadge {...incidentStatusBadge(incident.status)} />
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
