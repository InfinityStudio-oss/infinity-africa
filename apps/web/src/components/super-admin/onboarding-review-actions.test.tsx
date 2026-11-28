/**
 * What the reviewer actually reads after pressing a button.
 *
 * The bug this guards: a refused Approve rendered "Minified React error
 * #441; visit https://react.dev/errors/441 …" in red beside the row.
 * The gate's real sentence — which names the business's unverified login
 * email and what to do about it — never left the server, because the
 * action threw it instead of returning it.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const approveOnboardingAction = vi.fn();
const rejectOnboardingAction = vi.fn();
const requestInfoOnboardingAction = vi.fn();

vi.mock("@/lib/onboarding/admin-actions", () => ({
  approveOnboardingAction: (id: string) => approveOnboardingAction(id),
  rejectOnboardingAction: (id: string, note: string | null) => rejectOnboardingAction(id, note),
  requestInfoOnboardingAction: (id: string, note: string | null) => requestInfoOnboardingAction(id, note),
}));

import { OnboardingReviewActions } from "./onboarding-review-actions";

const ID = "11111111-2222-3333-4444-555555555555";
const GATE_MESSAGE =
  "Cannot approve: nobody has verified the login email owner@example.com. Fix it under Businesses - " +
  "resend the verification email, correct the address if it is wrong, or confirm it yourself - then approve.";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("OnboardingReviewActions", () => {
  it("shows the reason the server refused, word for word", async () => {
    approveOnboardingAction.mockResolvedValue({ type: "error", message: GATE_MESSAGE });
    render(<OnboardingReviewActions submissionId={ID} />);

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByText(GATE_MESSAGE)).toBeInTheDocument();
    // The old failure mode, in the one place it was visible.
    expect(screen.queryByText(/Minified React error/)).not.toBeInTheDocument();
  });

  it("keeps the reviewer's note when the action is refused", async () => {
    rejectOnboardingAction.mockResolvedValue({ type: "error", message: "Already rejected." });
    render(<OnboardingReviewActions submissionId={ID} />);

    const note = screen.getByPlaceholderText(/Add a note/);
    fireEvent.change(note, { target: { value: "Documents unreadable" } });
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));

    expect(await screen.findByText("Already rejected.")).toBeInTheDocument();
    // Retyping it after fixing whatever was wrong is the kind of small
    // insult that stops people writing notes at all.
    expect(note).toHaveValue("Documents unreadable");
  });

  it("clears the note once the action goes through", async () => {
    rejectOnboardingAction.mockResolvedValue({ type: "success", message: "Rejected." });
    render(<OnboardingReviewActions submissionId={ID} />);

    const note = screen.getByPlaceholderText(/Add a note/);
    fireEvent.change(note, { target: { value: "Documents unreadable" } });
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));

    expect(await screen.findByText("Rejected.")).toBeInTheDocument();
    expect(note).toHaveValue("");
    expect(rejectOnboardingAction).toHaveBeenCalledWith(ID, "Documents unreadable");
  });

  it("still says something when the action never reaches the server", async () => {
    approveOnboardingAction.mockRejectedValue(new Error("Failed to fetch"));
    render(<OnboardingReviewActions submissionId={ID} />);

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByText("Couldn't approve — try again.")).toBeInTheDocument();
  });

  it("reports a successful approval in the compact row too", async () => {
    approveOnboardingAction.mockResolvedValue({ type: "success", message: "Approved. Welcome email sent." });
    render(<OnboardingReviewActions submissionId={ID} variant="compact" />);

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(screen.getByText(/Approved/)).toBeInTheDocument());
  });
});
