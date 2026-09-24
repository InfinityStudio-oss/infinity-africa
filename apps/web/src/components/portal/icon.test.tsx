import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Icon } from "./icon";

/**
 * Regression cover for raw Material Symbols ligature names appearing as
 * readable text over the UI ("smartphone", "account_balance_wallet",
 * "qr_code_scanner" printed across the payment page on a hard refresh).
 *
 * The glyph IS the span's text content — that is how a ligature font works
 * — so a test cannot assert the name is absent from the DOM. What it can
 * assert is that the icon is hidden from assistive tech and still carries
 * the class the font and the pending-guard both key off. The font-loading
 * half is covered in app/seo-and-security.test.ts.
 */
describe("Icon", () => {
  it("hides the ligature name from screen readers by default", () => {
    render(<Icon name="qr_code_scanner" />);
    const glyph = screen.getByText("qr_code_scanner");
    expect(glyph).toHaveAttribute("aria-hidden", "true");
  });

  it("exposes an accessible name only when one is given", () => {
    render(<Icon name="smartphone" label="Mobile money" />);
    const glyph = screen.getByRole("img", { name: "Mobile money" });
    expect(glyph).not.toHaveAttribute("aria-hidden");
  });

  it("carries the class the font and the pending-guard both key off", () => {
    render(<Icon name="account_balance_wallet" />);
    expect(screen.getByText("account_balance_wallet")).toHaveClass("material-symbols-outlined");
  });
});
