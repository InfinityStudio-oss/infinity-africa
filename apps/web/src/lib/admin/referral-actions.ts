"use server";

import { revalidatePath } from "next/cache";

import {
  approveReferralCommission,
  clearReferralFraudHold,
  markReferralCommissionPaid,
  rejectReferralCommission,
  setReferralFraudHold,
} from "./live-api";

/** Server actions for the referrals queue.
 *
 * The table is a client component, and `lib/admin/live-api` reaches the
 * API with the caller's Supabase session through `server-only` code. A
 * client component importing it drags that into the browser bundle and
 * the production build refuses to compile - which is what happened, and
 * what `tsc` and `vitest` both failed to notice. Calling through server
 * actions is how every other admin client component here does it (see
 * lib/onboarding/admin-actions.ts).
 *
 * Each action revalidates the queue so the page re-reads the figures
 * rather than showing a stale row next to a changed one.
 */

function revalidateReferrals() {
  revalidatePath("/super-admin/referrals");
}

/** Marks a commission payable. Moves no money. */
export async function approveReferralCommissionAction(commissionId: string): Promise<void> {
  await approveReferralCommission(commissionId);
  revalidateReferrals();
}

export async function rejectReferralCommissionAction(
  commissionId: string,
  reason: string,
): Promise<void> {
  await rejectReferralCommission(commissionId, reason);
  revalidateReferrals();
}

/** Records a payout made through the normal withdrawal process. This does
 * not pay anything. */
export async function markReferralCommissionPaidAction(
  commissionId: string,
  note?: string,
): Promise<void> {
  await markReferralCommissionPaid(commissionId, note);
  revalidateReferrals();
}

export async function setReferralFraudHoldAction(referralId: string, reason: string): Promise<void> {
  await setReferralFraudHold(referralId, reason);
  revalidateReferrals();
}

export async function clearReferralFraudHoldAction(referralId: string): Promise<void> {
  await clearReferralFraudHold(referralId);
  revalidateReferrals();
}
