import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Merchant } from "@/lib/admin/types";

const approveMerchantAction = vi.fn();
const setMerchantStatusAction = vi.fn();
const correctMerchantContactEmailAction = vi.fn();

vi.mock("@/lib/admin/live-actions", () => ({
  approveMerchantAction: (...args: unknown[]) => approveMerchantAction(...args),
  setMerchantStatusAction: (...args: unknown[]) => setMerchantStatusAction(...args),
  correctMerchantContactEmailAction: (...args: unknown[]) => correctMerchantContactEmailAction(...args),
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
    live_api_without_webhook: false,
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

/** A merchant taking live money whose partner is never told. Silent by
 * nature: a wrong webhook URL fails loudly and alerts, while no URL
 * queues nothing at all — so the only way anyone finds out is this
 * badge. Two partners were in this state on 2026-10-16 with ten real
 * customers between them. */
describe("live API without webhook warning", () => {
  it("warns when a merchant has a live key and no webhook", () => {
    render(<MerchantsTable rows={[merchant({ live_api_without_webhook: true })]} />);

    expect(screen.getByText("Live API, no webhook")).toBeInTheDocument();
  });

  it("stays quiet when a webhook is configured", () => {
    render(<MerchantsTable rows={[merchant({ live_api_without_webhook: false })]} />);

    expect(screen.queryByText("Live API, no webhook")).not.toBeInTheDocument();
  });

  it("warns on the affected merchant only, not the whole list", () => {
    render(
      <MerchantsTable
        rows={[
          merchant({ merchant_id: "ok", business_name: "Has Webhook", live_api_without_webhook: false }),
          merchant({ merchant_id: "bad", business_name: "No Webhook", live_api_without_webhook: true }),
        ]}
      />,
    );

    expect(screen.getAllByText("Live API, no webhook")).toHaveLength(1);
  });
});

/** Every duplicate business in production was one merchant who mistyped
 * their email at signup, never got the verification link, and signed up
 * again. Signup now refuses the second attempt, so this button is the
 * only remaining way out - if it does not work, those merchants are
 * stuck, which is worse than the duplicates it replaced. */
describe("MerchantsTable correct signup email", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("prefills the address currently on the account, so support can see the typo", () => {
    render(<MerchantsTable rows={[merchant({ email: "huseinsaid211@gmail.com" })]} />);

    fireEvent.click(screen.getByTitle("Correct signup email"));

    expect(screen.getByLabelText("Correct signup email")).toHaveValue("huseinsaid211@gmail.com");
  });

  it("sends the corrected address", async () => {
    correctMerchantContactEmailAction.mockResolvedValue({ error: null, ok: true, message: "Email changed." });
    render(<MerchantsTable rows={[merchant({ email: "huseinsaid211@gmail.com" })]} />);

    fireEvent.click(screen.getByTitle("Correct signup email"));
    fireEvent.change(screen.getByLabelText("Correct signup email"), {
      target: { value: "hussensaid211@gmail.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(correctMerchantContactEmailAction).toHaveBeenCalledWith("merchant-1", "hussensaid211@gmail.com"),
    );
  });

  it("does not fire on opening the field", () => {
    render(<MerchantsTable rows={[merchant()]} />);

    fireEvent.click(screen.getByTitle("Correct signup email"));

    expect(correctMerchantContactEmailAction).not.toHaveBeenCalled();
  });

  it("shows the failure instead of looking like it worked", async () => {
    correctMerchantContactEmailAction.mockResolvedValue({
      error: "Another account already uses that email address.",
      ok: false,
      message: null,
    });
    render(<MerchantsTable rows={[merchant()]} />);

    fireEvent.click(screen.getByTitle("Correct signup email"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/Another account already uses/)).toBeInTheDocument();
  });

  it("is offered for a suspended business too", () => {
    render(<MerchantsTable rows={[merchant({ account_status: "suspended" })]} />);

    expect(screen.getByTitle("Correct signup email")).toBeInTheDocument();
  });
});
