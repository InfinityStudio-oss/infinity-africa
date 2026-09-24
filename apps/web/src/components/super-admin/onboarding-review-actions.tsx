"use client";

import { useOnboardingReviewAction } from "@/lib/onboarding/use-review-action";

const buttonBase = "rounded-lg text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed";
const approveButton = `${buttonBase} bg-primary-container text-on-primary hover:opacity-90`;
const secondaryButton = `${buttonBase} border border-outline-variant text-on-surface-variant hover:bg-surface-container-low`;

export function OnboardingReviewActions({
  submissionId,
  variant = "full",
}: {
  submissionId: string;
  variant?: "full" | "compact";
}) {
  const { note, setNote, outcome, isPending, approve, reject, requestInfo } = useOnboardingReviewAction(submissionId);

  const buttonSize = variant === "compact" ? "px-2.5 py-1 text-xs" : "px-4 py-2";
  const buttons = (
    <div className={variant === "compact" ? "flex gap-1.5" : "flex gap-2"}>
      <button type="button" onClick={approve} disabled={isPending} className={`${approveButton} ${buttonSize}`}>
        Approve
      </button>
      <button type="button" onClick={reject} disabled={isPending} className={`${secondaryButton} ${buttonSize}`}>
        Reject
      </button>
      <button type="button" onClick={requestInfo} disabled={isPending} className={`${secondaryButton} ${buttonSize}`}>
        {variant === "compact" ? "Request Info" : "Request More Info"}
      </button>
    </div>
  );

  const feedbackColor =
    outcome?.type === "success" ? "text-primary" : outcome?.type === "warning" ? "text-amber-600" : "text-error";
  const feedback = outcome && (
    <p className={`text-xs font-medium ${feedbackColor}`}>{isPending ? "" : outcome.message}</p>
  );

  if (variant === "compact") {
    return (
      <div className="flex flex-col items-end gap-1.5">
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Note (optional)"
          className="w-40 rounded-lg border border-outline-variant bg-transparent px-2 py-1 text-xs text-on-surface placeholder-outline focus:outline-none focus:border-primary-container"
        />
        {buttons}
        {feedback}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={3}
        placeholder="Add a note (optional) — shown to the business for Reject / Request More Info"
        className="w-full rounded-lg border border-outline-variant bg-transparent px-3 py-2 text-sm text-on-surface placeholder-outline focus:outline-none focus:border-primary-container"
      />
      {buttons}
      {feedback}
    </div>
  );
}
