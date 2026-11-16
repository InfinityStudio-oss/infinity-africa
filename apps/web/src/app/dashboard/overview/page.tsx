import { redirect } from "next/navigation";

import { OverviewDashboard } from "@/components/merchant/overview-dashboard";
import { PendingVerificationBanner } from "@/components/portal/pending-verification-banner";
import { PortalShell } from "@/components/portal/portal-shell";
import { requireCurrentUser } from "@/lib/auth/current-user";
import { getOnboardingStatus } from "@/lib/onboarding/api";
import { redirectIfSuspended } from "@/lib/onboarding/guard";
import { AccountStatus } from "@infinity/shared";

export const metadata = {
  title: "Overview | InfinityPay",
};

/**
 * Auth, the onboarding redirect, and the shell. The figures are fetched
 * by OverviewDashboard on the client.
 *
 * That split is not a style choice. lib/portal/api.ts attaches the
 * merchant's token with getAccessTokenClient(), which is a "use client"
 * module reading the BROWSER session - and its own header comment says
 * every page calling into it is a Client Component, naming
 * transactions/page.tsx as one that was converted for exactly this
 * reason. This page was not.
 *
 * So each of its server-side calls went out with no Authorization
 * header, apps/api answered 401, apiGet turned that into null, and the
 * page read that null as "this merchant has no data" and rendered the
 * first-run welcome screen. Every verified merchant saw it, nothing
 * logged, and the production data was healthy throughout - which is why
 * it looked like an undeployed redesign rather than a page that never
 * had a token.
 */
export default async function MerchantOverviewPage() {
  await requireCurrentUser("/dashboard/login");

  const onboarding = await getOnboardingStatus();
  redirectIfSuspended(onboarding);
  if (!onboarding || onboarding.next_path === "/onboarding") {
    redirect("/onboarding");
  }

  const isPending = onboarding.account_status === AccountStatus.PENDING_VERIFICATION;

  return (
    <PortalShell
      banner={isPending ? <PendingVerificationBanner /> : null}
      verified={onboarding.account_status === AccountStatus.VERIFIED}
    >
      <OverviewDashboard />
    </PortalShell>
  );
}
