import { beforeEach, describe, expect, it, vi } from "vitest";

const submitOnboardingAccount = vi.fn();

class FakeOnboardingApiError extends Error {
  code?: string;
  constructor(message: string, code?: string) {
    super(message);
    this.code = code;
  }
}

vi.mock("./api", () => ({
  OnboardingApiError: FakeOnboardingApiError,
  submitOnboardingAccount: (...args: unknown[]) => submitOnboardingAccount(...args),
}));

vi.mock("@/lib/auth/current-user", () => ({
  getCurrentUser: async () => ({ id: "user-1", email: "dave.m@example.com" }),
}));

vi.mock("next/navigation", () => ({
  redirect: () => {
    throw new Error("redirect called — the submission was expected to fail");
  },
}));

/** A complete, valid application. Every field the action validates
 * before it ever reaches the API, so a test about the API's answer is
 * not quietly passing on a local validation error instead. */
function validForm(): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries({
    businessName: "Chuo Wi-Fi",
    natureOfBusiness: "Hotspot",
    businessCategory: "Internet",
    physicalAddress: "Mbezi",
    regionCity: "Dar es Salaam",
    contactPhone: "0784114622",
    nidaNumber: "19900101123456789012",
  })) {
    data.set(key, value);
  }
  for (const flag of ["agreedToTerms", "agreedToPrivacy", "confirmedAccurate"]) {
    data.set(flag, "on");
  }
  data.set("servicesNeeded", "PAYMENT_COLLECTION");
  return data;
}

describe("what a duplicate signup is told", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the API's own reason instead of rewriting it", async () => {
    // The regression. A conflict used to be replaced with "You already
    // have a merchant account submitted for review" whatever the API
    // said. Chuo Wi-Fi's account was active and verified, not queued,
    // so that sentence was false and told them nothing they could act
    // on. It became a support ticket.
    submitOnboardingAccount.mockRejectedValue(
      new FakeOnboardingApiError("An account with this email already exists.", "conflict"),
    );
    const { submitOnboardingAction } = await import("./actions");

    const state = await submitOnboardingAction(null, validForm());

    expect(state?.formError).toBe("An account with this email already exists.");
    expect(state?.formError).not.toMatch(/submitted for review/i);
  });

  it("offers a way out, pointing at the page that actually unblocks them", async () => {
    submitOnboardingAccount.mockRejectedValue(
      new FakeOnboardingApiError("An account with this email already exists.", "conflict"),
    );
    const { submitOnboardingAction } = await import("./actions");

    const state = await submitOnboardingAction(null, validForm());

    expect(state?.formErrorAction?.href).toBe("/dashboard/resend-verification");
    expect(state?.formErrorAction?.label).toMatch(/resend/i);
  });

  it("keeps the detailed repeat-ID message, which names the address and the code", async () => {
    // duplicate_signup_message() on the API builds this. It is the most
    // useful sentence in the whole flow and was the one most worth not
    // discarding.
    const detailed =
      "You have already applied with this ID number. The application is on d***@gmail.com " +
      "(business code 27001234). If that email address is wrong, contact InfinityPay support.";
    submitOnboardingAccount.mockRejectedValue(new FakeOnboardingApiError(detailed, "conflict"));
    const { submitOnboardingAction } = await import("./actions");

    const state = await submitOnboardingAction(null, validForm());

    expect(state?.formError).toBe(detailed);
  });

  it("does not offer the resend link for a failure resending cannot fix", async () => {
    submitOnboardingAccount.mockRejectedValue(
      new FakeOnboardingApiError("Something went wrong on our side.", "server_error"),
    );
    const { submitOnboardingAction } = await import("./actions");

    const state = await submitOnboardingAction(null, validForm());

    expect(state?.formError).toBe("Something went wrong on our side.");
    expect(state?.formErrorAction).toBeUndefined();
  });

  it("still reports a network failure in its own words", async () => {
    submitOnboardingAccount.mockRejectedValue(new TypeError("fetch failed"));
    const { submitOnboardingAction } = await import("./actions");

    const state = await submitOnboardingAction(null, validForm());

    expect(state?.formError).toMatch(/Couldn't reach InfinityPay/i);
    expect(state?.formErrorAction).toBeUndefined();
  });
});
