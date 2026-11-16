import { redirect } from "next/navigation";

import { requireCurrentUser } from "@/lib/auth/current-user";
import { getOnboardingStatus } from "@/lib/onboarding/api";
import { redirectIfSuspended } from "@/lib/onboarding/guard";
import { getMerchantOverview, getOverviewReport, getPayoutWallet } from "@/lib/portal/api";
import { OverviewDashboard } from "@/components/merchant/overview-dashboard";
import { OverviewWelcome } from "@/components/merchant/overview-welcome";
import { PortalShell } from "@/components/portal/portal-shell";
import { PendingVerificationBanner } from "@/components/portal/pending-verification-banner";
import { AccountStatus } from "@infinity/shared";

export const metadata = {
  title: "Overview | InfinityPay",
};

export default async function MerchantOverviewPage() {
  await requireCurrentUser("/dashboard/login");

  const onboarding = await getOnboardingStatus();
  redirectIfSuspended(onboarding);
  if (!onboarding || onboarding.next_path === "/onboarding") {
    redirect("/onboarding");
  }

  // Real merchant data is only reachable once apps/api and Supabase are
  // actually running — getMerchantOverview() returning null (network
  // failure, backend down) is the expected case in this environment.
  // Falls back to the onboarding-status view rather than erroring.
  // All three in parallel. The charts and the payout card are additive,
  // so they must not each add a round trip to the first page a merchant
  // sees. The report is fetched here rather than on the client so the
  // first paint already has the charts instead of a spinner.
  const [overview, report, wallet] = await Promise.all([
    getMerchantOverview(),
    getOverviewReport({ days: 7 }),
    getPayoutWallet(),
  ]);
  const isPending = onboarding.account_status === AccountStatus.PENDING_VERIFICATION;

  return (
    <PortalShell banner={isPending ? <PendingVerificationBanner /> : null} verified={onboarding.account_status === AccountStatus.VERIFIED}>
      {overview ? (
        <OverviewDashboard
          overview={overview}
          initialReport={report.data}
          // noAccess means this merchant has no Disbursement API at all,
          // so the card is not rendered rather than shown empty. A failed
          // read is also null here - a wallet card is not worth a second
          // error state on a page that already has one.
          payoutWallet={wallet.data}
        />
      ) : (
        <OverviewWelcome accountStatus={onboarding.account_status ?? AccountStatus.PENDING_VERIFICATION} />
      )}
    </PortalShell>
  );
}
