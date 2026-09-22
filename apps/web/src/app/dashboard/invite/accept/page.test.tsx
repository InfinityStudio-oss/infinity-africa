import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// requireCurrentUser/getCurrentUser would redirect an unauthenticated
// visitor to /dashboard/login — the exact bug this page exists to fix. If
// the page ever starts calling either of these, these mocks throw, failing
// the test loudly instead of silently reintroducing the redirect-before-
// password-setup bug.
const requireCurrentUser = vi.fn(() => {
  throw new Error("requireCurrentUser must never be called on the invite-accept page");
});
const getCurrentUser = vi.fn(() => {
  throw new Error("getCurrentUser must never be called on the invite-accept page");
});

vi.mock("@/lib/auth/current-user", () => ({ requireCurrentUser, getCurrentUser }));

vi.mock("@/lib/portal/api", () => ({ acceptMyInvite: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

// The page renders the real AcceptInviteForm, which now establishes its
// own Supabase session from the URL (apps/web/src/lib/auth/recovery-link.ts)
// before showing the password fields — mock the client so that resolves,
// same pattern as accept-invite-form.test.tsx.
const setSession = vi.fn();
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { updateUser: vi.fn(), setSession, verifyOtp: vi.fn(), exchangeCodeForSession: vi.fn() } }),
}));

describe("MerchantInviteAcceptPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setSession.mockResolvedValue({ error: null });
    window.history.replaceState(null, "", "/dashboard/invite/accept#access_token=at&refresh_token=rt&type=invite");
  });

  it("renders the set-password form without any existing session or auth guard", async () => {
    const { default: MerchantInviteAcceptPage } = await import("./page");
    render(<MerchantInviteAcceptPage />);

    expect(screen.getByRole("heading", { name: "Set your password" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("New Password")).toBeInTheDocument());
    expect(screen.getByLabelText("Confirm Password")).toBeInTheDocument();
    expect(requireCurrentUser).not.toHaveBeenCalled();
    expect(getCurrentUser).not.toHaveBeenCalled();
  });
});
