import { redirect } from "next/navigation";

import { requireCurrentUser } from "@/lib/auth/current-user";
import { getOnboardingStatus } from "@/lib/onboarding/api";
import { RiskMonitoringView } from "@/components/merchant/risk-monitoring-view";
import { PortalShell } from "@/components/portal/portal-shell";

export const metadata = {
  title: "Risk Monitoring | InfinityPay",
};

export default async function RiskMonitoringPage() {
  await requireCurrentUser("/merchant/login");

  const onboarding = await getOnboardingStatus();
  if (!onboarding || onboarding.next_path === "/onboarding") {
    redirect("/onboarding");
  }

  return (
    <PortalShell>
      <RiskMonitoringView />
    </PortalShell>
  );
}
