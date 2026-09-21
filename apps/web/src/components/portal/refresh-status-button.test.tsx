import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RefreshStatusButton } from "./refresh-status-button";

describe("RefreshStatusButton", () => {
  it("shows the loading label while the refresh call is in flight, then calls onResult", async () => {
    let resolveRefresh: (value: { status: string }) => void = () => {};
    const onRefresh = vi.fn(
      () =>
        new Promise<{ status: string }>((resolve) => {
          resolveRefresh = resolve;
        }),
    );
    const onResult = vi.fn();

    render(<RefreshStatusButton onRefresh={onRefresh} onResult={onResult} />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));

    expect(await screen.findByRole("button", { name: "Checking payment status…" })).toBeInTheDocument();

    resolveRefresh({ status: "successful" });
    await waitFor(() => expect(onResult).toHaveBeenCalledWith({ status: "successful" }));
    expect(await screen.findByText("Payment completed")).toBeInTheDocument();
  });

  it("shows a pending message when the refresh confirms Selcom still hasn't completed it", async () => {
    const onRefresh = vi.fn().mockResolvedValue({ status: "processing" });

    render(<RefreshStatusButton onRefresh={onRefresh} onResult={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));

    expect(await screen.findByText("Payment still pending with Selcom")).toBeInTheDocument();
  });

  it.each([
    ["CANCELLED", "Payment cancelled"],
    ["USERCANCELLED", "Payment cancelled by customer"],
    ["REJECTED", "Payment rejected"],
  ])("shows distinct copy for a failed refresh with provider_payment_status=%s", async (providerStatus, expected) => {
    const onRefresh = vi.fn().mockResolvedValue({ status: "failed", provider_payment_status: providerStatus });

    render(<RefreshStatusButton onRefresh={onRefresh} onResult={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));

    expect(await screen.findByText(expected)).toBeInTheDocument();
  });

  it("appends the failure_reason when present", async () => {
    const onRefresh = vi.fn().mockResolvedValue({
      status: "failed",
      provider_payment_status: "REJECTED",
      failure_reason: "Insufficient funds",
    });

    render(<RefreshStatusButton onRefresh={onRefresh} onResult={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));

    expect(await screen.findByText("Payment rejected: Insufficient funds")).toBeInTheDocument();
  });

  it("shows an error message and never calls onResult if the refresh call throws", async () => {
    const onRefresh = vi.fn().mockRejectedValue(new Error("Couldn't reach InfinityPay."));
    const onResult = vi.fn();

    render(<RefreshStatusButton onRefresh={onRefresh} onResult={onResult} />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));

    expect(await screen.findByText("Couldn't reach InfinityPay.")).toBeInTheDocument();
    expect(onResult).not.toHaveBeenCalled();
  });
});
