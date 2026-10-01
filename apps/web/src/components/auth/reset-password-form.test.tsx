import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const updateUser = vi.fn();
const signOut = vi.fn();
const setSession = vi.fn();
const verifyOtp = vi.fn();
const exchangeCodeForSession = vi.fn();
const getSession = vi.fn();
const getAuthenticatorAssuranceLevel = vi.fn();
const listFactors = vi.fn();
const challenge = vi.fn();
const verify = vi.fn();
const push = vi.fn();

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: {
      updateUser,
      signOut,
      setSession,
      verifyOtp,
      exchangeCodeForSession,
      getSession,
      mfa: { getAuthenticatorAssuranceLevel, listFactors, challenge, verify },
    },
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
    // No MFA by default: a merchant account.
    getAuthenticatorAssuranceLevel.mockResolvedValue({ data: { currentLevel: "aal1", nextLevel: "aal1" } });
    listFactors.mockResolvedValue({ data: { totp: [{ id: "f1", status: "verified" }] }, error: null });
    challenge.mockResolvedValue({ data: { id: "c1" }, error: null });
    verify.mockResolvedValue({ error: null });
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







  // --- MFA-enabled accounts ------------------------------------------------
  //
  // Supabase refuses updateUser from an aal1 session when MFA is on, and a
  // recovery session is always aal1. The whole reset flow failed on this
  // for days, at the last possible moment, behind a message blaming the
  // link.

  function requireMfa() {
    getAuthenticatorAssuranceLevel.mockResolvedValue({
      data: { currentLevel: "aal1", nextLevel: "aal2" },
    });
  }

  it("asks for the authenticator code before the password form, not after", async () => {
    requireMfa();
    setValidRecoveryLinkUrl();
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("Authentication Code")).toBeInTheDocument());
    expect(screen.queryByLabelText("New Password")).not.toBeInTheDocument();
  });

  it("a correct code unlocks the password form", async () => {
    requireMfa();
    setValidRecoveryLinkUrl();
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("Authentication Code")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Authentication Code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByText("Continue"));

    await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());
    expect(verify).toHaveBeenCalledWith({ factorId: "f1", challengeId: "c1", code: "123456" });
  });

  it("a wrong code fails safely and keeps the password form shut", async () => {
    requireMfa();
    verify.mockResolvedValue({ error: { message: "Invalid TOTP code entered" } });
    setValidRecoveryLinkUrl();
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("Authentication Code")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Authentication Code"), { target: { value: "000000" } });
    fireEvent.click(screen.getByText("Continue"));

    await waitFor(() => expect(screen.getByText(/code isn't valid/)).toBeInTheDocument());
    expect(screen.queryByLabelText("New Password")).not.toBeInTheDocument();
  });

  it("never reveals whether a wrong code hit a live challenge", async () => {
    // One message for a wrong code and an expired challenge alike.
    requireMfa();
    challenge.mockResolvedValue({ data: null, error: { message: "challenge expired" } });
    setValidRecoveryLinkUrl();
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("Authentication Code")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Authentication Code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByText("Continue"));

    await waitFor(() => expect(screen.getByText(/code isn't valid/)).toBeInTheDocument());
    expect(screen.queryByText(/expired challenge|challenge expired/)).not.toBeInTheDocument();
  });

  it("offers no bypass when MFA is demanded but nothing is enrolled", async () => {
    requireMfa();
    listFactors.mockResolvedValue({ data: { totp: [] }, error: null });
    setValidRecoveryLinkUrl();
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("Authentication Code")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Authentication Code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByText("Continue"));

    await waitFor(() => expect(screen.getByText(/Ask another Super Admin/)).toBeInTheDocument());
    expect(screen.queryByLabelText("New Password")).not.toBeInTheDocument();
    expect(updateUser).not.toHaveBeenCalled();
  });

  it("a merchant without MFA still goes straight to the password form", async () => {
    setValidRecoveryLinkUrl();
    const { ResetPasswordForm } = await import("./reset-password-form");
    render(<ResetPasswordForm />);

    await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());
    expect(screen.queryByLabelText("Authentication Code")).not.toBeInTheDocument();
  });
});
