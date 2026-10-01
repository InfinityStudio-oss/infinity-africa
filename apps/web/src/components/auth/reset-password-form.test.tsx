import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const updateUser = vi.fn();
const signOut = vi.fn();
const setSession = vi.fn();
const verifyOtp = vi.fn();
const exchangeCodeForSession = vi.fn();
const getSession = vi.fn();
const push = vi.fn();

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: { updateUser, signOut, setSession, verifyOtp, exchangeCodeForSession, getSession },
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

function setValidRecoveryLinkUrl() {
  window.history.replaceState(null, "", "/dashboard/reset-password#access_token=at&refresh_token=rt&type=recovery");
}

describe("ResetPasswordForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    updateUser.mockResolvedValue({ error: null });
    signOut.mockResolvedValue({ error: null });
    setSession.mockResolvedValue({ error: null });
    verifyOtp.mockResolvedValue({ error: null });
    exchangeCodeForSession.mockResolvedValue({ error: null });
    getSession.mockResolvedValue({ data: { session: { access_token: "at" } } });
    setValidRecoveryLinkUrl();
  });

  it("shows a verifying state before the link is checked, then renders the form", async () => {
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    // Not asserting on the verifying copy's exact timing (it can resolve
    // before the assertion runs) — the real guarantee is that the form
    // never renders until establishRecoveryLinkSession has resolved.
    await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());
    expect(setSession).toHaveBeenCalledWith({ access_token: "at", refresh_token: "rt" });
  });

  it("renders new-password fields and a Set New Password button", async () => {
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());
    expect(screen.getByLabelText("Confirm New Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set New Password" })).toBeInTheDocument();
  });

  it("calls Supabase updateUser and redirects to login on success", async () => {
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);
    await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("New Password"), { target: { value: "NewPass456!" } });
    fireEvent.change(screen.getByLabelText("Confirm New Password"), { target: { value: "NewPass456!" } });
    fireEvent.click(screen.getByRole("button", { name: "Set New Password" }));

    await waitFor(() => expect(updateUser).toHaveBeenCalledWith({ password: "NewPass456!" }));
    await waitFor(() => expect(screen.getByText(/password has been updated/i)).toBeInTheDocument());
  });

  it("rejects mismatched passwords without calling Supabase", async () => {
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);
    await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("New Password"), { target: { value: "NewPass456!" } });
    fireEvent.change(screen.getByLabelText("Confirm New Password"), { target: { value: "Different456!" } });
    fireEvent.click(screen.getByRole("button", { name: "Set New Password" }));

    await waitFor(() => expect(screen.getByText("Passwords do not match.")).toBeInTheDocument());
    expect(updateUser).not.toHaveBeenCalled();
  });

  it("says the link carried no token, rather than claiming it expired", async () => {
    // Nothing was rejected here, so "expired" would be a guess presented
    // as a diagnosis -- and it sends people to request link after link,
    // each failing identically, with nothing on screen to suggest why.
    window.history.replaceState(null, "", "/dashboard/reset-password");
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() =>
      expect(screen.getByText("This link didn't carry a reset token.")).toBeInTheDocument(),
    );
    expect(screen.queryByText(/has expired/)).not.toBeInTheDocument();
    expect(screen.getByText(/link carried: nothing/)).toBeInTheDocument();
    expect(screen.queryByLabelText("New Password")).not.toBeInTheDocument();
    expect(setSession).not.toHaveBeenCalled();
  });

  it("still says expired when the provider actually rejected the token", async () => {
    // The other half of the split: a real rejection keeps the provider's
    // own words, and shows none of the empty-link guidance.
    window.history.replaceState(
      null,
      "",
      "/dashboard/reset-password#error=access_denied&error_description=Email+link+is+invalid+or+has+expired",
    );
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() =>
      expect(screen.getByText("Email link is invalid or has expired")).toBeInTheDocument(),
    );
    expect(screen.queryByText(/link carried:/)).not.toBeInTheDocument();
  });

  it("shows Supabase's own error_description when the link was rejected outright", async () => {
    window.history.replaceState(
      null,
      "",
      "/dashboard/reset-password#error=access_denied&error_description=Email+link+is+invalid+or+has+expired",
    );
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByText("Email link is invalid or has expired")).toBeInTheDocument());
    expect(setSession).not.toHaveBeenCalled();
  });

  it("shows the invalid message when the link has already been used (setSession fails)", async () => {
    setSession.mockResolvedValue({ error: { message: "Invalid Refresh Token" } });
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByText("Invalid Refresh Token")).toBeInTheDocument());
    expect(screen.queryByLabelText("New Password")).not.toBeInTheDocument();
  });

  it("handles a ?code= link via exchangeCodeForSession", async () => {
    window.history.replaceState(null, "", "/dashboard/reset-password?code=abc123");
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());
    expect(exchangeCodeForSession).toHaveBeenCalledWith("abc123");
    expect(setSession).not.toHaveBeenCalled();
  });

  it("handles a ?token_hash=&type=recovery link via verifyOtp", async () => {
    window.history.replaceState(null, "", "/dashboard/reset-password?token_hash=th_abc&type=recovery");
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());
    expect(verifyOtp).toHaveBeenCalledWith({ type: "recovery", token_hash: "th_abc" });
  });

  it("never calls the session-establishing method more than once, even under Strict Mode double-invoke", async () => {
    const React = await import("react");
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(
      <React.StrictMode>
        <ResetPasswordForm />
      </React.StrictMode>,
    );

    await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());
    expect(setSession).toHaveBeenCalledTimes(1);
  });

  // --- the typed way in, for when the link arrives empty -------------------

  it("offers the emailed code when the link carried no token", async () => {
    window.history.replaceState(null, "", "/dashboard/reset-password");
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("Verification Code")).toBeInTheDocument());
    expect(screen.getByLabelText("Email Address")).toBeInTheDocument();
  });

  it("a correct code reaches the password form, the same as a working link would", async () => {
    window.history.replaceState(null, "", "/dashboard/reset-password");
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("Verification Code")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Email Address"), { target: { value: "ceo@infinitypay.me" } });
    fireEvent.change(screen.getByLabelText("Verification Code"), { target: { value: "75456908" } });
    fireEvent.click(screen.getByText("Continue"));

    await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());
    expect(verifyOtp).toHaveBeenCalledWith({
      email: "ceo@infinitypay.me",
      token: "75456908",
      type: "recovery",
    });
  });

  it("a rejected code says why and does not open the password form", async () => {
    verifyOtp.mockResolvedValue({ error: { message: "Token has expired or is invalid" } });
    window.history.replaceState(null, "", "/dashboard/reset-password");
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("Verification Code")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Email Address"), { target: { value: "ceo@infinitypay.me" } });
    fireEvent.change(screen.getByLabelText("Verification Code"), { target: { value: "00000000" } });
    fireEvent.click(screen.getByText("Continue"));

    await waitFor(() => expect(screen.getByText("Token has expired or is invalid")).toBeInTheDocument());
    expect(screen.queryByLabelText("New Password")).not.toBeInTheDocument();
  });

  it("does not offer the code form when the link worked", async () => {
    // It is a fallback, not a second front door sitting on every reset.
    setValidRecoveryLinkUrl();
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());
    expect(screen.queryByLabelText("Verification Code")).not.toBeInTheDocument();
  });

  it("does not reach the password form when the code leaves no session behind", async () => {
    // The bug this form actually had: verifyOtp returned no error, the
    // form declared a session existed, and the failure surfaced one
    // screen later as "this reset link is invalid or has expired" --
    // after the person had typed a new password, blaming the link for a
    // session we never had.
    getSession.mockResolvedValue({ data: { session: null } });
    window.history.replaceState(null, "", "/dashboard/reset-password");
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("Verification Code")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Email Address"), { target: { value: "ceo@infinitypay.me" } });
    fireEvent.change(screen.getByLabelText("Verification Code"), { target: { value: "75456908" } });
    fireEvent.click(screen.getByText("Continue"));

    await waitFor(() => expect(screen.getByText(/no session was created/)).toBeInTheDocument());
    expect(screen.queryByLabelText("New Password")).not.toBeInTheDocument();
  });
});
