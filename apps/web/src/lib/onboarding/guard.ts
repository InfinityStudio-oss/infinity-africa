import "server-only";

import { redirect } from "next/navigation";

import { AccountStatus } from "@infinity/shared";

import { getOnboardingStatus } from "./api";
import type { OnboardingStatus } from "./types";

/**
 * Guard for merchant pages that move money — collections, payment links,
 * Pay by Link, withdrawals, invoices. A merchant may reach these only once
 * a Super Admin has *approved* their onboarding submission
 * (AccountStatus.VERIFIED).
 *
 *  - No submission yet  -> /onboarding (finish document/business verification)
 *  - Submitted, still under review / rejected / info-requested
 *                       -> /dashboard/overview (shows the pending banner and
 *                          the current review status; nothing financial)
 *  - Approved           -> allowed through
 *
 * This is a UX guard layered on top of the real enforcement, which lives
 * in apps/api (every money-movement endpoint under /v1/merchant/* checks
 * the merchant is active + verified before doing anything). Call it in a
 * Server Component after requireCurrentUser().
 */
export async function requireVerifiedMerchant(): Promise<OnboardingStatus> {
  const onboarding = await getOnboardingStatus();

  if (!onboarding || onboarding.next_path === "/onboarding") {
    redirect("/onboarding");
  }

  if (onboarding.account_status !== AccountStatus.VERIFIED) {
    redirect("/dashboard/overview");
  }

  return onboarding;
}
