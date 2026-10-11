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
export const SUSPENDED_PATH = "/dashboard/suspended";

/** merchants.status values that end a business's access. 'pending' is not
 * one: that is a new signup on its way through review, and it needs the
 * portal to get there. Mirrors _BLOCKED_MERCHANT_STATUSES in
 * apps/api/app/auth/dependencies.py. */
const BLOCKED_MERCHANT_STATUSES = new Set(["suspended", "closed"]);

/**
 * Sends a suspended or closed business to the suspended page.
 *
 * The backend refuses every /v1/merchant/* call from one (get_own_merchant),
 * and login refuses a fresh sign-in (lib/auth/actions.ts). This covers the
 * third case: a session that was already open when the Super Admin pressed
 * Suspend. Without it that session keeps rendering portal pages whose every
 * panel 403s, which looks like an outage rather than a suspension.
 *
 * Call it after getOnboardingStatus() in any server component that gates on
 * onboarding — /v1/onboarding/status itself stays readable while suspended,
 * which is what makes this possible.
 */
export function redirectIfSuspended(onboarding: OnboardingStatus | null): void {
  if (onboarding && BLOCKED_MERCHANT_STATUSES.has(onboarding.merchant_status ?? "")) {
    redirect(SUSPENDED_PATH);
  }
}

export async function requireVerifiedMerchant(): Promise<OnboardingStatus> {
  const onboarding = await getOnboardingStatus();

  redirectIfSuspended(onboarding);

  if (!onboarding || onboarding.next_path === "/onboarding") {
    redirect("/onboarding");
  }

  if (onboarding.account_status !== AccountStatus.VERIFIED) {
    redirect("/dashboard/overview");
  }

  return onboarding;
}
