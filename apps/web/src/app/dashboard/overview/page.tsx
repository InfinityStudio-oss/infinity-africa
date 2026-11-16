import { redirect } from "next/navigation";

import { OverviewDashboard } from "@/components/merchant/overview-dashboard";
import { PendingVerificationBanner } from "@/components/portal/pending-verification-banner";
import { PortalShell } from "@/components/portal/portal-shell";
import { requireCurrentUser } from "@/lib/auth/current-user";
import { getOnboardingStatus } from "@/lib/onboarding/api";
import { redirectIfSuspended } from "@/lib/onboarding/guard";
import { getOverviewReport, getPayoutWallet, readMerchantOverview } from "@/lib/portal/api";
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

  // All three in parallel: the charts and the payout card are additive
  // and must not each cost a round trip on the first page a merchant
  // sees. The report is fetched here, not on the client, so the first
  // paint already has the charts rather than a spinner.
  const [overview, report, wallet] = await Promise.all([
    readMerchantOverview(),
    getOverviewReport({ days: 7 }),
    getPayoutWallet(),
  ]);

  const isPending = onboarding.account_status === AccountStatus.PENDING_VERIFICATION;

  // By this line the merchant has an account and has finished onboarding
  // - the two checks above redirect otherwise - so the dashboard is the
  // right page for them, and it renders whether or not the overview call
  // came back.
  //
  // It did not always. This page used to read `overview ? dashboard :
  // welcome`, with `overview` coming from a helper that returns null for
  // every kind of failure. One flaky request therefore replaced a
  // trading merchant's dashboard with the first-run welcome screen and a
  // setup checklist, which is what was on screen in production: not an
  // old build, and not a missing redesign - the branch simply never
  // reached the dashboard. Failures now show as failures, in the figures
  // they affect, and never as a different page.
  return (
    <PortalShell
      banner={isPending ? <PendingVerificationBanner /> : null}
      verified={onboarding.account_status === AccountStatus.VERIFIED}
    >
      <OverviewDashboard
        overview={overview.data}
        overviewError={overview.error}
        initialReport={report.data}
        initialReportError={report.error}
        // noAccess means no Disbursement API for this merchant, so the
        // card is not rendered at all rather than shown empty.
        payoutWallet={wallet.data}
      />
    </PortalShell>
  );
}
