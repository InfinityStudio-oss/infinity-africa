import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const updateUser = vi.fn();
const setSession = vi.fn();
const verifyOtp = vi.fn();
const exchangeCodeForSession = vi.fn();
const push = vi.fn();
const acceptMyInvite = vi.fn();

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: { updateUser, setSession, verifyOtp, exchangeCodeForSession },
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/portal/api", () => ({
  acceptMyInvite: (...args: unknown[]) => acceptMyInvite(...args),
}));

const INVALID_INVITE_MESSAGE = "Invitation expired or invalid. Please ask your account admin to send a new invitation.";

function setValidInviteLinkUrl() {
  window.history.replaceState(null, "", "/dashboard/invite/accept#access_token=at&refresh_token=rt&type=invite");
}

async function renderReady() {
  const { AcceptInviteForm } = await import("./accept-invite-form");
  render(<AcceptInviteForm />);
  await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());
}

describe("AcceptInviteForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    updateUser.mockResolvedValue({ error: null });
    setSession.mockResolvedValue({ error: null });
    verifyOtp.mockResolvedValue({ error: null });
    exchangeCodeForSession.mockResolvedValue({ error: null });
    acceptMyInvite.mockResolvedValue({ id: "row-1", status: "active" });
    setValidInviteLinkUrl();
  });

  it("renders new-password fields and a Set Password button", async () => {
    await renderReady();

    expect(screen.getByLabelText("Confirm Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set Password" })).toBeInTheDocument();
    expect(setSession).toHaveBeenCalledWith({ access_token: "at", refresh_token: "rt" });
  });

  it("calls Supabase updateUser, then links the staff member to their merchant, then shows success", async () => {
    await renderReady();

    fireEvent.change(screen.getByLabelText("New Password"), { target: { value: "NewPass456!" } });
    fireEvent.change(screen.getByLabelText("Confirm Password"), { target: { value: "NewPass456!" } });
    fireEvent.click(screen.getByRole("button", { name: "Set Password" }));

    await waitFor(() => expect(updateUser).toHaveBeenCalledWith({ password: "NewPass456!" }));
    await waitFor(() => expect(acceptMyInvite).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Merchant Portal/i)).toBeInTheDocument();
  });

  it("redirects to the merchant portal (not login) after successfully accepting", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { AcceptInviteForm } = await import("./accept-invite-form");
    render(<AcceptInviteForm portalPath="/dashboard/overview" />);
    await vi.waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("New Password"), { target: { value: "NewPass456!" } });
    fireEvent.change(screen.getByLabelText("Confirm Password"), { target: { value: "NewPass456!" } });
    fireEvent.click(screen.getByRole("button", { name: "Set Password" }));

    await vi.waitFor(() => expect(acceptMyInvite).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(1500);

    expect(push).toHaveBeenCalledWith("/dashboard/overview");
    vi.useRealTimers();
  });

  it("rejects mismatched passwords without calling Supabase", async () => {
    await renderReady();

    fireEvent.change(screen.getByLabelText("New Password"), { target: { value: "NewPass456!" } });
    fireEvent.change(screen.getByLabelText("Confirm Password"), { target: { value: "Different456!" } });
    fireEvent.click(screen.getByRole("button", { name: "Set Password" }));

    await waitFor(() => expect(screen.getByText("Passwords do not match.")).toBeInTheDocument());
    expect(updateUser).not.toHaveBeenCalled();
  });

  it("does not ask for an old/current password anywhere on the form", async () => {
    await renderReady();

    expect(screen.queryByLabelText(/current password/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/old password/i)).not.toBeInTheDocument();
  });

  it("shows a friendly expired/invalid message, never redirecting to login automatically, when the link carries an error hash", async () => {
    window.history.replaceState(
      null,
      "",
      "/dashboard/invite/accept#error=access_denied&error_description=Email+link+is+invalid+or+has+expired",
    );
    const { AcceptInviteForm } = await import("./accept-invite-form");
    render(<AcceptInviteForm />);

    expect(await screen.findByText("Email link is invalid or has expired")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to login" })).toBeInTheDocument();
    expect(screen.queryByLabelText("New Password")).not.toBeInTheDocument();
    expect(updateUser).not.toHaveBeenCalled();
  });

  it("shows the fallback invalid-invite message when the link carries no usable token at all", async () => {
    window.history.replaceState(null, "", "/dashboard/invite/accept");
    const { AcceptInviteForm } = await import("./accept-invite-form");
    render(<AcceptInviteForm />);

    expect(await screen.findByText(INVALID_INVITE_MESSAGE)).toBeInTheDocument();
    expect(setSession).not.toHaveBeenCalled();
  });

  it("shows the invalid message when the invite link has already been used (setSession fails)", async () => {
    setSession.mockResolvedValue({ error: { message: "Invalid Refresh Token" } });
    const { AcceptInviteForm } = await import("./accept-invite-form");
    render(<AcceptInviteForm />);

    expect(await screen.findByText("Invalid Refresh Token")).toBeInTheDocument();
    expect(screen.queryByLabelText("New Password")).not.toBeInTheDocument();
  });

  it("accepts a resend-invite link, which reuses the recovery OTP type", async () => {
    window.history.replaceState(null, "", "/dashboard/invite/accept#access_token=at&refresh_token=rt&type=recovery");
    await renderReady();

    expect(setSession).toHaveBeenCalledWith({ access_token: "at", refresh_token: "rt" });
  });

  it("handles a ?token_hash=&type=invite link via verifyOtp", async () => {
    window.history.replaceState(null, "", "/dashboard/invite/accept?token_hash=th_abc&type=invite");
    await renderReady();

    expect(verifyOtp).toHaveBeenCalledWith({ type: "invite", token_hash: "th_abc" });
  });

  it("shows the same friendly message when updateUser itself reports a dead/expired session", async () => {
    updateUser.mockResolvedValue({ error: { message: "Auth session missing" } });
    await renderReady();

    fireEvent.change(screen.getByLabelText("New Password"), { target: { value: "NewPass456!" } });
    fireEvent.change(screen.getByLabelText("Confirm Password"), { target: { value: "NewPass456!" } });
    fireEvent.click(screen.getByRole("button", { name: "Set Password" }));

    expect(await screen.findByText(INVALID_INVITE_MESSAGE)).toBeInTheDocument();
    expect(acceptMyInvite).not.toHaveBeenCalled();
  });

  it("shows a recoverable error, not a silent failure, when the password is set but linking the staff account fails", async () => {
    acceptMyInvite.mockRejectedValue(new Error("No pending invitation found for your account"));
    await renderReady();

    fireEvent.change(screen.getByLabelText("New Password"), { target: { value: "NewPass456!" } });
    fireEvent.change(screen.getByLabelText("Confirm Password"), { target: { value: "NewPass456!" } });
    fireEvent.click(screen.getByRole("button", { name: "Set Password" }));

    await waitFor(() => expect(updateUser).toHaveBeenCalled());
    expect(await screen.findByText(/Your password was set/i)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("never calls the session-establishing method more than once, even under Strict Mode double-invoke", async () => {
    const React = await import("react");
    const { AcceptInviteForm } = await import("./accept-invite-form");
    render(
      <React.StrictMode>
        <AcceptInviteForm />
      </React.StrictMode>,
    );

    await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());
    expect(setSession).toHaveBeenCalledTimes(1);
  });
});
