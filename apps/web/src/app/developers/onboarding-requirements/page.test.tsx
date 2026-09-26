import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import OnboardingRequirementsPage from "./page";

describe("OnboardingRequirementsPage", () => {
  it("lists the fields the Get Started form actually asks for", () => {
    // The page used to describe a separate /onboarding step and a list of
    // documents to prepare. Neither exists: signup is one form, and
    // documents are only ever requested later during review.
    render(<OnboardingRequirementsPage />);

    for (const field of ["Business name", "Your name", "Business type", "NIDA number", "Business phone"]) {
      expect(screen.getByText(field)).toBeInTheDocument();
    }
  });

  it("marks TIN and the website link as optional", () => {
    render(<OnboardingRequirementsPage />);

    expect(screen.getByText("TIN")).toBeInTheDocument();
    expect(screen.getByText("Website or app link")).toBeInTheDocument();
    expect(screen.getAllByText("Optional").length).toBe(2);
  });

  it("says plainly that nothing is uploaded at signup", () => {
    // The point of the page: there is nothing to prepare in advance.
    render(<OnboardingRequirementsPage />);

    expect(screen.getByText(/No documents are uploaded at signup/i)).toBeInTheDocument();
  });

  it("explains that approval is what unlocks live keys and withdrawals", () => {
    render(<OnboardingRequirementsPage />);

    expect(screen.getByText(/Approval gates live API access and withdrawals/i)).toBeInTheDocument();
    expect(screen.getByText(/withdrawal_restricted/)).toBeInTheDocument();
  });

  it("does not describe the removed separate onboarding step", () => {
    // Guards the actual staleness this rewrite fixed, rather than just
    // asserting the new copy exists.
    const { container } = render(<OnboardingRequirementsPage />);

    expect(container.textContent).not.toMatch(/Infinity Africa/);
    expect(container.textContent).not.toMatch(/Physical business address/);
  });
});
