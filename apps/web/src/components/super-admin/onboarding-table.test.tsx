import { AccountStatus } from "@infinity/shared";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OnboardingTable } from "./onboarding-table";
import type { OnboardingSubmission } from "@/lib/onboarding/types";

vi.mock("@/components/super-admin/onboarding-review-actions", () => ({
  OnboardingReviewActions: () => null,
}));

function submission(
  name: string,
  review_status: AccountStatus,
  submitted_at: string,
): OnboardingSubmission {
  return {
    id: `id-${name}`,
    merchant_id: `m-${name}`,
    business_name: name,
    merchant_code: "27000000",
    legal_name: null,
    owner_email: `${name}@example.com`,
    contact_phone: null,
    nature_of_business: "ISP",
    business_category: "ISP",
    physical_address: "",
    region_city: "",
    services_needed: [],
    expected_monthly_volume: null,
    website_url: null,
    tin_number: null,
    nida_last4: null,
    notes: null,
    document_status: "UPLOADED",
    documents: [],
    review_status,
    review_note: null,
    reviewed_at: null,
    submitted_at,
  } as unknown as OnboardingSubmission;
}

/** A platform with many verified businesses and one waiting for approval —
 * the shape that made the pending one unfindable in production. */
const ROWS: OnboardingSubmission[] = [
  submission("Newest Verified", AccountStatus.VERIFIED, "2026-10-09T13:12:15Z"),
  submission("Second Verified", AccountStatus.VERIFIED, "2026-10-09T12:59:50Z"),
  submission("Waiting Business", AccountStatus.PENDING_VERIFICATION, "2026-10-08T10:36:43Z"),
  submission("Rejected Business", AccountStatus.REJECTED, "2026-10-01T09:00:00Z"),
];

describe("OnboardingTable", () => {
  it("opens on what is waiting for a decision, not the whole history", () => {
    render(<OnboardingTable rows={ROWS} />);

    expect(screen.getByText("Waiting Business")).toBeInTheDocument();
    // Verified businesses submitted more recently must not bury it.
    expect(screen.queryByText("Newest Verified")).not.toBeInTheDocument();
  });

  it("counts each status on its filter", () => {
    render(<OnboardingTable rows={ROWS} />);

    expect(screen.getByRole("button", { name: "Needs review (1)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Verified (2)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rejected (1)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All (4)" })).toBeInTheDocument();
  });

  it("still shows everything, with the waiting one first", () => {
    render(<OnboardingTable rows={ROWS} />);

    fireEvent.click(screen.getByRole("button", { name: "All (4)" }));

    const names = screen.getAllByRole("row").slice(1).map((r) => r.textContent ?? "");
    expect(names[0]).toContain("Waiting Business");
    expect(names).toHaveLength(4);
  });

  it("opens on everything when nothing needs a decision", () => {
    const settled = ROWS.filter((r) => r.review_status !== AccountStatus.PENDING_VERIFICATION);
    render(<OnboardingTable rows={settled} />);

    expect(screen.getByText("Newest Verified")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All (3)" })).toHaveAttribute("aria-pressed", "true");
  });

  it("says so plainly when the queue is clear", () => {
    const settled = ROWS.filter((r) => r.review_status !== AccountStatus.PENDING_VERIFICATION);
    render(<OnboardingTable rows={settled} />);

    fireEvent.click(screen.getByRole("button", { name: "Needs review (0)" }));

    expect(screen.getByText("Nothing is waiting for a decision right now.")).toBeInTheDocument();
  });

  it("does not render a bare comma when there is no address", () => {
    render(<OnboardingTable rows={ROWS} />);

    expect(screen.queryByText(",")).not.toBeInTheDocument();
  });
});
