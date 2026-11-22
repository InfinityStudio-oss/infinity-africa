import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PayoutFundingCode } from "./payout-funding-code";

const challenge = {
  otp_required: true as const,
  challenge_id: "28f85665-0000-0000-0000-000000000000",
  masked_email: "p**********8@gmail.com",
  expires_at: "2026-11-22T13:19:09Z",
  resend_cooldown_seconds: 60,
  max_attempts: 5,
};

/**
 * This component ships INSIDE the funding form, and that is the whole
 * reason these tests exist.
 *
 * It was written as a <form> with a type="submit" button. Nested forms
 * are invalid HTML — the browser drops the inner one, so the inner
 * button submits the OUTER form. In production that meant every click
 * of "Confirm and move funds" silently re-ran "request a code": three
 * codes were issued, not one was ever verified, attempts stayed at 0,
 * and the merchant watched a zero balance and concluded the feature was
 * broken.
 *
 * So the first test renders it exactly where it really lives — inside a
 * form — which is the only arrangement that could have caught it.
 */
describe("PayoutFundingCode", () => {
  it("confirms without submitting the form it is nested inside", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const outerSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());

    render(
      <form onSubmit={outerSubmit}>
        <PayoutFundingCode
          challenge={challenge}
          amountLabel="TZS 5,000.00"
          onConfirm={onConfirm}
          onCancel={() => {}}
        />
      </form>,
    );

    fireEvent.change(screen.getByLabelText("6-digit code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm and move funds" }));

    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("123456"));
    // The bug, stated: the outer form must not be submitted, because
    // doing so re-requests a code instead of verifying this one.
    expect(outerSubmit).not.toHaveBeenCalled();
  });

  it("renders no form of its own", () => {
    // Belt and braces on the same fault: a <form> here is invalid
    // wherever this component is used, so it must not have one.
    const { container } = render(
      <PayoutFundingCode
        challenge={challenge}
        amountLabel="TZS 5,000.00"
        onConfirm={vi.fn()}
        onCancel={() => {}}
      />,
    );
    expect(container.querySelector("form")).toBeNull();
  });

  it("will not confirm a code that is not six digits", () => {
    const onConfirm = vi.fn();
    render(
      <PayoutFundingCode
        challenge={challenge}
        amountLabel="TZS 5,000.00"
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    );

    fireEvent.change(screen.getByLabelText("6-digit code"), { target: { value: "123" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm and move funds" }));

    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("accepts Enter, which used to work for free via form submit", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(
      <PayoutFundingCode
        challenge={challenge}
        amountLabel="TZS 5,000.00"
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    );

    const input = screen.getByLabelText("6-digit code");
    fireEvent.change(input, { target: { value: "123456" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("123456"));
  });

  it("says nothing has moved yet, and names the amount", () => {
    render(
      <PayoutFundingCode
        challenge={challenge}
        amountLabel="TZS 5,000.00"
        onConfirm={vi.fn()}
        onCancel={() => {}}
      />,
    );

    expect(screen.getByText(/Nothing has moved yet/)).toBeInTheDocument();
    expect(screen.getByText("TZS 5,000.00")).toBeInTheDocument();
    expect(screen.getByText("p**********8@gmail.com")).toBeInTheDocument();
  });

  it("surfaces the server's refusal rather than a generic message", async () => {
    const onConfirm = vi.fn().mockRejectedValue(new Error("That code isn't valid."));
    render(
      <PayoutFundingCode
        challenge={challenge}
        amountLabel="TZS 5,000.00"
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    );

    fireEvent.change(screen.getByLabelText("6-digit code"), { target: { value: "999999" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm and move funds" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("That code isn't valid."));
  });
});
