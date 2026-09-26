import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PaymentLinksApiPage from "./page";

describe("PaymentLinksApiPage", () => {
  it("does not expose the underlying payment provider", () => {
    // The page used to carry a callout about a third party's hosted
    // checkout being inactive -- provider internals a partner has no
    // reason to read.
    const { container } = render(<PaymentLinksApiPage />);

    expect(container.textContent).not.toMatch(/Hosted Checkout/i);
    expect(container.textContent).not.toMatch(/currently inactive/i);
  });

  it("documents the new /pay endpoint, not the legacy /collect method field", () => {
    render(<PaymentLinksApiPage />);

    expect(screen.getByText("json — POST /public/payment-links/PLK-7X29QK/pay")).toBeInTheDocument();
    expect(screen.getAllByText(/WALLET_PUSH/).length).toBeGreaterThan(0);
  });

  it("no longer asks the business to set allowed_payment_methods on creation", () => {
    render(<PaymentLinksApiPage />);

    expect(screen.queryByText(/"allowed_payment_methods": \["USSD_PUSH"/)).not.toBeInTheDocument();
  });
});
