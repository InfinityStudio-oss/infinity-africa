import { Card } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { SmsWorkspace } from "@/components/super-admin/sms-workspace";
import {
  getAdminSmsOverview,
  getAdminSmsSettings,
  listAdminMerchants,
  listAdminSmsCampaigns,
  listAdminSmsMessages,
} from "@/lib/admin/live-api";

export const metadata = {
  title: "SMS | InfinityPay Super Admin",
};

export default async function SuperAdminSmsPage() {
  const [overview, settings, campaigns, messages, merchants] = await Promise.all([
    getAdminSmsOverview(),
    getAdminSmsSettings(),
    listAdminSmsCampaigns(),
    listAdminSmsMessages(),
    listAdminMerchants(),
  ]);

  return (
    <div className="space-y-8">
      <PageHeader
        title="SMS"
        description="Transactional payment alerts to merchants, and announcements. Recipients are merchants only — a paying customer is never sent an SMS from here."
      />

      {overview === null ? (
        <Card>
          <p className="text-sm text-on-surface-variant">
            The SMS service could not be reached. Nothing has been sent and nothing is lost — queued
            messages stay queued.
          </p>
        </Card>
      ) : (
        <SmsWorkspace
          overview={overview}
          settings={settings}
          campaigns={campaigns}
          messages={messages}
          merchants={merchants.map((m) => ({
            merchant_id: m.merchant_id,
            business_name: m.business_name,
            merchant_code: m.merchant_code,
          }))}
        />
      )}
    </div>
  );
}
