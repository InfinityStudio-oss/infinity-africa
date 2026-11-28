"use server";

import { revalidatePath } from "next/cache";

import {
  approveOnboardingSubmission,
  OnboardingApiError,
  rejectOnboardingSubmission,
  requestMoreInfoOnboardingSubmission,
} from "./api";
import type { ReviewOutcome } from "./types";

function revalidateOnboarding(id: string) {
  revalidatePath("/super-admin/onboarding");
  revalidatePath(`/super-admin/onboarding/${id}`);
}

/**
 * Why these three RETURN their failures instead of throwing them.
 *
 * A Server Action that throws does not hand its message to the browser.
 * React's Flight client replaces it with a placeholder, and in a
 * production build that placeholder is literally "Minified React error
 * #441" (resolveErrorProd in react-server-dom-turbopack-client) — which
 * is what a Super Admin saw in the review queue, in red, the first time
 * the login-email gate refused an application. The reason, the only part
 * worth reading, was dropped on the server.
 *
 * Next says the same thing: "For these errors, avoid using try/catch
 * blocks and throw errors. Instead, model expected errors as return
 * values" (next/dist/docs/01-app/01-getting-started/10-error-handling.md).
 * The Businesses table already works this way (lib/admin/live-actions.ts);
 * this queue was the last place still throwing.
 *
 * Only OnboardingApiError's message is passed through — that is a
 * sentence the API wrote for a person to read. Anything else (a dropped
 * connection, a bug) gets the caller's fallback, so no internal detail
 * reaches the screen.
 */
async function runReviewAction(
  id: string,
  work: () => Promise<ReviewOutcome>,
  failureMessage: string,
): Promise<ReviewOutcome> {
  let outcome: ReviewOutcome;
  try {
    outcome = await work();
  } catch (err) {
    return {
      type: "error",
      message: err instanceof OnboardingApiError && err.message ? err.message : failureMessage,
    };
  }
  // Only on success. Revalidating after a refusal would re-fetch the
  // whole queue to show the identical rows.
  revalidateOnboarding(id);
  return outcome;
}

export async function approveOnboardingAction(id: string): Promise<ReviewOutcome> {
  return runReviewAction(
    id,
    async () => {
      const submission = await approveOnboardingSubmission(id);
      return submission.welcome_email_warning
        ? { type: "warning", message: submission.welcome_email_warning }
        : {
            type: "success",
            message: "Approved. Welcome email sent — the merchant will get their next steps in their inbox.",
          };
    },
    "Couldn't approve — try again.",
  );
}

export async function rejectOnboardingAction(id: string, note: string | null): Promise<ReviewOutcome> {
  return runReviewAction(
    id,
    async () => {
      await rejectOnboardingSubmission(id, note);
      return { type: "success", message: "Rejected." };
    },
    "Couldn't reject — try again.",
  );
}

export async function requestInfoOnboardingAction(id: string, note: string | null): Promise<ReviewOutcome> {
  return runReviewAction(
    id,
    async () => {
      await requestMoreInfoOnboardingSubmission(id, note);
      return { type: "success", message: "Requested more information." };
    },
    "Couldn't send the request — try again.",
  );
}
