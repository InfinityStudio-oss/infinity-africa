import { AccountStatus } from "@infinity/shared";

import { AdminKpiCard } from "@/components/admin/kpi-card";
import { Card } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { OnboardingTable } from "@/components/super-admin/onboarding-table";
import { listOnboardingSubmissions } from "@/lib/onboarding/api";

export const metadata = {
  title: "Onboarding & Compliance/KYC | InfinityPay",
};

export default async function SuperAdminOnboardingPage() {
  const rows = await listOnboardingSubmissions();

  // Every merchant's onboarding/KYC review status, platform-wide — this is
  // the same real data a dedicated "Compliance/KYC" page would show, so
  // rather than duplicate it under a second URL, the counts live here.
  const verified = rows.filter((r) => r.review_status === AccountStatus.VERIFIED).length;
  const pending = rows.filter((r) => r.review_status === AccountStatus.PENDING_VERIFICATION).length;
  const infoRequested = rows.filter((r) => r.review_status === AccountStatus.INFO_REQUESTED).length;
  const rejected = rows.filter((r) => r.review_status === AccountStatus.REJECTED).length;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Onboarding & Compliance/KYC"
        description="Review merchant onboarding submissions and manage verification across the platform."
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <AdminKpiCard variant="brand" icon="verified_user" label="Verified Merchants" value={verified.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="hourglass_empty" label="Pending Review" value={pending.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="mark_email_unread" label="Info Requested" value={infoRequested.toLocaleString()} />
        <AdminKpiCard variant="brand" icon="block" label="Rejected" value={rejected.toLocaleString()} />
      </div>

      <Card padded={false}>
        <OnboardingTable rows={rows} />
      </Card>
    </div>
  );
}
