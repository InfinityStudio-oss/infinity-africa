import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * A rejected signup has to say so where the person is looking.
 *
 * Reported as the Create Account button "getting stuck". Nothing was
 * stuck. The form was rejecting the submit because NIDA Number was
 * empty, and saying so inline under that field - several hundred
 * pixels above the submit button at the bottom of a long form. From
 * where the person was standing, the button flicked to "Creating
 * account…" and back, and nothing else happened.
 *
 * Inline errors stay; they are the right place to correct a field.
 * What these tests pin is the part that was missing: a summary at the
 * top of the form naming every problem in the words the form uses, and
 * focus moved to the first field that needs attention.
 */

const signupWithBusinessAction = vi.fn();
let actionState: unknown = null;

vi.mock("react", async () => {
  const react = await vi.importActual<typeof import("react")>("react");
  return {
    ...react,
    // useActionState drives this form. Faked so a test can put the form
    // in the state a rejected submit leaves it in, without a server.
    useActionState: () => [actionState, signupWithBusinessAction, false],
  };
});

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/auth/actions", () => ({
  signupWithBusinessAction: (...args: unknown[]) => signupWithBusinessAction(...args),
  resendVerificationAction: vi.fn(),
}));

const { CreateAccountForm } = await import("./create-account-form");

function renderWith(state: unknown) {
  actionState = state;
  return render(<CreateAccountForm />);
}

beforeEach(() => {
  vi.clearAllMocks();
  actionState = null;
  // jsdom does not implement it, and the component calls it on every
  // failed submit.
  Element.prototype.scrollIntoView = vi.fn();
});

describe("a rejected signup says why, where it can be seen", () => {
  it("shows no summary before anything has been submitted", () => {
    renderWith(null);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("names the problem at the TOP of the form, not only beside the field", () => {
    // The exact case reported: everything filled in except NIDA.
    renderWith({
      values: { businessName: "Mashariki wifi" },
      errors: { nidaNumber: ["NIDA number is required."] },
    });

    const summary = screen.getByRole("alert");
    expect(summary).toHaveTextContent("One thing needs fixing");
    expect(summary).toHaveTextContent("NIDA Number");
    expect(summary).toHaveTextContent("NIDA number is required.");
  });

  it("calls the field what the form calls it, not what the code calls it", () => {
    // "nidaNumber" in an error list is a developer's word for it and
    // sends someone hunting down a long form.
    renderWith({ values: {}, errors: { businessCategory: ["Business type is required."] } });

    const summary = screen.getByRole("alert");
    expect(summary).toHaveTextContent("Business Type");
    expect(summary).not.toHaveTextContent("businessCategory");
  });

  it("counts them when several fields are wrong", () => {
    renderWith({
      values: {},
      errors: {
        nidaNumber: ["NIDA number is required."],
        password: ["Password is too short."],
        agreedToTerms: ["You must agree to the Terms of Service."],
      },
    });

    const summary = screen.getByRole("alert");
    expect(summary).toHaveTextContent("3 things need fixing");
    expect(summary).toHaveTextContent("NIDA Number");
    expect(summary).toHaveTextContent("Password");
    expect(summary).toHaveTextContent("Terms of Service");
  });

  it("moves the cursor into the first field that needs attention", () => {
    // Focus is what actually moves the page for a keyboard or
    // screen-reader user; the scroll is for everyone else.
    renderWith({ values: {}, errors: { nidaNumber: ["NIDA number is required."] } });

    expect(document.activeElement).toBe(document.getElementById("nidaNumber"));
  });

  it("scrolls the summary into view", () => {
    renderWith({ values: {}, errors: { nidaNumber: ["NIDA number is required."] } });

    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("still shows the error beside the field itself", () => {
    // The summary is in addition to the inline message, not instead of
    // it - the inline one is what you read while correcting the field.
    renderWith({ values: {}, errors: { nidaNumber: ["NIDA number is required."] } });

    // Matched outside the summary on purpose. The summary splits the
    // same sentence across a link and a text node, so an exact-text
    // match finds only the inline paragraph - which is precisely the
    // one this test is about.
    const inline = screen.getByText("NIDA number is required.");
    expect(inline).toBeInTheDocument();
    expect(screen.getByRole("alert")).not.toContainElement(inline);
  });

  it("keeps what was already typed, so nothing has to be entered twice", () => {
    renderWith({
      values: { businessName: "Mashariki wifi", businessPhone: "0750000000", tinNumber: "000000" },
      errors: { nidaNumber: ["NIDA number is required."] },
    });

    expect(screen.getByLabelText(/Business Name/i)).toHaveValue("Mashariki wifi");
    expect(screen.getByLabelText(/Business Phone/i)).toHaveValue("0750000000");
  });
});
