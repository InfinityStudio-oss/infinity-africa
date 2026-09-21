import { redirect } from "next/navigation";

import { requireCurrentUser } from "@/lib/auth/current-user";
import { getOnboardingStatus } from "@/lib/onboarding/api";
import { getMerchantOverview } from "@/lib/portal/api";
import { OverviewDashboard } from "@/components/merchant/overview-dashboard";
import { OverviewWelcome } from "@/components/merchant/overview-welcome";
import { PortalShell } from "@/components/portal/portal-shell";
import { PendingVerificationBanner } from "@/components/portal/pending-verification-banner";
import { AccountStatus } from "@infinity/shared";

export const metadata = {
  title: "Merchant Overview | InfinityPay",
};

export default async function MerchantOverviewPage() {
  await requireCurrentUser("/merchant/login");

  const onboarding = await getOnboardingStatus();
  if (!onboarding || onboarding.next_path === "/onboarding") {
    redirect("/onboarding");
  }

  // Real merchant data is only reachable once apps/api and Supabase are
  // actually running — getMerchantOverview() returning null (network
  // failure, backend down) is the expected case in this environment.
  // Falls back to the onboarding-status view rather than erroring.
  const overview = await getMerchantOverview();
  const isPending = onboarding.account_status === AccountStatus.PENDING_VERIFICATION;

  return (
    <PortalShell banner={isPending ? <PendingVerificationBanner /> : null}>
      {overview ? (
        <OverviewDashboard overview={overview} />
      ) : (
        <OverviewWelcome accountStatus={onboarding.account_status ?? AccountStatus.PENDING_VERIFICATION} />
      )}
    </PortalShell>
  );
}
