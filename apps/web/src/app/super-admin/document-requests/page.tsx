import { PageHeader } from "@/components/portal/page-header";
import { DocumentRequestsTable } from "@/components/super-admin/document-requests-table";
import { listAdminDocumentRequests } from "@/lib/admin/live-api";

export const metadata = {
  title: "Document Requests | InfinityPay Super Admin",
};

export default async function SuperAdminDocumentRequestsPage() {
  const requests = await listAdminDocumentRequests();

  return (
    <div className="space-y-8">
      <PageHeader title="Document Requests" description="Supporting evidence requested from businesses for flagged transactions." />
      <DocumentRequestsTable rows={requests} />
    </div>
  );
}
