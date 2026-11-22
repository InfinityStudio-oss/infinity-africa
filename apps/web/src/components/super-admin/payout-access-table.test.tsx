import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminPayoutAccessRow } from "@/lib/admin/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/admin/live-actions", () => ({
  setPayoutSandboxAction: vi.fn(),
  setPayoutLiveAction: vi.fn(),
  setPayoutPauseAction: vi.fn(),
  setPayoutFeeAction: vi.fn(),
}));

function row(overrides: Partial<AdminPayoutAccessRow> = {}): AdminPayoutAccessRow {
  return {
    merchant_id: "merchant-1",
    business_name: "Merchant",
    merchant_code: "27413765",
    enabled: true,
    sandbox_enabled: true,
    live_enabled: false,
    paused: false,
    paused_reason: null,
    per_payout_limit_tzs: null,
    daily_limit_tzs: null,
    fee_flat_tzs: null,
    fee_percentage: null,
    access_requested_at: null,
    version: 3,
    updated_at: "2026-11-21T17:03:45Z",
    wallet_available: "10000.00",
    wallet_reserved: "0",
    wallet_environment: "sandbox",
    ...overrides,
  };
}

describe("Super Admin payout access", () => {
  beforeEach(() => vi.clearAllMocks());

  it("switches the sandbox in one click — it only spends play money", async () => {
    const { setPayoutSandboxAction } = await import("@/lib/admin/live-actions");
    vi.mocked(setPayoutSandboxAction).mockResolvedValue({ error: null });
    const { PayoutAccessTable } = await import("./payout-access-table");

    render(<PayoutAccessTable rows={[row()]} />);
    fireEvent.click(screen.getByRole("switch", { name: "Sandbox payouts for Merchant" }));

    await waitFor(() => expect(setPayoutSandboxAction).toHaveBeenCalledWith("merchant-1", false, 3));
  });

  it("never grants live on a single click", async () => {
    const { setPayoutLiveAction } = await import("@/lib/admin/live-actions");
    vi.mocked(setPayoutLiveAction).mockResolvedValue({ error: null });
    const { PayoutAccessTable } = await import("./payout-access-table");

    render(<PayoutAccessTable rows={[row()]} />);
    fireEvent.click(screen.getByRole("switch", { name: "Live payouts for Merchant" }));

    // The click opens a confirmation. Nothing has been granted.
    expect(setPayoutLiveAction).not.toHaveBeenCalled();
    expect(screen.getByText(/real money/i)).toBeInTheDocument();
  });

  it("names the business in the live confirmation, so a wrong row is visible", async () => {
    const { PayoutAccessTable } = await import("./payout-access-table");
    render(<PayoutAccessTable rows={[row({ business_name: "GOOD NET" })]} />);

    fireEvent.click(screen.getByRole("switch", { name: "Live payouts for GOOD NET" }));

    // "Are you sure?" gets a reflex yes. The name is what makes the
    // operator look at which row they are on.
    expect(screen.getByText("GOOD NET", { selector: "span" })).toBeInTheDocument();
  });

  it("grants live once confirmed", async () => {
    const { setPayoutLiveAction } = await import("@/lib/admin/live-actions");
    vi.mocked(setPayoutLiveAction).mockResolvedValue({ error: null });
    const { PayoutAccessTable } = await import("./payout-access-table");

    render(<PayoutAccessTable rows={[row()]} />);
    fireEvent.click(screen.getByRole("switch", { name: "Live payouts for Merchant" }));
    fireEvent.click(screen.getByRole("button", { name: "Grant live" }));

    await waitFor(() => expect(setPayoutLiveAction).toHaveBeenCalledWith("merchant-1", true, 3));
  });

  it("withdraws live without any confirmation", async () => {
    const { setPayoutLiveAction } = await import("@/lib/admin/live-actions");
    vi.mocked(setPayoutLiveAction).mockResolvedValue({ error: null });
    const { PayoutAccessTable } = await import("./payout-access-table");

    render(<PayoutAccessTable rows={[row({ live_enabled: true })]} />);
    fireEvent.click(screen.getByRole("switch", { name: "Live payouts for Merchant" }));

    // Taking access away must never be harder than giving it.
    await waitFor(() => expect(setPayoutLiveAction).toHaveBeenCalledWith("merchant-1", false, 3));
  });

  it("will not pause without a reason", async () => {
    const { setPayoutPauseAction } = await import("@/lib/admin/live-actions");
    const { PayoutAccessTable } = await import("./payout-access-table");

    render(<PayoutAccessTable rows={[row()]} />);
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));

    const confirm = screen.getAllByRole("button", { name: "Pause" })[0];
    fireEvent.click(confirm);
    expect(setPayoutPauseAction).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole("textbox", { name: "Reason for pausing Merchant" }), {
      target: { value: "suspected key leak" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Pause" })[0]);

    await waitFor(() =>
      expect(setPayoutPauseAction).toHaveBeenCalledWith("merchant-1", true, 3, "suspected key leak"),
    );
  });

  it("says 'Standard (tariff)' rather than showing the tariff's number", async () => {
    const { PayoutAccessTable } = await import("./payout-access-table");
    render(<PayoutAccessTable rows={[row({ fee_percentage: null })]} />);

    // Printing "1%" here would read as this merchant's own negotiated
    // deal, and an operator would keep it while changing the tariff for
    // everyone else.
    expect(screen.getByText("Standard (tariff)")).toBeInTheDocument();
    expect(screen.queryByText("1%")).not.toBeInTheDocument();
  });

  it("shows a negotiated rate as that merchant's own", async () => {
    const { PayoutAccessTable } = await import("./payout-access-table");
    render(<PayoutAccessTable rows={[row({ fee_percentage: "0.5" })]} />);

    expect(screen.getByText("0.5%")).toBeInTheDocument();
    expect(screen.queryByText("Standard (tariff)")).not.toBeInTheDocument();
  });

  it("flags an absent daily limit, because nothing else caps the 24h total", async () => {
    const { PayoutAccessTable } = await import("./payout-access-table");
    render(<PayoutAccessTable rows={[row({ daily_limit_tzs: null })]} />);

    // authorize_payout skips the rolling check entirely when this is
    // null, so the wallet balance is the only ceiling left.
    expect(screen.getByText(/unlimited/)).toBeInTheDocument();
  });

  it("surfaces a refused change instead of swallowing it", async () => {
    const { setPayoutSandboxAction } = await import("@/lib/admin/live-actions");
    vi.mocked(setPayoutSandboxAction).mockResolvedValue({
      error: "These payout settings were changed by someone else.",
    });
    const { PayoutAccessTable } = await import("./payout-access-table");

    render(<PayoutAccessTable rows={[row()]} />);
    fireEvent.click(screen.getByRole("switch", { name: "Sandbox payouts for Merchant" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("changed by someone else"),
    );
  });

  it("gives each business its own controls", async () => {
    const { setPayoutSandboxAction } = await import("@/lib/admin/live-actions");
    vi.mocked(setPayoutSandboxAction).mockResolvedValue({ error: null });
    const { PayoutAccessTable } = await import("./payout-access-table");

    render(
      <PayoutAccessTable
        rows={[row(), row({ merchant_id: "merchant-2", business_name: "BennyWiFi", version: 7 })]}
      />,
    );

    fireEvent.click(screen.getByRole("switch", { name: "Sandbox payouts for BennyWiFi" }));

    await waitFor(() => expect(setPayoutSandboxAction).toHaveBeenCalledWith("merchant-2", false, 7));
  });

  it("explains an empty screen without implying everyone is switched on", async () => {
    const { PayoutAccessTable } = await import("./payout-access-table");
    render(<PayoutAccessTable rows={[]} />);

    // A blank screen on a money-permissions page should not be readable
    // as "everyone is allowed"; it has to say which way the default
    // falls, and that a row appearing here is not itself a grant.
    expect(screen.getByText(/No business has payout settings yet/)).toHaveTextContent(
      /not itself a grant/,
    );
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });
});
