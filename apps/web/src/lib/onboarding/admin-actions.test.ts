/**
 * The review queue's three buttons have one job beyond doing the thing:
 * saying why, when the server refuses.
 *
 * They did not. A Server Action that throws never hands its message to
 * the browser — React's Flight client substitutes a placeholder, and in
 * production that placeholder reads "Minified React error #441". A Super
 * Admin pressing Approve on an unverified business got exactly that in
 * red, where "nobody has verified the login email …" should have been.
 *
 * So these hold the shape in place: a refusal is a RETURNED value, never
 * a thrown one, and the API's own sentence is what comes back.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const revalidatePath = vi.fn();
vi.mock("next/cache", () => ({ revalidatePath: (p: string) => revalidatePath(p) }));

const approveOnboardingSubmission = vi.fn();
const rejectOnboardingSubmission = vi.fn();
const requestMoreInfoOnboardingSubmission = vi.fn();

class OnboardingApiError extends Error {
  code?: string;
  constructor(message: string, code?: string) {
    super(message);
    this.code = code;
  }
}

vi.mock("./api", () => ({
  OnboardingApiError,
  approveOnboardingSubmission: (id: string) => approveOnboardingSubmission(id),
  rejectOnboardingSubmission: (id: string, note: string | null) => rejectOnboardingSubmission(id, note),
  requestMoreInfoOnboardingSubmission: (id: string, note: string | null) =>
    requestMoreInfoOnboardingSubmission(id, note),
}));

const ID = "11111111-2222-3333-4444-555555555555";
const GATE_MESSAGE =
  "Cannot approve: nobody has verified the login email owner@example.com. Fix it under Businesses - " +
  "resend the verification email, correct the address if it is wrong, or confirm it yourself - then approve.";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("the onboarding review actions", () => {
  it("returns the server's refusal instead of throwing it", async () => {
    const { approveOnboardingAction } = await import("./admin-actions");
    approveOnboardingSubmission.mockRejectedValue(new OnboardingApiError(GATE_MESSAGE, "validation_error"));

    // Not .rejects — the whole point is that this resolves.
    await expect(approveOnboardingAction(ID)).resolves.toEqual({
      type: "error",
      message: GATE_MESSAGE,
    });
  });

  it("does not revalidate the queue when nothing changed", async () => {
    const { approveOnboardingAction } = await import("./admin-actions");
    approveOnboardingSubmission.mockRejectedValue(new OnboardingApiError(GATE_MESSAGE));

    await approveOnboardingAction(ID);

    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("confirms an approval and refreshes both the queue and the detail page", async () => {
    const { approveOnboardingAction } = await import("./admin-actions");
    approveOnboardingSubmission.mockResolvedValue({ welcome_email_warning: null });

    const outcome = await approveOnboardingAction(ID);

    expect(outcome.type).toBe("success");
    expect(outcome.message).toMatch(/Approved/);
    expect(revalidatePath).toHaveBeenCalledWith("/super-admin/onboarding");
    expect(revalidatePath).toHaveBeenCalledWith(`/super-admin/onboarding/${ID}`);
  });

  it("flags an approval whose welcome email could not be sent, without calling it a failure", async () => {
    const { approveOnboardingAction } = await import("./admin-actions");
    approveOnboardingSubmission.mockResolvedValue({
      welcome_email_warning: "Approved, but the welcome email could not be sent.",
    });

    const outcome = await approveOnboardingAction(ID);

    expect(outcome).toEqual({
      type: "warning",
      message: "Approved, but the welcome email could not be sent.",
    });
    // It DID happen, so the queue must refresh.
    expect(revalidatePath).toHaveBeenCalledWith("/super-admin/onboarding");
  });

  it("hides an unexpected failure behind a plain sentence", async () => {
    const { approveOnboardingAction } = await import("./admin-actions");
    // Not an OnboardingApiError: a dropped connection, a bug, a stack
    // trace. None of that belongs on a Super Admin's screen.
    approveOnboardingSubmission.mockRejectedValue(new TypeError("fetch failed: ECONNREFUSED 10.0.0.4:8080"));

    await expect(approveOnboardingAction(ID)).resolves.toEqual({
      type: "error",
      message: "Couldn't approve — try again.",
    });
  });

  it("reports a rejection's refusal too, and passes the note through", async () => {
    const { rejectOnboardingAction } = await import("./admin-actions");
    rejectOnboardingSubmission.mockRejectedValue(new OnboardingApiError("Already rejected."));

    await expect(rejectOnboardingAction(ID, "Documents unreadable")).resolves.toEqual({
      type: "error",
      message: "Already rejected.",
    });
    expect(rejectOnboardingSubmission).toHaveBeenCalledWith(ID, "Documents unreadable");
  });

  it("reports a request-more-info refusal too", async () => {
    const { requestInfoOnboardingAction } = await import("./admin-actions");
    requestMoreInfoOnboardingSubmission.mockRejectedValue(new OnboardingApiError("Nothing to ask for."));

    await expect(requestInfoOnboardingAction(ID, null)).resolves.toEqual({
      type: "error",
      message: "Nothing to ask for.",
    });
  });
});
