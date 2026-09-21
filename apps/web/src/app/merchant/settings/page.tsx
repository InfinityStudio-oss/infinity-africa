import { redirect } from "next/navigation";

import { requireCurrentUser } from "@/lib/auth/current-user";
import { getOnboardingStatus } from "@/lib/onboarding/api";
import { PageHeader } from "@/components/portal/page-header";
import { PortalShell } from "@/components/portal/portal-shell";
import { UpdatePasswordForm } from "@/components/auth/update-password-form";
import { NotificationSettingsCard } from "@/components/merchant/notification-settings-card";

export const metadata = {
  title: "Settings | InfinityPay",
};

export default async function MerchantSettingsPage() {
  const user = await requireCurrentUser("/merchant/login");

  const onboarding = await getOnboardingStatus();
  if (!onboarding || onboarding.next_path === "/onboarding") {
    redirect("/onboarding");
  }

  return (
    <PortalShell>
      <div className="space-y-8">
        <PageHeader title="Settings" description="Manage your account security and notifications." />
        <NotificationSettingsCard />
        <UpdatePasswordForm email={user.email} source={user.source} />
      </div>
    </PortalShell>
  );
}
