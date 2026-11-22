import { AdminKpiCard } from "@/components/admin/kpi-card";
import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { InvoicesFilters } from "@/components/super-admin/invoices-filters";
import { getAdminOverview, listAdminInvoices } from "@/lib/admin/live-api";
import { adminInvoiceBadge } from "@/lib/admin/status-tones";

export const metadata = {
  title: "Invoices | InfinityPay Super Admin",
};

interface SuperAdminInvoicesPageProps {
  searchParams: Promise<{ search?: string; status?: string; due_before?: string }>;
}

export default async function SuperAdminInvoicesPage({ searchParams }: SuperAdminInvoicesPageProps) {
  const filters = await searchParams;
  const anyFilter = Boolean(filters.search || filters.status || filters.due_before);
  const [invoices, overview] = await Promise.all([
    listAdminInvoices({
      search: filters.search,
      status: filters.status,
      dueBefore: filters.due_before,
    }),
    getAdminOverview(),
  ]);
  // These count the rows actually listed, so under a filter they
  // describe the filtered set - which is why the heading below says so.
  const paidToday = invoices.filter((i) => i.status === "PAID").length;
  const overdue = invoices.filter((i) => i.status === "OVERDUE").length;

  return (
    <div className="space-y-8">
      <PageHeader title="Invoice Management" description="Track every invoice issued across all businesses on the platform." />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
        <AdminKpiCard variant="brand" icon="receipt" label="Total Invoices" value={invoices.length.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="check_circle" label="Paid Today" value={paidToday.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="error" label="Overdue" value={overdue.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="payments" label="Value Outstanding" value={overview ? formatCurrency(overview.outstanding_invoice_value, "TZS") : "—"} />
      </div>

      <InvoicesFilters
        initial={{
          search: filters.search,
          status: filters.status,
          dueBefore: filters.due_before,
        }}
      />

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">
            {anyFilter ? "Matching Invoices" : "All Invoices"}
          </h3>
        </div>
        {invoices.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">
            {/* "None issued yet" when a filter is hiding them would tell
              * an operator the business has never invoiced anyone. */}
            {anyFilter
              ? "No invoices match these filters."
              : "No invoices have been issued yet."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[1020px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Invoice No</th>
                  <th className={thClass}>Merchant</th>
                  <th className={thClass}>Customer</th>
                  <th className={thClass}>Amount</th>
                  <th className={thClass}>Due Date</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass}>Email</th>
                  <th className={`${thClass} text-right`}>Actions</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {invoices.map((invoice) => (
                  <tr key={invoice.invoice_id} className={`border-t border-surface-container-highest ${invoice.status === "CANCELLED" ? "opacity-60" : ""}`}>
                    <td className={`${tdClass} font-mono text-on-background`}>{invoice.invoice_number}</td>
                    <td className={tdClass}>
                      <div>{invoice.merchant_name}</div>
                      {invoice.merchant_code && (
                        <div className="font-mono text-xs text-on-surface-variant">{invoice.merchant_code}</div>
                      )}
                    </td>
                    <td className={tdClass}>{invoice.customer_name ?? invoice.customer_phone ?? "—"}</td>
                    <td className={`${tdClass} font-semibold text-on-background`}>{formatCurrency(invoice.total_amount, "TZS")}</td>
                    <td className={`${tdClass} text-xs ${invoice.status === "OVERDUE" ? "text-error font-semibold" : "text-on-surface-variant"}`}>
                      {formatDateTime(invoice.due_date)}
                    </td>
                    <td className={tdClass}>
                      <StatusBadge {...adminInvoiceBadge(invoice.status)} />
                    </td>
                    <td className={tdClass}>
                      {invoice.email_status === "sent" ? (
                        <span
                          className="inline-flex items-center gap-1 text-xs font-semibold text-primary"
                          title={`Sent to ${invoice.customer_email ?? "customer"}${invoice.email_provider_message_id ? ` (${invoice.email_provider_message_id})` : ""}`}
                        >
                          <Icon name="mail" className="text-[16px]" />
                          Sent
                        </span>
                      ) : invoice.email_status === "failed" ? (
                        <span
                          className="inline-flex items-center gap-1 text-xs font-semibold text-error"
                          title={invoice.email_failed_reason ?? "Delivery failed"}
                        >
                          <Icon name="error" className="text-[16px]" />
                          Failed
                        </span>
                      ) : (
                        <span className="text-xs text-on-surface-variant">—</span>
                      )}
                    </td>
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
        )}
      </Card>
    </div>
  );
}
