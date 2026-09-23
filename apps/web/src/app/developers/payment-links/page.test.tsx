import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PaymentLinksApiPage from "./page";

describe("PaymentLinksApiPage", () => {
  it("clarifies that Selcom Hosted Checkout is not used", () => {
    render(<PaymentLinksApiPage />);

    expect(screen.getByText("Selcom Hosted Checkout is not used")).toBeInTheDocument();
    expect(screen.getAllByText(/currently inactive/).length).toBeGreaterThan(0);
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
