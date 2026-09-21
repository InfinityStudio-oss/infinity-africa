import { redirect } from "next/navigation";

import { requireCurrentUser } from "@/lib/auth/current-user";
import { getOnboardingStatus } from "@/lib/onboarding/api";
import { DisputesView } from "@/components/merchant/disputes-view";
import { PortalShell } from "@/components/portal/portal-shell";

export const metadata = {
  title: "Disputes | InfinityPay",
};

export default async function MerchantDisputesPage() {
  await requireCurrentUser("/merchant/login");

  const onboarding = await getOnboardingStatus();
  if (!onboarding || onboarding.next_path === "/onboarding") {
    redirect("/onboarding");
  }

  return (
    <PortalShell>
      <DisputesView />
    </PortalShell>
  );
}
