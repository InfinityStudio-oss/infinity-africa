import { redirect } from "next/navigation";

import { requireCurrentUser } from "@/lib/auth/current-user";
import { getOnboardingStatus } from "@/lib/onboarding/api";
import { PortalShell } from "@/components/portal/portal-shell";
import { UsersView } from "@/components/merchant/users-view";

export const metadata = {
  title: "Team | InfinityPay",
};

export default async function MerchantUsersPage() {
  await requireCurrentUser("/dashboard/login");

  const onboarding = await getOnboardingStatus();
  if (!onboarding || onboarding.next_path === "/onboarding") {
    redirect("/onboarding");
  }

  return (
    <PortalShell>
      <UsersView />
    </PortalShell>
  );
}
