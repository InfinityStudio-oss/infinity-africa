import { redirect } from "next/navigation";

import { requireUser } from "@/lib/supabase/protected-route";
import { getOnboardingStatus } from "@/lib/onboarding/api";
import { PortalShell } from "@/components/portal/portal-shell";
import { PendingVerificationBanner } from "@/components/portal/pending-verification-banner";
import { AccountStatus } from "@infinity/shared";

export const metadata = {
  title: "Merchant Portal | InfinityPay",
  robots: { index: false, follow: false },
};

export default async function PortalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  if (!process.env.__PORTAL_UI_PREVIEW__) {
    await requireUser("/dashboard/login");
    const onboarding = await getOnboardingStatus();
    if (!onboarding || onboarding.next_path === "/onboarding") redirect("/onboarding");

    return (
      <PortalShell
        banner={onboarding.account_status === AccountStatus.PENDING_VERIFICATION ? <PendingVerificationBanner /> : null}
      >
        {children}
      </PortalShell>
    );
  }

  return <PortalShell>{children}</PortalShell>;
}
