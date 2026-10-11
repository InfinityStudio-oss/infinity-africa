import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Merchant } from "@/lib/admin/types";

const approveMerchantAction = vi.fn();
const setMerchantStatusAction = vi.fn();

vi.mock("@/lib/admin/live-actions", () => ({
  approveMerchantAction: (...args: unknown[]) => approveMerchantAction(...args),
  setMerchantStatusAction: (...args: unknown[]) => setMerchantStatusAction(...args),
}));

import { MerchantsTable } from "./merchants-table";

function merchant(overrides: Partial<Merchant> = {}): Merchant {
  return {
    merchant_id: "merchant-1",
    merchant_code: "27039828",
    business_name: "Oddza Dev",
    owner_name: "Jane Doe",
    email: "owner@oddza.co.tz",
    contact_phone: "+255700000000",
    nature_of_business: null,
    physical_address: null,
    account_status: "active",
    kyc_status: "verified",
    api_access_suspended: false,
    production_api_eligible: true,
    available_balance: "0.00",
    created_at: "2026-10-01T09:00:00Z",
    ...overrides,
  };
}

/** Reported as "when I click this button is not showing anything". The
 * audit log proved Suspend had fired four times — the action worked and
 * the UI said nothing, which is indistinguishable from a dead button. */
describe("MerchantsTable actions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("asks before suspending, rather than acting on one click", () => {
    render(<MerchantsTable rows={[merchant()]} />);

    fireEvent.click(screen.getByTitle("Suspend"));

    expect(screen.getByText(/Suspend Oddza Dev\?/)).toBeInTheDocument();
    expect(setMerchantStatusAction).not.toHaveBeenCalled();
  });

  it("suspends once confirmed", async () => {
    setMerchantStatusAction.mockResolvedValue({ error: null, ok: true, message: "Suspended." });
    render(<MerchantsTable rows={[merchant()]} />);

    fireEvent.click(screen.getByTitle("Suspend"));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(setMerchantStatusAction).toHaveBeenCalledWith("merchant-1", "suspended"));
  });

  it("drops the confirmation on Cancel without calling anything", () => {
    render(<MerchantsTable rows={[merchant()]} />);

    fireEvent.click(screen.getByTitle("Suspend"));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByTitle("Suspend")).toBeInTheDocument();
    expect(setMerchantStatusAction).not.toHaveBeenCalled();
  });

  it("shows why a suspend failed, and leaves the button there to retry", async () => {
    setMerchantStatusAction.mockResolvedValue({
      error: "Merchant status could not be updated.",
      ok: false,
      message: null,
    });
    render(<MerchantsTable rows={[merchant()]} />);

    fireEvent.click(screen.getByTitle("Suspend"));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText("Merchant status could not be updated.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();
  });

  it("confirms a successful reactivation", async () => {
    setMerchantStatusAction.mockResolvedValue({ error: null, ok: true, message: "Reactivated." });
    render(<MerchantsTable rows={[merchant({ account_status: "suspended" })]} />);

    fireEvent.click(screen.getByTitle("Reactivate"));

    expect(await screen.findByText("Reactivated.")).toBeInTheDocument();
    expect(setMerchantStatusAction).toHaveBeenCalledWith("merchant-1", "active");
  });

  it("surfaces an approval failure instead of swallowing it", async () => {
    approveMerchantAction.mockResolvedValue({ error: "No onboarding submission found.", ok: false, message: null });
    render(<MerchantsTable rows={[merchant({ account_status: "pending" })]} />);

    fireEvent.click(screen.getByTitle("Approve"));

    expect(await screen.findByText("No onboarding submission found.")).toBeInTheDocument();
  });
});
