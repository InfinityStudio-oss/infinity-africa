import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PayoutsApiPage from "./page";
import { DOCS_NAV } from "@/components/docs/nav-items";

/**
 * Documentation for the one API that sends money out without a person
 * approving each request.
 *
 * These pin the handful of claims that would cost an integrator real
 * money if the page drifted from the API — not the prose around them.
 * Each was verified against production before being written down.
 *
 * Asserted against the page's normalised text rather than with
 * getByText: the sentences that matter run through <strong> and <code>,
 * so element-level matching fails on text that is plainly there, and
 * loosening the pattern until it passes is how a test ends up asserting
 * nothing.
 */

function pageText(): string {
  const { container } = render(<PayoutsApiPage />);
  return (container.textContent ?? "").replace(/\s+/g, " ");
}

describe("Payouts API documentation", () => {
  it("is reachable from the docs navigation", () => {
    const hrefs = DOCS_NAV.flatMap((group) => group.items.map((item) => item.href));
    expect(hrefs).toContain("/developers/payouts");
  });

  it("says the fee is added on top, with the arithmetic spelled out", () => {
    // The costly misreading is "the 1% comes out of the 1,000". It does
    // not: the beneficiary gets the full amount and the wallet pays the
    // fee on top.
    const text = pageText();
    expect(text).toContain("debits TZS 1,010 from your wallet");
    expect(text).toContain("beneficiary receives TZS 1,000");
  });

  it("warns that needs_reconciliation is not a failure", () => {
    // An integrator who reads this as failed and retries pays twice.
    const text = pageText();
    expect(text).toContain("needs_reconciliation is not a failure");
    expect(text).toContain("Do not retry it and do not refund against it");
    expect(text).toContain("STILL HELD");
  });

  it("states that a payout key cannot top up the wallet it spends from", () => {
    // The whole safety model: the balance is the ceiling, and it is only
    // a ceiling because the key cannot raise it.
    const text = pageText();
    expect(text).toContain("cannot");
    expect(text).toContain("funding is a dashboard action behind your own second factor");
  });

  it("is honest that beneficiaries cannot yet be created through the API", () => {
    // There is no endpoint. Saying so beats an integrator hunting for
    // one that does not exist.
    expect(pageText()).toContain("No self-service beneficiaries yet");
  });

  it("documents the refusal codes the API actually returns", () => {
    // Verified live: a missing Idempotency-Key and an unknown field are
    // both 422, an unknown beneficiary is 404. ValidationAPIError is 422
    // in this codebase, not 400 — which the first draft got wrong.
    const text = pageText();
    expect(text).toContain("422");
    expect(text).toContain("404");
    expect(text).toContain("409");
    expect(text).not.toContain("400 —");
  });

  it("names Idempotency-Key as a required header", () => {
    expect(pageText()).toContain("is a required header");
  });

  it("says a sandbox payout reaches no real recipient", () => {
    expect(pageText()).toContain("no real money moves and no real recipient is paid");
  });

  it("tells Collections integrators there are no payout webhooks", () => {
    // Collections notify by webhook; payouts do not. Someone who has
    // integrated Collections will assume they do and wait for a
    // callback that never arrives.
    const text = pageText();
    expect(text).toContain("There are no payout webhooks");
    expect(text).toContain("has to poll");
  });

  it("says a payout cannot be cancelled once created", () => {
    expect(pageText()).toContain("A payout cannot be cancelled once created");
  });

  it("contains no real account identifiers", () => {
    // The first draft pasted a live beneficiary id, payout id and
    // reference straight out of the pilot account into a public page.
    const text = pageText();
    for (const leaked of ["05104c2f", "81a04fe6", "3D20F0D3"]) {
      expect(text).not.toContain(leaked);
    }
  });
});
