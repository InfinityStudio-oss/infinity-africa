import { redirect } from "next/navigation";

import { requireCurrentUser } from "@/lib/auth/current-user";
import { getOnboardingStatus } from "@/lib/onboarding/api";
import { PageHeader } from "@/components/portal/page-header";
import { PortalShell } from "@/components/portal/portal-shell";
import { ProfileView } from "@/components/merchant/profile-view";

export const metadata = {
  title: "Profile | InfinityPay",
};

export default async function MerchantProfilePage() {
  const user = await requireCurrentUser("/merchant/login");

  const onboarding = await getOnboardingStatus();
  if (!onboarding || onboarding.next_path === "/onboarding") {
    redirect("/onboarding");
  }

  return (
    <PortalShell>
      <div className="space-y-8">
        <PageHeader title="Profile" description="Your account and business details." />
        <ProfileView email={user.email} />
      </div>
    </PortalShell>
  );
}
