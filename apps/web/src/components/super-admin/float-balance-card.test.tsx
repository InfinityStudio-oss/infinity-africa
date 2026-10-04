import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FloatBalanceCard } from "./float-balance-card";

/**
 * This card's job is to be trustworthy, not to always show a number.
 * It is the figure an operator decides to approve a payout on, so
 * showing a wrong one is worse than showing none.
 */
describe("FloatBalanceCard", () => {
  it("shows the float and confirms it covers what is waiting", () => {
    render(
      <FloatBalanceCard
        balance={{ available: "250000.00", currency: "TZS", reason: null }}
        pendingTotal="100000.00"
      />,
    );
    expect(screen.getByText(/Selcom float/)).toHaveTextContent("250,000");
    expect(screen.getByText(/Covers the/)).toBeInTheDocument();
  });

  it("warns when the float is smaller than the queue — the situation that caused the failed payout", () => {
    render(
      <FloatBalanceCard
        balance={{ available: "50000.00", currency: "TZS", reason: null }}
        pendingTotal="100000.00"
      />,
    );
    expect(screen.getByText(/some payouts will fail/i)).toBeInTheDocument();
  });

  it("warns outright when the account is empty", () => {
    render(
      <FloatBalanceCard balance={{ available: "0.00", currency: "TZS", reason: null }} pendingTotal="0.00" />,
    );
    expect(screen.getByText(/will fail until this account is topped up/i)).toBeInTheDocument();
  });

  it.each([
    ["provider_unavailable", /Selcom could not be reached/i],
    ["not_configured", /No Selcom disbursement account number/i],
    ["unrecognised_response", /shape this platform doesn't recognise/i],
  ] as const)("explains why the balance is missing when the reason is %s", (reason, expected) => {
    render(
      <FloatBalanceCard balance={{ available: null, currency: "TZS", reason }} pendingTotal="100000.00" />,
    );
    expect(screen.getByText(/unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("never invents a figure when the balance is unknown", () => {
    const { container } = render(
      <FloatBalanceCard
        balance={{ available: null, currency: "TZS", reason: "provider_unavailable" }}
        pendingTotal="100000.00"
      />,
    );
    // No digits at all beyond the explanation — in particular not the
    // pending total, which must never be mistaken for the float.
    expect(container.textContent).not.toMatch(/100,000/);
  });
});
