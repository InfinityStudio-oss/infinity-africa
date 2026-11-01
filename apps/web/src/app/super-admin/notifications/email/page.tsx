import { Card } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { NotificationEmailTable } from "@/components/super-admin/notification-email-table";
import { listAdminNotificationSettings } from "@/lib/admin/live-api";

export const metadata = {
  title: "Email Notifications | InfinityPay Super Admin",
};

export default async function SuperAdminNotificationEmailPage(
  props: PageProps<"/super-admin/notifications/email">,
) {
  const params = await props.searchParams;
  const search = typeof params.q === "string" ? params.q : "";
  const page = Number(typeof params.page === "string" ? params.page : "1") || 1;

  // Searched and paged on the server. This list is every merchant on the
  // platform, so filtering a single fetched page in the browser would
  // quietly search only the rows that happened to arrive.
  const { rows, totalPages } = await listAdminNotificationSettings({ search, page });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Email Notifications"
        description="Who is told when one of their collections succeeds. Managed here only — businesses can see this but cannot change it."
      />

      <Card>
        <p className="text-sm text-on-surface-variant">
          This controls <strong>successful-collection notification emails</strong> and nothing else.
          Verification, password resets, OTPs, security alerts, approval decisions and withdrawal
          emails are unaffected by the switch below and always send.
        </p>
      </Card>

      <NotificationEmailTable rows={rows} search={search} page={page} totalPages={totalPages} />
    </div>
  );
}
