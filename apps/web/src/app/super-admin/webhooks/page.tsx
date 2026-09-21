import { AdminKpiCard } from "@/components/admin/kpi-card";
import { Card, tdClass, thClass } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import { listAdminWebhookEvents } from "@/lib/admin/live-api";
import { adminWebhookEventBadge } from "@/lib/admin/status-tones";

export const metadata = {
  title: "Webhooks | InfinityPay Super Admin",
};

// Set once whenever a webhook lands with no matching collection for its
// transid/order_id — the exact, only wording app/routers/webhooks.py uses
// for that case (see complete_checkout_collection_once's caller). Matching
// on it is how "reconciliation" — spotting a provider callback that never
// found its transaction — surfaces here without a second, duplicate
// "Reconciliation Center" page over the same underlying table.
const UNMATCHED_ERROR_TEXT = "no matching collection";

export default async function SuperAdminWebhooksPage() {
  const events = await listAdminWebhookEvents();
  const processed = events.filter((e) => e.status === "processed").length;
  const failed = events.filter((e) => e.status === "failed").length;
  const received = events.filter((e) => e.status === "received").length;

  const today = new Date().toDateString();
  const autoMatchedToday = events.filter(
    (e) => e.status === "processed" && e.processed_at && new Date(e.processed_at).toDateString() === today,
  ).length;
  const unmatched = events.filter((e) => e.processing_error?.includes(UNMATCHED_ERROR_TEXT)).length;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Webhooks & Reconciliation"
        description="Inbound payment provider callbacks received by the platform, matched against transactions."
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-5">
        <AdminKpiCard variant="brand" icon="check_circle" label="Processed" value={processed.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="hourglass_empty" label="Received (Unprocessed)" value={received.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="error" label="Failed" value={failed.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="task_alt" label="Auto-Matched Today" value={autoMatchedToday.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="help" label="Unmatched Transactions" value={unmatched.toLocaleString()} />
      </div>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">Provider Callback Log</h3>
        </div>
        {events.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">No provider callbacks have been received yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[900px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Provider</th>
                  <th className={thClass}>Event Type</th>
                  <th className={thClass}>Reference</th>
                  <th className={thClass}>Received</th>
                  <th className={thClass}>Processed</th>
                  <th className={thClass}>Status</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {events.map((event) => (
                  <tr key={event.webhook_event_id} className="border-t border-surface-container-highest">
                    <td className={`${tdClass} font-medium text-on-background capitalize`}>{event.provider}</td>
                    <td className={`${tdClass} font-mono text-xs`}>{event.event_type}</td>
                    <td className={`${tdClass} font-mono text-xs text-on-surface-variant`}>{event.reference}</td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(event.created_at)}</td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{event.processed_at ? formatDateTime(event.processed_at) : "—"}</td>
                    <td className={tdClass}>
                      <StatusBadge {...adminWebhookEventBadge(event.status)} />
                      {event.processing_error && (
                        <p className="mt-1 text-xs text-on-surface-variant">{event.processing_error}</p>
                      )}
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
