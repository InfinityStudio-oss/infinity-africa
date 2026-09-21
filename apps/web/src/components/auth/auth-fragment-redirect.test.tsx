import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

describe("AuthFragmentRedirect", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, "", "/");
  });

  it("forwards a misdirected recovery hash fragment to the reset-password page", async () => {
    window.history.replaceState(null, "", "/#access_token=at&refresh_token=rt&type=recovery");
    const { AuthFragmentRedirect } = await import("./auth-fragment-redirect");
    render(<AuthFragmentRedirect />);

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/merchant/reset-password#access_token=at&refresh_token=rt&type=recovery"),
    );
  });

  it("forwards a misdirected invite hash fragment to the invite-accept page", async () => {
    window.history.replaceState(null, "", "/#access_token=at&refresh_token=rt&type=invite");
    const { AuthFragmentRedirect } = await import("./auth-fragment-redirect");
    render(<AuthFragmentRedirect />);

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/merchant/invite/accept#access_token=at&refresh_token=rt&type=invite"),
    );
  });

  it("forwards a misdirected ?token_hash=&type=recovery link", async () => {
    window.history.replaceState(null, "", "/?token_hash=th_abc&type=recovery");
    const { AuthFragmentRedirect } = await import("./auth-fragment-redirect");
    render(<AuthFragmentRedirect />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/merchant/reset-password?token_hash=th_abc&type=recovery"));
  });

  it("does nothing on a plain homepage visit with no auth params", async () => {
    const { AuthFragmentRedirect } = await import("./auth-fragment-redirect");
    render(<AuthFragmentRedirect />);

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(replace).not.toHaveBeenCalled();
  });

  it("does nothing for an unrecognized type", async () => {
    window.history.replaceState(null, "", "/#access_token=at&refresh_token=rt&type=signup");
    const { AuthFragmentRedirect } = await import("./auth-fragment-redirect");
    render(<AuthFragmentRedirect />);

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(replace).not.toHaveBeenCalled();
  });
});
