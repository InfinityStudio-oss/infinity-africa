import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

describe("ForgotPasswordForm", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { message: "If an account exists, we've sent password reset instructions." } }),
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  it("renders an email field and a Send Reset Link button", async () => {
    const { ForgotPasswordForm } = await import("./forgot-password-form");
    render(<ForgotPasswordForm />);

    expect(screen.getByPlaceholderText("you@business.co.tz")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send Reset Link" })).toBeInTheDocument();
  });

  it("posts to the backend forgot-password endpoint and shows the generic confirmation message", async () => {
    const { ForgotPasswordForm } = await import("./forgot-password-form");
    render(<ForgotPasswordForm />);

    fireEvent.change(screen.getByPlaceholderText("you@business.co.tz"), {
      target: { value: "merchant@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send Reset Link" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/v1/auth/forgot-password");
    expect(JSON.parse(init.body)).toEqual({
      email: "merchant@example.com",
      redirect_path: "/dashboard/reset-password",
    });
    await waitFor(() =>
      expect(screen.getByText(/If an account exists, we've sent password reset instructions\./)).toBeInTheDocument(),
    );
  });

  it("sends the admin redirect path when configured for the admin login flow", async () => {
    const { ForgotPasswordForm } = await import("./forgot-password-form");
    render(<ForgotPasswordForm resetPasswordPath="/admin-login/reset-password" />);

    fireEvent.change(screen.getByPlaceholderText("you@business.co.tz"), { target: { value: "admin@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send Reset Link" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).redirect_path).toBe("/admin-login/reset-password");
  });

  it("rejects an invalid email without calling the backend", async () => {
    const { ForgotPasswordForm } = await import("./forgot-password-form");
    render(<ForgotPasswordForm />);

    fireEvent.change(screen.getByPlaceholderText("you@business.co.tz"), { target: { value: "not-an-email" } });
    fireEvent.click(screen.getByRole("button", { name: "Send Reset Link" }));

    await waitFor(() => expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument());
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("still shows the generic confirmation message even if the request fails outright", async () => {
    fetchMock.mockRejectedValue(new Error("network down"));
    const { ForgotPasswordForm } = await import("./forgot-password-form");
    render(<ForgotPasswordForm />);

    fireEvent.change(screen.getByPlaceholderText("you@business.co.tz"), { target: { value: "merchant@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send Reset Link" }));

    await waitFor(() =>
      expect(screen.getByText(/If an account exists, we've sent password reset instructions\./)).toBeInTheDocument(),
    );
  });
});
