import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminPayoutRow } from "@/lib/admin/types";

vi.mock("@/lib/admin/live-actions", () => ({
  releasePayoutAction: vi.fn(),
}));

function row(overrides: Partial<AdminPayoutRow> = {}): AdminPayoutRow {
  return {
    id: "payout-1",
    merchant_id: "merchant-1",
    business_name: "Merchant",
    merchant_code: "27000006",
    environment: "sandbox",
    status: "needs_reconciliation",
    amount: "1000.00",
    fee_amount: "10.00",
    total_debit: "1010.00",
    currency: "TZS",
    failure_code: "provider_unreachable",
    failure_reason: "The provider request did not complete (SelcomAPIError).",
    provider_acknowledged: false,
    dispatch_attempts: 4,
    created_at: "2026-11-21T21:37:00Z",
    completed_at: null,
    ...overrides,
  };
}

describe("Releasing a stuck payout", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    // clearAllMocks drops the implementation too, so an unstubbed call
    // resolves to undefined and the component throws on result.error.
    // That is a test artefact, not a product bug - the action always
    // returns a state object - but it surfaces as an unhandled error
    // that can mask a real one.
    const { releasePayoutAction } = await import("@/lib/admin/live-actions");
    vi.mocked(releasePayoutAction).mockResolvedValue({ error: null });
  });

  it("never releases on a single click", async () => {
    const { releasePayoutAction } = await import("@/lib/admin/live-actions");
    const { StuckPayoutsTable } = await import("./stuck-payouts-table");

    render(<StuckPayoutsTable rows={[row()]} />);
    fireEvent.click(screen.getByRole("button", { name: "Release funds" }));

    expect(releasePayoutAction).not.toHaveBeenCalled();
    expect(screen.getByText(/Only do this if you know the provider did not pay/)).toBeInTheDocument();
  });

  it("will not release without a written reason", async () => {
    const { releasePayoutAction } = await import("@/lib/admin/live-actions");
    const { StuckPayoutsTable } = await import("./stuck-payouts-table");

    render(<StuckPayoutsTable rows={[row()]} />);
    fireEvent.click(screen.getByRole("button", { name: "Release funds" }));

    // The reason is the only record of the judgement being made, so the
    // button stays disabled until there is one.
    const confirm = screen.getAllByRole("button", { name: "Release funds" })[0];
    fireEvent.click(confirm);
    expect(releasePayoutAction).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole("textbox", { name: /Reason for releasing/ }), {
      target: { value: "Selcom confirmed the request never reached them." },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Release funds" })[0]);

    await waitFor(() =>
      expect(releasePayoutAction).toHaveBeenCalledWith(
        "payout-1",
        "Selcom confirmed the request never reached them.",
      ),
    );
  });

  it("offers no release at all when the provider acknowledged the payout", async () => {
    const { StuckPayoutsTable } = await import("./stuck-payouts-table");
    render(<StuckPayoutsTable rows={[row({ provider_acknowledged: true })]} />);

    // The backend refuses these, and a button that exists only to
    // produce an error teaches an operator to click through errors.
    expect(screen.queryByRole("button", { name: "Release funds" })).not.toBeInTheDocument();
    expect(screen.getByText(/Settle it with them/)).toBeInTheDocument();
  });

  it("names the business and the amount in the confirmation", async () => {
    const { StuckPayoutsTable } = await import("./stuck-payouts-table");
    render(<StuckPayoutsTable rows={[row({ business_name: "UHURU NET" })]} />);

    fireEvent.click(screen.getByRole("button", { name: "Release funds" }));

    // Scoped to the confirmation: the name is also in the Business
    // column, and an unscoped match would pass even if the confirmation
    // never named anyone — which is the whole point of it.
    const confirmation = screen.getByText(/Return TZS 1,010.00 to/);
    expect(confirmation).toHaveTextContent("UHURU NET");
    expect(confirmation).toHaveTextContent(/Only do this if you know the provider did not pay/);
  });

  it("surfaces a refusal from the server", async () => {
    const { releasePayoutAction } = await import("@/lib/admin/live-actions");
    vi.mocked(releasePayoutAction).mockResolvedValue({
      error: "The provider has acknowledged this payout, so it may have been paid.",
    });
    const { StuckPayoutsTable } = await import("./stuck-payouts-table");

    render(<StuckPayoutsTable rows={[row()]} />);
    fireEvent.click(screen.getByRole("button", { name: "Release funds" }));
    fireEvent.change(screen.getByRole("textbox", { name: /Reason for releasing/ }), {
      target: { value: "I believe this one failed outright." },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Release funds" })[0]);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("may have been paid"));
  });

  it("says plainly when nothing needs a decision", async () => {
    const { StuckPayoutsTable } = await import("./stuck-payouts-table");
    render(<StuckPayoutsTable rows={[]} />);

    expect(screen.getByText(/No payout is waiting on a decision/)).toBeInTheDocument();
  });
});
