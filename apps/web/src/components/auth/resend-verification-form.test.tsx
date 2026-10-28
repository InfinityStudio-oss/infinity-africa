import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

describe("ResendVerificationForm", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { message: "ok" } }),
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  it("renders an email field and a Send Verification Link button", async () => {
    const { ResendVerificationForm } = await import("./resend-verification-form");
    render(<ResendVerificationForm />);

    expect(screen.getByPlaceholderText("you@business.co.tz")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send Verification Link" })).toBeInTheDocument();
  });

  it("posts the address to the backend and shows the generic confirmation", async () => {
    const { ResendVerificationForm } = await import("./resend-verification-form");
    render(<ResendVerificationForm />);

    fireEvent.change(screen.getByPlaceholderText("you@business.co.tz"), {
      target: { value: "merchant@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send Verification Link" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/v1/auth/resend-verification");
    expect(JSON.parse(init.body)).toEqual({ email: "merchant@example.com" });
    await waitFor(() =>
      expect(screen.getByText(/If that account still needs verification/)).toBeInTheDocument(),
    );
  });

  it("sends no destination of its own — the backend fixes where the link goes", async () => {
    const { ResendVerificationForm } = await import("./resend-verification-form");
    render(<ResendVerificationForm />);

    fireEvent.change(screen.getByPlaceholderText("you@business.co.tz"), {
      target: { value: "merchant@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send Verification Link" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(Object.keys(JSON.parse(fetchMock.mock.calls[0][1].body))).toEqual(["email"]);
  });

  it("rejects an invalid email without calling the backend", async () => {
    const { ResendVerificationForm } = await import("./resend-verification-form");
    render(<ResendVerificationForm />);

    fireEvent.change(screen.getByPlaceholderText("you@business.co.tz"), {
      target: { value: "not-an-email" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send Verification Link" }));

    await waitFor(() => expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument());
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the same message when the request fails outright", async () => {
    // A network failure that showed something different would tell a
    // caller the address was not found, which is the one thing this
    // screen must never do.
    fetchMock.mockRejectedValue(new Error("network down"));
    const { ResendVerificationForm } = await import("./resend-verification-form");
    render(<ResendVerificationForm />);

    fireEvent.change(screen.getByPlaceholderText("you@business.co.tz"), {
      target: { value: "merchant@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send Verification Link" }));

    await waitFor(() =>
      expect(screen.getByText(/If that account still needs verification/)).toBeInTheDocument(),
    );
  });
});
