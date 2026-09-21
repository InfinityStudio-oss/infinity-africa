import { Card, tdClass, thClass } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { formatDateTime } from "@/lib/format";
import { listAdminInquiries } from "@/lib/admin/live-api";

export const metadata = {
  title: "Inquiries | InfinityPay Super Admin",
};

export default async function SuperAdminInquiriesPage() {
  const inquiries = await listAdminInquiries();

  return (
    <div className="space-y-8">
      <PageHeader
        title="Inquiries"
        description="Contact form submissions from the public marketing site. Each one also emails ceo@infinitypay.me as it arrives — this is the browsable record."
      />

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">Submissions</h3>
        </div>
        {inquiries.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">No inquiries have been submitted yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[900px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Received</th>
                  <th className={thClass}>From</th>
                  <th className={thClass}>Contact</th>
                  <th className={thClass}>Message</th>
                  <th className={thClass}>Source</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {inquiries.map((inquiry) => (
                  <tr key={inquiry.id} className="border-t border-surface-container-highest align-top">
                    <td className={`${tdClass} text-on-surface-variant text-xs whitespace-nowrap`}>
                      {formatDateTime(inquiry.created_at)}
                    </td>
                    <td className={tdClass}>
                      <div className="font-medium text-on-background">{inquiry.full_name}</div>
                      {inquiry.business_name && (
                        <div className="text-xs text-on-surface-variant">{inquiry.business_name}</div>
                      )}
                    </td>
                    <td className={`${tdClass} text-xs`}>
                      <div className="text-on-background">{inquiry.email}</div>
                      {inquiry.phone && <div className="text-on-surface-variant">{inquiry.phone}</div>}
                    </td>
                    <td className={`${tdClass} text-on-surface-variant max-w-md`}>
                      <p className="line-clamp-3">{inquiry.message}</p>
                    </td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{inquiry.source}</td>
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
