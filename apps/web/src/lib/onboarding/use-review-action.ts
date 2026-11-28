"use client";

import { useState, useTransition } from "react";

import {
  approveOnboardingAction,
  rejectOnboardingAction,
  requestInfoOnboardingAction,
} from "./admin-actions";
import type { ReviewOutcome } from "./types";

export type { ReviewOutcome };

/** Drives the Approve/Reject/Request Info actions for one onboarding
 * submission — used by both the review-queue table row and the submission
 * detail page (same three server actions, same note field, same
 * success/error feedback need). Runs each action via useTransition rather
 * than a native <form formAction>, so a result — success or failure — is
 * always visible here instead of only a silent revalidatePath: approving
 * an already-verified submission, for instance, succeeds but changes
 * nothing visible in the table, which previously looked exactly like a
 * broken button.
 *
 * The outcome is the action's RETURN VALUE, never a caught exception.
 * Reading err.message from a Server Action looked like it worked, because
 * in development React sends the real message — in production it sends
 * "Minified React error #441" instead, and that is what the reviewer
 * read. See the comment in admin-actions.ts. */
export function useOnboardingReviewAction(id: string) {
  const [note, setNote] = useState("");
  const [outcome, setOutcome] = useState<ReviewOutcome | null>(null);
  const [isPending, startTransition] = useTransition();

  function run(action: () => Promise<ReviewOutcome>, failureMessage: string) {
    setOutcome(null);
    startTransition(async () => {
      let result: ReviewOutcome;
      try {
        result = await action();
      } catch {
        // Not the action failing — the action's own failures arrive as a
        // value now. This is the call never completing: offline, or a
        // deploy swapping the action id mid-click.
        result = { type: "error", message: failureMessage };
      }
      setOutcome(result);
      // A refused action keeps the note, so the reviewer does not retype
      // it after fixing whatever was refused.
      if (result.type !== "error") setNote("");
    });
  }

  const approve = () => run(() => approveOnboardingAction(id), "Couldn't approve — try again.");
  const reject = () => run(() => rejectOnboardingAction(id, note.trim() || null), "Couldn't reject — try again.");
  const requestInfo = () =>
    run(() => requestInfoOnboardingAction(id, note.trim() || null), "Couldn't send the request — try again.");

  return { note, setNote, outcome, isPending, approve, reject, requestInfo };
}
