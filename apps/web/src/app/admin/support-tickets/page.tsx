import { AdminKpiCard } from "@/components/admin/kpi-card";
import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import { listSupportTickets } from "@/lib/admin/api";
import { ticketPriorityBadge, ticketStatusBadge } from "@/lib/admin/status-tones";

export const metadata = {
  title: "Support Tickets | InfinityPay Super Admin",
};

export default async function SupportTicketsPage() {
  const tickets = await listSupportTickets();
  const open = tickets.filter((t) => t.status === "Open").length;
  const awaiting = tickets.filter((t) => t.status === "Awaiting Merchant").length;
  const resolved = tickets.filter((t) => t.status === "Resolved").length;

  return (
    <div className="space-y-8">
      <PageHeader title="Support Tickets" description="Merchant support requests escalated to the InfinityPay platform team." />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <AdminKpiCard icon="confirmation_number" label="Open Tickets" value={open.toLocaleString()} />
        <AdminKpiCard icon="hourglass_empty" label="Awaiting Merchant" value={awaiting.toLocaleString()} />
        <AdminKpiCard icon="check_circle" label="Resolved This Week" value={resolved.toLocaleString()} />
        <AdminKpiCard icon="schedule" label="Avg. First Response" value="38 min" />
      </div>

      <Card>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <input className="px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm" placeholder="Search by merchant name" />
          <select className="px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm">
            <option>All</option>
            <option>Low</option>
            <option>Medium</option>
            <option>High</option>
            <option>Urgent</option>
          </select>
          <select className="px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm">
            <option>All</option>
            <option>Open</option>
            <option>Awaiting Merchant</option>
            <option>Resolved</option>
            <option>Closed</option>
          </select>
        </div>
      </Card>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">All Tickets</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[880px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Ticket ID</th>
                <th className={thClass}>Merchant</th>
                <th className={thClass}>Subject</th>
                <th className={thClass}>Priority</th>
                <th className={thClass}>Status</th>
                <th className={thClass}>Updated</th>
                <th className={`${thClass} text-right`}>Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {tickets.map((ticket) => (
                <tr key={ticket.id} className="border-t border-surface-container-highest">
                  <td className={`${tdClass} font-mono text-on-background`}>{ticket.ticket_number}</td>
                  <td className={tdClass}>{ticket.merchant_name}</td>
                  <td className={`${tdClass} text-on-surface-variant`}>{ticket.subject}</td>
                  <td className={tdClass}>
                    <StatusBadge {...ticketPriorityBadge(ticket.priority)} />
                  </td>
                  <td className={tdClass}>
                    <StatusBadge {...ticketStatusBadge(ticket.status)} />
                  </td>
                  <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(ticket.updated_at)}</td>
                  <td className={`${tdClass} text-right`}>
                    <button className="p-1.5 text-on-surface-variant hover:text-primary" title="View">
                      <Icon name="visibility" className="text-[18px]" />
                    </button>
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
