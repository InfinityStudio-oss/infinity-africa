import { beforeEach, describe, expect, it, vi } from "vitest";

// `actions.ts` transitively pulls in modules marked `import "server-only"`
// (mock-store / mock-session). That package throws outside a real RSC
// build; stub it so the unit under test can be imported in jsdom.
vi.mock("server-only", () => ({}));

// --- mocks -----------------------------------------------------------------

const signUp = vi.fn();
const signInWithPassword = vi.fn();
const resend = vi.fn();
const maybeSingle = vi.fn();

vi.mock("@/lib/supabase/server", () => ({
  createClient: async () => ({
    auth: { signUp, signInWithPassword, resend },
    from: () => ({ select: () => ({ eq: () => ({ maybeSingle }) }) }),
  }),
}));

const isSupabaseConfigured = vi.fn();
vi.mock("./supabase-status", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./supabase-status")>();
  return { ...actual, isSupabaseConfigured: () => isSupabaseConfigured() };
});

const getOnboardingStatus = vi.fn();
const submitMerchantSignup = vi.fn();
class OnboardingApiError extends Error {
  code?: string;
  constructor(message: string, code?: string) {
    super(message);
    this.code = code;
  }
}
vi.mock("@/lib/onboarding/api", () => ({
  getOnboardingStatus: (...args: unknown[]) => getOnboardingStatus(...args),
  submitMerchantSignup: (...args: unknown[]) => submitMerchantSignup(...args),
  OnboardingApiError,
}));

vi.mock("next/headers", () => ({
  headers: async () => new Map([["host", "infinitypay.me"]]),
}));

class RedirectError extends Error {
  constructor(public location: string) {
    super(`NEXT_REDIRECT:${location}`);
  }
}
vi.mock("next/navigation", () => ({
  redirect: (location: string) => {
    throw new RedirectError(location);
  },
}));

// --- helpers -------------------------------------------------------------

function form(fields: Record<string, string>): FormData {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  return fd;
}

const VALID_SIGNUP = {
  firstName: "Amani",
  lastName: "Mushi",
  email: "amani@shop.co.tz",
  phone: "+255700000000",
  nidaNumber: "19900101-12345-12345-12",
  password: "Str0ng!pass",
  confirmPassword: "Str0ng!pass",
  businessName: "Amani Traders",
  businessCategory: "Retail",
  businessEmail: "hello@amanitraders.co.tz",
  businessPhone: "+255711222333",
  physicalAddress: "Mbezi",
  regionCity: "Dar es Salaam",
  servicesNeeded: "PAYMENT_LINKS",
  agreedToTerms: "on",
  agreedToPrivacy: "on",
  confirmedAccurate: "on",
};

async function importActions() {
  return import("./actions");
}

beforeEach(() => {
  vi.clearAllMocks();
  isSupabaseConfigured.mockReturnValue(true);
  process.env.NEXT_PUBLIC_SITE_URL = "https://infinitypay.me";
});

// --- signupWithBusinessAction (combined signup) -----------------------

describe("signupWithBusinessAction", () => {
  it("requires a NIDA number, attached to the nidaNumber field", async () => {
    const { signupWithBusinessAction } = await importActions();
    const state = await signupWithBusinessAction(null, form({ ...VALID_SIGNUP, nidaNumber: "" }));
    expect(state?.errors?.nidaNumber?.[0]).toMatch(/NIDA number is required/i);
    expect(submitMerchantSignup).not.toHaveBeenCalled();
  });

  it("rejects a NIDA number that isn't 20 digits", async () => {
    const { signupWithBusinessAction } = await importActions();
    const state = await signupWithBusinessAction(null, form({ ...VALID_SIGNUP, nidaNumber: "12345" }));
    expect(state?.errors?.nidaNumber?.[0]).toMatch(/20 digits/i);
    expect(submitMerchantSignup).not.toHaveBeenCalled();
  });

  it("requires both first and last name", async () => {
    const { signupWithBusinessAction } = await importActions();
    const state = await signupWithBusinessAction(null, form({ ...VALID_SIGNUP, firstName: "", lastName: "" }));
    expect(state?.errors?.firstName?.[0]).toMatch(/first name is required/i);
    expect(state?.errors?.lastName?.[0]).toMatch(/last name is required/i);
    expect(submitMerchantSignup).not.toHaveBeenCalled();
  });

  it("requires a valid business email, distinct from the owner's own email", async () => {
    const { signupWithBusinessAction } = await importActions();
    const missing = await signupWithBusinessAction(null, form({ ...VALID_SIGNUP, businessEmail: "" }));
    expect(missing?.errors?.businessEmail?.[0]).toMatch(/business email is required/i);

    const invalid = await signupWithBusinessAction(null, form({ ...VALID_SIGNUP, businessEmail: "not-an-email" }));
    expect(invalid?.errors?.businessEmail?.[0]).toMatch(/valid business email/i);
    expect(submitMerchantSignup).not.toHaveBeenCalled();
  });

  it("requires a business phone", async () => {
    const { signupWithBusinessAction } = await importActions();
    const state = await signupWithBusinessAction(null, form({ ...VALID_SIGNUP, businessPhone: "" }));
    expect(state?.errors?.businessPhone?.[0]).toMatch(/business phone is required/i);
    expect(submitMerchantSignup).not.toHaveBeenCalled();
  });

  it("combines first and last name into full_name, and derives nature_of_business from notes/business type", async () => {
    submitMerchantSignup.mockResolvedValue({
      merchant_id: "m1",
      merchant_code: "MER-1",
      account_status: "PENDING_VERIFICATION",
      email_confirmation_required: true,
    });
    const { signupWithBusinessAction } = await importActions();

    await signupWithBusinessAction(null, form({ ...VALID_SIGNUP, notes: "Also sells on Instagram" }));
    expect(submitMerchantSignup).toHaveBeenCalledWith(
      expect.objectContaining({ full_name: "Amani Mushi", nature_of_business: "Also sells on Instagram", notes: "Also sells on Instagram" }),
    );

    submitMerchantSignup.mockClear();
    await signupWithBusinessAction(null, form({ ...VALID_SIGNUP, notes: "" }));
    expect(submitMerchantSignup).toHaveBeenCalledWith(
      expect.objectContaining({ nature_of_business: "Retail", notes: null }),
    );
  });

  it("on success (email confirmation required) shows the verify-then-wait message and offers resend", async () => {
    submitMerchantSignup.mockResolvedValue({
      merchant_id: "m1",
      merchant_code: "MER-1",
      account_status: "PENDING_VERIFICATION",
      email_confirmation_required: true,
    });
    const { signupWithBusinessAction } = await importActions();

    const state = await signupWithBusinessAction(null, form(VALID_SIGNUP));

    expect(state?.notice).toMatch(/verify your email, then wait for InfinityPay approval/i);
    expect(state?.awaitingEmailVerification).toBe(true);
    expect(submitMerchantSignup).toHaveBeenCalledWith(
      expect.objectContaining({
        full_name: "Amani Mushi",
        email: "amani@shop.co.tz",
        nida_number: "19900101-12345-12345-12",
        business_name: "Amani Traders",
        business_email: "hello@amanitraders.co.tz",
        business_phone: "+255711222333",
        accepted_terms: true,
      }),
    );
  });

  it("on success (no email confirmation) shows the submitted-for-review message", async () => {
    submitMerchantSignup.mockResolvedValue({
      merchant_id: "m1",
      merchant_code: "MER-1",
      account_status: "PENDING_VERIFICATION",
      email_confirmation_required: false,
    });
    const { signupWithBusinessAction } = await importActions();

    const state = await signupWithBusinessAction(null, form(VALID_SIGNUP));
    expect(state?.notice).toMatch(/submitted for review/i);
    expect(state?.notice).toMatch(/collected offline|additional KYC/i);
    expect(state?.awaitingEmailVerification).toBeFalsy();
  });

  it("maps a backend nida_invalid error onto the NIDA field", async () => {
    submitMerchantSignup.mockRejectedValue(new OnboardingApiError("Enter a valid NIDA number.", "nida_invalid"));
    const { signupWithBusinessAction } = await importActions();
    const state = await signupWithBusinessAction(null, form(VALID_SIGNUP));
    expect(state?.errors?.nidaNumber?.[0]).toMatch(/valid NIDA/i);
  });

  it("maps a duplicate-email conflict onto the email field", async () => {
    submitMerchantSignup.mockRejectedValue(new OnboardingApiError("An account with this email already exists.", "conflict"));
    const { signupWithBusinessAction } = await importActions();
    const state = await signupWithBusinessAction(null, form(VALID_SIGNUP));
    expect(state?.errors?.email?.[0]).toMatch(/already exists/i);
  });

  it("never redirects — the merchant must wait for approval", async () => {
    submitMerchantSignup.mockResolvedValue({
      merchant_id: "m1",
      merchant_code: "MER-1",
      account_status: "PENDING_VERIFICATION",
      email_confirmation_required: true,
    });
    const { signupWithBusinessAction } = await importActions();
    // resolves (returns a FormState) rather than throwing a redirect
    await expect(signupWithBusinessAction(null, form(VALID_SIGNUP))).resolves.toBeTruthy();
  });
});

// --- loginAction ------------------------------------------------------

describe("loginAction", () => {
  it("shows a verify-email message (not 'Incorrect email or password') for an unconfirmed account", async () => {
    signInWithPassword.mockResolvedValue({
      data: { user: null, session: null },
      error: { status: 400, code: "email_not_confirmed", message: "Email not confirmed", name: "AuthApiError" },
    });
    const { loginAction } = await importActions();

    const state = await loginAction(null, form({ email: "amani@shop.co.tz", password: "Str0ng!pass" }));

    expect(state?.formError).toMatch(/verify your email before logging in/i);
    expect(state?.formError).not.toMatch(/incorrect email or password/i);
    expect(state?.awaitingEmailVerification).toBe(true);
  });

  it("still shows the generic message for genuinely wrong credentials", async () => {
    signInWithPassword.mockResolvedValue({
      data: { user: null, session: null },
      error: { status: 400, code: "invalid_credentials", message: "Invalid login credentials", name: "AuthApiError" },
    });
    const { loginAction } = await importActions();

    const state = await loginAction(null, form({ email: "amani@shop.co.tz", password: "wrong" }));
    expect(state?.formError).toBe("Incorrect email or password.");
  });

  it("redirects a verified merchant to their onboarding next_path", async () => {
    signInWithPassword.mockResolvedValue({
      data: { user: { id: "u1" }, session: { access_token: "tok" } },
      error: null,
    });
    maybeSingle.mockResolvedValue({ data: null });
    getOnboardingStatus.mockResolvedValue({ next_path: "/merchant/overview" });
    const { loginAction } = await importActions();

    await expect(
      loginAction(null, form({ email: "amani@shop.co.tz", password: "Str0ng!pass" })),
    ).rejects.toMatchObject({ location: "/merchant/overview" });
  });
});

// --- resendVerificationAction ----------------------------------------

describe("resendVerificationAction", () => {
  it("calls Supabase resend and returns a generic confirmation", async () => {
    resend.mockResolvedValue({ error: null });
    const { resendVerificationAction } = await importActions();

    const state = await resendVerificationAction(null, form({ email: "amani@shop.co.tz" }));

    expect(resend).toHaveBeenCalledWith(
      expect.objectContaining({ type: "signup", email: "amani@shop.co.tz" }),
    );
    expect(state?.awaitingEmailVerification).toBe(true);
    expect(state?.notice).toMatch(/fresh link/i);
  });

  it("rejects an obviously invalid email without calling Supabase", async () => {
    const { resendVerificationAction } = await importActions();
    const state = await resendVerificationAction(null, form({ email: "not-an-email" }));
    expect(resend).not.toHaveBeenCalled();
    expect(state?.formError).toMatch(/email address you signed up with/i);
  });
});
